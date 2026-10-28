"""`SwarmEngine` 编排与状态机行为测试。

被测单元是 **SwarmEngine 自身的编排决策**：
- `run()` 的运行时托管 / 预算守卫启动顺序
- `_run_core()` 的阶段编排（自裂变 → 经验检索 → 世界模型 → 澄清门禁 →
  任务分解 → 管道执行 → 事务提交/回滚 → 结果汇总）
- 单任务回退、异常回退、断点恢复（coordination_state）三条控制流
- `_on_worker_sync()` / `_on_audit_fail()` 两条消息驱动的状态转移

协作者（Orchestrator / Pipeline / LTM / Integrator / 消息总线 / 世界模型）
一律用**手写 fake**，因为它们要么需要 LLM、要么会写 ``.clawd`` 磁盘状态；
本文件断言的是引擎对它们的**调用契约**，而不是它们的内部实现。
这与 ``test_pipeline_flow.py`` 的做法一致。

## 本文件暴露的两个真实缺陷（测试按其**真实行为**断言，不修）

1. ``engine.py:29`` + ``:220`` —— ``get_metrics_collector`` 是**工厂函数**，
   却被 `as EnterpriseMetricsCollector` 当成采集器实例使用。
   `_run_core()` 第一行 `record_start()` 即抛 ``AttributeError``，
   即 ``SwarmEngine.run()`` 永远跑不起来（调用方在
   ``workflow/healable_executor.py`` 用 ``except Exception`` 吞掉）。
2. ``engine.py:373`` —— `decomposition.sub_tasks` 实际是 ``list[dict]``
   （见 ``orchestrator.TaskDecomposition`` 与 ``decompose_task`` 的返回），
   但汇总阶段按 ``t.task_id`` / ``t.result`` 取属性。真实链路上必然抛
   ``AttributeError``，被 390 行的兜底 except 捕获 → 即使跑通也会
   ``success=False`` 或回退单 Agent。
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.agent.swarm import engine as engine_mod
from src.agent.swarm.auditor import AuditFinding, AuditReport
from src.agent.swarm.config import SwarmConfig
from src.agent.swarm.engine import SwarmEngine, SwarmResult
from src.agent.swarm.message_bus import MessageType
from src.agent.swarm.orchestrator import TaskDAG, TaskDecomposition
from src.agent.swarm.quality_gate import GateResult
from src.agent.swarm.task_registry import TaskStatus
from src.memory.enterprise_ltm import PatternType


# ==========================================================================
# 手写 fake 协作者
# ==========================================================================


class FakeWorldModel:
    """只实现引擎用到的世界模型契约。"""

    def __init__(self, root_dir=None) -> None:
        self.root_dir = root_dir
        self._is_initialized = False
        self.initialize_calls = 0

    async def initialize(self) -> None:
        self.initialize_calls += 1
        self._is_initialized = True

    def stats(self) -> dict[str, int]:
        return {"node_count": 42}


class FakeLTM:
    """记录 learn_pattern / session 生命周期的调用参数。"""

    def __init__(self) -> None:
        self.session_starts: list[tuple[str, str]] = []
        self.session_failures: list[tuple[str, str]] = []
        self.patterns: list[dict[str, Any]] = []

    async def record_session_start(self, session_id: str, goal: str) -> None:
        self.session_starts.append((session_id, goal))

    async def record_session_failure(self, session_id: str, error_msg: str) -> None:
        self.session_failures.append((session_id, error_msg))

    async def learn_pattern(
        self,
        goal: str,
        implementation: Any = None,
        rejection_reason: str | None = None,
        pattern_type: PatternType = PatternType.SUCCESS,
    ) -> None:
        self.patterns.append(
            {
                "goal": goal,
                "implementation": implementation,
                "rejection_reason": rejection_reason,
                "pattern_type": pattern_type,
            }
        )


class FakeBus:
    """记录订阅（含 catch_up）与发布。"""

    def __init__(self, storage_dir=None, **kwargs: Any) -> None:
        self.storage_dir = storage_dir
        self.subscriptions: list[dict[str, Any]] = []
        self.published: list[Any] = []

    def subscribe(self, message_type, callback, catch_up: bool = False, recipient_id=None) -> None:
        self.subscriptions.append(
            {
                "message_type": message_type,
                "callback": callback,
                "catch_up": catch_up,
                "recipient_id": recipient_id,
            }
        )

    async def publish(self, message) -> None:
        self.published.append(message)


class FakeIntegrator:
    def __init__(self, workdir=None, message_bus=None) -> None:
        self.events: list[str] = []

    async def start_transaction(self) -> None:
        self.events.append("start")

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


class FakeBudgetGuard:
    def __init__(self, config=None, run_dir: str = "latest") -> None:
        self.config = config
        self.started = False
        self.validations = 0

    def start(self) -> None:
        self.started = True

    def validate(self) -> None:
        self.validations += 1


class FakeRuntimeHost:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class FakeMetrics:
    """替代被误用的 `EnterpriseMetricsCollector`（见模块 docstring 缺陷 1）。"""

    def __init__(self) -> None:
        self.start_calls = 0
        self.completions: list[float] = []

    def record_start(self) -> None:
        self.start_calls += 1

    def record_completion(self, elapsed: float) -> None:
        self.completions.append(elapsed)

    def get_report(self) -> dict[str, Any]:
        return {"requests_started": self.start_calls}


class FakeOrchestrator:
    """固定 decompose / summarize 的返回值，记录调用次数。"""

    def __init__(self, sub_tasks: list[Any] | None = None, summary: str = "汇总结果") -> None:
        self.agent_id = "orchestrator-1"
        self._sub_tasks = sub_tasks if sub_tasks is not None else []
        self._summary = summary
        self.decompose_calls = 0
        self.summarized: dict[str, Any] | None = None

    async def decompose_task(self, goal: str) -> TaskDecomposition:
        self.decompose_calls += 1
        if self._sub_tasks and isinstance(self._sub_tasks[0], dict):
            dag = TaskDAG(self._sub_tasks)
        else:
            dag = TaskDAG()
        return TaskDecomposition(sub_tasks=list(self._sub_tasks), dag=dag)

    async def summarize_results(self, task_results: dict[str, str]) -> str:
        self.summarized = task_results
        return self._summary


class FakeSurfaceManager:
    def __init__(self) -> None:
        self.saved: list[tuple[str, Any]] = []

    def save_surface(self, name: str, payload: Any) -> None:
        self.saved.append((name, payload))


class FakeCoordinationState:
    def __init__(self, sessions: dict[str, Any] | None = None) -> None:
        self.sessions = sessions or {}
        self.obligations: list[tuple[str, str]] = []
        self.state_updates: list[tuple[str, Any]] = []

    def add_session(self, info) -> None:
        self.sessions[info.session_id] = info

    def assign_obligation(self, session_id: str, task_id: str) -> None:
        self.obligations.append((session_id, task_id))

    def update_session(self, session_id: str, state=None) -> None:
        self.state_updates.append((session_id, state))


@pytest.fixture
def make_engine(monkeypatch, tmp_path):
    """构造一个协作者全为 fake 的 SwarmEngine。

    需要 patch 的依据：
    - `EnterpriseLTM()` 会建 ``.clawd/enterprise_ltm.db``；
    - `PersistentMessageBus` 会建 ``.clawd/control`` 目录；
    - `BudgetGuard` 会建 ``latest/`` 运行目录；
    - `RepositoryWorldModel.initialize()` 会全仓扫描。
    这些都属于"测试不该产生的磁盘副作用"，不是被测行为。
    """
    monkeypatch.setattr(engine_mod, "EnterpriseLTM", FakeLTM)
    monkeypatch.setattr(engine_mod, "AtomicIntegrator", FakeIntegrator)
    monkeypatch.setattr(
        "src.agent.swarm.persistent_message_bus.PersistentMessageBus", FakeBus
    )
    monkeypatch.setattr("src.brain.world_model.RepositoryWorldModel", FakeWorldModel)
    monkeypatch.setattr("src.core.budget_guard.BudgetGuard", FakeBudgetGuard)
    monkeypatch.setattr(
        "src.core.git.worktree.WorktreeManager", lambda *a, **k: SimpleNamespace()
    )
    monkeypatch.setattr(engine_mod, "EnterpriseMetricsCollector", FakeMetrics())

    def _make(**overrides: Any) -> SwarmEngine:
        cfg = SwarmConfig(enable_runtime_host=False, enable_coordination_state=False)
        for key, value in overrides.items():
            setattr(cfg, key, value)
        return SwarmEngine(config=cfg, workdir=Path(tmp_path))

    return _make


# ==========================================================================
# __init__ / _get_worker_engine / _progress
# ==========================================================================


class TestWorkerEngine:
    def test_worker_engine_is_cached_and_created_once(self, make_engine, monkeypatch):
        engine = make_engine()
        created: list[dict[str, Any]] = []

        def fake_create(**kwargs):
            created.append(kwargs)
            return object()

        monkeypatch.setattr(engine_mod, "create_agent_engine", fake_create)

        first = engine._get_worker_engine()
        second = engine._get_worker_engine()

        assert first is second
        assert len(created) == 1
        # 无 llm_config 时的降级契约：openai / 空 key / gpt-4o
        assert created[0]["provider_type"] == "openai"
        assert created[0]["api_key"] == ""
        assert created[0]["model"] == "gpt-4o"

    def test_worker_engine_uses_llm_config_and_worker_model_override(
        self, make_engine, monkeypatch
    ):
        engine = make_engine(worker_model="qwen-coder")
        engine.llm_config = SimpleNamespace(
            provider=SimpleNamespace(value="deepseek"), api_key="sk-test", model="llm-model"
        )
        created: list[dict[str, Any]] = []
        monkeypatch.setattr(
            engine_mod, "create_agent_engine", lambda **kw: created.append(kw) or object()
        )

        engine._get_worker_engine()

        assert created[0]["provider_type"] == "deepseek"
        assert created[0]["api_key"] == "sk-test"
        # config.worker_model 优先于 llm_config.model
        assert created[0]["model"] == "qwen-coder"


class TestInitAgents:
    def test_agents_are_created_once_and_inherit_config(self, make_engine):
        engine = make_engine(
            enable_auditor=True, lint_strict=False, auditor_max_line_length=99
        )

        engine._init_agents()
        orchestrator, auditor = engine.orchestrator, engine.auditor

        assert orchestrator is not None
        assert auditor is not None
        # Auditor 必须继承 SwarmConfig 的审计配置
        assert auditor.lint_strict is False
        assert auditor.require_tests == engine.config.require_tests
        assert auditor.max_line_length == 99

        # 二次调用不重建
        engine._init_agents()
        assert engine.orchestrator is orchestrator
        assert engine.auditor is auditor

    def test_auditor_skipped_when_disabled(self, make_engine):
        engine = make_engine(enable_auditor=False)

        engine._init_agents()

        assert engine.orchestrator is not None
        assert engine.auditor is None


class TestProgress:
    def test_progress_without_callback_does_not_raise(self, make_engine):
        engine = make_engine()
        engine.on_progress = None
        engine._progress("swarm", "无回调")

    def test_progress_forwards_to_callback(self, make_engine):
        engine = make_engine()
        received: list[tuple[str, str]] = []
        engine.on_progress = lambda agent, msg: received.append((agent, msg))

        engine._progress("clarify", "得分 0.3")

        assert received == [("clarify", "得分 0.3")]


# ==========================================================================
# run() 外壳
# ==========================================================================


class FakeTracingContext:
    """`run()` 里用到的 TracingContext 契约（`start_request` + `get_request_id`）。"""

    request_id = "trace-abc"

    @classmethod
    def start_request(cls):
        return contextlib.nullcontext()

    @classmethod
    def get_request_id(cls) -> str:
        return cls.request_id


class TestRunShell:
    def test_run_starts_runtime_and_budget_then_delegates(self, make_engine, monkeypatch):
        engine = make_engine()
        host = FakeRuntimeHost()
        engine.runtime_host = host
        engine.budget_guard = FakeBudgetGuard()
        seen: dict[str, Any] = {}

        async def fake_core(goal, request_id):
            seen["goal"] = goal
            seen["request_id"] = request_id
            return SwarmResult(success=True, goal=goal)

        monkeypatch.setattr(engine, "_run_core", fake_core)
        monkeypatch.setattr("src.utils.tracing.TracingContext", FakeTracingContext)

        result = asyncio.run(engine.run("实现登录"))

        assert result.success is True
        assert host.started is True
        assert engine.budget_guard.started is True
        assert seen["goal"] == "实现登录"
        assert seen["request_id"] == "trace-abc"

    def test_run_is_currently_blocked_by_tracing_context_defect(self, make_engine):
        """缺陷 4 的真实行为：``run()`` 在 ``engine.py:212`` 直接 AttributeError。

        `TracingContext`（`src/utils/tracing.py`）只有 `trace_block()` /
        `ensure_request_id()` / `get_request_id()`，**没有** `start_request()`。
        因此 `SwarmEngine.run()` 连 `_run_core` 都进不去。
        """
        engine = make_engine()

        async def fake_core(goal, request_id):  # pragma: no cover - 不应被调用
            raise AssertionError("_run_core 不应被调用")

        engine._run_core = fake_core  # type: ignore[method-assign]

        with pytest.raises(AttributeError, match="start_request"):
            asyncio.run(engine.run("任意目标"))

    def test_run_is_also_blocked_by_metrics_collector_defect(
        self, make_engine, monkeypatch
    ):
        """缺陷 1 的真实行为：绕过 212 行后，``engine.py:220`` 立刻 AttributeError。

        `engine.py:29` 把工厂函数 ``get_metrics_collector`` 别名成
        ``EnterpriseMetricsCollector``，``engine.py:220`` 却直接调用
        ``record_start()``（且 `MetricsCollector` 本身也没有该方法）。
        """
        engine = make_engine()
        monkeypatch.setattr("src.utils.tracing.TracingContext", FakeTracingContext)
        # 还原被 fixture 换掉的指标采集器，暴露真实缺陷
        from src.core.telemetry.exporter import get_metrics_collector

        monkeypatch.setattr(engine_mod, "EnterpriseMetricsCollector", get_metrics_collector)

        with pytest.raises(AttributeError, match="record_start"):
            asyncio.run(engine.run("任意目标"))


# ==========================================================================
# _run_core: 成功路径
# ==========================================================================


def _object_subtasks(*task_ids: str):
    """`engine.py:373` 期望的形态（带 .task_id 的对象）。真实 Orchestrator 给的是 dict。"""
    return [SimpleNamespace(task_id=tid, title=tid, description="d") for tid in task_ids]


class TestRunCoreSuccess:
    def test_happy_path_commits_and_records_success_pattern(
        self, make_engine, monkeypatch
    ):
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
        )
        orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1", "T2"))
        engine.orchestrator = orchestrator
        changes = {"src/a.py": "print(1)"}
        report = AuditReport(passed=True, findings=[], summary="ok")
        gates = [GateResult(passed=True, gate_name="lint")]

        class _Pipe:
            def __init__(self, **kwargs):
                pass

            async def execute(self, goal, request_id, decomposition, budget_guard=None):
                return changes, report, gates

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)

        result = asyncio.run(engine._run_core("目标", "req-1"))

        assert result.success is True
        assert result.goal == "目标"
        assert result.final_result == "汇总结果"
        assert result.code_changes == changes
        assert result.audit_report is report
        assert result.gate_results == gates
        assert result.elapsed_seconds >= 0

        # 世界模型在未初始化时被初始化一次
        assert engine.world_model.initialize_calls == 1
        # 事务：开 + 提交，不回滚
        assert engine.integrator.events == ["start", "commit"]
        # 成功经验入库
        assert engine.ltm.patterns[0]["pattern_type"] == PatternType.SUCCESS
        assert engine.ltm.patterns[0]["implementation"] == changes
        assert engine.ltm.session_starts == [("req-1", "目标")]
        # 汇总阶段收到的是 task_id → result 映射
        assert orchestrator.summarized is not None
        assert result.task_stats["enterprise_metrics"] == {"requests_started": 1}
        assert engine.budget_guard.validations == 1

    def test_pipeline_receives_assembled_collaborators(self, make_engine, monkeypatch):
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
        )
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1"))
        captured: dict[str, Any] = {}

        class _Pipe:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def execute(self, goal, request_id, decomposition, budget_guard=None):
                return {}, None, []

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)

        asyncio.run(engine._run_core("g", "r"))

        assert captured["orchestrator"] is engine.orchestrator
        assert captured["task_registry"] is engine.task_registry
        assert captured["integrator"] is engine.integrator
        assert captured["worktree_manager"] is engine.worktree_manager
        assert captured["progress_callback"] == engine._progress

    def test_dict_subtasks_break_result_summary(self, make_engine, monkeypatch):
        """缺陷 2 的真实行为：真实 Orchestrator 返回 dict 子任务 → 汇总阶段崩。

        `engine.py:373` 用 `t.task_id` 取属性，而 `TaskDecomposition.sub_tasks`
        的元素类型是 dict。异常被 390 行的兜底 except 捕获，
        且默认 `fallback_to_single_agent=True` 时会改走单 Agent 回退。
        """
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
        )
        engine.orchestrator = FakeOrchestrator(
            sub_tasks=[{"task_id": "T1", "title": "t", "description": "d", "depends_on": ""}]
        )

        class _Pipe:
            def __init__(self, **kwargs):
                pass

            async def execute(self, goal, request_id, decomposition, budget_guard=None):
                return {"a.py": "x"}, None, []

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)

        fallback_calls: list[str] = []

        async def fake_fallback(goal, start_time):
            fallback_calls.append(goal)
            return SwarmResult(success=True, goal=goal, final_result="单 Agent 结果")

        monkeypatch.setattr(engine, "_fallback_single_agent", fake_fallback)

        result = asyncio.run(engine._run_core("目标", "req"))

        # 事务已提交（走到 390 行之前），随后异常 → 回滚 → 回退
        assert engine.integrator.events == ["start", "commit", "rollback"]
        assert fallback_calls == ["目标"]
        assert result.final_result == "单 Agent 结果"

    def test_quality_gate_failure_rolls_back_then_falls_back_due_to_defect(
        self, make_engine, monkeypatch
    ):
        """门禁失败 → 回滚；但"记录失败模式"这一步会崩（缺陷 5）。

        `engine.py:362` 读 `audit_report.issues`，而 `AuditReport` 只有
        `passed / findings / warnings / summary`（没有 `issues`）。
        于是 AttributeError 被 390 行兜底 except 捕获 → 回退单 Agent，
        **失败经验永远进不了 LTM**。
        """
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
        )
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1", "T2"))
        report = AuditReport(
            passed=False,
            findings=[
                AuditFinding(
                    severity="high",
                    category="security",
                    file="a.py",
                    line=1,
                    description="x",
                )
            ],
        )
        gates = [GateResult(passed=False, gate_name="tests", severity="minor")]

        class _Pipe:
            def __init__(self, **kwargs):
                pass

            async def execute(self, goal, request_id, decomposition, budget_guard=None):
                return {"a.py": "x"}, report, gates

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)

        fallback_calls: list[str] = []

        async def fake_fallback(goal, start_time):
            fallback_calls.append(goal)
            return SwarmResult(success=True, goal=goal, final_result="fallback")

        monkeypatch.setattr(engine, "_fallback_single_agent", fake_fallback)

        result = asyncio.run(engine._run_core("目标", "req"))

        # 回滚发生两次：门禁失败时一次（358），兜底 except 又回滚一次（399）
        assert engine.integrator.events == ["start", "rollback", "rollback"]
        assert "commit" not in engine.integrator.events
        assert fallback_calls == ["目标"]
        assert result.final_result == "fallback"
        # 失败经验未被记录 —— 这正是缺陷的表现
        assert engine.ltm.patterns == []

    def test_quality_gate_failure_records_failure_pattern_with_issues_attr(
        self, make_engine, monkeypatch
    ):
        """缺陷 5 的反向契约：只要对象暴露 `issues`，失败经验就会被写入 LTM。"""
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
        )
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1", "T2"))

        class _Report:
            passed = False
            issues = ["安全漏洞: 使用了 eval"]

            def to_markdown(self) -> str:
                return "report"

        gates = [GateResult(passed=False, gate_name="security", severity="critical")]

        class _Pipe:
            def __init__(self, **kwargs):
                pass

            async def execute(self, goal, request_id, decomposition, budget_guard=None):
                return {"a.py": "x"}, _Report(), gates

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)

        result = asyncio.run(engine._run_core("目标", "req"))

        assert result.success is False
        assert engine.integrator.events == ["start", "rollback"]
        assert engine.ltm.patterns[0]["pattern_type"] == PatternType.FAILURE_PREVENTION
        assert "eval" in engine.ltm.patterns[0]["rejection_reason"]


class TestRunCoreRecovery:
    def test_recovery_rebuilds_decomposition_from_registry(
        self, make_engine, monkeypatch
    ):
        """有持久化协作状态 + registry 已有任务时，不得再调用 LLM 分解。"""
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
            enable_coordination_state=True,
        )
        engine.surface_manager = FakeSurfaceManager()
        engine.coordination_state = FakeCoordinationState(sessions={"w1": object()})
        orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1"))
        engine.orchestrator = orchestrator
        engine.task_registry.register("任务一", "描述", task_id="T9")
        engine.task_registry.get_task("T9").metadata["depends_on"] = ""

        captured: dict[str, Any] = {}

        class _Pipe:
            def __init__(self, **kwargs):
                pass

            async def execute(self, goal, request_id, decomposition, budget_guard=None):
                captured["sub_tasks"] = decomposition.sub_tasks
                return {}, None, []

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)

        asyncio.run(engine._run_core("目标", "req"))

        assert orchestrator.decompose_calls == 0
        assert [t["task_id"] for t in captured["sub_tasks"]] == ["T9"]
        assert captured["sub_tasks"][0]["title"] == "任务一"
        # 恢复模式下不再记录会话开始
        assert engine.ltm.session_starts == []


class TestRunCoreFailure:
    def test_exception_without_fallback_returns_failure_result(
        self, make_engine, monkeypatch
    ):
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
            fallback_to_single_agent=False,
        )
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1", "T2"))

        class _Boom:
            def __init__(self, **kwargs):
                pass

            async def execute(self, **kwargs):
                raise RuntimeError("pipeline 炸了")

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Boom)

        result = asyncio.run(engine._run_core("目标", "req"))

        assert result.success is False
        assert "pipeline 炸了" in result.final_result
        assert result.errors == ["pipeline 炸了"]
        assert engine.integrator.events == ["start", "rollback"]
        assert engine.ltm.session_failures == [("req", "pipeline 炸了")]

    def test_exception_with_fallback_switches_to_single_agent(
        self, make_engine, monkeypatch
    ):
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
            fallback_to_single_agent=True,
        )
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1", "T2"))

        class _Boom:
            def __init__(self, **kwargs):
                pass

            async def execute(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Boom)

        async def fake_fallback(goal, start_time):
            return SwarmResult(success=True, goal=goal, final_result="fallback")

        monkeypatch.setattr(engine, "_fallback_single_agent", fake_fallback)

        result = asyncio.run(engine._run_core("目标", "req"))

        assert result.final_result == "fallback"
        # 回退路径不写 failure 记录（由 fallback 自身的结果决定）
        assert engine.ltm.session_failures == []

    def test_single_subtask_without_fallback_flag_goes_single_agent(
        self, make_engine, monkeypatch
    ):
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
            fallback_to_single_agent=False,
        )
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1"))
        called: list[str] = []

        async def fake_fallback(goal, start_time):
            called.append(goal)
            return SwarmResult(success=True, goal=goal, final_result="single")

        monkeypatch.setattr(engine, "_fallback_single_agent", fake_fallback)

        result = asyncio.run(engine._run_core("唯一目标", "req"))

        assert called == ["唯一目标"]
        assert result.final_result == "single"


class TestFallbackSingleAgent:
    def test_success_exposes_session_result(self, make_engine, monkeypatch):
        engine = make_engine()
        worker = SimpleNamespace(
            run=lambda goal: _async_return(SimpleNamespace(final_result="worker 输出"))
        )
        monkeypatch.setattr(engine, "_get_worker_engine", lambda: worker)

        result = asyncio.run(engine._fallback_single_agent("目标", 0.0))

        assert result.success is True
        assert result.final_result == "worker 输出"
        assert result.task_stats == {"mode": "single_agent_fallback"}

    def test_failure_is_captured_not_raised(self, make_engine, monkeypatch):
        engine = make_engine()

        async def boom(goal):
            raise RuntimeError("worker 崩了")

        monkeypatch.setattr(engine, "_get_worker_engine", lambda: SimpleNamespace(run=boom))

        result = asyncio.run(engine._fallback_single_agent("目标", 0.0))

        assert result.success is False
        assert "worker 崩了" in result.final_result
        assert result.errors == ["worker 崩了"]


async def _async_return(value):
    return value


# ==========================================================================
# Step 0: 自裂变 / 经验检索 / 澄清门禁
# ==========================================================================


class TestSelfFission:
    def test_no_features_returns_empty_and_reports(self, make_engine, monkeypatch):
        engine = make_engine()
        messages: list[tuple[str, str]] = []
        engine.on_progress = lambda a, m: messages.append((a, m))

        class _Analyzer:
            def __init__(self, threshold):
                self.threshold = threshold

            async def analyze(self, goal, workdir):
                return SimpleNamespace(features=[], tags=[])

        monkeypatch.setattr(
            "src.agent.swarm.self_fission.SemanticCodeAnalyzer", _Analyzer
        )

        assert asyncio.run(engine._self_fission("目标")) == []
        assert any("未检测到语义特征" in m for _, m in messages)

    def test_synthesizes_agents_from_features(self, make_engine, monkeypatch):
        engine = make_engine()
        messages: list[tuple[str, str]] = []
        engine.on_progress = lambda a, m: messages.append((a, m))
        agent = SimpleNamespace(agent_id="specialist-1")

        class _Analyzer:
            def __init__(self, threshold):
                self.threshold = threshold

            async def analyze(self, goal, workdir):
                return SimpleNamespace(features=["sql"], tags=["sql", "security"])

        class _Factory:
            def __init__(self, llm_config=None):
                pass

            def synthesize(self, features, message_bus, workdir, max_agents):
                assert features == ["sql"]
                assert max_agents == engine.config.max_specialized_agents
                return [agent]

        monkeypatch.setattr(
            "src.agent.swarm.self_fission.SemanticCodeAnalyzer", _Analyzer
        )
        monkeypatch.setattr("src.agent.swarm.self_fission.AgentSynthesisFactory", _Factory)

        agents = asyncio.run(engine._self_fission("目标"))

        assert agents == [agent]
        assert any("sql, security" in m for _, m in messages)
        assert any("specialist-1" in m for _, m in messages)

    def test_import_error_is_degraded_with_visible_message(self, make_engine, monkeypatch):
        engine = make_engine()
        messages: list[tuple[str, str]] = []
        engine.on_progress = lambda a, m: messages.append((a, m))

        class _Analyzer:
            def __init__(self, threshold):
                pass

            async def analyze(self, goal, workdir):
                raise ImportError("no module named x")

        monkeypatch.setattr(
            "src.agent.swarm.self_fission.SemanticCodeAnalyzer", _Analyzer
        )

        assert asyncio.run(engine._self_fission("目标")) == []
        assert any("自裂变模块未安装" in m for _, m in messages)

    def test_generic_error_is_degraded_with_visible_message(self, make_engine, monkeypatch):
        engine = make_engine()
        messages: list[tuple[str, str]] = []
        engine.on_progress = lambda a, m: messages.append((a, m))

        class _Analyzer:
            def __init__(self, threshold):
                pass

            async def analyze(self, goal, workdir):
                raise RuntimeError("分析器崩了")

        monkeypatch.setattr(
            "src.agent.swarm.self_fission.SemanticCodeAnalyzer", _Analyzer
        )

        assert asyncio.run(engine._self_fission("目标")) == []
        assert any("自裂变失败" in m and "分析器崩了" in m for _, m in messages)


class TestExperienceHints:
    def test_hints_include_best_practices_and_warnings(self, make_engine, monkeypatch):
        engine = make_engine()

        class _Hub:
            def find_best_practices(self, goal, top_k=3):
                return [
                    SimpleNamespace(
                        task_description="实现认证",
                        solution="用 PyJWT",
                        success_rate=0.75,
                        total_attempts=4,
                    )
                ]

            def get_failure_warnings(self, goal):
                return [
                    SimpleNamespace(pattern="忘记加 rate limit", frequency=3),
                    SimpleNamespace(pattern="未校验 token", frequency=2),
                    SimpleNamespace(pattern="第三条应被截断", frequency=1),
                ]

        monkeypatch.setattr(
            "src.agent.swarm.self_fission.rl_experience.RLExperienceHub", _Hub
        )

        hints = asyncio.run(engine._retrieve_experience_hints("认证"))

        assert "历史方案 1: 实现认证 -> 用 PyJWT (成功率: 75%, 尝试: 4)" in hints
        assert "⚠️ 失败预警: 忘记加 rate limit (出现 3 次)" in hints
        # 只取前两条失败预警
        assert len([h for h in hints if h.startswith("⚠️")]) == 2

    def test_empty_hub_returns_empty(self, make_engine, monkeypatch):
        engine = make_engine()

        class _Hub:
            def find_best_practices(self, goal, top_k=3):
                return []

            def get_failure_warnings(self, goal):
                return []

        monkeypatch.setattr(
            "src.agent.swarm.self_fission.rl_experience.RLExperienceHub", _Hub
        )

        assert asyncio.run(engine._retrieve_experience_hints("目标")) == []

    def test_hub_error_returns_empty(self, make_engine, monkeypatch):
        engine = make_engine()

        class _Hub:
            def __init__(self):
                raise RuntimeError("db 打不开")

        monkeypatch.setattr(
            "src.agent.swarm.self_fission.rl_experience.RLExperienceHub", _Hub
        )

        assert asyncio.run(engine._retrieve_experience_hints("目标")) == []


class TestClarifyGate:
    def test_non_goals_are_appended_to_goal(self, make_engine, monkeypatch):
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=True,
            fallback_to_single_agent=False,
        )
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1", "T2"))
        messages: list[tuple[str, str]] = []
        engine.on_progress = lambda a, m: messages.append((a, m))

        class _Gate:
            async def analyze_intent(self, goal):
                return {
                    "clarity_score": 0.4,
                    "draft_contract": {"non_goals": ["不做多租户", "不改数据库"]},
                }

            def should_ask_user(self, analysis):
                return True

        engine.clarify_gate = _Gate()
        seen: dict[str, str] = {}

        class _Pipe:
            def __init__(self, **kwargs):
                pass

            async def execute(self, goal, request_id, decomposition, budget_guard=None):
                seen["goal"] = goal
                return {}, None, []

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)
        # 让 decompose 拿到增强后的 goal（不是原始 goal）
        decomposed: list[str] = []
        orig_decompose = engine.orchestrator.decompose_task

        async def spy_decompose(goal):
            decomposed.append(goal)
            return await orig_decompose(goal)

        engine.orchestrator.decompose_task = spy_decompose

        asyncio.run(engine._run_core("实现登录", "req"))

        assert any("意图清晰度得分: 0.4" in m for _, m in messages)
        assert any("建议进行深层对话" in m for _, m in messages)
        assert "[NON-GOALS]:" in decomposed[0]
        assert "- 不做多租户" in decomposed[0]
        assert seen["goal"] == decomposed[0]


# ==========================================================================
# 消息驱动：审计失败 / Worker 状态同步
# ==========================================================================


def _msg(sender="worker-1", metadata=None):
    return SimpleNamespace(sender=sender, metadata=metadata or {})


class TestOnAuditFail:
    def test_records_failure_pattern(self, make_engine):
        engine = make_engine()
        messages: list[tuple[str, str]] = []
        engine.on_progress = lambda a, m: messages.append((a, m))

        asyncio.run(
            engine._on_audit_fail(
                _msg(metadata={"task_id": "T1", "report": "安全漏洞"})
            )
        )

        assert engine.ltm.patterns[0]["goal"] == "任务 T1 审计失败"
        assert engine.ltm.patterns[0]["rejection_reason"] == "安全漏洞"
        assert engine.ltm.patterns[0]["pattern_type"] == PatternType.FAILURE_PREVENTION
        assert any("T1" in m for _, m in messages)

    def test_message_without_task_id_is_ignored(self, make_engine):
        engine = make_engine()

        asyncio.run(engine._on_audit_fail(_msg(metadata={"report": "x"})))

        assert engine.ltm.patterns == []


class TestOnWorkerSync:
    def test_missing_status_or_task_id_is_ignored(self, make_engine):
        engine = make_engine()

        asyncio.run(engine._on_worker_sync(_msg(metadata={"task_id": "T1"})))
        asyncio.run(engine._on_worker_sync(_msg(metadata={"status": "completed"})))

        assert engine.task_registry.get_all_tasks() == []

    def test_existing_task_status_is_updated(self, make_engine):
        engine = make_engine()
        engine.task_registry.register("t", "d", task_id="T1")

        asyncio.run(engine._on_worker_sync(_msg(metadata={"task_id": "T1", "status": "in_progress"})))

        assert engine.task_registry.get_task("T1").status == TaskStatus.IN_PROGRESS

    def test_completed_task_receives_result_and_evidence(self, make_engine):
        engine = make_engine()
        engine.task_registry.register("t", "d", task_id="T1")

        asyncio.run(
            engine._on_worker_sync(
                _msg(
                    metadata={
                        "task_id": "T1",
                        "status": "completed",
                        "result_summary": "已实现登录",
                        "evidence_paths": ["evidence/a.log", "evidence/a.log"],
                    }
                )
            )
        )

        task = engine.task_registry.get_task("T1")
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "已实现登录"
        # 证据路径去重
        assert task.evidence_paths == ["evidence/a.log"]

    def test_unknown_task_is_registered_as_recovered(self, make_engine):
        engine = make_engine()
        messages: list[tuple[str, str]] = []
        engine.on_progress = lambda a, m: messages.append((a, m))

        asyncio.run(engine._on_worker_sync(_msg(metadata={"task_id": "T-ghost", "status": "submitted"})))

        task = engine.task_registry.get_task("T-ghost")
        assert task is not None
        assert task.title == "Recovered: T-ghost"
        assert task.status == TaskStatus.SUBMITTED
        assert any("T-ghost" in m for _, m in messages)

    def test_coordination_state_is_updated_and_persisted(self, make_engine):
        engine = make_engine(enable_coordination_state=True)
        engine.surface_manager = FakeSurfaceManager()
        engine.coordination_state = FakeCoordinationState()
        engine.task_registry.register("t", "d", task_id="T1")

        asyncio.run(engine._on_worker_sync(_msg(sender="worker-7", metadata={"task_id": "T1", "status": "completed"})))

        state = engine.coordination_state
        assert "worker-7" in state.sessions
        assert state.obligations == [("worker-7", "T1")]
        assert state.state_updates and state.state_updates[0][0] == "worker-7"
        assert state.state_updates[0][1].value == "completed"
        assert engine.surface_manager.saved[0][0] == "coordination_state"

    def test_invalid_status_with_coordination_state_persists_then_crashes(self, make_engine):
        """缺陷 3：非法 status 在 `try/except: pass` 里被吞（`engine.py:560`），
        但随后 566 行再次构造 `TaskStatus(status)` 抛出 ValueError，
        进入 593 行的 except —— 那里调用 **不存在的** `self.logger`
        （SwarmEngine 从未定义该属性），于是 AttributeError 直接冒泡给订阅方。

        正确修复应为 `logger.debug(...)`（模块级 logger）。修复后本测试应改为
        断言"非法状态被安全忽略"。
        """
        engine = make_engine(enable_coordination_state=True)
        engine.surface_manager = FakeSurfaceManager()
        engine.coordination_state = FakeCoordinationState()

        with pytest.raises(AttributeError, match="logger"):
            asyncio.run(
                engine._on_worker_sync(_msg(metadata={"task_id": "T1", "status": "not-a-status"}))
            )

        # 崩溃前协调状态已被持久化 —— 说明"部分失败"是静默的
        assert engine.surface_manager.saved

    def test_invalid_status_without_coordination_state_crashes(self, make_engine):
        engine = make_engine()

        with pytest.raises(AttributeError, match="logger"):
            asyncio.run(
                engine._on_worker_sync(_msg(metadata={"task_id": "T1", "status": "bogus"}))
            )


# ==========================================================================
# `_run_core` 的增强阶段与运行时托管
# ==========================================================================


class TestRunCoreOptionalStages:
    def test_self_fission_and_experience_stages_are_reported(
        self, make_engine, monkeypatch
    ):
        engine = make_engine(
            enable_self_fission=True,
            enable_experience_retrieval=True,
            enable_clarify_gate=False,
        )
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1", "T2"))
        messages: list[tuple[str, str]] = []
        engine.on_progress = lambda a, m: messages.append((a, m))

        async def fake_fission(goal):
            return [SimpleNamespace(agent_id="a1"), SimpleNamespace(agent_id="a2")]

        async def fake_hints(goal):
            return ["hint-1"]

        monkeypatch.setattr(engine, "_self_fission", fake_fission)
        monkeypatch.setattr(engine, "_retrieve_experience_hints", fake_hints)

        class _Pipe:
            def __init__(self, **kwargs):
                pass

            async def execute(self, **kwargs):
                return {}, None, []

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)

        asyncio.run(engine._run_core("目标", "req"))

        assert any("合成 2 个专项 Agent" in m for _, m in messages)
        assert any("检索到 1 条历史经验" in m for _, m in messages)
        assert any(stage == "world-model" for stage, _ in messages)

    def test_initialized_world_model_is_not_reinitialized(self, make_engine, monkeypatch):
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
        )
        engine.world_model._is_initialized = True
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1", "T2"))

        class _Pipe:
            def __init__(self, **kwargs):
                pass

            async def execute(self, **kwargs):
                return {}, None, []

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)

        asyncio.run(engine._run_core("目标", "req"))

        assert engine.world_model.initialize_calls == 0

    def test_runtime_host_is_stopped_on_success(self, make_engine, monkeypatch):
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
        )
        host = FakeRuntimeHost()
        engine.runtime_host = host
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1", "T2"))

        class _Pipe:
            def __init__(self, **kwargs):
                pass

            async def execute(self, **kwargs):
                return {}, None, []

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)

        asyncio.run(engine._run_core("目标", "req"))

        assert host.stopped is True

    def test_runtime_host_is_stopped_on_failure(self, make_engine, monkeypatch):
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
            fallback_to_single_agent=False,
        )
        host = FakeRuntimeHost()
        engine.runtime_host = host
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1", "T2"))

        class _Boom:
            def __init__(self, **kwargs):
                pass

            async def execute(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Boom)

        asyncio.run(engine._run_core("目标", "req"))

        assert host.stopped is True


class TestSessionStateMapping:
    """`_on_worker_sync` 把 TaskStatus 映射为 SessionState（engine.py:551-559）。"""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("completed", "completed"),
            ("failed", "failed"),
            ("in_progress", "executing"),
        ],
    )
    def test_status_maps_to_session_state(self, make_engine, status, expected):
        engine = make_engine(enable_coordination_state=True)
        engine.surface_manager = FakeSurfaceManager()
        engine.coordination_state = FakeCoordinationState()
        engine.task_registry.register("t", "d", task_id="T1")

        asyncio.run(
            engine._on_worker_sync(
                _msg(sender="worker-1", metadata={"task_id": "T1", "status": status})
            )
        )

        session_id, state = engine.coordination_state.state_updates[0]
        assert session_id == "worker-1"
        assert state.value == expected


# ==========================================================================
# 消息订阅契约
# ==========================================================================


class TestSubscriptionContract:
    def test_run_core_subscribes_audit_fail_and_catchup_sync(
        self, make_engine, monkeypatch
    ):
        engine = make_engine(
            enable_self_fission=False,
            enable_experience_retrieval=False,
            enable_clarify_gate=False,
        )
        engine.orchestrator = FakeOrchestrator(sub_tasks=_object_subtasks("T1"))

        class _Pipe:
            def __init__(self, **kwargs):
                pass

            async def execute(self, **kwargs):
                return {}, None, []

        monkeypatch.setattr("src.agent.swarm.pipeline.SwarmPipeline", _Pipe)

        asyncio.run(engine._run_core("目标", "req"))

        types = {s["message_type"]: s for s in engine.message_bus.subscriptions}
        assert MessageType.AUDIT_FAIL in types
        assert types[MessageType.AUDIT_FAIL]["catch_up"] is False
        # SYNC_STATE 必须开 catch_up 才能回放历史、恢复 task_registry
        assert types[MessageType.SYNC_STATE]["catch_up"] is True
        assert types[MessageType.SYNC_STATE]["recipient_id"] == "orchestrator-1"

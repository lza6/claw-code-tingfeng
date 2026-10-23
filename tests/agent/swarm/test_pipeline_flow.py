"""`SwarmPipeline.execute` 的调度/事务/门禁行为测试。

被测单元是**流水线调度逻辑本身**：任务就绪判定、并发启动、失败后是否继续、
审计触发、质量门禁拦截、事务提交与回滚。

因此对协作者（orchestrator / auditor / quality_gate / integrator / task_registry）
使用**手写 fake**（而非 MagicMock），以固定它们被调用的契约；
`_execute_task_fn` 与 `extract_file_changes` 属于另一个单元，用 monkeypatch 隔离。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from src.agent.swarm import pipeline as pipeline_mod
from src.agent.swarm.config import SwarmConfig
from src.agent.swarm.pipeline import SwarmPipeline
from src.agent.swarm.quality_gate import GateResult
from src.agent.swarm.task_registry import SubTask, TaskStatus


class FakeDag:
    """最小 DAG 契约：只实现 execute 用到的 4 个方法。"""

    def __init__(self, tasks: dict[str, dict], order: list[str] | None = None):
        self.tasks = tasks
        self._order = order or list(tasks)
        self.completed: set[str] = set()
        self._ready_calls = 0

    def is_complete(self, completed: set[str]) -> bool:
        return len(completed) >= len(self.tasks)

    def get_ready_tasks(self, completed: set[str]) -> list[str]:
        self._ready_calls += 1
        if self._ready_calls > 20:  # 防止测试自身死循环
            return []
        return [t for t in self._order if t not in completed]

    def mark_task_completed(self, task_id: str) -> None:
        self.completed.add(task_id)


class FakeTaskRegistry:
    def __init__(self):
        self._tasks: dict[str, SubTask] = {}
        self.status_by_id: dict[str, TaskStatus] = {}
        self.registered: list[str] = []

    def get_task(self, task_id: str) -> SubTask | None:
        return self._tasks.get(task_id)

    def register_subtask(self, data: dict) -> SubTask:
        tid = data.get("id", "t")
        task = SubTask(task_id=tid, description=data.get("description", ""))
        self._tasks[tid] = task
        self.registered.append(tid)
        return task

    def get_dependency_results(self, task_id: str) -> dict:
        return {}

    def get_tasks_by_status(self, status: TaskStatus) -> list[SubTask]:
        return [t for t in self._tasks.values() if self.status_by_id.get(t.task_id) == status]


class FakeIntegrator:
    def __init__(self):
        self.events: list[str] = []
        self.batches: list[dict] = []

    async def start_transaction(self) -> None:
        self.events.append("start")

    async def integrate_batch(self, changes: dict) -> None:
        self.events.append("integrate")
        self.batches.append(changes)

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


class FakeBus:
    def __init__(self):
        self.published: list[Any] = []

    async def publish(self, message) -> None:
        self.published.append(message)


class FakeOrchestrator:
    def __init__(self):
        self.message_bus = FakeBus()
        self.surface_manager = None


class FakeAuditor:
    def __init__(self, passed: bool = True):
        self._passed = passed
        self.calls = 0

    async def audit(self, code_changes):
        self.calls += 1

        class _Report:
            passed = self._passed

            @staticmethod
            def to_markdown() -> str:
                return "report"

        return _Report()


class FakeQualityGate:
    def __init__(self, results: list[GateResult] | None = None):
        self._results = results or []
        self.calls = 0

    def run_all_gates(self, audit_report=None, code_changes=None):
        self.calls += 1
        return self._results


class FakeConfig(SwarmConfig):
    pass


def _make_pipeline(
    dag: FakeDag,
    *,
    config: SwarmConfig | None = None,
    auditor: FakeAuditor | None = None,
    gate_results: list[GateResult] | None = None,
    integrator: FakeIntegrator | None = None,
    registry: FakeTaskRegistry | None = None,
    progress: list[tuple[str, str]] | None = None,
) -> SwarmPipeline:
    cfg = config or SwarmConfig()
    return SwarmPipeline(
        config=cfg,
        workdir=Path("."),
        llm_config=None,
        orchestrator=FakeOrchestrator(),
        auditor=auditor,
        task_registry=registry or FakeTaskRegistry(),
        quality_gate=FakeQualityGate(gate_results),
        integrator=integrator or FakeIntegrator(),
        ltm=object(),
        get_worker_engine=lambda role: object(),
        progress_callback=((lambda stage, msg: progress.append((stage, msg))) if progress is not None else None),
    )


def _decomposition(dag: FakeDag):
    class _Dec:
        pass

    d = _Dec()
    d.dag = dag
    return d


@pytest.fixture(autouse=True)
def _stub_task_fn(monkeypatch):
    """隔离 _execute_task_fn：本测试只关心调度。"""

    async def fake_exec(self, task: SubTask) -> str:
        if getattr(task, "should_fail", False):
            raise RuntimeError("boom")
        return f"result-{task.task_id}"

    monkeypatch.setattr(SwarmPipeline, "_execute_task_fn", fake_exec)


@pytest.fixture(autouse=True)
def _stub_changes(monkeypatch):
    """让每个任务产出确定的一处文件变更。"""
    monkeypatch.setattr(
        pipeline_mod, "extract_file_changes", lambda result, meta: {f"{result}.py": "x"}
    )


class TestEmptyFlow:
    def test_no_tasks_still_runs_gate_and_commits(self):
        dag = FakeDag({})
        integ = FakeIntegrator()
        pipe = _make_pipeline(dag, integrator=integ)

        changes, report, _gates = asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        assert changes == {}
        assert report is None
        assert integ.events == ["start", "commit"]


class TestSuccessFlow:
    def test_single_task_collects_changes_and_commits(self):
        dag = FakeDag({"t1": {"id": "t1", "description": "do it"}})
        integ = FakeIntegrator()
        pipe = _make_pipeline(dag, integrator=integ)

        changes, _, _ = asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        assert "result-t1.py" in changes
        assert integ.events == ["start", "integrate", "commit"]
        assert integ.batches[0] == {"result-t1.py": "x"}

    def test_progress_callback_receives_messages(self):
        dag = FakeDag({"t1": {"id": "t1", "description": "d"}})
        progress: list[tuple[str, str]] = []
        pipe = _make_pipeline(dag, progress=progress)

        asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        stages = {s for s, _ in progress}
        assert "swarm" in stages
        assert any("已完成" in m for _, m in progress)

    def test_task_failure_is_swallowed_but_flow_continues(self):
        """单任务异常不得中断整条流水线（设计如此），且仍然提交事务。"""
        dag = FakeDag({"t1": {"id": "t1", "description": "d"}})
        registry = FakeTaskRegistry()
        integ = FakeIntegrator()
        pipe = _make_pipeline(dag, integrator=integ, registry=registry)

        async def fail_exec(task):
            raise RuntimeError("worker crashed")

        pipe._execute_task_fn = fail_exec  # type: ignore[method-assign]

        changes, _, _ = asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        assert changes == {}
        assert "commit" in integ.events
        assert "rollback" not in integ.events


class TestAudit:
    def test_auditor_runs_when_changes_exist(self):
        dag = FakeDag({"t1": {"id": "t1", "description": "d"}})
        auditor = FakeAuditor(passed=True)
        pipe = _make_pipeline(dag, auditor=auditor)

        asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        assert auditor.calls == 1

    def test_audit_failure_publishes_message(self):
        dag = FakeDag({"t1": {"id": "t1", "description": "d"}})
        auditor = FakeAuditor(passed=False)
        pipe = _make_pipeline(dag, auditor=auditor)

        asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        assert len(pipe.orchestrator.message_bus.published) == 1


class TestQualityGate:
    def test_critical_gate_failure_rolls_back(self):
        dag = FakeDag({"t1": {"id": "t1", "description": "d"}})
        integ = FakeIntegrator()
        gate = GateResult(passed=False, gate_name="security", severity="critical", failures=["bad"])
        pipe = _make_pipeline(dag, integrator=integ, gate_results=[gate])

        with pytest.raises(RuntimeError, match="关键质量门禁"):
            asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        assert integ.events[-1] == "rollback"

    def test_non_critical_gate_failure_still_commits(self):
        dag = FakeDag({"t1": {"id": "t1", "description": "d"}})
        integ = FakeIntegrator()
        gate = GateResult(passed=False, gate_name="style", severity="minor", warnings=["meh"])
        pipe = _make_pipeline(dag, integrator=integ, gate_results=[gate])

        _changes, _, gates = asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        assert integ.events[-1] == "commit"
        assert len(gates) == 1


class TestBudget:
    def test_budget_guard_validated_before_each_task(self):
        dag = FakeDag({"t1": {"id": "t1", "description": "d"}, "t2": {"id": "t2", "description": "d2"}})

        class _BG:
            def __init__(self):
                self.calls = 0

            def validate(self):
                self.calls += 1

        bg = _BG()
        pipe = _make_pipeline(dag)

        asyncio.run(pipe.execute("goal", "r1", _decomposition(dag), budget_guard=bg))

        assert bg.calls >= 1


class TestDependencyContext:
    def test_dependency_results_injected_into_task_metadata(self):
        dag = FakeDag({"t1": {"id": "t1", "description": "d"}})

        class _Reg(FakeTaskRegistry):
            def get_dependency_results(self, task_id):
                return {"t0": "upstream result"}

        registry = _Reg()
        pipe = _make_pipeline(dag, registry=registry)

        asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        task = registry.get_task("t1")
        assert task is not None
        assert task.metadata["dependency_context"] == {"t0": "upstream result"}


class TestDeadlockGuard:
    def test_no_ready_task_but_incomplete_breaks_loop(self):
        """DAG 永远不给就绪任务时，必须跳出循环而不是死等。"""

        class _StuckDag(FakeDag):
            def get_ready_tasks(self, completed):
                return []

            def is_complete(self, completed):
                return False

        dag = _StuckDag({"t1": {"id": "t1", "description": "d"}})
        integ = FakeIntegrator()
        pipe = _make_pipeline(dag, integrator=integ)

        changes, _, _ = asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        assert changes == {}
        assert integ.events[-1] == "commit"


class TestAuditRetry:
    def test_audit_failed_task_is_retried_within_limit(self):
        dag = FakeDag({})
        registry = FakeTaskRegistry()
        task = SubTask(task_id="t1", description="d")
        task.retry_count = 0
        registry._tasks["t1"] = task
        registry.status_by_id["t1"] = TaskStatus.AUDIT_FAILED

        class _Cfg(SwarmConfig):
            pass

        cfg = _Cfg()
        cfg.enable_auditor = True
        cfg.max_audit_retries = 3

        pipe = _make_pipeline(dag, config=cfg, auditor=FakeAuditor(passed=False), registry=registry)

        async def ok_exec(t):
            return "retried"

        pipe._execute_task_fn = ok_exec  # type: ignore[method-assign]

        # 需要一个 code_change 才会触发审计
        with_audit_dag = FakeDag({"t0": {"id": "t0", "description": "d"}})
        pipe.task_registry = registry

        _changes, _, _ = asyncio.run(pipe.execute("goal", "r1", _decomposition(with_audit_dag)))

        assert task.retry_count == 1
        assert task.metadata["audit_feedback"]

    def test_audit_retry_exhausted_raises(self):
        dag = FakeDag({"t0": {"id": "t0", "description": "d"}})
        registry = FakeTaskRegistry()
        task = SubTask(task_id="t1", description="d")
        task.retry_count = 99
        registry._tasks["t1"] = task
        registry.status_by_id["t1"] = TaskStatus.AUDIT_FAILED

        cfg = SwarmConfig()
        cfg.enable_auditor = True
        cfg.max_audit_retries = 2

        integ = FakeIntegrator()
        pipe = _make_pipeline(
            dag, config=cfg, auditor=FakeAuditor(passed=False), registry=registry, integrator=integ
        )

        with pytest.raises(RuntimeError, match="超过重试限制"):
            asyncio.run(pipe.execute("goal", "r1", _decomposition(dag)))

        assert integ.events[-1] == "rollback"

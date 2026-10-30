"""多引擎协同测试（确定性：注入假后端，不烧 LLM）"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from src.backends.base import BackendResult
from src.workflow.collaborate import VERDICT_APPROVE, VERDICT_NEEDS_FIX, Collaborator, parse_verdict

runner = CliRunner()


class FakeBackend:
    """按队列返回预设输出的假后端，并记录收到的 prompt"""

    def __init__(self, name: str, outputs: list[str]):
        self.name = name
        self._outputs = list(outputs)
        self.prompts: list[str] = []

    def run(self, goal: str, timeout: float = 900.0) -> BackendResult:
        self.prompts.append(goal)
        text = self._outputs.pop(0) if self._outputs else ""
        return BackendResult(engine=self.name, text=text, exit_code=0)


def factory_of(**backends: FakeBackend):
    def factory(name: str) -> FakeBackend:
        return backends[name]

    return factory


# ==========================================================================
# 结论解析（确定性，不靠语气）
# ==========================================================================


class TestParseVerdict:
    def test_approve(self):
        verdict, issues = parse_verdict(f"看起来没问题\n{VERDICT_APPROVE}")
        assert verdict == "APPROVE"
        assert issues == []

    def test_needs_fix_with_numbered_issues(self):
        text = "发现两个问题：\n1. 缺少单元测试\n2. 没有处理空输入\nVERDICT: NEEDS_FIX"
        verdict, issues = parse_verdict(text)

        assert verdict == "NEEDS_FIX"
        assert issues == ["缺少单元测试", "没有处理空输入"]

    def test_needs_fix_wins_over_approve(self):
        """两种都写时必须判为不通过，绝不放行"""
        text = f"{VERDICT_APPROVE}\n{VERDICT_NEEDS_FIX}"
        assert parse_verdict(text)[0] == "NEEDS_FIX"

    def test_unknown_when_no_marker(self):
        """没有结论标记 → UNKNOWN（不猜成通过）"""
        assert parse_verdict("我觉得还行")[0] == "UNKNOWN"

    def test_empty_text(self):
        assert parse_verdict("")[0] == "UNKNOWN"


# ==========================================================================
# 编排流程
# ==========================================================================


class TestCollaboratorFlow:
    def test_happy_path_three_phases(self):
        planner = FakeBackend("p", ["1. 建文件\n2. 写内容"])
        executor = FakeBackend("e", ["已创建 demo.txt"])
        reviewer = FakeBackend("r", ["核对无误\n" + VERDICT_APPROVE])

        result = Collaborator(
            "创建文件", planner="p", executor="e", reviewer="r",
            backend_factory=factory_of(p=planner, e=executor, r=reviewer),
        ).run()

        assert result.ok is True
        assert [p.phase for p in result.phases] == ["plan", "execute", "review"]
        assert result.plan.startswith("1. 建文件")
        assert result.final == "已创建 demo.txt"
        assert result.rounds == 0

    def test_prompts_carry_plan_and_draft(self):
        planner = FakeBackend("p", ["计划A"])
        executor = FakeBackend("e", ["结果B"])
        reviewer = FakeBackend("r", [VERDICT_APPROVE])

        Collaborator(
            "目标任务", planner="p", executor="e", reviewer="r",
            backend_factory=factory_of(p=planner, e=executor, r=reviewer),
        ).run()

        assert "计划A" in executor.prompts[0]      # 执行看得到计划
        assert "结果B" in reviewer.prompts[0]      # 审查看得到执行结果
        assert "目标任务" in reviewer.prompts[0]

    def test_need_fix_triggers_repair_and_re_review(self):
        planner = FakeBackend("p", ["计划A"])
        executor = FakeBackend("e", ["初稿", "修复后版本"])
        reviewer = FakeBackend("r", [
            "1. 缺少测试\n" + VERDICT_NEEDS_FIX,
            "补上了\n" + VERDICT_APPROVE,
        ])

        result = Collaborator(
            "任务", planner="p", executor="e", reviewer="r",
            max_repair_rounds=1,
            backend_factory=factory_of(p=planner, e=executor, r=reviewer),
        ).run()

        assert result.rounds == 1
        assert result.ok is True
        assert result.final == "修复后版本"
        assert "缺少测试" in executor.prompts[-1]   # 审查意见回灌给执行者

    def test_repair_rounds_are_capped(self):
        planner = FakeBackend("p", ["计划"])
        executor = FakeBackend("e", ["稿1", "稿2", "稿3", "稿4"])
        reviewer = FakeBackend("r", [VERDICT_NEEDS_FIX] * 10)

        result = Collaborator(
            "任务", planner="p", executor="e", reviewer="r",
            max_repair_rounds=2,
            backend_factory=factory_of(p=planner, e=executor, r=reviewer),
        ).run()

        assert result.rounds == 2          # 不会无限循环
        assert result.ok is False
        assert result.verdict == "NEEDS_FIX"

    def test_planner_failure_aborts_early_with_reason(self):
        planner = FakeBackend("p", [""])
        executor = FakeBackend("e", ["不该被调用"])
        reviewer = FakeBackend("r", [VERDICT_APPROVE])

        result = Collaborator(
            "任务", planner="p", executor="e", reviewer="r",
            backend_factory=factory_of(p=planner, e=executor, r=reviewer),
        ).run()

        assert result.ok is False
        assert result.issues and "规划阶段失败" in result.issues[0]
        assert executor.prompts == []      # 规划失败不继续烧执行

    def test_backend_exception_is_recorded_not_raised(self):
        class Boom:
            def run(self, goal, timeout=900.0):
                raise RuntimeError("引擎崩了")

        class Ok:
            def __init__(self, text):
                self.text = text
                self.prompts = []

            def run(self, goal, timeout=900.0):
                self.prompts.append(goal)
                return BackendResult(engine="ok", text=self.text, exit_code=0)

        executor = Ok("初稿")
        reviewer = Ok(VERDICT_APPROVE)

        result = Collaborator(
            "任务", planner="boom", executor="ok", reviewer="ok",
            backend_factory=lambda n: {"boom": Boom(), "ok": executor if n == "executor" else reviewer}[n],
        ).run()

        assert result.ok is False
        assert "引擎崩了" in result.phases[0].error

    def test_summary_lists_engines_and_verdict(self):
        planner = FakeBackend("codex", ["计划"])
        executor = FakeBackend("native", ["稿"])
        reviewer = FakeBackend("opencode", [VERDICT_APPROVE])

        result = Collaborator(
            "任务", planner="codex", executor="native", reviewer="opencode",
            backend_factory=factory_of(codex=planner, native=executor, opencode=reviewer),
        ).run()

        text = result.summary()
        assert "plan(codex)" in text and "execute(native)" in text and "review(opencode)" in text
        assert "APPROVE" in text


class TestCollaborateCli:
    def test_cli_exposes_engine_options(self):
        from src.cli.entrypoint import app as cli_app

        result = runner.invoke(cli_app, ["collaborate", "--help"])
        assert result.exit_code == 0
        # rich 按终端宽度断行 + ANSI 码（CI 无 TTY 宽度不同）→ 剥码去空白再断言
        import re as _re

        plain = _re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        compact = _re.sub(r"\s+", "", plain)
        for flag in ("--planner", "--executor", "--reviewer", "--rounds"):
            assert flag.replace("-", "") in compact.replace("-", ""), flag


class TestBackendCaching:
    """同一引擎跨阶段必须复用（实测三阶段各建一次引擎 → 世界模型重复初始化）"""

    def test_same_engine_name_reuses_one_backend(self):
        from src.workflow.collaborate import _default_factory

        factory = _default_factory(".", 5)
        first = factory("native")
        second = factory("native")

        assert first is second

    def test_different_names_get_different_backends(self, monkeypatch):
        from src.workflow import collaborate as mod

        created = []

        class _FakeNative:
            def __init__(self, **kw):
                created.append("native")

            def run(self, goal, timeout=900.0):
                return BackendResult(engine="native", text="x", exit_code=0)

        monkeypatch.setattr("src.backends.native.NativeBackend", _FakeNative)
        monkeypatch.setattr(
            "src.backends.registry.get_backend",
            lambda name, **kw: _FakeNative(),
        )

        factory = mod._default_factory(".", 5)
        native_backend = factory("native")
        codex_backend = factory("codex")
        again_native = factory("native")

        assert native_backend is not codex_backend     # 不同引擎 → 不同后端
        assert again_native is native_backend          # 同名引擎 → 复用

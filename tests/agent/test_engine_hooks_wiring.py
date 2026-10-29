"""引擎 ↔ Hook 接线测试（回归：hook_registry 2.5k 行在引擎里零调用点）

审计 P1-4 的事实：`src/hooks/` + `src/core/hook_registry/` 造好没人调，
配置里写 hook 等于写了一段不生效的配置。现在引擎在三个点接线：
SESSION_START / SESSION_END、PRE_TOOL_USE（可拒绝）、POST_TOOL_USE、TOOL_ERROR。
"""

from __future__ import annotations

import asyncio

import pytest

from src.agent.engine import AgentEngine
from src.core.hook_registry.enums import HookPoint, HookResult
from src.core.hook_registry.registry import (
    get_hook_point_specs,
    register_hook,
    unregister_hook,
)
from src.core.hook_registry.specs import FunctionHookSpec, HookExecutionResult
from src.tools_runtime.base import ToolResult


@pytest.fixture
def engine() -> AgentEngine:
    return AgentEngine()


@pytest.fixture(autouse=True)
def _clean_hooks():
    points = [HookPoint.PRE_TOOL_USE, HookPoint.POST_TOOL_USE, HookPoint.TOOL_ERROR,
              HookPoint.SESSION_START, HookPoint.SESSION_END]
    for point in points:
        unregister_hook(point)
    yield
    for point in points:
        unregister_hook(point)


def _register(point: HookPoint, handler, name: str = "test-hook") -> None:
    register_hook(point, FunctionHookSpec(point, handler, name=name))


class TestHookPointDispatch:
    def test_no_registered_hook_returns_none(self, engine: AgentEngine):
        assert engine._execute_hook_point("pre_tool_use", {"tool": "x"}) is None

    def test_registered_hook_is_invoked(self, engine: AgentEngine):
        seen: list[str] = []
        _register(HookPoint.PRE_TOOL_USE,
                  lambda ctx: (seen.append(ctx.get("tool")),
                               HookExecutionResult(result=HookResult.CONTINUE))[1])

        result = engine._execute_hook_point("pre_tool_use", {"tool": "FileReadTool"})
        assert seen == ["FileReadTool"]
        assert result.result == HookResult.CONTINUE

    def test_unknown_point_name_is_ignored(self, engine: AgentEngine):
        assert engine._execute_hook_point("not_a_real_point", {}) is None

    def test_hook_exception_does_not_break_flow(self, engine: AgentEngine):
        def boom(_ctx):
            raise RuntimeError("hook 内部炸了")

        _register(HookPoint.PRE_TOOL_USE, boom)
        # 不应抛异常：hook 出错只记录，不打断主流程
        engine._execute_hook_point("pre_tool_use", {"tool": "x"})


class TestToolExecutionHooks:
    def test_pre_hook_deny_blocks_tool_and_reports_reason(self, engine: AgentEngine):
        called: list[str] = []

        async def fake_execute(tool_name, tool_args):
            called.append(tool_name)
            return ToolResult(success=True, output="should not run")

        engine.tool_manager.execute_tool = fake_execute  # type: ignore[method-assign]
        _register(
            HookPoint.PRE_TOOL_USE,
            lambda ctx: HookExecutionResult(result=HookResult.DENY, message="路径受保护"),
        )

        result = asyncio.run(engine._execute_tool_with_hooks("BashTool", {"command": "rm -rf /"}))

        assert called == [], "被 hook 拒绝时工具绝不能被执行"
        assert result.success is False
        assert "路径受保护" in result.error

    def test_post_hook_receives_result_summary(self, engine: AgentEngine):
        events: list[dict] = []

        async def fake_execute(tool_name, tool_args):
            return ToolResult(success=True, output="hello")

        engine.tool_manager.execute_tool = fake_execute  # type: ignore[method-assign]
        _register(
            HookPoint.POST_TOOL_USE,
            lambda ctx: (events.append(dict(ctx.data)),
                         HookExecutionResult(result=HookResult.CONTINUE))[1],
        )

        result = asyncio.run(engine._execute_tool_with_hooks("FileReadTool", {"file_path": "a"}))

        assert result.success is True
        assert len(events) == 1
        assert events[0]["tool"] == "FileReadTool"
        assert events[0]["success"] is True
        assert events[0]["output"] == "hello"

    def test_tool_error_hook_fires_then_reraises(self, engine: AgentEngine):
        errors: list[str] = []

        async def failing_execute(tool_name, tool_args):
            raise OSError("磁盘炸了")

        engine.tool_manager.execute_tool = failing_execute  # type: ignore[method-assign]
        _register(
            HookPoint.TOOL_ERROR,
            lambda ctx: (errors.append(ctx.get("error")),
                         HookExecutionResult(result=HookResult.CONTINUE))[1],
        )

        with pytest.raises(OSError):
            asyncio.run(engine._execute_tool_with_hooks("FileWriteTool", {}))
        assert errors and "OSError" in errors[0]

    def test_multiple_specs_on_one_point_all_run(self, engine: AgentEngine):
        """1 点多 hook：注册表改成 1:N 后，两个 spec 都要执行"""
        seen: list[str] = []
        for name in ("h1", "h2"):
            _register(
                HookPoint.PRE_TOOL_USE,
                (lambda n: lambda ctx: (seen.append(n),
                                        HookExecutionResult(result=HookResult.CONTINUE))[1])(name),
                name=name,
            )
        engine._execute_hook_point("pre_tool_use", {"tool": "x"})
        assert seen == ["h1", "h2"]
        assert len(get_hook_point_specs(HookPoint.PRE_TOOL_USE)) == 2


class TestSessionHooksViaRun:
    def test_session_start_and_end_fire_around_run(self, engine: AgentEngine, monkeypatch):
        fired: list[str] = []
        _register(HookPoint.SESSION_START,
                  lambda ctx: (fired.append("start"),
                               HookExecutionResult(result=HookResult.CONTINUE))[1])
        _register(HookPoint.SESSION_END,
                  lambda ctx: (fired.append("end"),
                               HookExecutionResult(result=HookResult.CONTINUE))[1])

        async def fake_core(**kwargs):
            return {"session": _FakeSession()}

        monkeypatch.setattr(engine, "_load_extended_tools", _async_none)
        monkeypatch.setattr(engine, "_run_agent_core", fake_core)
        monkeypatch.setattr(engine, "_persist_session", lambda _s: None)

        asyncio.run(engine.run("做点事"))
        assert fired == ["start", "end"]

    def test_session_end_fires_even_when_run_fails(self, engine: AgentEngine, monkeypatch):
        fired: list[str] = []
        _register(HookPoint.SESSION_END,
                  lambda ctx: (fired.append("end"),
                               HookExecutionResult(result=HookResult.CONTINUE))[1])

        async def boom(**kwargs):
            raise RuntimeError("核心炸了")

        monkeypatch.setattr(engine, "_load_extended_tools", _async_none)
        monkeypatch.setattr(engine, "_run_agent_core", boom)

        with pytest.raises(RuntimeError):
            asyncio.run(engine.run("做点事"))
        assert fired == ["end"], "失败的轮次也必须发 SESSION_END（否则 hook 侧状态会泄漏）"


class _FakeSession:
    final_result = "ok"
    steps: list = []
    total_tokens = 0
    is_complete = True


async def _async_none(*args, **kwargs):
    return None


class TestFailureHintSurfaced:
    """收尾消息不能只说"达到最大迭代次数"——要把最后一次失败原因带出来

    真实 E2E 发现的：PRE_TOOL_USE 拒绝 BashTool 后模型反复重试，最终只输出
    "达到最大迭代次数，任务可能未完成。"，用户看不到"被拒"这个真实原因。
    """

    def test_helper_returns_last_failure_result(self):
        from src.agent.engine_loop import _last_failure_hint
        from src.agent.engine_session_data import AgentStep

        class _Session:
            steps = [
                AgentStep("execute", "a", "ok", True),
                AgentStep("execute", "b", "Hook 拒绝执行 BashTool: 禁止 shell", False),
            ]

        assert "Hook 拒绝执行 BashTool" in _last_failure_hint(_Session())

    def test_helper_returns_empty_when_all_success(self):
        from src.agent.engine_loop import _last_failure_hint
        from src.agent.engine_session_data import AgentStep

        class _Session:
            steps = [AgentStep("execute", "a", "ok", True)]

        assert _last_failure_hint(_Session()) == ""

    def test_deny_result_tells_model_not_to_retry(self, engine: AgentEngine):
        import asyncio as _asyncio

        async def fake_execute(tool_name, tool_args):
            raise AssertionError("被拒绝的工具不应被执行")

        engine.tool_manager.execute_tool = fake_execute  # type: ignore[method-assign]
        _register(
            HookPoint.PRE_TOOL_USE,
            lambda ctx: HookExecutionResult(result=HookResult.DENY, message="验证用拒绝"),
        )
        result = _asyncio.run(engine._execute_tool_with_hooks("BashTool", {"command": "echo hi"}))
        assert "不要用相同参数重试" in result.error

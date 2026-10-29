"""Hook 注册表 1:N 修复（审计 P1-1）+ HookPoint 可读值（P1-2）

修复前：`_REGISTRY` 是 1:1 字典，重复注册只打 warning 就覆盖
→ 配置里第二个 hook 永远不生效，日志却报 "Loaded N hooks"（静默说谎）。
"""

from __future__ import annotations

from src.core.hook_registry.enums import HookPoint
from src.core.hook_registry.registry import (
    _REGISTRY,
    execute_hook,
    get_all_specs,
    get_hook_point_spec,
    get_hook_point_specs,
    get_registered_hook_lists,
    get_registered_hooks,
    register_hook,
    unregister_hook,
)
from src.core.hook_registry.specs import (
    FunctionHookSpec,
    HookContext,
    HookExecutionResult,
    HookResult,
)


def _spec(name: str, recorder: list[str], result: HookResult = HookResult.CONTINUE):
    def handler(_ctx):
        recorder.append(name)
        return HookExecutionResult(result=result, message=f"{name}-ran")

    return FunctionHookSpec(hook_point=HookPoint.PRE_TOOL_USE, handler=handler, name=name)


class TestHookPointValues:
    """P1-2：值必须是可读名，不能是 auto() 生成的 '10'"""

    def test_values_are_readable_names(self):
        for point in HookPoint:
            assert point.value == point.name.lower(), f"{point.name} 的 value 不可读: {point.value!r}"

    def test_no_numeric_values(self):
        numeric = [p.name for p in HookPoint if p.value.isdigit()]
        assert numeric == [], f"仍有数字枚举值: {numeric}"

    def test_str_comparison_works(self):
        assert HookPoint.SESSION_START == "session_start"


class TestMultiRegistration:
    def setup_method(self):
        _REGISTRY.clear()

    def teardown_method(self):
        _REGISTRY.clear()

    def test_two_hooks_on_same_point_both_register(self):
        calls: list[str] = []
        register_hook(HookPoint.PRE_TOOL_USE, _spec("a", calls))
        register_hook(HookPoint.PRE_TOOL_USE, _spec("b", calls))

        assert len(get_hook_point_specs(HookPoint.PRE_TOOL_USE)) == 2
        assert len(get_all_specs()) == 2

    def test_both_hooks_actually_execute(self):
        """核心回归：修复前只有最后一个会跑"""
        calls: list[str] = []
        register_hook(HookPoint.PRE_TOOL_USE, _spec("a", calls))
        register_hook(HookPoint.PRE_TOOL_USE, _spec("b", calls))

        execute_hook(HookPoint.PRE_TOOL_USE, HookContext(hook_point=HookPoint.PRE_TOOL_USE, data={"tool_name": "t", "tool_input": "{}"}))

        assert calls == ["a", "b"], f"两个 hook 都该执行，实际: {calls}"

    def test_same_name_replaces_not_duplicates(self):
        calls: list[str] = []
        register_hook(HookPoint.PRE_TOOL_USE, _spec("a", calls))
        register_hook(HookPoint.PRE_TOOL_USE, _spec("a", calls))

        assert len(get_hook_point_specs(HookPoint.PRE_TOOL_USE)) == 1

    def test_replace_flag_clears_all(self):
        calls: list[str] = []
        register_hook(HookPoint.PRE_TOOL_USE, _spec("a", calls))
        register_hook(HookPoint.PRE_TOOL_USE, _spec("b", calls), replace=True)

        assert [s.name for s in get_hook_point_specs(HookPoint.PRE_TOOL_USE)] == ["b"]

    def test_deny_short_circuits(self):
        calls: list[str] = []
        register_hook(HookPoint.PRE_TOOL_USE, _spec("a", calls))
        register_hook(HookPoint.PRE_TOOL_USE, _spec("deny", calls, HookResult.DENY))
        register_hook(HookPoint.PRE_TOOL_USE, _spec("c", calls))

        result = execute_hook(HookPoint.PRE_TOOL_USE, HookContext(hook_point=HookPoint.PRE_TOOL_USE, data={"tool_name": "t", "tool_input": "{}"}))

        assert result.result == HookResult.DENY
        assert calls == ["a", "deny"], f"DENY 后应短路，实际: {calls}"

    def test_single_hook_behavior_unchanged(self):
        calls: list[str] = []
        register_hook(HookPoint.PRE_TOOL_USE, _spec("only", calls))

        execute_hook(HookPoint.PRE_TOOL_USE, HookContext(hook_point=HookPoint.PRE_TOOL_USE, data={"tool_name": "t", "tool_input": "{}"}))

        assert calls == ["only"]
        assert get_hook_point_spec(HookPoint.PRE_TOOL_USE).name == "only"

    def test_legacy_accessors_still_work(self):
        calls: list[str] = []
        register_hook(HookPoint.PRE_TOOL_USE, _spec("a", calls))
        register_hook(HookPoint.PRE_TOOL_USE, _spec("b", calls))

        # 旧 API：每点返回最后一个（与旧版语义一致）
        assert get_registered_hooks()[HookPoint.PRE_TOOL_USE].name == "b"
        # 新 API：拿到全部
        assert [s.name for s in get_registered_hook_lists()[HookPoint.PRE_TOOL_USE]] == ["a", "b"]

    def test_unregister_removes_all_for_point(self):
        calls: list[str] = []
        register_hook(HookPoint.PRE_TOOL_USE, _spec("a", calls))
        register_hook(HookPoint.PRE_TOOL_USE, _spec("b", calls))

        assert unregister_hook(HookPoint.PRE_TOOL_USE) is True
        assert get_hook_point_specs(HookPoint.PRE_TOOL_USE) == []

    def test_unregistered_point_returns_continue(self):
        result = execute_hook(
            HookPoint.POST_LLM_CALL,
            HookContext(hook_point=HookPoint.POST_LLM_CALL, data={}),
        )
        assert result.result == HookResult.CONTINUE

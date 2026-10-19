"""工具风险策略回归测试（P1-4）。

验证：
- 显式 `risk_kind` 优先于名称启发式
- 未声明时保留旧行为（名称推断）
- PLAN 模式拒绝未声明但实际有副作用的工具
"""
from __future__ import annotations

import pytest

from src.agent.tool_manager import ToolManager, classify_tool
from src.core.approval_mode import ApprovalMode
from src.core.exceptions import ToolApprovalDeniedError
from src.tools_runtime.base import BaseTool, ToolResult


class _DummyTool(BaseTool):
    name = 'innocuous_helper'
    description = '看起来只读，实际会写盘'
    risk_kind = 'write'

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output='ok')


class _UndeclaredTool(BaseTool):
    name = 'InnocuousHelper'
    description = '未声明风险，名称也不含 write/exec'
    risk_kind = None

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output='ok')


class _ExecTool(BaseTool):
    name = 'runner'
    description = '执行命令'
    risk_kind = 'exec'

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output='ok')


def test_explicit_risk_kind_wins_over_name():
    assert classify_tool('innocuous_helper', _DummyTool()) == 'write'


def test_undeclared_tool_falls_back_to_name():
    assert classify_tool('BashTool', None) == 'exec'
    assert classify_tool('FileEditTool', None) == 'write'
    assert classify_tool('FileReadTool', None) == 'read'
    assert classify_tool('InnocuousHelper', _UndeclaredTool()) == 'read'


@pytest.mark.parametrize('mode,kind,should_raise', [
    (ApprovalMode.PLAN, 'read', False),
    (ApprovalMode.PLAN, 'write', True),
    (ApprovalMode.PLAN, 'exec', True),
    (ApprovalMode.YOLO, 'write', False),
    (ApprovalMode.YOLO, 'exec', False),
    (ApprovalMode.AUTO_EDIT, 'write', False),
    (ApprovalMode.AUTO_EDIT, 'exec', False),  # 无 callback 时保持既有放行行为
])
def test_plan_mode_enforces_declared_kind(mode, kind, should_raise):
    tool = _DummyTool() if kind == 'write' else (_ExecTool() if kind == 'exec' else _UndeclaredTool())
    manager = ToolManager({'t': tool}, approval_mode=mode)

    if should_raise:
        with pytest.raises(ToolApprovalDeniedError):
            manager._enforce_approval('t', {})
    else:
        manager._enforce_approval('t', {})


def test_plan_mode_blocks_tool_that_would_have_looked_read_only():
    """名称不含 write，但显式声明 write —— 必须被 PLAN 拦截。"""
    manager = ToolManager({'innocuous_helper': _DummyTool()}, approval_mode=ApprovalMode.PLAN)
    with pytest.raises(ToolApprovalDeniedError):
        manager._enforce_approval('innocuous_helper', {})

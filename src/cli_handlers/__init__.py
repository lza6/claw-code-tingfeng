"""CLI 命令处理器 - 模块化版本（v0.16.0 重构）

从单文件 cli_handlers.py 拆分为多个模块，提升可维护性。
"""
from __future__ import annotations

import argparse
from collections.abc import Callable

from ..core.models import CommandResult
from ..workflow.cli_handler import handle_workflow
from .display import handle_cost_report

# 命令处理器类型
CommandHandler = Callable[[argparse.Namespace], CommandResult]


# 命令注册表
COMMAND_REGISTRY: dict[str, CommandHandler] = {
    'cost-report': handle_cost_report,
    'workflow': handle_workflow,
}


def get_command_handler(command: str) -> CommandHandler | None:
    """获取命令处理器"""
    return COMMAND_REGISTRY.get(command)


def get_available_commands() -> list[str]:
    """获取可用命令列表"""
    return list(COMMAND_REGISTRY.keys())



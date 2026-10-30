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
    'reason': lambda args: _handle_reason_wrapper(args),
}


def _handle_reason_wrapper(args: argparse.Namespace) -> "CommandResult":
    """reason 命令包装：reason_handler 的 cmd_reason 输出文本，转 CommandResult"""
    import contextlib
    import io

    from .reason_handler import cmd_reason

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            # cmd_reason 接收 argv 列表；从 Namespace 还原
            argv = [args.command]
            if getattr(args, "reason_pattern", None):
                argv = [args.reason_pattern, args.reason_task]
                if getattr(args, "reason_conclusion", None):
                    argv += ["--conclusion", args.reason_conclusion]
                if getattr(args, "reason_branching", 3) != 3:
                    argv += ["--branching", str(args.reason_branching)]
                if getattr(args, "reason_depth", 2) != 2:
                    argv += ["--depth", str(args.reason_depth)]
                if getattr(args, "reason_rounds", 2) != 2:
                    argv += ["--rounds", str(args.reason_rounds)]
                if getattr(args, "reason_max_iterations", 8) != 8:
                    argv += ["--max-iterations", str(args.reason_max_iterations)]
                if getattr(args, "reason_json", False):
                    argv += ["--json"]
            code = cmd_reason(argv[1:] if len(argv) > 1 else argv)
        return CommandResult(output=buf.getvalue(), exit_code=code)
    except SystemExit as e:
        # argparse 错误
        return CommandResult(output=buf.getvalue(), exit_code=int(e.code or 1))


def get_command_handler(command: str) -> CommandHandler | None:
    """获取命令处理器"""
    return COMMAND_REGISTRY.get(command)


def get_available_commands() -> list[str]:
    """获取可用命令列表"""
    return list(COMMAND_REGISTRY.keys())

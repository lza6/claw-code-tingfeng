"""交互式 CLI REPL — 类 Claude Code / Codex 的聊天界面

核心功能:
- 启动后进入交互式对话循环
- 集成 AgentEngine 完成实际编程任务
- 内置命令: /help, /exit, /clear, /model, /cost, /status, /doctor
- 流式输出 LLM 响应
- Ctrl+C 中止当前任务，再次按退出
- 底部 HUD 状态栏显示 token/成本信息
- 历史记录支持（readline）

本模块已被拆分为以下子模块:
- repl_session.py: ReplSession 类核心逻辑
- repl_task.py: 任务执行逻辑
- repl_handlers.py: 命令处理逻辑
- repl_commands.py: 命令实现

向后兼容性: 所有原有 API 导出保持不变
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .repl_session import ReplSession


def start_repl(
    workdir: Path | None = None,
    max_iterations: int = 10,
    use_textual_tui: bool = False,
    project_ctx: Any = None,
) -> int:
    """启动交互式 REPL

    参数:
        workdir: 工作目录
        max_iterations: 最大迭代次数
        use_textual_tui: 是否使用 Textual TUI 全屏仪表盘
        project_ctx: 项目上下文 (可选，用于共享 .clawd 目录)

    返回:
        退出码
    """
    if use_textual_tui:
        from .textual_dashboard import start_textual_tui
        workdir_str = str(workdir) if workdir else None
        return start_textual_tui(
            workdir=workdir_str,
            max_iterations=max_iterations,
        )

    session = ReplSession(
        workdir=workdir,
        max_iterations=max_iterations,
        project_ctx=project_ctx,
    )
    return session.run()


# ─── 向后兼容导出 (测试文件和其他模块依赖这些) ───────────────────────
from . import command_registry  # noqa: E402, F401, I001

from .repl_commands import (  # noqa: E402, F401
    _print,
    _handle_help,
    _handle_version,
    _handle_doctor,
    _handle_tools,
    _handle_cost,
    _handle_status,
    BUILTIN_COMMANDS,
)

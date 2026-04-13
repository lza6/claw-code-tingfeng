"""Aider 风格命令处理器 — 扩展 Clawd Code 命令系统

借鉴 Aider 的命令设计，新增以下命令:
- /add: 添加文件到聊天
- /drop: 从聊天移除文件
- /web: 搜索网页
- /run: 执行 shell 命令
- /test: 运行测试
- /lint: 运行 linter
- /refactor: 代码重构
- /summarize: 总结代码库
- /goto: 跳转到文件/行

用法:
    from src.cli.aider_commands import AiderCommandHandler

    handler = AiderCommandHandler()
    handler.register_to(command_registry)

注意: 此模块已拆分为多个子模块以便于维护。
如需直接访问命令实现，请使用:
    from src.cli.aider_commands_base import AiderCommandHandler
    from src.cli.aider_commands_registry import register_aider_commands
"""
from __future__ import annotations

import logging

# 向后兼容: 从子模块重新导出所有公共接口
from .aider_commands_base import (
    AiderCommandHandler,
    get_aider_command_handler,
)
from .aider_commands_registry import register_aider_commands

logger = logging.getLogger(__name__)

# 保持原有导入路径兼容
_aider_command_handler: AiderCommandHandler | None = None

# 确保兼容的模块级别别名
__all__ = [
    "AiderCommandHandler",
    "get_aider_command_handler",
    "register_aider_commands",
]

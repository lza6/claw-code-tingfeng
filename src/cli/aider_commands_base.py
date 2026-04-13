"""Aider 命令处理器基类

此模块包含 AiderCommandHandler 基类定义和单例函数。
命令实现已拆分到以下模块:
- aider_commands_file.py: 文件操作
- aider_commands_execution.py: 执行命令
- aider_commands_git.py: Git 命令
- aider_commands_model.py: 模型配置
- aider_commands_info.py: 信息查询

用法:
    from src.cli.aider_commands_base import AiderCommandHandler

    handler = AiderCommandHandler()
    handler.register_to(command_registry)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 导入各模块的命令实现
from . import (
    aider_commands_execution,
    aider_commands_file,
    aider_commands_git,
    aider_commands_info,
    aider_commands_model,
)


class AiderCommandHandler:
    """Aider 风格命令处理器

    提供 Aider 特色的命令实现，兼容现有的 command_registry。
    """

    def __init__(self, engine_ref: Any | None = None):
        self.engine_ref = engine_ref
        self._chat_fnames: set = set()
        self._read_only_fnames: set = set()
        self._thinking_enabled: bool = True
        self._thinking_tokens: int = 16000
        self._subtree_path: str | None = None

    def set_engine(self, engine: Any) -> None:
        """设置引擎引用"""
        self.engine_ref = engine

    def set_chat_files(self, fnames: set, read_only_fnames: set) -> None:
        """设置当前聊天文件列表"""
        self._chat_fnames = fnames
        self._read_only_fnames = read_only_fnames

    # ---------- 代理到各子模块命令实现 ----------

    # 文件操作命令
    cmd_add = aider_commands_file.cmd_add
    cmd_drop = aider_commands_file.cmd_drop
    cmd_read = aider_commands_file.cmd_read
    cmd_edit = aider_commands_file.cmd_edit
    cmd_subtree = aider_commands_file.cmd_subtree

    # 执行命令
    cmd_run = aider_commands_execution.cmd_run
    cmd_shell = aider_commands_execution.cmd_shell
    cmd_test = aider_commands_execution.cmd_test
    cmd_lint = aider_commands_execution.cmd_lint

    # Git 命令
    cmd_git = aider_commands_git.cmd_git
    cmd_undo = aider_commands_git.cmd_undo
    cmd_diff = aider_commands_git.cmd_diff
    cmd_commit = aider_commands_git.cmd_commit

    # 模型命令
    cmd_model = aider_commands_model.cmd_model
    cmd_editor_model = aider_commands_model.cmd_editor_model
    cmd_weak_model = aider_commands_model.cmd_weak_model
    cmd_chat_mode = aider_commands_model.cmd_chat_mode
    cmd_thinking = aider_commands_model.cmd_thinking
    cmd_cache = aider_commands_model.cmd_cache
    cmd_map = aider_commands_model.cmd_map

    # 信息命令
    cmd_web = aider_commands_info.cmd_web
    cmd_tokens = aider_commands_info.cmd_tokens
    cmd_browse = aider_commands_info.cmd_browse


_aider_command_handler: AiderCommandHandler | None = None


def get_aider_command_handler(engine: Any = None) -> AiderCommandHandler:
    """获取 Aider 命令处理器实例"""
    global _aider_command_handler
    if _aider_command_handler is None:
        _aider_command_handler = AiderCommandHandler(engine)
    return _aider_command_handler

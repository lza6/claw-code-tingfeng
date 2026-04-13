"""Aider 命令注册

此模块包含将 Aider 风格命令注册到 command_registry 的函数。
"""
from __future__ import annotations

import logging
from typing import Any

from .aider_commands_base import get_aider_command_handler

logger = logging.getLogger(__name__)


def register_aider_commands(registry: Any, engine: Any = None) -> None:
    """将 Aider 风格命令注册到 command_registry

    Args:
        registry: CommandRegistry 实例
        engine: AgentEngine 实例
    """
    handler = get_aider_command_handler(engine)
    if engine:
        handler.set_engine(engine)

    # 文件操作命令
    registry.register(
        "/add",
        lambda args: handler.cmd_add(args)[1],
        "添加文件到聊天",
        category="文件",
    )

    registry.register(
        "/drop",
        lambda args: handler.cmd_drop(args)[1],
        "从聊天移除文件",
        category="文件",
    )

    # 执行命令
    registry.register(
        "/run",
        lambda args: handler.cmd_run(args)[1],
        "执行 shell 命令",
        category="执行",
        aliases=["/!"],
    )

    registry.register(
        "/shell",
        lambda args: handler.cmd_shell(args)[1],
        "启动交互式 shell",
        category="执行",
    )

    # Git 命令
    registry.register(
        "/git",
        lambda args: handler.cmd_git(args)[1],
        "Git 快捷命令",
        category="Git",
        aliases=["/g"],
    )

    # 读写命令
    registry.register(
        "/read",
        lambda args: handler.cmd_read(args)[1],
        "读取文件内容",
        category="文件",
    )

    registry.register(
        "/edit",
        lambda args: handler.cmd_edit(args)[1],
        "编辑文件（行号编辑）",
        category="文件",
    )

    # 测试和 Lint
    registry.register(
        "/test",
        lambda args: handler.cmd_test(args)[1],
        "运行测试",
        category="执行",
    )

    registry.register(
        "/lint",
        lambda args: handler.cmd_lint(args)[1],
        "运行代码检查",
        category="执行",
    )

    # Web 功能
    registry.register(
        "/web",
        lambda args: handler.cmd_web(args)[1],
        "搜索网页",
        category="信息",
    )

    # Git 操作
    registry.register(
        "/undo",
        lambda args: handler.cmd_undo(args)[1],
        "撤销上一次 AI 修改",
        category="Git",
    )

    registry.register(
        "/diff",
        lambda args: handler.cmd_diff(args)[1],
        "显示未提交的变更",
        category="Git",
    )

    registry.register(
        "/commit",
        lambda args: handler.cmd_commit(args)[1],
        "提交当前变更",
        category="Git",
    )

    # 模型控制
    registry.register(
        "/model",
        lambda args: handler.cmd_model(args)[1],
        "显示/切换模型",
        category="模型",
    )

    # 高级功能
    registry.register(
        "/thinking",
        lambda args: handler.cmd_thinking(args)[1],
        "控制思考过程显示",
        category="高级",
    )

    registry.register(
        "/cache",
        lambda args: handler.cmd_cache(args)[1],
        "控制缓存行为",
        category="高级",
    )

    registry.register(
        "/map",
        lambda args: handler.cmd_map(args)[1],
        "显示/设置代码地图详细程度",
        category="高级",
    )

    registry.register(
        "/subtree",
        lambda args: handler.cmd_subtree(args)[1],
        "限制文件操作范围到子目录",
        category="高级",
    )

    # ---------- Aider 特色增强命令 (v0.40.0 整合) ----------

    # Switch 模型命令
    registry.register(
        "/editor-model",
        lambda args: handler.cmd_editor_model(args)[1],
        "切换编辑器模型",
        category="模型",
    )

    registry.register(
        "/weak-model",
        lambda args: handler.cmd_weak_model(args)[1],
        "切换弱模型 (用于摘要/commit)",
        category="模型",
    )

    # Chat mode 切换
    registry.register(
        "/chat-mode",
        lambda args: handler.cmd_chat_mode(args)[1],
        "切换聊天模式 (ask/code/architect/context)",
        category="高级",
    )

    # Token 预算查看
    registry.register(
        "/tokens",
        lambda args: handler.cmd_tokens(args)[1],
        "查看当前上下文 token 使用情况",
        category="诊断",
    )

    # 浏览器功能
    registry.register(
        "/browse",
        lambda args: handler.cmd_browse(args)[1],
        "抓取网页并转换为 Markdown",
        category="信息",
    )

    logger.info("Aider v0.40.0 风格命令注册完成")

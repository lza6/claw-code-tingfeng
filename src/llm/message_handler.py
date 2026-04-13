"""Message Handler — 消息处理模块

借鉴 Aider sendchat.py 的消息处理逻辑:
1. 消息交替验证
2. 消息角色修正
3. 消息格式化

使用:
    from src.llm.message_handler import (
        ensure_alternating_roles,
        sanity_check_messages,
        format_messages_for_llm,
    )
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def sanity_check_messages(messages: list[dict[str, Any]]) -> bool:
    """检查消息是否正确交替 user/assistant 角色。

    system 消息可以出现在任意位置。
    同时验证最后一条非 system 消息来自 user。

    参数:
        messages: 消息字典列表，每条包含 'role' 和 'content'

    返回:
        True 如果格式合法
    """
    last_role: str | None = None
    last_non_system_role: str | None = None

    for msg in messages:
        role = msg.get('role')
        if role == 'system':
            continue

        if last_role and role == last_role:
            logger.warning(
                f'消息角色未正确交替: 连续出现两次 "{role}" 角色',
            )
            return False

        last_role = role
        last_non_system_role = role

    return last_non_system_role == 'user'


def ensure_alternating_roles(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """确保消息交替出现 'assistant' 和 'user' 角色。

    当发现连续相同角色时，插入空消息的相反角色。

    参数:
        messages: 消息字典列表

    返回:
        修正后的消息列表
    """
    if not messages:
        return messages

    fixed_messages: list[dict[str, Any]] = []
    prev_role: str | None = None

    for msg in messages:
        current_role = msg.get('role')

        if current_role == prev_role:
            if current_role == 'user':
                fixed_messages.append({'role': 'assistant', 'content': ''})
            else:
                fixed_messages.append({'role': 'user', 'content': ''})

        fixed_messages.append(msg)
        prev_role = current_role

    return fixed_messages


def dedup_consecutive_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并连续相同角色的消息内容为一条。

    与 ensure_alternating_roles 相反：不是插入空消息分隔，
    而是将连续的同角色消息合并，减少消息总数。

    参数:
        messages: 消息字典列表

    返回:
        合并后的消息列表
    """
    if not messages:
        return messages

    merged: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get('role')
        content = msg.get('content', '')

        if merged and merged[-1].get('role') == role:
            # 合并内容
            prev_content = merged[-1].get('content', '')
            merged[-1] = {
                'role': role,
                'content': prev_content + '\n\n' + content if prev_content else content,
            }
        else:
            merged.append({'role': role, 'content': content})

    return merged


def sanitize_messages(
    messages: list[dict[str, Any]],
    *,
    strategy: str = 'insert_empty',
) -> list[dict[str, Any]]:
    """消息清洗入口 — 根据策略修正消息格式。

    参数:
        messages: 消息字典列表
        strategy: 修正策略
            - 'insert_empty': 插入空消息分隔（默认）
            - 'merge': 合并连续同角色消息
            - 'check_only': 仅检查不修正

    返回:
        修正后的消息列表

    抛出:
        ValueError: 当 strategy='check_only' 且消息格式不合规时
    """
    if strategy == 'check_only':
        if not sanity_check_messages(messages):
            raise ValueError('消息格式不合规：user/assistant 角色未正确交替')
        return messages

    if strategy == 'merge':
        return dedup_consecutive_messages(messages)

    # 默认: insert_empty
    return ensure_alternating_roles(messages)


def format_messages_for_llm(
    messages: list[dict[str, Any]],
    *,
    sanitize: bool = True,
    max_length: int = 100000,
) -> list[dict[str, Any]]:
    """为 LLM 格式化消息

    参数:
        messages: 原始消息列表
        sanitize: 是否进行消息清洗
        max_length: 单条消息最大长度

    返回:
        格式化后的消息列表
    """
    formatted = []

    for msg in messages:
        role = msg.get('role', 'user')
        content = msg.get('content', '')

        # 截断过长内容
        if len(content) > max_length:
            content = content[:max_length] + f"\n... [truncated {len(content) - max_length} chars]"

        formatted.append({
            'role': role,
            'content': content,
        })

    # 可选：清洗消息
    if sanitize:
        formatted = ensure_alternating_roles(formatted)

    return formatted


def extract_system_prompt(messages: list[dict[str, Any]]) -> str | None:
    """从消息中提取系统提示词

    参数:
        messages: 消息列表

    返回:
        系统提示词或 None
    """
    for msg in messages:
        if msg.get('role') == 'system':
            return msg.get('content')
    return None


def has_tool_calls(messages: list[dict[str, Any]]) -> bool:
    """检查消息列表中是否有工具调用

    参数:
        messages: 消息列表

    返回:
        是否有工具调用
    """
    return any(msg.get('role') == 'assistant' and msg.get('tool_calls') for msg in messages)


def count_messages_by_role(messages: list[dict[str, Any]]) -> dict[str, int]:
    """统计各角色的消息数量

    参数:
        messages: 消息列表

    返回:
        角色 -> 数量 的字典
    """
    counts: dict[str, int] = {}
    for msg in messages:
        role = msg.get('role', 'unknown')
        counts[role] = counts.get(role, 0) + 1
    return counts


def get_last_user_message(messages: list[dict[str, Any]]) -> str | None:
    """获取最后一条用户消息

    参数:
        messages: 消息列表

    返回:
        最后一条用户消息的内容或 None
    """
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            return msg.get('content')
    return None


# ==================== 便捷函数 ====================

def validate_and_fix_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """验证并尝试修复消息列表

    参数:
        messages: 消息列表

    返回:
        (修复后的消息, 是否需要修复)
    """
    is_valid = sanity_check_messages(messages)
    if is_valid:
        return messages, False

    fixed = ensure_alternating_roles(messages)
    return fixed, True


# 导出
__all__ = [
    "count_messages_by_role",
    "dedup_consecutive_messages",
    "ensure_alternating_roles",
    "extract_system_prompt",
    "format_messages_for_llm",
    "get_last_user_message",
    "has_tool_calls",
    "sanitize_messages",
    "sanity_check_messages",
    "validate_and_fix_messages",
]

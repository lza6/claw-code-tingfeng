"""消息角色修正模块 — 从 Aider sendchat.py 移植

确保发送给 LLM 的消息列表中 user/assistant 角色交替出现。
某些 LLM 提供商（Anthropic, OpenAI）要求消息严格交替，否则会报错。

核心功能:
- ensure_alternating_roles(): 自动插入空消息修正连续相同角色
- sanity_check_messages(): 验证消息格式是否合规
- dedup_consecutive_messages(): 合并连续相同角色的消息内容
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 敏感模式定义
SENSITIVE_PATTERNS = {
    "API_KEY": re.compile(r'(?i)(api[_-]?key|secret|token|password|auth|credential)["\s:=]+[A-Za-z0-9_\-\.]{16,}'),
    "IPV4": re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'),
    "EMAIL": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
}


def scrub_sensitive_data(content: str | Any) -> str | Any:
    """脱敏敏感数据"""
    if not isinstance(content, str):
        return content

    scrubbed = content
    for name, pattern in SENSITIVE_PATTERNS.items():
        scrubbed = pattern.sub(f"[[REDACTED_{name}]]", scrubbed)
    return scrubbed


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
                '消息角色未正确交替 user/assistant，'
                '连续出现两次 "%s" 角色。考虑调用 ensure_alternating_roles() 修复。',
                role,
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
    scrub_sensitive: bool = True,
) -> list[dict[str, Any]]:
    """消息清洗入口 — 根据策略修正消息格式并脱敏。

    参数:
        messages: 消息字典列表
        strategy: 修正策略
            - 'insert_empty': 插入空消息分隔（默认，适合 Anthropic/OpenAI）
            - 'merge': 合并连续同角色消息
            - 'check_only': 仅检查不修正
        scrub_sensitive: 是否执行敏感数据脱敏

    返回:
        修正并脱敏后的消息列表

    抛出:
        ValueError: 当 strategy='check_only' 且消息格式不合规时
    """
    if strategy == 'check_only':
        if not sanity_check_messages(messages):
            raise ValueError('消息格式不合规：user/assistant 角色未正确交替')
        processed = messages
    elif strategy == 'merge':
        processed = dedup_consecutive_messages(messages)
    else:
        # 默认: insert_empty
        processed = ensure_alternating_roles(messages)

    # 脱敏处理
    if scrub_sensitive:
        for msg in processed:
            if 'content' in msg:
                msg['content'] = scrub_sensitive_data(msg['content'])

    return processed

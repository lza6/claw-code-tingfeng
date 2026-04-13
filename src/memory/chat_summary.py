"""ChatSummary - 对话历史压缩模块 — 从 Aider history.py 移植

支持智能压缩对话历史，避免上下文窗口溢出。

用法:
    from src.memory.chat_summary import ChatSummary

    summarizer = ChatSummary(max_tokens=4000)
    compressed = summarizer.summarize(messages)

核心算法:
1. 从尾部保留最新消息
2. 递归分割摘要
3. 多模型回退
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 默认摘要提示词
SUMMARIZE_PROMPT = """请总结以下对话的关键内容，保留：
1. 用户的核心需求
2. 已完成的工作
3. 待解决的问题
4. 重要的技术决策

用简洁的中文回复，不超过 500 字。"""

SUMMARY_PREFIX = """[以下是之前对话的摘要]\n
"""


@dataclass
class SummaryResult:
    """摘要结果"""
    messages: list[dict[str, str]]
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float = 0.0

    def __post_init__(self):
        if self.original_tokens > 0:
            self.compression_ratio = 1 - (self.compressed_tokens / self.original_tokens)


class ChatSummary:
    """对话历史压缩器

    功能:
    - Token 预算管理
    - 递归分割摘要
    - 多模型回退
    - 保留最新消息

    示例:
        >>> summarizer = ChatSummary(max_tokens=4000)
        >>> result = summarizer.summarize(messages)
        >>> print(f"压缩率: {result.compression_ratio:.1%}")
    """

    def __init__(
        self,
        max_tokens: int = 1024,
        token_counter: Callable[[dict], int] | None = None,
        summarize_fn: Callable[[str], str] | None = None,
        model_max_input_tokens: int = 4096,
    ) -> None:
        """初始化压缩器

        参数:
            max_tokens: 目标 token 数
            token_counter: 自定义 token 计数函数
            summarize_fn: 自定义摘要函数
            model_max_input_tokens: 模型最大输入 token 数
        """
        self.max_tokens = max_tokens
        self.model_max_input_tokens = model_max_input_tokens
        self._summarize_fn = summarize_fn
        self._token_counter = token_counter or self._default_token_counter

    def _default_token_counter(self, message: dict) -> int:
        """默认 token 计数器（简单估算）"""
        content = message.get('content', '')
        if isinstance(content, str):
            # 简单估算：中文约 0.5 token/字，英文约 0.25 token/char
            chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
            other_chars = len(content) - chinese_chars
            return int(chinese_chars * 0.5 + other_chars * 0.25) + 10
        return 10

    def _summarize_content(self, content: str) -> str:
        """执行摘要 — 优先使用 weak_model 降低成本 (v0.45.0)"""
        if self._summarize_fn:
            return self._summarize_fn(content)

        # 尝试使用 LLM (优先 weak_model)
        try:
            from ..core.settings import get_settings
            from ..llm import LLMConfig, LLMMessage, create_llm_provider

            _s = get_settings()
            weak_model_name = getattr(_s, 'weak_model', None)
            if weak_model_name:
                try:
                    import asyncio

                    weak_config = LLMConfig(
                        provider=_s.llm_provider,
                        api_key=_s.llm_api_key or '',
                        model=weak_model_name,
                        base_url=_s.llm_base_url,
                        max_tokens=500,
                    )
                    provider = create_llm_provider(weak_config)
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # 已在 async 上下文中，创建新线程执行
                        response = asyncio.run_coroutine_threadsafe(
                            provider.chat([LLMMessage(role='user', content=f"{SUMMARIZE_PROMPT}\n\n---\n\n{content}")]),
                            loop,
                        ).result(timeout=30)
                    else:
                        response = asyncio.run(
                            provider.chat([LLMMessage(role='user', content=f"{SUMMARIZE_PROMPT}\n\n---\n\n{content}")])
                        )
                    if response and response.content:
                        return SUMMARY_PREFIX + response.content
                except Exception:
                    pass  # 回退到主模型

            # 主模型回退
            from ..llm import chat

            prompt = f"{SUMMARIZE_PROMPT}\n\n---\n\n{content}"
            response = chat(prompt, max_tokens=500)
            if response:
                return SUMMARY_PREFIX + response
        except Exception as e:
            logger.warning(f'摘要失败: {e}')

        # 回退：截断内容
        return SUMMARY_PREFIX + content[:1000] + '...[内容已截断]'

    def tokenize(self, messages: list[dict]) -> list[tuple[int, dict]]:
        """计算消息的 token 数"""
        sized = []
        for msg in messages:
            tokens = self._token_counter(msg)
            sized.append((tokens, msg))
        return sized

    def too_big(self, messages: list[dict]) -> bool:
        """检查是否超过 token 预算"""
        sized = self.tokenize(messages)
        total = sum(tokens for tokens, _msg in sized)
        return total > self.max_tokens

    def summarize(self, messages: list[dict], depth: int = 0) -> list[dict]:
        """压缩对话历史

        参数:
            messages: 消息列表
            depth: 递归深度

        返回:
            压缩后的消息列表
        """
        result = self._summarize_real(messages, depth)

        # 确保以 assistant 消息结尾
        if result and result[-1].get('role') != 'assistant':
            result.append({'role': 'assistant', 'content': '好的。'})

        return result

    def _summarize_real(self, messages: list[dict], depth: int = 0) -> list[dict]:
        """实际摘要逻辑"""
        if not messages:
            return []

        sized = self.tokenize(messages)
        total = sum(tokens for tokens, _msg in sized)

        # 如果不需要压缩
        if total <= self.max_tokens and depth == 0:
            return messages

        min_split = 4
        if len(messages) <= min_split or depth > 3:
            return self._summarize_all(messages)

        # 从尾部计算保留的消息
        tail_tokens = 0
        split_index = len(messages)
        half_max_tokens = self.max_tokens // 2

        for i in range(len(sized) - 1, -1, -1):
            tokens, _msg = sized[i]
            if tail_tokens + tokens < half_max_tokens:
                tail_tokens += tokens
                split_index = i
            else:
                break

        # 确保 head 以 assistant 消息结尾
        while messages[split_index - 1].get('role') != 'assistant' and split_index > 1:
            split_index -= 1

        if split_index <= min_split:
            return self._summarize_all(messages)

        # 分割 head 和 tail
        tail = messages[split_index:]
        sized_head = sized[:split_index]

        # 计算保留的消息
        model_max = self.model_max_input_tokens - 512  # 预留 buffer
        keep = []
        current_tokens = 0

        for tokens, msg in sized_head:
            current_tokens += tokens
            if current_tokens > model_max:
                break
            keep.append(msg)

        # 摘要 head
        summary = self._summarize_all(keep)

        # 检查摘要 + tail 是否合适
        summary_tokens = sum(self._token_counter(m) for m in summary)
        tail_tokens = sum(tokens for tokens, _ in sized[split_index:])

        if summary_tokens + tail_tokens < self.max_tokens:
            return summary + tail

        # 递归处理
        return self._summarize_real(summary + tail, depth + 1)

    def _summarize_all(self, messages: list[dict]) -> list[dict]:
        """摘要所有消息"""
        content = ""

        for msg in messages:
            role = msg.get('role', '').upper()
            if role not in ('USER', 'ASSISTANT'):
                continue

            content += f"# {role}\n"
            content += msg.get('content', '')
            if not content.endswith('\n'):
                content += '\n'

        if not content.strip():
            return messages

        summary = self._summarize_content(content)
        return [{'role': 'user', 'content': summary}]

    def get_stats(self, messages: list[dict]) -> dict[str, Any]:
        """获取统计信息"""
        sized = self.tokenize(messages)
        total = sum(tokens for tokens, _ in sized)

        by_role: dict[str, int] = {}
        for tokens, msg in sized:
            role = msg.get('role', 'unknown')
            by_role[role] = by_role.get(role, 0) + tokens

        return {
            'total_tokens': total,
            'message_count': len(messages),
            'by_role': by_role,
            'needs_compression': total > self.max_tokens,
        }


def compress_messages(
    messages: list[dict],
    max_tokens: int = 4000,
    summarize_fn: Callable[[str], str] | None = None,
) -> tuple[list[dict], SummaryResult]:
    """压缩消息的便捷函数

    参数:
        messages: 消息列表
        max_tokens: 目标 token 数
        summarize_fn: 自定义摘要函数

    返回:
        (压缩后的消息, 摘要结果)
    """
    summarizer = ChatSummary(
        max_tokens=max_tokens,
        summarize_fn=summarize_fn,
    )

    # 计算原始 token 数
    sized = summarizer.tokenize(messages)
    original_tokens = sum(tokens for tokens, _ in sized)

    # 压缩
    compressed = summarizer.summarize(messages)

    # 计算压缩后 token 数
    sized_compressed = summarizer.tokenize(compressed)
    compressed_tokens = sum(tokens for tokens, _ in sized_compressed)

    result = SummaryResult(
        messages=compressed,
        original_tokens=original_tokens,
        compressed_tokens=compressed_tokens,
    )

    return compressed, result

"""History Compressor — 对话历史压缩

借鉴 Aider 的 history.py ChatSummary，实现:
1. 递归压缩旧消息
2. 保留最近 N 条完整消息
3. 使用 weak_model 生成摘要

这能有效减少 token 消耗，避免上下文溢出。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class CompressionResult:
    """压缩结果"""
    messages: list[dict[str, str]]
    original_count: int
    compressed_count: int
    tokens_saved: int
    summary: str | None = None


# 压缩提示词 (借鉴 Aider)
SUMMARIZE_PROMPT = """*Briefly* summarize this partial conversation about programming.
Include less detail about older parts and more detail about the most recent messages.
Start a new paragraph every time the topic changes!

This is only part of a longer conversation so *DO NOT* conclude the summary with language like "Finally, ...".
Because the conversation continues after the summary.

The summary *MUST* include:
- Function names, libraries, packages being discussed
- Filenames referenced in the conversation
- Key decisions made
- Current status and next steps

The summaries *MUST NOT* include ```...``` fenced code blocks!

Format the summary with structural headers like:
### Context & Decisions
[Summary of what we decided and why]

### Referenced Symbols & Files
[List of files/functions]

Phrase the summary with the USER in first person, telling the ASSISTANT about the conversation.
Write *as* the user. The user should refer to the assistant as *you*.
Start the summary with "I asked you...".
"""

SUMMARY_PREFIX = "I spoke to you previously about a number of things.\n"


class HistoryCompressor:
    """对话历史压缩器

    借鉴 Aider 的 ChatSummary 设计:
    - 递归压缩，直到满足 token 限制
    - 保留最近消息，压缩旧消息
    - 使用弱模型生成摘要

    使用:
        compressor = HistoryCompressor(
            token_counter=lambda msg: count_tokens(msg),
            max_tokens=4000,
            weak_model_callback=weak_model.send,
        )
        compressed = compressor.compress(messages)
    """

    def __init__(
        self,
        token_counter: Callable[[dict], int],
        max_tokens: int = 4096,
        weak_model_callback: Callable[[list[dict]], str] | None = None,
        min_split: int = 4,
        max_depth: int = 3,
    ):
        """初始化压缩器

        Args:
            token_counter: Token 计数函数
            max_tokens: 最大 token 数
            weak_model_callback: 弱模型回调 (messages) -> summary
            min_split: 最小分割大小
            max_depth: 最大递归深度
        """
        self.token_counter = token_counter
        self.max_tokens = max_tokens
        self.weak_model_callback = weak_model_callback
        self.min_split = min_split
        self.max_depth = max_depth

    def compress(
        self,
        messages: list[dict[str, str]],
    ) -> CompressionResult:
        """压缩消息列表

        Args:
            messages: 消息列表

        Returns:
            CompressionResult
        """
        if not messages:
            return CompressionResult(
                messages=[],
                original_count=0,
                compressed_count=0,
                tokens_saved=0,
            )

        original_tokens = sum(self.token_counter(m) for m in messages)

        # 检查是否需要压缩
        if original_tokens <= self.max_tokens:
            return CompressionResult(
                messages=messages,
                original_count=len(messages),
                compressed_count=len(messages),
                tokens_saved=0,
            )

        # 执行压缩
        compressed = self._compress_recursive(messages, depth=0)
        compressed_tokens = sum(self.token_counter(m) for m in compressed)

        return CompressionResult(
            messages=compressed,
            original_count=len(messages),
            compressed_count=len(compressed),
            tokens_saved=original_tokens - compressed_tokens,
            summary=compressed[0].get("content") if compressed else None,
        )

    def _compress_recursive(
        self,
        messages: list[dict[str, str]],
        depth: int,
    ) -> list[dict[str, str]]:
        """递归压缩

        借鉴 Aider 的 summarize_real() 算法。
        """
        # 计算总 token
        sized = [(self.token_counter(m), m) for m in messages]
        total = sum(t for t, _ in sized)

        # 满足限制，直接返回
        if total <= self.max_tokens and depth == 0:
            return messages

        # 消息太少或递归太深，全部压缩
        if len(messages) <= self.min_split or depth > self.max_depth:
            return self._summarize_all(messages)

        # 分割点：保留后半部分
        tail_tokens = 0
        split_index = len(messages)
        half_max = self.max_tokens // 2

        for i in range(len(sized) - 1, -1, -1):
            tokens, _ = sized[i]
            if tail_tokens + tokens < half_max:
                tail_tokens += tokens
                split_index = i
            else:
                break

        # 确保 head 以 assistant 消息结尾
        while (
            split_index > 1
            and messages[split_index - 1].get("role") != "assistant"
        ):
            split_index -= 1

        if split_index <= self.min_split:
            return self._summarize_all(messages)

        # 分割
        tail = messages[split_index:]
        head = messages[:split_index]

        # 压缩 head
        summary = self._summarize_all(head)

        # 检查是否满足限制
        summary_tokens = sum(self.token_counter(m) for m in summary)
        tail_tokens = sum(self.token_counter(m) for m in tail)

        if summary_tokens + tail_tokens < self.max_tokens:
            return summary + tail

        # 递归压缩
        return self._compress_recursive(summary + tail, depth + 1)

    def _summarize_all(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """将所有消息压缩为一个摘要，但保留受保护的系统指令"""
        if not messages:
            return []

        # 检查是否有弱模型
        if not self.weak_model_callback:
            logger.warning("[HistoryCompressor] No weak_model_callback, returning original")
            return messages

        # 分离受保护的消息和需要压缩的消息
        protected_messages = []
        messages_to_summarize = []

        for i, msg in enumerate(messages):
            role = msg.get("role", "").upper()
            # 保护机制:
            # 1. 显式标记为 protected
            # 2. 对话开头的系统提示词 (前 3 条)
            if msg.get("protected") or (role == "SYSTEM" and i < 3):
                protected_messages.append(msg)
                continue

            if role in ("USER", "ASSISTANT"):
                messages_to_summarize.append(msg)

        if not messages_to_summarize:
            return protected_messages

        # 构建摘要请求
        summary_content = ""
        for msg in messages_to_summarize:
            role = msg.get("role", "").upper()
            summary_content += f"# {role}\n"
            summary_content += msg.get("content", "")
            if not summary_content.endswith("\n"):
                summary_content += "\n"

        summarize_messages = [
            {"role": "system", "content": SUMMARIZE_PROMPT},
            {"role": "user", "content": summary_content},
        ]

        try:
            summary = self.weak_model_callback(summarize_messages)
            if summary:
                summary_text = SUMMARY_PREFIX + summary
                return protected_messages + [{"role": "user", "content": summary_text}]
        except Exception as e:
            logger.error(f"[HistoryCompressor] Summarization failed: {e}")

        return messages

    def estimate_tokens_saved(
        self,
        messages: list[dict[str, str]],
    ) -> int:
        """预估可节省的 token 数"""
        total = sum(self.token_counter(m) for m in messages)
        return max(0, total - self.max_tokens)


def create_simple_token_counter(model_type: str = "gpt") -> Callable[[dict], int]:
    """创建简单的 token 计数器

    使用估算方法，精度有限但速度快。
    """
    # 中文约 1.5 字/token，英文约 4 字/token
    def counter(msg: dict) -> int:
        content = msg.get("content", "")
        # 简单估算
        char_count = len(content)
        # 假设平均 3.5 字符/token
        return max(1, char_count // 3)

    return counter

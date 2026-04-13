"""Chat Summarizer — 借鉴 Project B 的 ChatCompressionService
使用 LLM 对历史对话进行总结，保留关键状态。
"""
from __future__ import annotations

import logging

from ..llm import BaseLLMProvider, LLMMessage
from .config.settings import get_settings

logger = logging.getLogger(__name__)

class ChatSummarizer:
    """聊天历史总结器 — 使 Agent 能够处理超长上下文。

    Ported from Project B (qwen-code-main).
    """

    def __init__(self, llm_provider: BaseLLMProvider) -> None:
        self.llm_provider = llm_provider
        self.settings = get_settings()

    def find_split_point(self, messages: list[LLMMessage], preserve_ratio: float = 0.3) -> int:
        """寻找平衡的压缩分割点。

        保留最近的 preserve_ratio (默认 30%) 的消息不被压缩。
        确保分割点不在工具调用对之间。
        """
        if len(messages) <= 4:
            return 0

        # 排除 system 消息
        content_msgs = messages[1:] if messages[0].role == 'system' else messages
        offset = 1 if messages[0].role == 'system' else 0

        target_count = int(len(content_msgs) * (1 - preserve_ratio))
        split_idx = max(1, target_count)

        # 寻找安全的分割点 (避免截断工具调用链)
        # 从 split_idx 向后寻找，直到找到一个 user 消息 (通常是新一轮的开始)
        for i in range(split_idx + offset, len(messages)):
            if messages[i].role == 'user':
                return i

        return split_idx + offset

    async def summarize(self, messages_to_summarize: list[LLMMessage]) -> str:
        """解析并压缩一段历史消息。"""
        if not messages_to_summarize:
            return ""

        history_text = ""
        for m in messages_to_summarize:
            history_text += f"{m.role.upper()}: {m.content}\n---\n"

        prompt = [
            LLMMessage(role="system", content=(
                "你是一个对话摘要专家。请将以下对话历史压缩为一个极其精炼的 <state_snapshot>。\n"
                "要求：\n"
                "1. 保留当前的任务进度和已完成的步骤。\n"
                "2. 保留已发现的关键信息（如错误原因、文件路径、重要参数）。\n"
                "3. 丢弃冗余的工具输出和中间推理过程。\n"
                "4. 格式：<state_snapshot>\n... 摘要内容 ...\n</state_snapshot>"
            )),
            LLMMessage(role="user", content=f"对话历史：\n\n{history_text}")
        ]

        try:
            response = await self.llm_provider.chat(prompt)
            summary = response.content.strip()
            if "<state_snapshot>" not in summary:
                summary = f"<state_snapshot>\n{summary}\n</state_snapshot>"
            return summary
        except Exception as e:
            logger.error(f"聊天历史总结失败: {e}")
            return "[摘要生成失败，部分历史已丢失]"

    async def compress_if_needed(self, messages: list[LLMMessage], total_tokens: int, max_tokens: int) -> list[LLMMessage]:
        """如果 token 超过阈值，执行 LLM 辅助压缩。"""
        threshold = self.settings.compression_token_threshold
        if total_tokens < max_tokens * threshold:
            return messages

        logger.info(f"Token 占用率 ({total_tokens}/{max_tokens}) 触发智能压缩")

        split_idx = self.find_split_point(messages, self.settings.compression_preserve_threshold)
        if split_idx <= 1:
            return messages

        system_msg = messages[0] if messages[0].role == 'system' else None
        to_summarize = messages[1:split_idx] if system_msg else messages[:split_idx]
        kept_messages = messages[split_idx:]

        summary = await self.summarize(to_summarize)

        new_history = []
        if system_msg:
            new_history.append(system_msg)

        new_history.append(LLMMessage(role="system", content=(
            f"[历史上下文压缩摘要]\n{summary}\n\n[注：以上内容是较早前对话的快照，详细记录已被归档。]"
        )))
        new_history.extend(kept_messages)

        return new_history

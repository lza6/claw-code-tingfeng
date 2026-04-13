"""消息截断器 - AgentEngine 的消息截断和 token 计数模块

从 agent/engine.py 拆分，负责：
- Token 计数（tiktoken 精确计数 + 字符计数回退）
- 消息截断策略（保留 system + 最近对话 + 摘要）
"""
from __future__ import annotations

import re
from typing import Any

from ..core.chat_summarizer import ChatSummarizer
from ..core.config.settings import get_settings
from ..llm import BaseLLMProvider, LLMMessage
from ..utils import debug, warn


class MessageTruncator:
    """消息截断器

    优化策略 (v0.60+):
    1. 始终保留 system 消息（第一条）
    2. 如果启用了智能总结 (Project B 特性)，使用 LLM 生成历史快照 (<state_snapshot>)
    3. 否则，使用基于规则的截断（保留最近 N 条，中间摘要）
    """

    def __init__(
        self,
        max_context_tokens: int = 8000,
        encoding: Any = None,
        llm_provider: BaseLLMProvider | None = None,
    ) -> None:
        """初始化截断器"""
        self.max_context_tokens = max_context_tokens
        self._encoding = encoding
        self._llm_provider = llm_provider
        self._summarizer: ChatSummarizer | None = None
        if llm_provider:
            self._summarizer = ChatSummarizer(llm_provider)

    def count_tokens(self, messages: list[LLMMessage]) -> int:
        """计算消息列表的 token 数量

        参数:
            messages: 消息列表
        """
        """计算消息列表的 token 数量

        如果 tiktoken 可用，使用精确 token 计数；
        否则回退到字符计数（1 token ≈ 4 字符）。
        """
        if self._encoding:
            return sum(len(self._encoding.encode(m.content)) for m in messages)
        # 回退：字符计数（粗略估算 1 token ≈ 4 字符）
        return sum(len(m.content) for m in messages) // 4

    async def truncate_messages(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """截断消息列表，防止上下文过长

        优化策略:
        1. 优先尝试使用 LLM 进行智能总结 (如果已启用且 provider 可用)。
        2. 如果智能总结不可用，退回到基于规则的截断。
        """
        if not messages:
            return messages

        max_tokens = self.max_context_tokens
        total_tokens = self.count_tokens(messages)

        if total_tokens <= max_tokens:
            return messages

        # 尝试 Project B 风格的 LLM 智能总结
        settings = get_settings()
        if settings.enable_chat_summarization and self._summarizer:
            try:
                summarized_messages = await self._summarizer.compress_if_needed(
                    messages, total_tokens, max_tokens
                )
                # 检查压缩是否有效
                if len(summarized_messages) < len(messages):
                    return summarized_messages
            except Exception as e:
                warn(f'智能总结失败，退回到规则截断: {e}')

        warn(f'消息总 token ({total_tokens}) 超过阈值 ({max_tokens})，执行规则截断')

        # 计算每条消息的 token
        message_token_counts = [self.count_tokens([m]) for m in messages]

        # 分离 system 消息
        system_msg = messages[0] if messages[0].role == 'system' else None
        system_tokens = message_token_counts[0] if system_msg else 0
        remaining_messages = messages[1:] if system_msg else list(messages)
        remaining_token_counts = message_token_counts[1:] if system_msg else list(message_token_counts)

        # 计算可用 token 预算
        available_tokens = max(0, max_tokens - system_tokens - 100)  # 保留 100 token 余量

        # 策略：保留最近 N 条消息，直到 token 预算内
        kept_messages: list[LLMMessage] = []
        kept_token_counts: list[int] = []
        current_total = 0
        kept_count = 0

        # 从后往前遍历，保留最近的消息
        for i in range(len(remaining_messages) - 1, -1, -1):
            msg_tokens = remaining_token_counts[i]
            if current_total + msg_tokens <= available_tokens:
                kept_messages.insert(0, remaining_messages[i])
                kept_token_counts.insert(0, msg_tokens)
                current_total += msg_tokens
                kept_count += 1
            else:
                break

        # 构建结果
        result: list[LLMMessage] = []
        if system_msg:
            if system_tokens > max_tokens - 200:
                # 截断 system 消息
                if self._encoding:
                    tokens = self._encoding.encode(system_msg.content)
                    truncated_tokens = tokens[:max_tokens - 200]
                    truncated_content = self._encoding.decode(truncated_tokens) + '\n...[已截断]'
                else:
                    truncated_content = system_msg.content[:max_tokens * 4 - 800] + '\n...[已截断]'
                result.append(LLMMessage(role='system', content=truncated_content))
            else:
                result.append(system_msg)

        # 添加摘要（如果有消息被截断）
        kept_count = len(kept_messages)
        total_remaining = len(remaining_messages)
        if kept_count < total_remaining:
            truncated_count = total_remaining - kept_count
            summary_msg = self._generate_truncation_summary(
                truncated_count, kept_count, remaining_messages[:truncated_count]
            )
            result.append(summary_msg)

        result.extend(kept_messages)

        # 如果最后一条消息过长，截断其内容
        if result:
            last_msg = result[-1]
            last_tokens = self.count_tokens([last_msg])
            max_last_tokens = max_tokens // 4
            if last_tokens > max_last_tokens:
                if self._encoding:
                    tokens = self._encoding.encode(last_msg.content)
                    truncated_tokens = tokens[-max_last_tokens:]
                    truncated = self._encoding.decode(truncated_tokens)
                else:
                    truncated = last_msg.content[-(max_last_tokens * 4):]
                result[-1] = LLMMessage(
                    role=last_msg.role,
                    content='...[历史消息已截断]\n' + truncated,
                )

        debug(f'消息截断: {len(messages)} -> {len(result)} 条 (保留最近 {kept_count} 条)')
        return result

    def _generate_truncation_summary(
        self,
        truncated_count: int,
        kept_count: int,
        truncated_messages: list[LLMMessage],
    ) -> LLMMessage:
        """生成被截断消息的智能摘要

        P1 优化:
        - 提取工具名称、执行状态（成功/失败）、关键输出片段
        - 保留 assistant 的推理步骤摘要
        - 按时间线组织摘要，便于 LLM 理解上下文

        参数:
            truncated_count: 被截断的消息数量
            kept_count: 保留的消息数量
            truncated_messages: 被截断的消息列表

        返回:
            包含摘要信息的 system 消息
        """
        tool_summaries: list[dict[str, str]] = []
        reasoning_steps: list[str] = []

        for msg in truncated_messages:
            if msg.role == 'user':
                # 提取工具执行结果
                tool_match = re.search(r'工具\s+(\w+)\s+执行结果', msg.content)
                if tool_match:
                    tool_name = tool_match.group(1)
                    # 判断执行状态
                    if '错误' in msg.content or '失败' in msg.content:
                        status = '失败'
                        preview = msg.content.split('错误：')[-1][:80] if '错误：' in msg.content else '未知错误'
                    else:
                        status = '成功'
                        preview = msg.content.split('执行结果：\n')[-1][:80] if '执行结果：\n' in msg.content else '结果已截断'
                    tool_summaries.append({
                        'name': tool_name,
                        'status': status,
                        'preview': preview,
                    })
            elif msg.role == 'assistant':
                # 提取 assistant 的推理步骤
                if '<tool>' not in msg.content and len(msg.content) > 20:
                    reasoning_steps.append(msg.content[:100])

        # 构建结构化摘要
        lines = [f'[历史上下文摘要 - {truncated_count} 条消息已截断，保留最近 {kept_count} 条]']

        if tool_summaries:
            lines.append('')
            lines.append('工具执行记录:')
            for ts in tool_summaries[:8]:
                status_icon = '✅' if ts['status'] == '成功' else '❌'
                lines.append(f'  {status_icon} {ts["name"]}: {ts["preview"]}...')
            if len(tool_summaries) > 8:
                lines.append(f'  ... 等 {len(tool_summaries)} 个工具调用')

        if reasoning_steps:
            lines.append('')
            lines.append('推理步骤摘要:')
            for step in reasoning_steps[:3]:
                lines.append(f'  - {step}...')
            if len(reasoning_steps) > 3:
                lines.append(f'  ... 等 {len(reasoning_steps)} 个推理步骤')

        lines.append('')
        lines.append('[注: 以上历史信息已压缩，详细内容可在需要时重新查询]')

        return LLMMessage(role='system', content='\n'.join(lines))

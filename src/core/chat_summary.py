"""ChatSummary - 聊天历史压缩 — 从 Aider history.py 移植并增强

智能压缩长对话历史，使用弱模型进行摘要化，保留最近消息原文。

核心算法:
1. 估算当前对话 token 数
2. 超过阈值时触发压缩
3. 递归分割头部和尾部
4. 使用弱模型摘要化头部
5. 保留尾部消息原文

用法:
    summary = ChatSummary(models=weak_model, max_tokens=2048)
    compressed = summary.summarize(messages)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ChatSummary:
    """聊天历史摘要器

    使用弱模型对长对话进行递归压缩，保留最近消息。
    """

    def __init__(
        self,
        models: Any = None,
        max_tokens: int = 1024,
    ) -> None:
        """初始化

        参数:
            models: 模型实例或列表（需要有 token_count 方法）
            max_tokens: 最大 token 数量
        """
        if not models:
            raise ValueError('必须提供至少一个模型')

        self.models = models if isinstance(models, list) else [models]
        self.max_tokens = max_tokens
        self.token_count = self.models[0].token_count

    def too_big(self, messages: list[dict]) -> bool:
        """检查消息是否超过 token 限制

        参数:
            messages: 消息列表

        返回:
            是否超过限制
        """
        sized = self._tokenize(messages)
        total = sum(tokens for tokens, _ in sized)
        return total > self.max_tokens

    def _tokenize(self, messages: list[dict]) -> list[tuple[int, dict]]:
        """计算每条消息的 token 数"""
        sized: list[tuple[int, dict]] = []
        for msg in messages:
            content = msg.get('content', '')
            tokens = self.token_count(content) if content else 0
            sized.append((tokens, msg))
        return sized

    def summarize(self, messages: list[dict], depth: int = 0) -> list[dict]:
        """压缩消息列表

        参数:
            messages: 消息列表
            depth: 递归深度（内部使用）

        返回:
            压缩后的消息列表
        """
        messages = self._summarize_real(messages)
        if messages and messages[-1].get('role') != 'assistant':
            messages.append({'role': 'assistant', 'content': 'Ok.'})
        return messages

    def _summarize_real(self, messages: list[dict], depth: int = 0) -> list[dict]:
        """递归摘要实现"""
        if not self.models:
            raise ValueError('无可用模型')

        sized = self._tokenize(messages)
        total = sum(tokens for tokens, _ in sized)

        if total <= self.max_tokens and depth == 0:
            return messages

        # 消息太少或递归过深，全部摘要化
        min_split = 4
        if len(messages) <= min_split or depth > 3:
            return self._summarize_all(messages)

        # 从尾部向前累加，找到分割点
        half_max = self.max_tokens // 2
        split_index = len(messages)
        tail_tokens = 0

        for i in range(len(sized) - 1, -1, -1):
            tokens, _ = sized[i]
            if tail_tokens + tokens < half_max:
                tail_tokens += tokens
                split_index = i
            else:
                break

        # 确保头部以 assistant 消息结尾
        while messages[split_index - 1].get('role') != 'assistant' and split_index > 1:
            split_index -= 1

        if split_index <= min_split:
            return self._summarize_all(messages)

        # 分割头部和尾部
        tail = messages[split_index:]

        # 限制头部大小
        model_max = self.models[0].info.get('max_input_tokens', 4096) if hasattr(self.models[0], 'info') else 4096
        model_max -= 512

        keep: list[dict] = []
        total_head = 0
        for tokens, msg in sized[:split_index]:
            total_head += tokens
            if total_head > model_max:
                break
            keep.append(msg)

        # 摘要化头部
        summary = self._summarize_all(keep)

        # 如果摘要 + 尾部仍然超限，递归压缩
        summary_tokens = self.token_count(
            ''.join(m.get('content', '') for m in summary)
        )
        if summary_tokens + tail_tokens < self.max_tokens:
            return summary + tail

        return self._summarize_real(summary + tail, depth + 1)

    def _summarize_all(self, messages: list[dict]) -> list[dict]:
        """将所有消息摘要为一条

        参数:
            messages: 消息列表

        返回:
            包含摘要的单条消息列表
        """
        if not messages:
            return []

        content = ''
        for msg in messages:
            role = msg.get('role', 'unknown')
            text = msg.get('content', '')
            if not text:
                continue

            if role == 'user':
                content += f'# User:\n{text}\n\n'
            elif role == 'assistant':
                content += f'# Assistant:\n{text}\n\n'
            elif role == 'tool':
                tool_name = msg.get('name', 'tool')
                content += f'# Tool ({tool_name}):\n{text}\n\n'
            elif role == 'system':
                content += f'# System:\n{text}\n\n'
            else:
                content += f'# {role}:\n{text}\n\n'

        if not content.strip():
            return messages

        # 使用弱模型生成摘要
        prompt = (
            'Summarize the following conversation concisely. '
            'Focus on: what was requested, what was done, what remains. '
            'Use the same language as the conversation.\n\n'
            f'{content}\n\n'
            'Summary:'
        )

        try:
            summary_text = self._call_model(prompt)
            return [{'role': 'user', 'content': f'Previous conversation summary:\n{summary_text}'}]
        except Exception as e:
            logger.warning(f'摘要生成失败: {e}')
            # 回退：简单截取
            truncated = content[:self.max_tokens * 4]
            return [{'role': 'user', 'content': f'Previous conversation:\n{truncated}'}]

    def _call_model(self, prompt: str) -> str:
        """调用模型生成摘要"""
        for model in self.models:
            try:
                if hasattr(model, 'chat'):
                    resp = model.chat(
                        messages=[{'role': 'user', 'content': prompt}],
                        max_tokens=self.max_tokens // 2,
                    )
                    return resp.get('content', resp) if isinstance(resp, dict) else str(resp)
                elif hasattr(model, 'complete'):
                    return model.complete(prompt, max_tokens=self.max_tokens // 2)
                elif callable(model):
                    result = model(prompt)
                    return result if isinstance(result, str) else str(result)
            except Exception:
                continue

        raise RuntimeError('所有模型调用失败')


# ==================== 便捷函数 ====================

def summarize_messages(
    messages: list[dict],
    models: Any = None,
    max_tokens: int = 1024,
) -> list[dict]:
    """压缩消息列表（便捷函数）

    参数:
        messages: 消息列表
        models: 模型实例
        max_tokens: 最大 token 数

    返回:
        压缩后的消息列表
    """
    if not models:
        return messages

    summary = ChatSummary(models=models, max_tokens=max_tokens)
    return summary.summarize(messages)

"""ContextWindow - 动态上下文窗口管理器

增强特性:
- 基于 token 的动态修剪（防止 OOM）
- 消息优先级队列（system > 最近对话 > 工具结果 > 摘要）
- 内存使用监控和告警
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ContextMessage:
    """上下文消息"""
    role: str
    content: str
    timestamp: float = 0.0
    tokens: int = 0  # 预估 Token 数
    priority: int = 0  # 优先级: 0=system, 1=recent, 2=tool_result, 3=normal


class ContextWindowManager:
    """上下文窗口管理器

    职责:
    1. 管理当前活动的对话上下文
    2. 当上下文超过阈值时进行智能修剪
    3. 支持对旧历史进行摘要压缩
    4. 防止 OOM（内存上限保护）
    """

    # 默认配置
    DEFAULT_MAX_TOKENS = 8000
    DEFAULT_KEEP_RECENT = 5
    DEFAULT_SUMMARY_THRESHOLD = 0.8
    DEFAULT_MAX_MEMORY_MB = 256  # 最大内存（MB）

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        keep_recent_count: int = DEFAULT_KEEP_RECENT,
        summary_threshold: float = DEFAULT_SUMMARY_THRESHOLD,
        max_memory_mb: float = DEFAULT_MAX_MEMORY_MB,
    ) -> None:
        self.max_tokens = max_tokens
        self.keep_recent_count = keep_recent_count
        self.summary_threshold = summary_threshold
        self.max_memory_bytes = int(max_memory_mb * 1024 * 1024)
        self._messages: list[ContextMessage] = []
        self._summary: str = ""
        self._total_tokens: int = 0

    def add_message(self, role: str, content: str, tokens: int = 0, priority: int = 3) -> None:
        """添加新消息并检查窗口

        Args:
            role: 消息角色 (system/user/assistant/tool)
            content: 消息内容
            tokens: 预估 token 数（0 时自动估算）
            priority: 优先级 (0=system, 1=recent, 2=tool_result, 3=normal)
        """
        estimated_tokens = tokens if tokens > 0 else max(1, len(content) // 4)
        msg = ContextMessage(
            role=role,
            content=content,
            timestamp=time.time(),
            tokens=estimated_tokens,
            priority=priority,
        )
        self._messages.append(msg)
        self._total_tokens += estimated_tokens
        self._prune_if_needed()

    def get_full_context(self) -> list[dict[str, str]]:
        """获取格式化后的完整上下文"""
        result = []
        if self._summary:
            result.append({"role": "system", "content": f"历史对话摘要: {self._summary}"})

        for msg in self._messages:
            result.append({"role": msg.role, "content": msg.content})

        return result

    def get_stats(self) -> dict[str, Any]:
        """获取窗口统计信息"""
        estimated_memory = self._total_tokens * 4  # 粗略估算：1 token ≈ 4 bytes
        return {
            "message_count": len(self._messages),
            "total_tokens": self._total_tokens,
            "max_tokens": self.max_tokens,
            "summary_length": len(self._summary),
            "estimated_memory_bytes": estimated_memory,
            "memory_limit_bytes": self.max_memory_bytes,
            "memory_usage_pct": estimated_memory / self.max_memory_bytes if self.max_memory_bytes > 0 else 0,
        }

    def _prune_if_needed(self) -> None:
        """智能修剪过长的上下文"""
        # 检查 token 阈值
        token_threshold = self.max_tokens * self.summary_threshold
        if self._total_tokens <= token_threshold and len(self._messages) <= self.keep_recent_count * 2:
            return

        logger.info(
            f"[ContextWindow] 触发修剪: tokens={self._total_tokens}/{self.max_tokens}, "
            f"messages={len(self._messages)}"
        )

        # 分离 system 消息（永远保留）
        system_msgs = [m for m in self._messages if m.priority == 0]
        non_system = [m for m in self._messages if m.priority > 0]

        # 按优先级和时间排序（高优先级 + 新消息优先）
        non_system.sort(key=lambda m: (-m.priority, m.timestamp))

        # 保留最近的高优先级消息
        kept = non_system[:self.keep_recent_count]
        to_summarize = non_system[self.keep_recent_count:]

        if to_summarize:
            # 生成摘要
            summary_parts = []
            for msg in to_summarize[:10]:  # 最多摘要 10 条
                preview = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                summary_parts.append(f"[{msg.role}] {preview}")

            if len(to_summarize) > 10:
                summary_parts.append(f"... 等 {len(to_summarize)} 条消息已压缩")

            new_summary = "\n".join(summary_parts)
            if self._summary:
                self._summary = f"{self._summary}\n\n--- 新摘要 ---\n{new_summary}"
            else:
                self._summary = new_summary

            # 计算被移除消息的 token 数
            removed_tokens = sum(m.tokens for m in to_summarize)
            self._total_tokens -= removed_tokens

        self._messages = system_msgs + kept

        # 内存保护：如果仍然超限，强制截断最长消息
        self._force_truncate_if_needed()

        logger.info(
            f"[ContextWindow] 修剪完成: tokens={self._total_tokens}/{self.max_tokens}, "
            f"messages={len(self._messages)}"
        )

    def _force_truncate_if_needed(self) -> None:
        """强制截断（内存保护）"""
        # 检查内存上限
        estimated_memory = self._total_tokens * 4
        if estimated_memory > self.max_memory_bytes * 0.9:  # 90% 阈值触发
            logger.warning(
                f"[ContextWindow] 内存使用过高 ({estimated_memory / 1024 / 1024:.1f}MB)，强制截断"
            )
            # 移除最旧的非 system 消息
            while self._messages and estimated_memory > self.max_memory_bytes * 0.8:
                for i in range(len(self._messages) - 1, -1, -1):
                    if self._messages[i].priority > 0:
                        removed = self._messages.pop(i)
                        self._total_tokens -= removed.tokens
                        estimated_memory = self._total_tokens * 4
                        break
                else:
                    break  # 没有可移除的非 system 消息了

    def clear(self) -> None:
        """清空所有消息"""
        self._messages.clear()
        self._summary = ""
        self._total_tokens = 0

    def set_summary(self, summary: str) -> None:
        """设置新的历史摘要"""
        self._summary = summary

    @property
    def messages(self) -> list[ContextMessage]:
        return self._messages

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

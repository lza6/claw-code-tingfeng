"""LLM Provider Base Classes - 基础抽象层"""
from __future__ import annotations

import logging
import random
import re
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

# 从父包导入已拆分的模块
from ..config import LLMMessage, LLMResponse
from ..rate_limiter import GlobalRateLimiter

logger = logging.getLogger('llm')

# LLM Client 连接池（LRU + TTL 双策略）
_client_cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
_CLIENT_CACHE_TTL = 3600  # 缓存过期时间（秒）
_CLIENT_CACHE_MAX_SIZE = 32  # 最大缓存条目数（LRU 上限）
_client_cache_lock = threading.Lock()


class BaseLLMProvider(ABC):
    """LLM 提供商基类"""
    _max_retries = 3
    _base_delay = 1.0

    @abstractmethod
    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """发送聊天消息"""
        ...

    @abstractmethod
    async def chat_stream(self, messages: list[LLMMessage], **kwargs) -> AsyncIterator[str | tuple[str, str]]:
        """流式发送聊天消息"""
        ...

    @abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        """获取模型信息"""
        ...

    def _calculate_retry_delay(self, error: Exception, attempt: int) -> float:
        """计算重试延迟 - 支持 429 速率限制的 Retry-After 头"""
        error_str = str(error).lower()
        if '429' in error_str or 'rate_limit' in error_str or 'rate limit' in error_str:
            retry_after_match = re.search(r'retry[-_]?after["\s:]+(\d+)', str(error), re.IGNORECASE)
            if retry_after_match:
                server_delay = int(retry_after_match.group(1))
                return min(float(server_delay), 60.0)
        exponential_delay = self._base_delay * (2 ** attempt)
        jitter = random.uniform(0, 0.5)
        return min(exponential_delay + jitter, 60.0)

    def _get_provider_name(self) -> str:
        """子类覆盖此方法返回提供商名称"""
        return 'unknown'

    async def _execute_with_limit(self, coro):
        """使用全局限流器执行"""
        limiter = GlobalRateLimiter.get_instance()
        async with limiter.limit():
            return await coro

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        output_schema: Any,
        max_retries: int | None = None,
        validate_schema: bool = True,
        **kwargs: Any,
    ) -> Any:
        """结构化输出 - 使用委托模式"""
        from ..structured_output import StructuredOutputMixin, get_structured_mixin
        mixin_cls = get_structured_mixin(self.config)
        mixin = StructuredOutputMixin.__new__(mixin_cls)
        mixin._chat_with_format = lambda msgs, schema, **kw: self._structured_chat_delegate(msgs, schema, **kw)
        return await mixin.chat_structured(
            messages=messages,
            output_schema=output_schema,
            max_retries=max_retries,
            validate_schema=validate_schema,
            **kwargs,
        )

    async def _structured_chat_delegate(
        self,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> LLMResponse:
        """结构化输出的实际执行委托"""
        from ..structured_output import StructuredOutputMixin
        constraint = StructuredOutputMixin._build_constraint_message(schema)
        enhanced = list(messages)
        if enhanced and enhanced[0].role == 'system':
            enhanced[0] = LLMMessage(role='system', content=enhanced[0].content + '\n\n' + constraint)
        else:
            enhanced.insert(0, LLMMessage(role='system', content=constraint))
        return await self.chat(messages=enhanced, **kwargs)


__all__ = [
    '_CLIENT_CACHE_MAX_SIZE',
    '_CLIENT_CACHE_TTL',
    'BaseLLMProvider',
    '_client_cache',
    '_client_cache_lock',
]

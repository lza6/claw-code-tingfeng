"""OpenAI Compatible Provider - OpenAI 兼容 API 提供商基类"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from ..config import LLMConfig, LLMMessage, LLMProviderType, LLMResponse
from ..optimization import try_optimizations
from ..parsers import ContentType as _CT
from ..parsers import ThinkTagParser
from .base import (
    _CLIENT_CACHE_MAX_SIZE,
    _CLIENT_CACHE_TTL,
    BaseLLMProvider,
    _client_cache,
    _client_cache_lock,
)

logger = logging.getLogger('llm')


class OpenAICompatibleProvider(BaseLLMProvider):
    """OpenAI 兼容 API 提供商基类

    适用于所有兼容 OpenAI API 格式的 LLM 提供商：
    - OpenAI
    - Google Gemini (OpenAI 兼容模式)
    - Groq
    - Together AI
    - 其他兼容 OpenAI API 的服务

    子类只需提供:
    - DEFAULT_BASE_URL: 默认 API 端点
    - DEFAULT_MODEL: 默认模型名称
    - _get_provider_name(): 提供商名称
    """

    DEFAULT_BASE_URL: str = ''
    DEFAULT_MODEL: str = ''

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._max_retries = config.max_retries
        self._client: Any = None

    def _get_client(self) -> Any:
        """获取或创建 OpenAI 客户端（懒加载 + LRU+TTL 连接池复用）

        同步锁保护全局缓存（缓存操作本质同步）:
        - LRU + TTL 双策略：缓存带 TTL 过期 + 最大条目数限制
        - 相同配置的多个 AgentEngine 实例共享同一 client
        - 缓存满时自动驱逐最久未使用的条目
        - 访问缓存条目时更新 LRU 顺序
        """
        cache_key = self._get_cache_key()
        now = time.time()

        # Fast path: check LRU cache first
        with _client_cache_lock:
            if cache_key in _client_cache:
                cached_client, cached_time = _client_cache[cache_key]
                if now - cached_time < _CLIENT_CACHE_TTL:
                    _client_cache[cache_key] = (cached_client, now)
                    _client_cache.move_to_end(cache_key)
                    self._client = cached_client
                    return cached_client
                else:
                    del _client_cache[cache_key]

            # Only create if not already cached (simplify: remove instance cache)
            if len(_client_cache) >= _CLIENT_CACHE_MAX_SIZE:
                _client_cache.popitem(last=False)

            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(
                    api_key=self.config.api_key,
                    base_url=self.config.base_url or self.DEFAULT_BASE_URL or None,
                    timeout=self.config.timeout,
                )
                _client_cache[cache_key] = (client, now)
                return client
            except ImportError:
                raise ImportError('请安装 openai 包: pip install openai') from None

    def _get_cache_key(self) -> str:
        """生成 client 缓存键"""
        base_url = self.config.base_url or self.DEFAULT_BASE_URL or ''
        key_prefix = self.config.api_key[:8] if len(self.config.api_key) >= 8 else self.config.api_key
        return f'{self.__class__.__name__}:{key_prefix}:{base_url}:{self.config.model}'

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """发送聊天消息（带优化拦截 + 指数退避重试）"""

        # 尝试优化拦截（Project B 核心特性）
        system_msg = kwargs.get('system_message', '')
        opt_result = try_optimizations(messages, system=system_msg, model=self.config.model)
        if opt_result:
            return LLMResponse(**opt_result)

        last_error = None
        for attempt in range(self._max_retries):
            try:
                client = self._get_client()
                # 检查是否需要强制 JSON (对 DeepSeek 等优化)
                if self.config.provider == LLMProviderType.DEEPSEEK and 'response_format' not in kwargs:
                    kwargs['response_format'] = {"type": "json_object"}

                response = await client.chat.completions.create(
                    model=self.config.model or self.DEFAULT_MODEL,
                    messages=[{'role': m.role, 'content': m.content} for m in messages],
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    **kwargs,
                )
                choice = response.choices[0]
                content = choice.message.content or ''

                # 提取思维链（部分模型如 DeepSeek-R1 支持 reasoning_content）
                thinking = ""
                if hasattr(choice.message, 'reasoning_content') and choice.message.reasoning_content:
                    thinking = choice.message.reasoning_content
                elif '<think>' in content:
                    # 启发式提取
                    parts = content.split('', 1)
                    if len(parts) > 1:
                        thinking = parts[0].replace('<think>', '').strip()
                        content = parts[1].strip()

                return LLMResponse(
                    content=content,
                    model=response.model,
                    thinking=thinking,
                    usage={
                        'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                        'completion_tokens': response.usage.completion_tokens if response.usage else 0,
                        'total_tokens': response.usage.total_tokens if response.usage else 0,
                    },
                    finish_reason=choice.finish_reason or 'stop',
                )
            except Exception as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._calculate_retry_delay(e, attempt)
                    logging.getLogger('llm').warning(
                        f'{self._get_provider_name()} 调用失败，{delay:.1f}s 后重试 ({attempt + 1}/{self._max_retries}): {e}')
                    await asyncio.sleep(delay)

        # 所有重试失败
        logging.getLogger('llm').error(f'{self._get_provider_name()} 所有重试失败: {last_error}')
        raise last_error

    async def _structured_chat_delegate(
        self,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> LLMResponse:
        """OpenAI 兼容的 JSON mode 实现 — 使用 response_format={"type": "json_object"}"""
        from ..structured_output import StructuredOutputMixin
        constraint = StructuredOutputMixin._build_constraint_message(schema)
        enhanced = list(messages)
        if enhanced and enhanced[0].role == 'system':
            enhanced[0] = LLMMessage(role='system', content=enhanced[0].content + '\n\n' + constraint)
        else:
            enhanced.insert(0, LLMMessage(role='system', content=constraint))
        return await self.chat(messages=enhanced, response_format={'type': 'json_object'}, **kwargs)

    async def chat_stream(self, messages: list[LLMMessage], **kwargs) -> AsyncIterator[str | tuple[str, str]]:
        """流式输出，支持 Thinking Token 分离"""
        logger = logging.getLogger('llm')
        parser = ThinkTagParser()

        try:
            client = self._get_client()
            stream = await client.chat.completions.create(
                model=self.config.model or self.DEFAULT_MODEL,
                messages=[{'role': m.role, 'content': m.content} for m in messages],
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                content = ""

                # 优先处理原生 reasoning_content (DeepSeek)
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    yield ("thinking", delta.reasoning_content)
                    continue

                if delta.content:
                    content = delta.content

                # 使用 ThinkTagParser 处理嵌入在 content 中的 <think> 标签
                for p_chunk in parser.feed(content):
                    if p_chunk.type == _CT.THINKING:
                        yield ("thinking", p_chunk.content)
                    else:
                        yield p_chunk.content

        except Exception as e:
            logger.error(f'{self._get_provider_name()} 流式调用失败: {e}')
            raise

    def get_model_info(self) -> dict[str, Any]:
        return {
            'provider': self._get_provider_name(),
            'model': self.config.model or self.DEFAULT_MODEL,
            'max_tokens': self.config.max_tokens,
            'supports_streaming': True,
        }

    def _get_provider_name(self) -> str:
        """子类覆盖此方法返回提供商名称"""
        return 'openai-compatible'


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI 提供商实现"""

    DEFAULT_BASE_URL = ''
    DEFAULT_MODEL = 'gpt-4o'

    def _get_provider_name(self) -> str:
        return 'openai'


__all__ = ['OpenAICompatibleProvider', 'OpenAIProvider']

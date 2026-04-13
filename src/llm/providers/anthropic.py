"""Anthropic Provider - Anthropic Claude 提供商实现"""
from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from ..config import LLMConfig, LLMMessage, LLMResponse
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


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude 提供商实现（含 Prompt Caching 支持）

    Prompt Caching (借鉴 Aider):
    - 对 system prompt 标记 cache_control breakpoint
    - 减少重复上下文的 token 成本 ~90%
    - 自动检测 SDK 是否支持 caching
    """

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._max_retries = config.max_retries
        self._client: Any = None
        self._cache_control = getattr(config, 'cache_control', None)
        # 检测 SDK 是否支持 prompt caching
        self._supports_caching = self._check_caching_support()

    def _get_client(self) -> Any:
        """获取或创建 Anthropic 客户端（懒加载 + LRU+TTL 连接池复用）

        同步锁保护全局缓存（与 OpenAICompatibleProvider 一致）。
        """
        if self._client is not None:
            return self._client

        key_prefix = self.config.api_key[:8] if len(self.config.api_key) >= 8 else self.config.api_key
        cache_key = f'AnthropicProvider:{key_prefix}:{self.config.model}'
        now = time.time()

        with _client_cache_lock:
            if self._client is not None:
                return self._client

            if cache_key in _client_cache:
                cached_client, cached_time = _client_cache[cache_key]
                if now - cached_time < _CLIENT_CACHE_TTL:
                    _client_cache[cache_key] = (cached_client, now)
                    _client_cache.move_to_end(cache_key)
                    self._client = cached_client
                    return self._client
                else:
                    del _client_cache[cache_key]

            if len(_client_cache) >= _CLIENT_CACHE_MAX_SIZE:
                _client_cache.popitem(last=False)

            try:
                from anthropic import AsyncAnthropic
                client = AsyncAnthropic(
                    api_key=self.config.api_key,
                    timeout=self.config.timeout,
                )
                _client_cache[cache_key] = (client, now)
                self._client = client
                return client
            except ImportError:
                raise ImportError('请安装 anthropic 包: pip install anthropic') from None

    @staticmethod
    def _check_caching_support() -> bool:
        """检查 Anthropic SDK 是否支持 prompt caching"""
        try:
            import anthropic
            version = getattr(anthropic, '__version__', '0.0.0')
            # caching 从 0.18.0 开始支持
            from packaging.version import parse as parse_version
            return parse_version(version) >= parse_version('0.18.0')
        except Exception:
            return False

    def _build_system_with_cache(self, system_msg: str) -> Any:
        """构建带 cache_control 的 system prompt（借鉴 Aider）

        Anthropic Prompt Caching:
        - 对长 system prompt 标记 cache_control breakpoint
        - 后续请求如果 system prompt 不变，可复用缓存
        - 缓存命中时 input token 成本降低 90%
        """
        if not self._supports_caching or not self._cache_control:
            return system_msg

        # system prompt 超过 1024 token 时才启用缓存（短 prompt 缓存无意义）
        estimated_tokens = len(system_msg) // 4
        if estimated_tokens < 1024:
            return system_msg

        try:
            # Anthropic cache_control 格式
            return [
                {
                    'type': 'text',
                    'text': system_msg,
                    'cache_control': {'type': 'ephemeral'},
                }
            ]
        except Exception:
            return system_msg

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """发送聊天消息（带优化拦截 + 指数退避重试 + Prompt Caching）"""
        # 尝试优化拦截
        system_msg = next((m.content for m in messages if m.role == 'system'), '')
        opt_result = try_optimizations(messages, system=system_msg, model=self.config.model)
        if opt_result:
            return LLMResponse(**opt_result)

        # 构建 system prompt（含缓存控制）
        system_prompt = self._build_system_with_cache(system_msg)

        last_error = None
        for attempt in range(self._max_retries):
            try:
                client = self._get_client()
                create_kwargs: dict[str, Any] = {
                    'model': self.config.model or 'claude-3-5-sonnet-20241022',
                    'system': system_prompt,
                    'messages': [{'role': m.role, 'content': m.content} for m in messages if m.role != 'system'],
                    'max_tokens': self.config.max_tokens,
                    'temperature': self.config.temperature,
                }

                # Prompt Caching: 添加 cache-breaking 参数（从 Aider 移植）
                if self._supports_caching and self._cache_control:
                    # 启用 prompt caching
                    create_kwargs['extra_headers'] = {
                        'anthropic-beta': 'prompt-caching-2024-07-31',
                    }

                response = await self._execute_with_limit(
                    client.messages.create(**create_kwargs)
                )

                content = response.content[0].text if response.content else ''
                thinking = ""

                # Anthropic 原生 Thinking 支持
                if hasattr(response, 'thinking') and response.thinking:
                    thinking = response.thinking

                # 提取缓存命中信息（用于成本追踪）
                usage_data = {
                    'input_tokens': response.usage.input_tokens if response.usage else 0,
                    'output_tokens': response.usage.output_tokens if response.usage else 0,
                }
                if hasattr(response.usage, 'cache_read_input_tokens'):
                    usage_data['cache_read_tokens'] = response.usage.cache_read_input_tokens or 0
                if hasattr(response.usage, 'cache_creation_input_tokens'):
                    usage_data['cache_write_tokens'] = response.usage.cache_creation_input_tokens or 0

                return LLMResponse(
                    content=content,
                    model=response.model,
                    thinking=thinking,
                    usage=usage_data,
                    finish_reason=response.stop_reason or 'stop',
                )
            except Exception as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._calculate_retry_delay(e, attempt)
                    logging.getLogger('llm').warning(
                        f'{self._get_provider_name()} 调用失败，{delay:.1f}s 后重试 ({attempt + 1}/{self._max_retries}): {e}')
                    await asyncio.sleep(delay)

        logging.getLogger('llm').error(f'{self._get_provider_name()} 所有重试失败: {last_error}')
        raise last_error

    async def chat_stream(self, messages: list[LLMMessage], **kwargs) -> AsyncIterator[str | tuple[str, str]]:
        logger = logging.getLogger('llm')
        parser = ThinkTagParser()

        try:
            client = self._get_client()
            system_msg = next((m.content for m in messages if m.role == 'system'), '')
            user_msgs = [m for m in messages if m.role != 'system']

            # 注意：Anthropic SDK 的 stream 是 context manager
            async with client.messages.stream(
                model=self.config.model or 'claude-3-5-sonnet-20241022',
                system=system_msg,
                messages=[{'role': m.role, 'content': m.content} for m in user_msgs],
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                **kwargs,
            ) as stream:
                async for event in stream:
                    # 兼容新旧 SDK 版本
                    if hasattr(event, 'type'):
                        if event.type == 'content_block_delta':
                            if hasattr(event.delta, 'text'):
                                content = event.delta.text
                                for p_chunk in parser.feed(content):
                                    if p_chunk.type == _CT.THINKING:
                                        yield ("thinking", p_chunk.content)
                                    else:
                                        yield p_chunk.content
                            elif hasattr(event.delta, 'thinking'):
                                # 未来原生支持思考
                                yield ("thinking", event.delta.thinking)
                    elif isinstance(event, str):
                        # 旧版 text_stream 包装
                        for p_chunk in parser.feed(event):
                            if p_chunk.type == _CT.THINKING:
                                yield ("thinking", p_chunk.content)
                            else:
                                yield p_chunk.content
        except Exception as e:
            logger.error(f'{self._get_provider_name()} 流式调用失败: {e}')
            raise

    def _get_provider_name(self) -> str:
        return 'anthropic'

    def get_model_info(self) -> dict[str, Any]:
        return {
            'provider': 'anthropic',
            'model': self.config.model or 'claude-3-5-sonnet-20241022',
            'max_tokens': self.config.max_tokens,
            'supports_streaming': True,
        }


# 需要 asyncio 用于重试
import asyncio

__all__ = ['AnthropicProvider']

"""Other Providers - Google, Groq, Together, Mistral, DeepSeek, OpenRouter"""
from typing import Any

from .openai import OpenAICompatibleProvider


class GoogleProvider(OpenAICompatibleProvider):
    """Google Gemini 提供商实现（使用 OpenAI 兼容模式）

    Google Gemini 支持 OpenAI 兼容的 API 格式，
    通过 https://generativelanguage.googleapis.com/v1beta/openai/ 端点访问。
    此实现复用 OpenAICompatibleProvider 基类，零新增依赖。
    """

    DEFAULT_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/openai/'
    DEFAULT_MODEL = 'gemini-2.0-flash'

    def _get_provider_name(self) -> str:
        return 'google'


class GroqProvider(OpenAICompatibleProvider):
    """Groq LLM 提供商实现（使用 OpenAI 兼容模式）

    Groq 提供超高速推理，兼容 OpenAI API 格式。
    默认端点: https://api.groq.com/openai/v1
    支持模型: llama-3.3-70b-versatile, mixtral-8x7b-32768 等
    """

    DEFAULT_BASE_URL = 'https://api.groq.com/openai/v1'
    DEFAULT_MODEL = 'llama-3.3-70b-versatile'

    def _get_provider_name(self) -> str:
        return 'groq'


class TogetherProvider(OpenAICompatibleProvider):
    """Together AI LLM 提供商实现（使用 OpenAI 兼容模式）

    Together AI 提供多种开源模型，兼容 OpenAI API 格式。
    默认端点: https://api.together.xyz/v1
    支持模型: meta-llama/Llama-3.3-70B-Instruct-Turbo, mistralai/Mixtral-8x7B-Instruct-v0.1 等
    """

    DEFAULT_BASE_URL = 'https://api.together.xyz/v1'
    DEFAULT_MODEL = 'meta-llama/Llama-3.3-70B-Instruct-Turbo'

    def _get_provider_name(self) -> str:
        return 'together'


class MistralProvider(OpenAICompatibleProvider):
    """Mistral AI LLM 提供商实现（使用 OpenAI 兼容模式)

    Mistral AI 提供高效的开源模型，兼容 OpenAI API 格式。
    默认端点: https://api.mistral.ai/v1
    支持模型: mistral-large-latest, mistral-small-latest, codestral-latest 等
    """

    DEFAULT_BASE_URL = 'https://api.mistral.ai/v1'
    DEFAULT_MODEL = 'mistral-large-latest'

    def _get_provider_name(self) -> str:
        return 'mistral'


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek LLM 提供商实现（使用 OpenAI 兼容模式）

    DeepSeek 提供高性价比的开源模型，兼容 OpenAI API 格式。
    默认端点: https://api.deepseek.com/v1
    支持模型: deepseek-chat, deepseek-coder, deepseek-reasoner 等
    """

    DEFAULT_BASE_URL = 'https://api.deepseek.com/v1'
    DEFAULT_MODEL = 'deepseek-chat'

    def _get_provider_name(self) -> str:
        return 'deepseek'


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter LLM 聚合平台提供商（使用 OpenAI 兼容模式）

    OpenRouter 聚合 300+ 模型，支持自动路由、fallback、缓存等。
    默认端点: https://openrouter.ai/api/v1
    支持模型: qwen/qwen3.6-plus:free, anthropic/claude-3.5-sonnet, openai/gpt-4o 等

    特色功能:
    - 多模型自动 fallback
    - 内置请求缓存（部分模型支持）
    - 统一的 API 接口
    - 成本优化（免费模型支持）
    """

    DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1'
    DEFAULT_MODEL = 'qwen/qwen3.6-plus:free'

    def _get_provider_name(self) -> str:
        return 'openrouter'

    def _get_client(self) -> Any:
        """获取 OpenRouter 客户端（添加特殊 headers）"""
        import time

        # 复用 base.py 的缓存
        from .base import _CLIENT_CACHE_MAX_SIZE, _CLIENT_CACHE_TTL, _client_cache, _client_cache_lock

        cache_key = self._get_cache_key()
        now = time.time()

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

            if len(_client_cache) >= _CLIENT_CACHE_MAX_SIZE:
                _client_cache.popitem(last=False)

            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(
                    api_key=self.config.api_key,
                    base_url=self.config.base_url or self.DEFAULT_BASE_URL,
                    timeout=self.config.timeout,
                    default_headers={
                        'HTTP-Referer': 'https://github.com/claw-code-tingfeng',  # OpenRouter 要求
                        'X-Title': 'Clawd Code',  # 应用标识
                    },
                )
                _client_cache[cache_key] = (client, now)
                self._client = client
                return client
            except ImportError:
                raise ImportError('请安装 openai 包: pip install openai') from None


__all__ = [
    'DeepSeekProvider',
    'GoogleProvider',
    'GroqProvider',
    'MistralProvider',
    'OpenRouterProvider',
    'TogetherProvider',
]

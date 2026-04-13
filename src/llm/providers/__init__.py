# LLM Providers - 可扩展的提供商模块
"""
按提供商类型拆分的模块化设计。

每个提供商独立文件，便于维护和扩展。
"""
# 从 base 模块导入基础类
# 从 config 模块导入配置类
from ..config import LLMConfig, LLMMessage, LLMProviderType, LLMResponse

# 从 rate_limiter 模块导入速率限制器
from ..rate_limiter import GlobalRateLimiter

# 从 anthropic 模块导入 Anthropic 提供商
from .anthropic import AnthropicProvider
from .base import (
    _CLIENT_CACHE_MAX_SIZE,
    _CLIENT_CACHE_TTL,
    BaseLLMProvider,
    _client_cache,
    _client_cache_lock,
)

# 从 openai 模块导入 OpenAI 兼容提供商
from .openai import OpenAICompatibleProvider, OpenAIProvider

# 从 others 模块导入其他提供商
from .others import (
    DeepSeekProvider,
    GoogleProvider,
    GroqProvider,
    MistralProvider,
    OpenRouterProvider,
    TogetherProvider,
)


def create_llm_provider(config: LLMConfig) -> BaseLLMProvider:
    """工厂方法 - 创建 LLM 提供商实例"""
    providers = {
        LLMProviderType.OPENAI: OpenAIProvider,
        LLMProviderType.ANTHROPIC: AnthropicProvider,
        LLMProviderType.GOOGLE: GoogleProvider,
        LLMProviderType.GROQ: GroqProvider,
        LLMProviderType.TOGETHER: TogetherProvider,
        LLMProviderType.MISTRAL: MistralProvider,
        LLMProviderType.DEEPSEEK: DeepSeekProvider,
        LLMProviderType.OPENROUTER: OpenRouterProvider,
    }
    provider_class = providers.get(config.provider)
    if provider_class is None:
        raise ValueError(f'不支持的 LLM 提供商: {config.provider}')
    return provider_class(config)


__all__ = [
    '_CLIENT_CACHE_MAX_SIZE',
    '_CLIENT_CACHE_TTL',
    'AnthropicProvider',
    # Base
    'BaseLLMProvider',
    'DeepSeekProvider',
    'GlobalRateLimiter',
    'GoogleProvider',
    'GroqProvider',
    'LLMConfig',
    'LLMMessage',
    'LLMProviderType',
    'LLMResponse',
    'MistralProvider',
    # Providers
    'OpenAICompatibleProvider',
    'OpenAIProvider',
    'OpenRouterProvider',
    'TogetherProvider',
    # 缓存相关（供内部使用）
    '_client_cache',
    '_client_cache_lock',
    # Factory
    'create_llm_provider',
]

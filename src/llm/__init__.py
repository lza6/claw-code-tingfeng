"""LLM 抽象层 - 支持多提供商（含 Client 连接池 LRU+TTL 优化）

此模块已被拆分为多个子模块：
- config: 配置类和数据类
- rate_limiter: 全局速率限制器
- providers: LLM 提供商实现
- 其他现有模块保持不变
"""
from __future__ import annotations

# 从 reasoning 模块导入推理标签处理
# 导入缓存相关（向后兼容）
from . import cache, channel_cache

# 从 config 模块导入配置类
from .config import (
    LLMConfig,
    LLMMessage,
    LLMProviderType,
    LLMResponse,
)

# 从 lazy_litellm 模块导入 LiteLLM
from .lazy_litellm import (
    completion_cost,
    get_litellm,
    litellm,
)

# 从 message_handler 模块导入消息处理
from .message_handler import (
    count_messages_by_role,
    dedup_consecutive_messages,
    extract_system_prompt,
    format_messages_for_llm,
    get_last_user_message,
    has_tool_calls,
    validate_and_fix_messages,
)

# 从 message_sanitizer 模块导入消息清理
from .message_sanitizer import (
    ensure_alternating_roles,
    sanitize_messages,
    sanity_check_messages,
)

# 从 prompts 模块导入提示词
from .prompts import (
    BasePrompts,
    EditPrompts,
    PromptSection,
    get_prompts_for_model,
)

# 从 providers 模块导入所有提供商
# 工厂方法
from .providers import (
    AnthropicProvider,
    BaseLLMProvider,
    DeepSeekProvider,
    GoogleProvider,
    GroqProvider,
    MistralProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    OpenRouterProvider,
    TogetherProvider,
    create_llm_provider,
)

# 从 rate_limiter 模块导入速率限制器
from .rate_limiter import GlobalRateLimiter
from .reasoning import (
    REASONING_TAG,
    REASONING_TAG_ALIASES,
    extract_reasoning_content,
    format_reasoning_content,
    get_reasoning_stats,
    has_reasoning_content,
    normalize_reasoning_tags,
    remove_reasoning_content,
    replace_reasoning_tags,
    split_reasoning_and_answer,
)

# 从 structured_output 模块导入结构化输出
from .structured_output import (
    AnthropicStructuredMixin,
    GoogleStructuredMixin,
    JsonSchema,
    OpenAICompatibleStructuredMixin,
    StructuredOutputMixin,
    StructuredResponse,
    create_structured_prompt,
    get_structured_mixin,
    validate_structured_response,
)

# 从 weak_model_router 模块导入弱模型路由
from .weak_model_router import (
    WeakModelConfig,
    WeakModelRouter,
    auto_detect_weak_model,
)

logger = __import__('logging').getLogger('llm')

__all__ = [
    # Reasoning Tags
    'REASONING_TAG',
    'REASONING_TAG_ALIASES',
    'AnthropicProvider',
    # 结构化输出
    'AnthropicStructuredMixin',
    # 提供商
    'BaseLLMProvider',
    # Prompts
    'BasePrompts',
    'DeepSeekProvider',
    'EditPrompts',
    # 速率限制器
    'GlobalRateLimiter',
    'GoogleProvider',
    'GoogleStructuredMixin',
    'GroqProvider',
    'JsonSchema',
    'LLMConfig',
    'LLMMessage',
    # 配置类
    'LLMProviderType',
    'LLMResponse',
    'MistralProvider',
    'OpenAICompatibleProvider',
    'OpenAICompatibleStructuredMixin',
    'OpenAIProvider',
    'OpenRouterProvider',
    'PromptSection',
    'StructuredOutputMixin',
    'StructuredResponse',
    'TogetherProvider',
    'WeakModelConfig',
    # Weak Model Router
    'WeakModelRouter',
    'auto_detect_weak_model',
    'completion_cost',
    'count_messages_by_role',
    # 工厂方法
    'create_llm_provider',
    'create_structured_prompt',
    'dedup_consecutive_messages',
    # Message Sanitization
    'ensure_alternating_roles',
    'extract_reasoning_content',
    'extract_system_prompt',
    # Message Handler
    'format_messages_for_llm',
    'format_reasoning_content',
    'get_last_user_message',
    'get_litellm',
    'get_prompts_for_model',
    'get_reasoning_stats',
    'get_structured_mixin',
    'has_reasoning_content',
    'has_tool_calls',
    # LiteLLM
    'litellm',
    'normalize_reasoning_tags',
    'remove_reasoning_content',
    'replace_reasoning_tags',
    'sanitize_messages',
    'sanity_check_messages',
    'split_reasoning_and_answer',
    'validate_and_fix_messages',
    'validate_structured_response',
]

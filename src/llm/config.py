"""LLM 配置模块 - 数据类与枚举"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class LLMProviderType(Enum):
    """LLM 提供商类型"""
    OPENAI = 'openai'
    ANTHROPIC = 'anthropic'
    GOOGLE = 'google'
    GROQ = 'groq'
    TOGETHER = 'together'
    MISTRAL = 'mistral'
    DEEPSEEK = 'deepseek'
    OPENROUTER = 'openrouter'  # OpenRouter 多模型聚合
    CUSTOM = 'custom'


@dataclass(frozen=True)
class LLMMessage:
    """LLM 消息

    `tool_calls` / `tool_call_id` / `name` 用于原生 function calling：
    - assistant 消息携带 `tool_calls`；
    - 工具结果以 `role="tool"` + `tool_call_id` 回传。
    不使用原生调用时这些字段均为 None，行为与旧版一致。
    """
    role: str  # system | user | assistant | tool
    #: 纯文本用 str；带图消息用内容块列表（OpenAI 兼容的
    #: `[{"type": "text", ...}, {"type": "image_url", ...}]`），见 src/llm/vision.py
    content: str | list[dict]
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    thinking: str = ""  # 推理过程（Ported from Project B）
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = 'stop'
    #: 原生 function calling 的原始 tool_calls（OpenAI 兼容格式）。
    #: 为空表示模型没有发起工具调用。
    tool_calls: list[dict] | None = None


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: LLMProviderType
    api_key: str = ''
    base_url: str = ''
    api_path_suffix: str = '/v1/chat/completions'  # API 路径后缀
    model: str = ''
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 60
    max_retries: int = 5  # 企业级默认重试次数
    cache_control: bool = False  # 启用 Prompt Caching（借鉴 Aider）

    @classmethod
    def from_env(cls) -> LLMConfig:
        """从环境变量自动加载 LLM 配置（零依赖）

        支持的环境变量：
        - LLM_PROVIDER: openai | anthropic | google | groq | together | mistral | deepseek (默认 openai)
        - OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY / GROQ_API_KEY 等
        - OPENAI_MODEL / ANTHROPIC_MODEL / GOOGLE_MODEL 等
        - OPENAI_BASE_URL / ANTHROPIC_BASE_URL / GOOGLE_BASE_URL 等
        - MAX_TOKENS (默认 4096)
        - TEMPERATURE (默认 0.7)
        - TIMEOUT (默认 60)
        """
        provider_str = os.environ.get('LLM_PROVIDER', 'openai').lower()
        provider_map = {
            'openai': LLMProviderType.OPENAI,
            'anthropic': LLMProviderType.ANTHROPIC,
            'google': LLMProviderType.GOOGLE,
            'groq': LLMProviderType.GROQ,
            'together': LLMProviderType.TOGETHER,
            'mistral': LLMProviderType.MISTRAL,
            'deepseek': LLMProviderType.DEEPSEEK,
            'openrouter': LLMProviderType.OPENROUTER,
            'custom': LLMProviderType.CUSTOM,
        }
        provider = provider_map.get(provider_str, LLMProviderType.OPENAI)

        # 根据提供商类型读取对应的环境变量
        prefix = provider.value.upper()
        api_key = os.environ.get(f'{prefix}_API_KEY', '')
        base_url = os.environ.get(f'{prefix}_BASE_URL', '')
        api_path_suffix = os.environ.get('API_PATH_SUFFIX', '/v1/chat/completions')
        model = os.environ.get(f'{prefix}_MODEL', '')

        max_tokens = int(os.environ.get('MAX_TOKENS', '4096'))
        temperature = float(os.environ.get('TEMPERATURE', '0.7'))
        timeout = int(os.environ.get('TIMEOUT', '60'))
        max_retries = int(os.environ.get('MAX_RETRIES', '5'))

        return cls(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            api_path_suffix=api_path_suffix,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            max_retries=max_retries,
        )


__all__ = [
    'LLMConfig',
    'LLMMessage',
    'LLMProviderType',
    'LLMResponse',
]

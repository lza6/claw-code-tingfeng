"""Onboarding - 新用户引导 — 从 Aider onboarding.py 移植

自动检测 API 密钥、推荐默认模型、引导首次使用。

用法:
    onboarding = Onboarding()
    default_model = onboarding.try_select_default_model()
    onboarding.check_and_warn(io)
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ==================== API 密钥检测 ====================

# 环境变量到提供商的映射
ENV_KEY_MODEL_MAP: list[tuple[str, str, str]] = [
    ('ANTHROPIC_API_KEY', 'anthropic', 'claude-sonnet-4-5'),
    ('OPENAI_API_KEY', 'openai', 'gpt-4o'),
    ('DEEPSEEK_API_KEY', 'deepseek', 'deepseek/deepseek-chat'),
    ('GEMINI_API_KEY', 'google', 'gemini/gemini-2.5-pro'),
    ('OPENROUTER_API_KEY', 'openrouter', 'openrouter/anthropic/claude-sonnet-4'),
    ('GROQ_API_KEY', 'groq', 'groq/llama-3.1-70b-versatile'),
    ('TOGETHER_API_KEY', 'together', 'together/mistralai/Mixtral-8x7B-Instruct-v0.1'),
    ('MISTRAL_API_KEY', 'mistral', 'mistral/mistral-large-latest'),
    ('OLLAMA_API_BASE', 'ollama', 'ollama/llama3'),
]


class Onboarding:
    """新用户引导器

    自动检测环境中的 API 密钥，推荐默认模型，
    并提供首次使用的引导信息。
    """

    def __init__(self, settings: Any = None) -> None:
        """初始化

        参数:
            settings: 项目设置对象
        """
        self.settings = settings
        self._detected_keys: dict[str, str] = {}
        self._detected_providers: list[str] = []

    def detect_api_keys(self) -> dict[str, str]:
        """检测环境中可用的 API 密钥

        返回:
            {环境变量名: 提供商} 字典
        """
        self._detected_keys = {}

        for env_key, provider, _ in ENV_KEY_MODEL_MAP:
            value = os.environ.get(env_key)
            if value and value.strip():
                # 检查是否是占位符
                if value.strip().lower() in ('', 'your-key-here', 'sk-xxx'):
                    continue
                self._detected_keys[env_key] = provider

        return self._detected_keys

    def try_select_default_model(self) -> str | None:
        """尝试根据可用 API 密钥选择默认模型

        优先级:
        1. 已在设置中配置的模型
        2. Anthropic (Claude)
        3. OpenAI (GPT)
        4. DeepSeek
        5. Google (Gemini)
        6. OpenRouter
        7. 其他

        返回:
            推荐的模型名称，或 None
        """
        # 检查设置中已配置的模型
        if self.settings:
            configured_model = getattr(self.settings, 'default_model', None)
            if configured_model:
                return configured_model

        # 按优先级检测
        priority_order = [
            'ANTHROPIC_API_KEY',
            'OPENAI_API_KEY',
            'DEEPSEEK_API_KEY',
            'GEMINI_API_KEY',
            'OPENROUTER_API_KEY',
            'GROQ_API_KEY',
            'TOGETHER_API_KEY',
            'MISTRAL_API_KEY',
            'OLLAMA_API_BASE',
        ]

        for env_key in priority_order:
            if env_key in self._detected_keys:
                for ek, _provider, model in ENV_KEY_MODEL_MAP:
                    if ek == env_key:
                        return model

        return None

    def check_openrouter_tier(self, api_key: str) -> bool | None:
        """检查 OpenRouter 是否为免费层

        参数:
            api_key: OpenRouter API 密钥

        返回:
            True=免费层, False=付费层, None=检查失败
        """
        try:
            import httpx

            resp = httpx.get(
                'https://openrouter.ai/api/v1/auth/key',
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get('data', {}).get('is_free_tier', True)
        except Exception:
            return None

    def get_welcome_message(self, model_name: str | None = None) -> str:
        """生成欢迎消息

        参数:
            model_name: 选定的模型名称

        返回:
            欢迎消息字符串
        """
        keys = self.detect_api_keys()
        providers = list(set(keys.values()))

        lines: list[str] = []
        lines.append('欢迎使用 ClawCode AI 编程助手!')

        if model_name:
            lines.append(f'当前模型: {model_name}')

        if providers:
            provider_names = ', '.join(providers)
            lines.append(f'已检测到 API 密钥: {provider_names}')
        else:
            lines.append('')
            lines.append('未检测到 API 密钥。请设置以下环境变量之一:')
            for env_key, provider, model in ENV_KEY_MODEL_MAP[:5]:
                lines.append(f'  {env_key} → {provider} ({model})')
            lines.append('')
            lines.append('提示: 在 .env 文件中配置 API 密钥')

        return '\n'.join(lines)

    def get_status_report(self) -> dict[str, Any]:
        """生成环境状态报告

        返回:
            状态字典
        """
        keys = self.detect_api_keys()
        model = self.try_select_default_model()

        return {
            'has_api_keys': len(keys) > 0,
            'detected_providers': list(set(keys.values())),
            'recommended_model': model,
            'num_providers': len(set(keys.values())),
        }


# ==================== 便捷函数 ====================

def quick_check() -> str:
    """快速环境检查（便捷函数）

    返回:
        格式化的环境状态字符串
    """
    onboarding = Onboarding()
    keys = onboarding.detect_api_keys()
    model = onboarding.try_select_default_model()

    lines: list[str] = ['环境检查结果:']
    lines.append(f'  API 密钥: {len(keys)} 个已检测')

    if keys:
        for env_key, provider in keys.items():
            lines.append(f'    {env_key} → {provider}')

    lines.append(f'  推荐模型: {model or "未确定"}')

    return '\n'.join(lines)

"""模型别名映射

提供模型名称到规范名称的映射。
"""
from __future__ import annotations

# ==================== 模型别名映射 ====================

MODEL_ALIASES: dict[str, str] = {
    # Claude 系列
    'sonnet': 'claude-sonnet-4-5',
    'haiku': 'claude-haiku-4-5',
    'opus': 'claude-opus-4-6',
    'claude': 'claude-sonnet-4-5',
    'claude3': 'claude-3-5-sonnet-20241022',
    'claude3.5': 'claude-3-5-sonnet-20241022',
    # GPT 系列
    '4': 'gpt-4o',
    '4o': 'gpt-4o',
    '4-turbo': 'gpt-4o',
    '35turbo': 'gpt-3.5-turbo',
    '35-turbo': 'gpt-3.5-turbo',
    '3': 'gpt-3.5-turbo',
    'gpt': 'gpt-4o',
    'mini': 'gpt-4o-mini',
    # o 系列
    'o1': 'o1',
    'o1-preview': 'o1-preview',
    'o1-mini': 'o1-mini',
    'o3': 'o3-mini',
    # DeepSeek
    'deepseek': 'deepseek/deepseek-chat',
    'r1': 'deepseek/deepseek-reasoner',
    # Gemini
    'gemini': 'gemini/gemini-2.5-pro',
    'gemini-2.5-pro': 'gemini/gemini-2.5-pro',
    'flash': 'gemini/gemini-2.5-flash',
    'flash-lite': 'gemini/gemini-2.5-flash-lite',
    # Grok
    'grok': 'xai/grok-3-beta',
    'grok3': 'xai/grok-3-beta',
    # 其他
    'qwen': 'qwen/qwen-2.5-72b-instruct',
    # OpenRouter 快捷方式
    'quasar': 'openrouter/openrouter/quasar-alpha',
    'optimus': 'openrouter/openrouter/optimus-alpha',
}


__all__ = ['MODEL_ALIASES']

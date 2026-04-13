"""内置模型元数据

包含所有内置模型的 ModelInfo 和 ModelSettings 数据。
"""
from __future__ import annotations

from .dataclasses import ModelInfo, ModelSettings

# ==================== 内置模型信息 ====================

BUILTIN_MODEL_INFO: dict[str, ModelInfo] = {
    # Claude 系列
    'claude-opus-4-6': ModelInfo(
        name='claude-opus-4-6',
        max_input_tokens=200000,
        max_output_tokens=32000,
        input_price_per_million=15.0,
        output_price_per_million=75.0,
        cache_read_price_per_million=1.5,
        cache_write_price_per_million=18.75,
        supports_vision=True,
        supports_function_calling=True,
        supports_prompt_cache=True,
        edit_format='udiff',
        context_window=200000,
    ),
    'claude-sonnet-4-5': ModelInfo(
        name='claude-sonnet-4-5',
        max_input_tokens=200000,
        max_output_tokens=16000,
        input_price_per_million=3.0,
        output_price_per_million=15.0,
        cache_read_price_per_million=0.3,
        cache_write_price_per_million=3.75,
        supports_vision=True,
        supports_function_calling=True,
        supports_prompt_cache=True,
        edit_format='diff',
        context_window=200000,
    ),
    'claude-haiku-4-5': ModelInfo(
        name='claude-haiku-4-5',
        max_input_tokens=200000,
        max_output_tokens=8192,
        input_price_per_million=0.80,
        output_price_per_million=4.0,
        cache_read_price_per_million=0.08,
        cache_write_price_per_million=1.0,
        supports_vision=True,
        supports_function_calling=True,
        supports_prompt_cache=True,
        edit_format='diff',
        context_window=200000,
    ),
    # GPT 系列
    'gpt-4o': ModelInfo(
        name='gpt-4o',
        max_input_tokens=128000,
        max_output_tokens=16384,
        input_price_per_million=2.50,
        output_price_per_million=10.0,
        cache_read_price_per_million=1.25,
        cache_write_price_per_million=2.50,
        supports_vision=True,
        supports_function_calling=True,
        supports_prompt_cache=True,
        edit_format='diff',
        context_window=128000,
    ),
    'gpt-4o-mini': ModelInfo(
        name='gpt-4o-mini',
        max_input_tokens=128000,
        max_output_tokens=16384,
        input_price_per_million=0.15,
        output_price_per_million=0.60,
        supports_vision=True,
        supports_function_calling=True,
        edit_format='whole',
        context_window=128000,
    ),
    # Gemini 系列
    'gemini/gemini-2.5-pro': ModelInfo(
        name='gemini/gemini-2.5-pro',
        max_input_tokens=1048576,
        max_output_tokens=65536,
        input_price_per_million=1.25,
        output_price_per_million=10.0,
        supports_vision=True,
        supports_function_calling=True,
        edit_format='diff',
        context_window=1048576,
    ),
    # Claude 3.5 系列
    'claude-3-5-sonnet-20241022': ModelInfo(
        name='claude-3-5-sonnet-20241022',
        max_input_tokens=200000,
        max_output_tokens=8192,
        input_price_per_million=3.0,
        output_price_per_million=15.0,
        cache_read_price_per_million=0.3,
        cache_write_price_per_million=3.75,
        supports_vision=True,
        supports_function_calling=True,
        supports_prompt_cache=True,
        edit_format='diff',
        context_window=200000,
    ),
    'claude-3-5-haiku-20241022': ModelInfo(
        name='claude-3-5-haiku-20241022',
        max_input_tokens=200000,
        max_output_tokens=8192,
        input_price_per_million=1.0,
        output_price_per_million=5.0,
        cache_read_price_per_million=0.1,
        cache_write_price_per_million=1.25,
        supports_vision=True,
        supports_function_calling=True,
        supports_prompt_cache=True,
        edit_format='diff',
        context_window=200000,
    ),
    # Gemini Flash
    'gemini/gemini-2.5-flash': ModelInfo(
        name='gemini/gemini-2.5-flash',
        max_input_tokens=1048576,
        max_output_tokens=65536,
        input_price_per_million=0.15,
        output_price_per_million=0.60,
        supports_vision=True,
        supports_function_calling=True,
        edit_format='diff',
        context_window=1048576,
    ),
    'gemini/gemini-2.5-flash-lite': ModelInfo(
        name='gemini/gemini-2.5-flash-lite',
        max_input_tokens=1048576,
        max_output_tokens=65536,
        input_price_per_million=0.075,
        output_price_per_million=0.30,
        supports_vision=True,
        supports_function_calling=True,
        edit_format='whole',
        context_window=1048576,
    ),
    # o1 系列
    'o1': ModelInfo(
        name='o1',
        max_input_tokens=200000,
        max_output_tokens=100000,
        input_price_per_million=15.0,
        output_price_per_million=60.0,
        supports_vision=True,
        supports_function_calling=True,
        edit_format='diff',
        context_window=200000,
    ),
    'o3-mini': ModelInfo(
        name='o3-mini',
        max_input_tokens=200000,
        max_output_tokens=100000,
        input_price_per_million=1.10,
        output_price_per_million=4.40,
        supports_function_calling=True,
        edit_format='diff',
        context_window=200000,
    ),
    # Grok
    'xai/grok-3-beta': ModelInfo(
        name='xai/grok-3-beta',
        max_input_tokens=131072,
        max_output_tokens=32768,
        input_price_per_million=3.0,
        output_price_per_million=15.0,
        supports_function_calling=True,
        edit_format='diff',
        context_window=131072,
    ),
    # DeepSeek
    'deepseek/deepseek-chat': ModelInfo(
        name='deepseek/deepseek-chat',
        max_input_tokens=64000,
        max_output_tokens=8192,
        input_price_per_million=0.14,
        output_price_per_million=0.28,
        supports_function_calling=True,
        edit_format='diff',
        context_window=64000,
    ),
    'deepseek/deepseek-reasoner': ModelInfo(
        name='deepseek/deepseek-reasoner',
        max_input_tokens=64000,
        max_output_tokens=8192,
        input_price_per_million=0.55,
        output_price_per_million=2.19,
        supports_function_calling=True,
        edit_format='diff',
        reasoning_tag='think',
        context_window=64000,
    ),
}


# ==================== 模型设置（行为配置） ====================

BUILTIN_MODEL_SETTINGS: list[ModelSettings] = [
    # Claude Opus 系列 — 最强推理
    ModelSettings(
        name='claude-opus-4-6',
        edit_format='udiff',
        use_repo_map=True,
        caches_by_default=True,
        weak_model_name='claude-haiku-4-5',
        extra_params={'temperature': 1.0},
    ),
    ModelSettings(
        name='claude-3-opus-20240229',
        edit_format='diff',
        use_repo_map=True,
        caches_by_default=True,
        weak_model_name='claude-3-5-haiku-20241022',
    ),
    # Claude Sonnet 系列 — 平衡性价比
    ModelSettings(
        name='claude-sonnet-4-5',
        edit_format='diff',
        use_repo_map=True,
        caches_by_default=True,
        weak_model_name='claude-haiku-4-5',
    ),
    ModelSettings(
        name='claude-3-5-sonnet-20241022',
        edit_format='diff',
        use_repo_map=True,
        caches_by_default=True,
        weak_model_name='claude-3-5-haiku-20241022',
    ),
    ModelSettings(
        name='claude-3-5-sonnet-20240620',
        edit_format='diff',
        use_repo_map=True,
        weak_model_name='claude-3-5-haiku-20241022',
    ),
    # Claude Haiku 系列 — 快速轻量
    ModelSettings(
        name='claude-haiku-4-5',
        edit_format='diff',
        lazy=True,
        caches_by_default=True,
    ),
    ModelSettings(
        name='claude-3-5-haiku-20241022',
        edit_format='diff',
        lazy=True,
    ),
    # GPT-4 系列
    ModelSettings(
        name='gpt-4o',
        edit_format='diff',
        use_repo_map=True,
        weak_model_name='gpt-4o-mini',
        extra_params={'temperature': 0.0},
    ),
    ModelSettings(
        name='gpt-4o-2024-05-13',
        edit_format='diff',
        use_repo_map=True,
        weak_model_name='gpt-4o-mini',
    ),
    ModelSettings(
        name='gpt-4-turbo',
        edit_format='udiff',
        use_repo_map=True,
        weak_model_name='gpt-4o-mini',
    ),
    ModelSettings(
        name='gpt-4',
        edit_format='diff',
        use_repo_map=True,
        weak_model_name='gpt-4o-mini',
    ),
    # GPT-4o-mini
    ModelSettings(
        name='gpt-4o-mini',
        edit_format='whole',
        lazy=True,
    ),
    # GPT-3.5
    ModelSettings(
        name='gpt-3.5-turbo',
        edit_format='whole',
        lazy=True,
        reminder='sys',
    ),
    # o1 系列推理模型
    ModelSettings(
        name='o1',
        edit_format='diff',
        use_repo_map=True,
        use_system_prompt=False,
        use_temperature=False,
        streaming=False,
    ),
    ModelSettings(
        name='o1-preview',
        edit_format='diff',
        use_repo_map=True,
        use_system_prompt=False,
        use_temperature=False,
        streaming=False,
    ),
    ModelSettings(
        name='o1-mini',
        edit_format='diff',
        use_repo_map=True,
        use_system_prompt=False,
        use_temperature=False,
        streaming=False,
    ),
    # o3-mini
    ModelSettings(
        name='o3-mini',
        edit_format='diff',
        use_repo_map=True,
        use_temperature=False,
    ),
    # DeepSeek
    ModelSettings(
        name='deepseek/deepseek-chat',
        edit_format='diff',
        use_repo_map=True,
        reminder='sys',
    ),
    ModelSettings(
        name='deepseek/deepseek-reasoner',
        edit_format='diff',
        reasoning_tag='think',
        use_repo_map=True,
    ),
    # Gemini
    ModelSettings(
        name='gemini/gemini-2.5-pro',
        edit_format='diff',
        use_repo_map=True,
        extra_params={'temperature': 1.0},
    ),
    ModelSettings(
        name='gemini/gemini-2.5-flash',
        edit_format='diff',
        lazy=True,
    ),
    ModelSettings(
        name='gemini/gemini-2.5-flash-lite',
        edit_format='whole',
        lazy=True,
    ),
    # OpenRouter 模型
    ModelSettings(
        name='openrouter/anthropic/claude-sonnet-4',
        edit_format='diff',
        use_repo_map=True,
        caches_by_default=True,
    ),
    ModelSettings(
        name='openrouter/deepseek/deepseek-r1',
        edit_format='diff',
        reasoning_tag='think',
        use_repo_map=True,
    ),
    # Grok
    ModelSettings(
        name='xai/grok-2-1212',
        edit_format='diff',
        use_repo_map=True,
    ),
    ModelSettings(
        name='xai/grok-3-beta',
        edit_format='diff',
        use_repo_map=True,
    ),
    # Qwen
    ModelSettings(
        name='qwen/qwen-2.5-72b-instruct',
        edit_format='diff',
        use_repo_map=True,
    ),
    # 本地模型 (Ollama)
    ModelSettings(
        name='ollama/codellama',
        edit_format='whole',
        reminder='sys',
    ),
    ModelSettings(
        name='ollama/llama3.1',
        edit_format='whole',
        reminder='sys',
    ),
    ModelSettings(
        name='ollama/qwen2.5-coder',
        edit_format='diff',
        use_repo_map=True,
    ),
]


__all__ = ['BUILTIN_MODEL_INFO', 'BUILTIN_MODEL_SETTINGS']

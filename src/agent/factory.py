"""AgentEngine 工厂方法 - 创建代理引擎实例

从 agent/engine.py 拆分，负责：
- create_agent_engine 工厂函数
- 环境变量配置加载
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..llm import LLMConfig, LLMProviderType
from ..utils import debug

if TYPE_CHECKING:
    from .engine import AgentEngine


def create_agent_engine(
    provider_type: str = 'openai',
    api_key: str | None = None,
    model: str = '',
    workdir: Path | None = None,
    max_iterations: int = 10,
    enable_cost_tracking: bool = True,
    # RTK 集成 (v0.40.0)
    enable_output_compression: bool = True,
    enable_tee_mode: bool = True,
    enable_token_tracking: bool = True,
    developer_mode: bool = False,
    intent: str = 'deliver', # 新增意图参数
) -> AgentEngine:
    """工厂方法 - 创建代理引擎

    参数:
        provider_type: LLM 提供商类型 (openai/anthropic/google/groq/together/mistral/deepseek)
        api_key: API 密钥（为 None 时尝试从环境变量读取）
        model: 模型名称（为空时使用默认模型）
        workdir: 工作目录
        max_iterations: 最大迭代次数
        enable_cost_tracking: 是否启用成本追踪
        enable_output_compression: 是否启用输出压缩 (RTK 风格)
        enable_tee_mode: 是否启用 tee 模式 (失败时保存原始输出)
        enable_token_tracking: 是否启用 token 用量追踪
    """
    from .engine import AgentEngine

    # 如果未提供 api_key，尝试从环境变量加载配置
    if api_key is None:
        try:
            config = LLMConfig.from_env()
            debug(f'从环境变量加载 LLM 配置: {config.provider.value}')
            from ..core.config import get_settings
            _s = get_settings()
            return AgentEngine(
                llm_config=config,
                workdir=workdir,
                max_iterations=max_iterations,
                enable_cost_tracking=enable_cost_tracking,
                enable_output_compression=enable_output_compression,
                enable_tee_mode=enable_tee_mode,
                enable_token_tracking=enable_token_tracking,
                developer_mode=getattr(_s, 'developer_mode', developer_mode),
                intent=intent,
            )
        except (KeyError, ValueError) as e:
            debug(f'环境变量加载失败: {e}，使用默认配置')

    provider_map = {
        'openai': LLMProviderType.OPENAI,
        'anthropic': LLMProviderType.ANTHROPIC,
        'google': LLMProviderType.GOOGLE,
        'groq': LLMProviderType.GROQ,
        'together': LLMProviderType.TOGETHER,
        'mistral': LLMProviderType.MISTRAL,
        'deepseek': LLMProviderType.DEEPSEEK,
    }

    provider = provider_map.get(provider_type.lower(), LLMProviderType.OPENAI)

    model_map = {
        'openai': model or 'gpt-4o',
        'anthropic': model or 'claude-3-5-sonnet-20241022',
        'google': model or 'gemini-2.0-flash',
        'groq': model or 'llama-3.3-70b-versatile',
        'together': model or 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
        'mistral': model or 'mistral-large-latest',
        'deepseek': model or 'deepseek-chat',
    }

    config = LLMConfig(
        provider=provider,
        api_key=api_key or '',
        model=model_map.get(provider_type.lower(), 'gpt-4o'),
    )

    return AgentEngine(
        llm_config=config,
        workdir=workdir,
        max_iterations=max_iterations,
        enable_cost_tracking=enable_cost_tracking,
        enable_output_compression=enable_output_compression,
        enable_tee_mode=enable_tee_mode,
        enable_token_tracking=enable_token_tracking,
        developer_mode=developer_mode,
        intent=intent,
    )

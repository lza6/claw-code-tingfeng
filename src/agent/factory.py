"""AgentEngine 工厂方法 - 创建代理引擎实例

从 agent/engine.py 拆分，负责：
- create_agent_engine 工厂函数
- 环境变量配置加载
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..llm import LLMConfig, LLMProviderType
from ..utils import debug

if TYPE_CHECKING:
    from .engine import AgentEngine

#: 建立 RAG 索引时跳过的目录（与仓库约定一致）
_RAG_SKIP_DIRS = {
    '__pycache__', '.git', 'node_modules', 'dist', 'build', 'target',
    '.venv', 'venv', '.mypy_cache', '.pytest_cache', '.ruff_cache',
}

#: RAG 索引的文件上限，避免在超大仓库上拖慢启动
_RAG_MAX_FILES = 2000


def _create_rag_index(workdir: Path | None) -> object | None:
    """按需创建 RAG 索引。

    - 默认**不启用**（不改变既有行为）；
    - 设置 `CLAWD_ENABLE_RAG=1` 后，为工作目录建立惰性文本索引；
    - 索引在首次搜索时才真正构建（`LazyIndexer`），不阻塞启动；
    - 任何失败都降级为“无 RAG”，并留下 debug 痕迹。
    """
    if os.environ.get('CLAWD_ENABLE_RAG', '').lower() not in ('1', 'true', 'yes'):
        return None

    try:
        from ..rag import LazyIndexer

        index = LazyIndexer(index_content=True)
        root = workdir or Path.cwd()
        count = 0
        for path in root.rglob('*.py'):
            if count >= _RAG_MAX_FILES:
                break
            if any(part in _RAG_SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                index.add_file(path)
                count += 1
        debug(f'RAG 索引已挂载: {root} ({count} 个 Python 文件)')
        return index
    except Exception as e:
        debug(f'RAG 索引初始化失败，降级为无 RAG: {e}')
        return None


def get_agent_prompt(agent_name: str) -> str | None:
    """获取指定 Agent 的 Prompt 模板

    参数:
        agent_name: Agent 名称 (如 "analyst", "planner" 等)

    返回:
        Prompt 字符串，如果不存在则返回 None
    """
    try:
        from prompts.agents import get_prompt
        return get_prompt(agent_name)
    except Exception:
        return None


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
                rag_index=_create_rag_index(workdir),
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
        rag_index=_create_rag_index(workdir),
    )


# ===== 导出 =====
__all__ = [
    "create_agent_engine",
    "get_agent_prompt",
]

"""Configuration package for claw-code-tingfeng.

集中管理所有配置相关功能:
- 配置模型与加载 (AgentSettings / get_settings / load_settings)
- Feature flags (功能开关)
- Config TOML 合并与修复
- Skill catalog (Skill 清单)

历史问题 (v0.51.0 修复):
    本包曾只 re-export `merger` 的内容，导致
    `from src.core.config import AgentSettings / get_settings / load_settings`
    全部 ImportError —— 而 `src/agent/factory.py` 正是这样导入的，
    使 `create_agent_engine()`（创建 Agent 的主入口）直接崩溃。
    这些符号在 `.settings` 中一直存在，只是没有对外暴露。
"""

from __future__ import annotations

from pathlib import Path

from .enums import ApprovalMode, ConfigSource, ConfigSourceKind, LLMProviderEnum, LogLevelEnum
from .merger import (
    OMX_FEATURE_FLAGS,
    OMX_TOP_LEVEL_KEYS,
    get_model_from_config,
    get_reasoning_effort,
    merge_config,
    merge_config_file,
)
from .settings import (
    AgentSettings,
    apply_config_overrides,
    get_config_priority_report,
    get_runtime_config,
    get_settings,
    load_settings,
    reload_config,
    reload_settings,
    reset_settings,
    set_runtime_config,
)


def ensure_project_dirs(workdir: str | Path | None = None) -> None:
    """确保项目运行所需的 `.clawd/` 目录骨架存在。

    调用方（项目初始化流程）需要先建目录再写配置，因此该函数归属配置包。
    实现委托给 `ProjectContext.ensure_dirs()` —— 目录清单只保留一份真相源，
    避免两处各自维护而漂移。

    Args:
        workdir: 项目根目录；None 表示当前工作目录。
    """
    # 延迟导入：project_context 会间接依赖核心模块，放在函数内可避免
    # 包初始化期的循环引用。
    from ..project_context import ProjectContext

    ProjectContext(workdir=Path(workdir) if workdir else None).ensure_dirs()


__all__ = [
    'OMX_FEATURE_FLAGS',
    'OMX_TOP_LEVEL_KEYS',
    # Model & Functions
    'AgentSettings',
    # Enums
    'ApprovalMode',
    'ConfigSource',
    'ConfigSourceKind',
    'LLMProviderEnum',
    'LogLevelEnum',
    'apply_config_overrides',
    'ensure_project_dirs',
    'get_config_priority_report',
    'get_model_from_config',
    'get_reasoning_effort',
    'get_runtime_config',
    'get_settings',
    'load_settings',
    'merge_config',
    'merge_config_file',
    'reload_config',
    'reload_settings',
    'reset_settings',
    'set_runtime_config',
]

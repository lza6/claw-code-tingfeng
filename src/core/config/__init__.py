"""Configuration package for claw-code-tingfeng.

集中管理所有配置相关功能:
- Feature flags (功能开关)
- Config TOML 合并与修复
- Skill catalog (Skill 清单)
"""

from .merger import (
    OMX_FEATURE_FLAGS,
    OMX_TOP_LEVEL_KEYS,
    get_model_from_config,
    get_reasoning_effort,
    merge_config,
    merge_config_file,
)

__all__ = [
    'OMX_FEATURE_FLAGS',
    'OMX_TOP_LEVEL_KEYS',
    'get_model_from_config',
    'get_reasoning_effort',
    'merge_config',
    'merge_config_file',
]

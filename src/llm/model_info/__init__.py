"""模型信息管理器 — 从 Aider models.py 移植并增强

集中管理模型元数据、别名映射和能力配置。

核心功能:
- 模型别名映射（sonnet → claude-sonnet-4-5）
- 模型能力元数据（max_tokens, edit_format, cache_support 等）
- 模型验证和推荐
- 多提供商统一接口

用法:
    manager = ModelInfoManager()
    info = manager.get_model_info('sonnet')
    print(info.max_input_tokens)

模块结构:
- aliases: 模型别名映射
- dataclasses: ModelSettings 和 ModelInfo 数据类
- builtins: 内置模型元数据
- manager: ModelInfoManager 管理器类
"""
from __future__ import annotations

# 从子模块导入所有公共 API，保持向后兼容
from .aliases import MODEL_ALIASES
from .builtins import BUILTIN_MODEL_INFO, BUILTIN_MODEL_SETTINGS
from .dataclasses import ModelInfo, ModelSettings
from .manager import (
    ModelInfoManager,
    get_model_info_manager,
)

# ==================== 向后兼容导出 ====================

# 为了保持向后兼容，直接在模块级别导出这些类
__all__ = [
    # 内置数据
    'BUILTIN_MODEL_INFO',
    'BUILTIN_MODEL_SETTINGS',
    # 别名
    'MODEL_ALIASES',
    'ModelInfo',
    # 管理器
    'ModelInfoManager',
    # 数据类
    'ModelSettings',
    'get_model_info_manager',
]

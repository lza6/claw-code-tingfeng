"""模型信息管理器 — 已迁移到 model_info 子模块

此文件已拆分为 model_info/ 子模块:
- src/llm/model_info/aliases.py - 模型别名映射
- src/llm/model_info/dataclasses.py - 数据类定义
- src/llm/model_info/builtins.py - 内置模型元数据
- src/llm/model_info/manager.py - 管理器实现

向后兼容: 所有原有导入路径继续工作。
"""
from __future__ import annotations

# 重新导出，保持向后兼容
from .model_info import (
    BUILTIN_MODEL_INFO,
    BUILTIN_MODEL_SETTINGS,
    MODEL_ALIASES,
    ModelInfo,
    ModelInfoManager,
    ModelSettings,
    get_model_info_manager,
)

__all__ = [
    'BUILTIN_MODEL_INFO',
    'BUILTIN_MODEL_SETTINGS',
    'MODEL_ALIASES',
    'ModelInfo',
    'ModelInfoManager',
    'ModelSettings',
    'get_model_info_manager',
]

"""Brain — 中枢神经系统模块

Clawd Code V5.0 的 "中枢神经系统"，负责:
- 长效记忆的模式识别 (Pattern Extraction)
- 自省逻辑 (Self-Reflection)
- 工具权限的动态调节
- 语义熵分析 (Semantic Entropy)
- 配置热修补 (Config Patch)

模块结构:
- models.py: 数据模型 (OptimizationAdvice, BrainRule, EntropyReport, ConfigPatch)
- entropy.py: SemanticEntropyAnalyzer
- pattern_extractor.py: 模式提取协议
- config_patcher.py: 配置热修补
- evolution_oracle.py: EvolutionOracle 主类
- memory_adapter.py: SQLite 持久化适配器
"""
from __future__ import annotations

from .config_patcher import ConfigPatcher
from .entropy import SemanticEntropyAnalyzer
from .evolution_oracle import EvolutionOracle
from .memory_adapter import MemoryAdapter
from .models import (
    BrainRule,
    ConfigPatchResult,
    EntropyReport,
    FailureSequence,
    OptimizationAdvice,
    SuccessVector,
)
from .pattern_extractor import PatternExtractor
from .world_model import RepositoryWorldModel

__all__ = [
    "BrainRule",
    "ConfigPatchResult",
    "ConfigPatcher",
    "EntropyReport",
    "EvolutionOracle",
    "FailureSequence",
    "MemoryAdapter",
    "OptimizationAdvice",
    "PatternExtractor",
    "RepositoryWorldModel",
    "SemanticEntropyAnalyzer",
    "SuccessVector",
]

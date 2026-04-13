"""Self-Healing — 自主自愈引擎

工作流错误自动感知与 AI 驱动的无干预修复循环。

组件:
- SelfHealingEngine: 自愈主引擎
- ErrorClassifier: 错误分类器
- AIDiagnoser: AI 诊断器
- Verifier: 验证器

使用示例:
    from src.self_healing import SelfHealingEngine, SelfHealingConfig

    engine = SelfHealingEngine(workdir=Path.cwd())
    result = await engine.heal(error=e, context={'code': code})
    print(f"修复成功: {result.success}")
"""
from __future__ import annotations

from .classifier import BUILTIN_PATTERNS, ErrorClassifier
from .diagnoser import AIDiagnoser
from .engine import SelfHealingConfig, SelfHealingEngine
from .models import (
    ErrorCategory,
    HealingResult,
    HealingStats,
    HealingStrategyType,
    VerificationLevel,
)
from .verifier import Verifier

__all__ = [
    'BUILTIN_PATTERNS',
    'AIDiagnoser',
    'ErrorCategory',
    'ErrorClassifier',
    'HealingResult',
    'HealingStats',
    'HealingStrategyType',
    'SelfHealingConfig',
    'SelfHealingEngine',
    'VerificationLevel',
    'Verifier',
]

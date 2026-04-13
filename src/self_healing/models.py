"""Self-Healing 数据模型"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ErrorCategory(str, Enum):
    """错误分类"""
    SYNTAX = 'syntax'
    IMPORT = 'import'
    RUNTIME = 'runtime'
    LLM = 'llm'
    LOGIC = 'logic'
    SECURITY = 'security'
    TIMEOUT = 'timeout'
    UNKNOWN = 'unknown'


class HealingStrategyType(str, Enum):
    """修复策略类型"""
    CODE_PATCH = 'code_patch'
    CONFIG_FIX = 'config_fix'
    WORKAROUND = 'workaround'
    SKIP_AND_LOG = 'skip_and_log'
    ROLLBACK = 'rollback'


class VerificationLevel(str, Enum):
    """验证级别"""
    L1_SYNTAX = 'L1'       # 语法检查
    L2_STATIC = 'L2'       # 静态分析
    L3_UNIT_TEST = 'L3'    # 单元测试
    L4_INTEGRATION = 'L4'  # 集成测试
    L5_SECURITY = 'L5'     # 安全扫描


@dataclass
class ErrorPattern:
    """错误模式"""
    id: str
    category: ErrorCategory
    signature: str              # 正则表达式特征
    description: str
    strategy: HealingStrategyType
    fix_prompt: str = ""        # AI 修复提示词模板
    confidence: float = 0.5     # 策略置信度
    success_count: int = 0
    failure_count: int = 0


@dataclass
class HealingResult:
    """自愈结果"""
    success: bool
    error: str = ""
    error_category: ErrorCategory = ErrorCategory.UNKNOWN
    root_cause: str = ""
    strategy_used: HealingStrategyType = HealingStrategyType.CODE_PATCH
    fix_applied: str = ""
    verification_passed: bool = False
    attempts: int = 0
    elapsed_seconds: float = 0.0
    messages: list[str] = field(default_factory=list)


@dataclass
class HealingStats:
    """自愈统计"""
    total_errors_detected: int = 0
    total_healing_attempts: int = 0
    successful_healings: int = 0
    failed_healings: int = 0
    avg_attempts: float = 0.0
    avg_elapsed_seconds: float = 0.0
    error_categories: dict[str, int] = field(default_factory=dict)

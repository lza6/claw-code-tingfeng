"""Workflow Engine — 5 阶段执行管道（版本管理 / 热修复 / 技术债务 / 自愈）"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import WorkflowEngine

# 自愈式工作流循环
from .error_classifier import ErrorCategory, ErrorClassification, ErrorClassifier, ErrorPattern
from .experience_bank import ExperienceBank, ExperienceRecord
from .feedback_loop import ErrorAnalyzer, ExceptionFeedbackLoop, FeedbackResult
from .hotfix_manager import HotfixManager
from .models import (
    TechDebtPriority,
    TechDebtRecord,
    VersionBumpType,
    VersionInfo,
    WorkflowPhase,
    WorkflowPhaseCategory,
    WorkflowResult,
    WorkflowStatus,
    WorkflowTask,
)
from .tech_debt import TechDebtManager
from .version_manager import VersionManager

def __getattr__(name: str):
    if name == 'WorkflowEngine':
        from .engine import WorkflowEngine
        return WorkflowEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'ErrorAnalyzer',
    'ErrorCategory',
    'ErrorClassification',
    # 自愈式工作流
    'ErrorClassifier',
    'ErrorPattern',
    'ExceptionFeedbackLoop',
    'ExperienceBank',
    'ExperienceRecord',
    'FeedbackResult',
    'HotfixManager',
    'TechDebtManager',
    'TechDebtPriority',
    'TechDebtRecord',
    'VersionBumpType',
    'VersionInfo',
    'VersionManager',
    'WorkflowEngine',
    'WorkflowPhase',
    'WorkflowPhaseCategory',
    'WorkflowResult',
    'WorkflowStatus',
    'WorkflowTask',
]

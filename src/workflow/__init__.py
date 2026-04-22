"""Workflow Engine — 5 阶段执行管道（版本管理 / 热修复 / 技术债务 / 自愈）

从 oh-my-codex-main 汲取的新功能:
- mode_state.py: 独占模式互斥检查
- ralph_ledger.py: RALPH 进度账本与视觉反馈
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import WorkflowEngine

# 自愈式工作流循环
from .error_classifier import ErrorCategory, ErrorClassification, ErrorClassifier, ErrorPattern
from .experience_bank import ExperienceBank, ExperienceRecord
from .feedback_loop import ErrorAnalyzer, ExceptionFeedbackLoop, FeedbackResult
from .hotfix_manager import HotfixManager

# 从 oh-my-codex 汲取的模式状态管理
from .mode_state import (
    EXCLUSIVE_MODES,
    ModeState,
    ModeStateManager,
    ModeType,
    assert_mode_allowed,
    cancel_mode,
    check_mode_conflict,
    list_active_modes,
    read_mode_state,
    start_mode,
    update_mode_state,
)
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

# 从 oh-my-codex 汲取的管道恢复
from .pipeline_orchestrator import (
    can_resume_pipeline,
    cancel_pipeline,
    read_pipeline_state,
)

# 从 oh-my-codex 汲取的 RALPH 账本
from .ralph_ledger import (
    RalphProgressLedger,
    RalphVisualFeedback,
    add_progress_entry,
    get_latest_visual_feedback,
    get_ralph_progress_path,
    migrate_legacy_progress,
    read_ralph_progress,
    record_visual_feedback,
)

# 从 oh-my-codex 汲取的会话历史搜索
from .session_history_search import (
    SessionMatch,
    SessionSearchResult,
    count_sessions,
    get_active_sessions,
    get_latest_session,
    search_sessions,
)

# 从 oh-my-codex 汲取的团队工作流
from .team import (
    TaskCounts,
    TeamPhase,
    TeamPhaseState,
    TerminalPhase,
    calculate_team_phase,
    default_persisted_phase_state,
    infer_phase_target_from_task_counts,
    is_terminal_phase,
    is_valid_transition,
    reconcile_phase_state_for_monitor,
)

# 从 oh-my-codex 汲取的团队持久化
from .team_persistence import (
    TeamMemberState,
    TeamMessage,
    TeamStateData,
    add_team_member,
    add_team_message,
    get_team_messages,
    read_team_state,
    remove_team_member,
    update_member_status,
    write_team_state,
)
from .tech_debt import TechDebtManager
from .version_manager import VersionManager


def __getattr__(name: str):
    if name == 'WorkflowEngine':
        from .engine import WorkflowEngine
        return WorkflowEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Mode State (from oh-my-codex)
    'ALL_SUPPORTED_MODES',
    'ALL_SUPPORTED_MODES',
    'EXCLUSIVE_MODES',
    # Original exports
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
    'ModeState',
    'ModeStateManager',
    'ModeType',
    # Ralph Ledger (from oh-my-codex)
    'RalphProgressLedger',
    'RalphVisualFeedback',
    # Session history search
    'SessionMatch',
    'SessionSearchResult',
    'TaskCounts',
    # Team persistence
    'TeamMemberState',
    'TeamMessage',
    # Team Workflow (from oh-my-codex)
    'TeamPhase',
    'TeamPhaseState',
    'TeamStateData',
    'TechDebtManager',
    'TechDebtPriority',
    'TechDebtRecord',
    'TerminalPhase',
    'VersionBumpType',
    'VersionInfo',
    'VersionManager',
    'WorkflowEngine',
    'WorkflowPhase',
    'WorkflowPhaseCategory',
    'WorkflowResult',
    'WorkflowStatus',
    'WorkflowTask',
    'add_progress_entry',
    'add_team_member',
    'add_team_message',
    'assert_mode_allowed',
    'calculate_team_phase',
    # Pipeline recovery
    'can_resume_pipeline',
    'cancel_mode',
    'cancel_pipeline',
    'check_mode_conflict',
    'count_sessions',
    'default_persisted_phase_state',
    'get_active_sessions',
    'get_latest_session',
    'get_latest_visual_feedback',
    'get_ralph_progress_path',
    'get_team_messages',
    'infer_phase_target_from_task_counts',
    'is_terminal_phase',
    'is_valid_transition',
    'list_active_modes',
    'migrate_legacy_progress',
    'read_mode_state',
    'read_pipeline_state',
    'read_ralph_progress',
    'read_team_state',
    'reconcile_phase_state_for_monitor',
    'record_visual_feedback',
    'remove_team_member',
    'search_sessions',
    'start_mode',
    'update_member_status',
    'update_mode_state',
    'write_team_state',
]

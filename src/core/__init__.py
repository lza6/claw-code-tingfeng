"""Core 核心模块 - 数据模型、错误、上下文、历史、会话、转录、事件总线、会话压缩、成本追踪、Hook 系统

从 claw-code-main (Rust/TS) 移植的核心模块:
- compact: 会话压缩算法
- usage: 精确成本追踪
- hooks: Hook 系统 (PreToolUse/PostToolUse)

RTK 风格集成 (v0.40.0):
- token_tracker: SQLite token 用量追踪
- output_compressor: 12 种过滤策略的智能输出压缩

Aider 整合 (2026-04-08):
- important_files: 重要文件识别
- args_parser: 增强的参数解析
"""

from .args_parser import (
    ClawdArgParser,
    EditFormatChoices,
    create_parser,
    load_config_file,
    quick_parse,
    resolve_env_vars,
    validate_edit_format,
)
from .compact import (
    CompactionConfig,
    CompactionResult,
    ContentBlock,
    ConversationMessage,
    MessageRole,
    Session,
    compact_session,
    estimate_session_tokens,
    format_compact_summary,
    should_compact,
)
from .config.injector import config_injector

# 注意：usage.py 里的内容大部分迁移到了 telemetry.metrics 和 token_tracker
# 路径重导向以支持旧代码引用 (v0.50.0 兼容性层)
from .config.settings import AgentSettings, ConfigSourceKind, get_settings
from .context import PortContext, build_port_context, render_context
from .events import (
    Event,
    EventBus,
    EventType,
    get_event_bus,
    reset_event_bus,
)
from .exceptions import (
    ClawdError,
    ErrorCode,
    LLMNotConfiguredError,
    LLMProviderError,
    SecurityError,
    ToolExecutionError,
    create_error,
    format_error,
)
from .git_integration import CommitInfo, DiffResult, GitManager, get_git_manager
from .history import HistoryEvent, HistoryLog
from .hook_registry import (
    HookContext as HookContext,
)
from .hook_registry import (
    HookExecutionResult as HookExecutionResult,
)

# 新增：Onyx 风格的 Hook 注册表系统（补充而非替换）
from .hook_registry import (
    HookPoint as HookPoint,
)
from .hook_registry import (
    HookPointSpec as HookPointSpec,
)
from .hook_registry import (
    HookResult as HookResult,
)
from .hook_registry import (
    execute_hook as execute_hook,
)
from .hook_registry import (
    hook as hook,
)
from .hook_registry import (
    register_hook as register_hook,
)
from .hook_registry import (
    validate_registry as validate_registry,
)
from .hooks import (
    CompositeHookRunner,
    ConfigHookRunner,
    HookEvent,
    HookPayload,
    HookRunResult,
    PluginHookRunner,
)

# Aider 整合的模块
from .important_files import (
    ROOT_IMPORTANT_FILES,
    filter_important_files,
    get_importance_score,
    is_config_file,
    is_dependency_file,
    is_documentation,
    is_important,
    sort_by_importance,
)
from .models import (
    PermissionDenial,
    PortingBacklog,
    PortingModule,
    PortingTask,
    Subsystem,
    UsageSummary,
)
from .project_context import ProjectContext
from .serialization import JSONSerializer, from_dict, to_dict
from .session_store import DEFAULT_SESSION_DIR, StoredSession, load_session, save_session
from .state import (
    AuthoritySnapshot,
    BacklogSnapshot,
    ReadinessSnapshot,
    ReplaySnapshot,
    StateManager,
    SystemSnapshot,
)
from .telemetry.exporter import get_metrics_collector as metrics_exporter
from .telemetry.metrics import (
    MODEL_PRICING,
    ModelPricing,
    get_model_pricing,
)
from .telemetry.observability import (
    LogEntry,
    StructuredLogger,
)
from .telemetry.output_compressor import (
    FilterRule,
    FilterStrategy,
    OutputCompressor,
)
from .telemetry.token_tracker import (
    TokenTracker,
    TokenUsage,  # 这里原先是 from .usage import TokenUsage
    TrackingRecord,
)
from .transcript import TranscriptStore
from .workspace import Workspace, WorkspaceManager

__all__ = [
    # 现有
    'DEFAULT_SESSION_DIR',
    'MODEL_PRICING',
    'ROOT_IMPORTANT_FILES',
    'AuthoritySnapshot',
    'BacklogSnapshot',
    # Aider 整合
    'ClawdArgParser',
    'ClawdError',
    'CommitInfo',
    'CompactionConfig',
    'CompactionResult',
    'CompositeHookRunner',
    'ConfigHookRunner',
    'ContentBlock',
    'ConversationMessage',
    'DiffResult',
    'EditFormatChoices',
    # 异常
    'ErrorCode',
    # 事件总线
    'Event',
    'EventBus',
    'EventType',
    'FilterRule',
    'FilterStrategy',
    'GitManager',
    # 历史
    'HistoryEvent',
    'HistoryLog',
    # Hook 系统
    'HookEvent',
    'HookPayload',
    'HookRunResult',
    'JSONSerializer',
    'LLMNotConfiguredError',
    'LLMProviderError',
    'LogEntry',
    # 会话压缩
    'MessageRole',
    'ModelPricing',
    # RTK 输出压缩
    'OutputCompressor',
    'PermissionDenial',
    'PluginHookRunner',
    # 上下文
    'PortContext',
    'PortingBacklog',
    'PortingModule',
    'PortingTask',
    'ProjectContext',
    'ReadinessSnapshot',
    'ReplaySnapshot',
    'SecurityError',
    'Session',
    'StateManager',
    # 会话
    'StoredSession',
    # 观测性
    'StructuredLogger',
    # 基础模型
    'Subsystem',
    'SystemSnapshot',
    'TokenTracker',
    # 成本追踪
    'TokenUsage',
    'ToolExecutionError',
    'TrackingRecord',
    'TranscriptStore',
    'UsageRecord',
    'UsageSummary',
    'UsageTracker',
    'Workspace',
    'WorkspaceManager',
    'build_port_context',
    'compact_session',
    'create_error',
    'create_parser',
    'estimate_session_tokens',
    'filter_important_files',
    'format_compact_summary',
    'format_error',
    'from_dict',
    'get_event_bus',
    'get_git_manager',
    'get_importance_score',
    'get_model_pricing',
    'is_config_file',
    'is_dependency_file',
    'is_documentation',
    'is_important',
    'load_config_file',
    'load_session',
    'quick_parse',
    'render_context',
    'reset_event_bus',
    'resolve_env_vars',
    'save_session',
    'should_compact',
    'sort_by_importance',
    'to_dict',
    'validate_edit_format',
]

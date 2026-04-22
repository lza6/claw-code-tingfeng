"""
Hook Extensibility Types - 钩子扩展系统类型定义

从 oh-my-codex-main/src/hooks/extensibility/types.ts 转换而来。
定义钩子系统的核心类型和接口。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ===== 钩子事件版本 =====
class HookSchemaVersion(str, Enum):
    """钩子模式版本"""
    V1 = "1"


class HookEventSource(str, Enum):
    """钩子事件来源"""
    NATIVE = "native"
    DERIVED = "derived"


# ===== 钩子事件名称 =====
class HookEventName(str, Enum):
    """钩子事件名称"""
    SESSION_START = "session-start"
    SESSION_END = "session-end"
    SESSION_IDLE = "session-idle"
    TURN_COMPLETE = "turn-complete"
    BLOCKED = "blocked"
    FINISHED = "finished"
    FAILED = "failed"
    RETRY_NEEDED = "retry-needed"
    PR_CREATED = "pr-created"
    TEST_STARTED = "test-started"
    TEST_FINISHED = "test-finished"
    TEST_FAILED = "test-failed"
    HANDOFF_NEEDED = "handoff-needed"
    NEEDS_INPUT = "needs-input"
    PRE_TOOL_USE = "pre-tool-use"
    POST_TOOL_USE = "post-tool-use"


# ===== 核心类型 =====
@dataclass
class HookEventEnvelope:
    """钩子事件包装器"""
    schema_version: HookSchemaVersion = HookSchemaVersion.V1
    event: str = ""
    timestamp: str = ""
    source: HookEventSource = HookEventSource.NATIVE
    context: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    mode: str | None = None
    confidence: float | None = None
    parser_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version.value,
            "event": self.event,
            "timestamp": self.timestamp,
            "source": self.source.value,
            "context": self.context,
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "mode": self.mode,
            "confidence": self.confidence,
            "parser_reason": self.parser_reason,
        }


@dataclass
class HookPluginDescriptor:
    """钩子插件描述符"""
    id: str
    name: str
    file: str
    path: str
    file_path: str
    file_name: str
    valid: bool = True
    reason: str | None = None


@dataclass
class HookPluginLogContext:
    """钩子插件日志上下文"""
    timestamp: str | None = None
    event: str = ""
    plugin_id: str | None = None
    status: str | None = None
    reason: str | None = None
    source: HookEventSource | None = None


@dataclass
class HookPluginTmuxSendKeysOptions:
    """TMux发送按键选项"""
    pane_id: str | None = None
    session_name: str | None = None
    text: str = ""
    submit: bool = True
    cooldown_ms: int = 0


@dataclass
class HookPluginTmuxSendKeysResult:
    """TMux发送按键结果"""
    ok: bool
    reason: str
    target: str | None = None
    pane_id: str | None = None
    error: str | None = None


# ===== OMX状态类型 =====
@dataclass
class HookPluginOmxSessionState:
    """OMX会话状态"""
    session_id: str
    started_at: str | None = None
    cwd: str | None = None
    pid: int | None = None
    platform: str | None = None
    pid_start_ticks: int | None = None
    pid_cmdline: str | None = None


@dataclass
class HookPluginOmxHudState:
    """OMX HUD状态"""
    last_turn_at: str | None = None
    turn_count: int | None = None
    last_agent_output: str | None = None


@dataclass
class HookPluginOmxNotifyFallbackState:
    """OMX通知回退状态"""
    pid: int | None = None
    parent_pid: int | None = None
    started_at: str | None = None
    cwd: str | None = None
    notify_script: str | None = None
    poll_ms: int | None = None
    pid_file: str | None = None
    max_lifetime_ms: int | None = None
    tracked_files: int | None = None
    seen_turns: int | None = None
    stop_reason: str | None = None
    stop_signal: str | None = None
    stopping: bool = False


@dataclass
class HookPluginOmxUpdateCheckState:
    """OMX更新检查状态"""
    last_checked_at: str | None = None
    last_seen_latest: str | None = None


# ===== 调度结果类型 =====
class HookPluginDispatchStatus(str, Enum):
    """插件调度状态"""
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"
    INVALID_EXPORT = "invalid_export"
    RUNNER_ERROR = "runner_error"
    SPAWN_FAILED = "spawn_failed"
    RUNNER_MISSING = "runner_missing"
    SKIPPED_TEAM_WORKER = "skipped_team_worker"
    SKIPPED = "skipped"


@dataclass
class HookPluginDispatchResult:
    """插件调度结果"""
    plugin: str
    path: str
    ok: bool
    duration_ms: int
    plugin_id: str | None = None
    file: str | None = None
    status: HookPluginDispatchStatus | None = None
    duration_ms: int | None = None
    reason: str | None = None
    output: Any | None = None
    error: str | None = None
    exit_code: int | None = None
    skipped: bool = False


@dataclass
class HookDispatchResult:
    """钩子调度结果"""
    enabled: bool
    event: str
    source: HookEventSource | None = None
    plugin_count: int = 0
    reason: str = ""
    results: list[HookPluginDispatchResult] = field(default_factory=list)


@dataclass
class HookDispatchOptions:
    """钩子调度选项"""
    cwd: str | None = None
    event: HookEventEnvelope | None = None
    env: dict | None = None
    timeout_ms: int | None = None
    allow_in_team_worker: bool | None = None
    allow_team_worker_side_effects: bool | None = None
    side_effects_enabled: bool | None = None
    enabled: bool | None = None


@dataclass
class HookValidateOptions:
    """钩子验证选项"""
    cwd: str | None = None
    env: dict | None = None
    timeout_ms: int | None = None


@dataclass
class HookRuntimeDispatchInput:
    """运行时调度输入"""
    cwd: str
    event: HookEventEnvelope
    allow_team_worker_side_effects: bool | None = None
    side_effects_enabled: bool | None = None


@dataclass
class HookRuntimeDispatchResult:
    """运行时调度结果"""
    dispatched: bool
    reason: str
    result: HookDispatchResult


@dataclass
class HookDispatchOptions:
    """钩子调度选项"""
    cwd: str | None = None
    event: HookEventEnvelope | None = None
    env: dict | None = None
    timeout_ms: int | None = None
    allow_in_team_worker: bool | None = None
    allow_team_worker_side_effects: bool | None = None
    side_effects_enabled: bool | None = None
    enabled: bool | None = None


@dataclass
class HookValidateOptions:
    """钩子验证选项"""
    cwd: str | None = None
    env: dict | None = None
    timeout_ms: int | None = None


@dataclass
class HookRuntimeDispatchInput:
    """运行时调度输入"""
    cwd: str
    event: HookEventEnvelope
    allow_team_worker_side_effects: bool | None = None
    side_effects_enabled: bool | None = None


@dataclass
class HookRuntimeDispatchResult:
    """运行时调度结果"""
    dispatched: bool
    reason: str
    result: HookDispatchResult


# ===== 导出 =====
__all__ = [
    "HookDispatchOptions",
    "HookDispatchResult",
    "HookEventEnvelope",
    "HookEventName",
    "HookEventSource",
    "HookPluginDescriptor",
    "HookPluginDispatchResult",
    "HookPluginDispatchStatus",
    "HookPluginLogContext",
    "HookPluginOmxHudState",
    "HookPluginOmxNotifyFallbackState",
    "HookPluginOmxSessionState",
    "HookPluginOmxUpdateCheckState",
    "HookPluginTmuxSendKeysOptions",
    "HookPluginTmuxSendKeysResult",
    "HookRuntimeDispatchInput",
    "HookRuntimeDispatchResult",
    "HookSchemaVersion",
    "HookValidateOptions",
]

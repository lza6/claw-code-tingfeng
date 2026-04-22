"""
Runtime - 运行时模块

核心组件（汲取 oh-my-codex 设计）:
- engine: RuntimeEngine 状态机引擎
- dispatch: DispatchLog 任务分派跟踪
- mailbox: MailboxLog 消息传递
- bridge: 与现有代码的桥接

参考: omx-runtime-core/src/
"""

# 延迟导入以避免循环依赖
def __getattr__(name):
    if name == "RuntimeEngine":
        from .engine import RuntimeEngine
        return RuntimeEngine
    if name == "EngineError":
        from .engine import EngineError
        return EngineError
    if name == "AuthorityLease":
        from .engine import AuthorityLease
        return AuthorityLease
    if name == "AuthorityError":
        from .engine import AuthorityError
        return AuthorityError
    if name == "DispatchLog":
        from .engine import DispatchLog
        return DispatchLog
    if name == "DispatchRecord":
        from .engine import DispatchRecord
        return DispatchRecord
    if name == "DispatchStatus":
        from .engine import DispatchStatus
        return DispatchStatus
    if name == "DispatchError":
        from .engine import DispatchError
        return DispatchError
    if name == "MailboxLog":
        from .engine import MailboxLog
        return MailboxLog
    if name == "MailboxRecord":
        from .engine import MailboxRecord
        return MailboxRecord
    if name == "MailboxError":
        from .engine import MailboxError
        return MailboxError
    if name == "ReplayState":
        from .engine import ReplayState
        return ReplayState
    if name == "AuthoritySnapshot":
        from .engine import AuthoritySnapshot
        return AuthoritySnapshot
    if name == "BacklogSnapshot":
        from .engine import BacklogSnapshot
        return BacklogSnapshot
    if name == "ReplaySnapshot":
        from .engine import ReplaySnapshot
        return ReplaySnapshot
    if name == "ReadinessSnapshot":
        from .engine import ReadinessSnapshot
        return ReadinessSnapshot
    if name == "RuntimeSnapshot":
        from .engine import RuntimeSnapshot
        return RuntimeSnapshot
    if name == "RuntimeEvent":
        from .engine import RuntimeEvent
        return RuntimeEvent
    if name == "RuntimeCommand":
        from .engine import RuntimeCommand
        return RuntimeCommand
    if name == "RUNTIME_SCHEMA_VERSION":
        from .engine import RUNTIME_SCHEMA_VERSION
        return RUNTIME_SCHEMA_VERSION
    if name == "derive_readiness":
        from .engine import derive_readiness
        return derive_readiness
    raise AttributeError(f"module {__name__} has no attribute {name}")

__all__ = [
    "RUNTIME_SCHEMA_VERSION",
    "AuthorityError",
    "AuthorityLease",
    "AuthoritySnapshot",
    "AuthoritySnapshot",
    "BacklogSnapshot",
    "DispatchError",
    "DispatchLog",
    "DispatchRecord",
    "DispatchStatus",
    "EngineError",
    "MailboxError",
    "MailboxLog",
    "MailboxRecord",
    "ReadinessSnapshot",
    "ReplaySnapshot",
    "ReplayState",
    "RuntimeCommand",
    "RuntimeEngine",
    "RuntimeEvent",
    "RuntimeSnapshot",
    # Bridge (legacy)
    "RuntimeSnapshot",
    "derive_readiness",
    "get_bridge_enabled",
    "is_runtime_ready",
    "read_authority_snapshot",
    "read_runtime_snapshot",
]

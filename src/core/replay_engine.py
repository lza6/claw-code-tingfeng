"""
事件回放引擎

从 oh-my-codex 的 Rust replay.rs 汲取的事件回放系统。
记录关键事件用于调试和会话重放，改善问题诊断体验。

来源: oh-my-codex crates/omx-runtime-core/src/replay.rs
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """事件类型"""
    # 工作流事件
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"

    # Agent 事件
    AGENT_DISPATCHED = "agent_dispatched"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"

    # 工具执行事件
    TOOL_EXECUTED = "tool_executed"
    TOOL_FAILED = "tool_failed"
    TOOL_STARTED = "tool_started"              # 工具开始执行
    TOOL_COMPLETED = "tool_completed"          # 工具执行完成
    TOOL_TIMEOUT = "tool_timeout"              # 工具执行超时
    TOOL_CAPSULE_CREATED = "tool_capsule_created"   # 工具胶囊创建
    TOOL_CAPSULE_DESTROYED = "tool_capsule_destroyed"  # 工具胶囊销毁

    # LLM 交互事件
    LLM_REQUEST_SENT = "llm_request_sent"
    LLM_RESPONSE_RECEIVED = "llm_response_received"
    LLM_ERROR = "llm_error"

    # 状态变更事件
    STATE_CHANGED = "state_changed"
    MODE_ACTIVATED = "mode_activated"
    MODE_DEACTIVATED = "mode_deactivated"

    # 用户交互事件
    USER_INPUT = "user_input"
    USER_OUTPUT = "user_output"


@dataclass
class ReplayEvent:
    """回放事件"""
    timestamp: str
    event_type: str
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "payload": self.payload,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplayEvent:
        """从字典创建"""
        return cls(
            timestamp=data.get("timestamp", ""),
            event_type=data.get("event_type", ""),
            session_id=data.get("session_id", ""),
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
        )


class ReplayEngine:
    """事件回放引擎

    负责记录、存储和重放会话事件，用于调试和问题诊断。
    """

    def __init__(self, state_dir: str = "."):
        self._state_dir = Path(state_dir) / ".clawd" / "replay"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._buffer: list[ReplayEvent] = []
        self._flush_size = 10  # 每 10 个事件刷新一次到磁盘

    def record_event(
        self,
        event_type: str | EventType,
        session_id: str,
        payload: dict[str, Any] = None,
        metadata: dict[str, Any] = None,
    ) -> ReplayEvent:
        """记录事件"""
        event = ReplayEvent(
            timestamp=datetime.now().isoformat(),
            event_type=event_type.value if isinstance(event_type, EventType) else event_type,
            session_id=session_id,
            payload=payload or {},
            metadata=metadata or {},
        )

        self._buffer.append(event)

        # 达到缓冲区大小时刷新到磁盘
        if len(self._buffer) >= self._flush_size:
            self._flush_to_disk(session_id)

        logger.debug(f"[ReplayEngine] Recorded event: {event.event_type} for session {session_id}")
        return event

    def _flush_to_disk(self, session_id: str) -> None:
        """将缓冲的事件刷新到磁盘"""
        if not self._buffer:
            return

        log_file = self._get_log_file(session_id)

        # 追加写入
        with open(log_file, 'a', encoding='utf-8') as f:
            for event in self._buffer:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + '\n')

        logger.info(f"[ReplayEngine] Flushed {len(self._buffer)} events to {log_file}")
        self._buffer.clear()

    def _get_log_file(self, session_id: str) -> Path:
        """获取会话日志文件路径"""
        # 使用安全的文件名（替换非法字符）
        safe_session_id = session_id.replace('/', '_').replace('\\', '_')
        return self._state_dir / f"{safe_session_id}.jsonl"

    def load_events(self, session_id: str) -> list[ReplayEvent]:
        """加载会话的所有事件"""
        log_file = self._get_log_file(session_id)

        if not log_file.exists():
            logger.warning(f"[ReplayEngine] No replay log found for session {session_id}")
            return []

        events = []
        try:
            with open(log_file, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        events.append(ReplayEvent.from_dict(data))
        except Exception as e:
            logger.error(f"[ReplayEngine] Failed to load events from {log_file}: {e}")

        logger.info(f"[ReplayEngine] Loaded {len(events)} events for session {session_id}")
        return events

    def replay_session(
        self,
        session_id: str,
        callback=None,
    ) -> list[ReplayEvent]:
        """重放会话事件

        Args:
            session_id: 会话 ID
            callback: 可选的回调函数，用于处理每个事件

        Returns:
            重放的事件列表
        """
        events = self.load_events(session_id)

        if not events:
            logger.warning(f"[ReplayEngine] No events to replay for session {session_id}")
            return []

        logger.info(f"[ReplayEngine] Replaying {len(events)} events for session {session_id}")

        for event in events:
            if callback:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"[ReplayEngine] Callback failed for event {event.event_type}: {e}")

        return events

    def get_session_summary(self, session_id: str) -> dict[str, Any]:
        """获取会话摘要"""
        events = self.load_events(session_id)

        if not events:
            return {"session_id": session_id, "event_count": 0}

        # 统计事件类型
        event_type_counts: dict[str, int] = {}
        for event in events:
            event_type_counts[event.event_type] = event_type_counts.get(event.event_type, 0) + 1

        # 时间范围
        start_time = events[0].timestamp
        end_time = events[-1].timestamp

        return {
            "session_id": session_id,
            "event_count": len(events),
            "start_time": start_time,
            "end_time": end_time,
            "event_type_counts": event_type_counts,
            "duration_seconds": self._calculate_duration(start_time, end_time),
        }

    def _calculate_duration(self, start: str, end: str) -> float:
        """计算持续时间（秒）"""
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            return (end_dt - start_dt).total_seconds()
        except Exception:
            return 0.0

    def clear_session(self, session_id: str) -> bool:
        """清除会话数据"""
        log_file = self._get_log_file(session_id)

        if not log_file.exists():
            return False

        try:
            log_file.unlink()
            logger.info(f"[ReplayEngine] Cleared replay log for session {session_id}")
            return True
        except Exception as e:
            logger.error(f"[ReplayEngine] Failed to clear session {session_id}: {e}")
            return False

    def flush_all(self) -> None:
        """刷新所有缓冲的事件"""
        # 按会话分组
        sessions: dict[str, list[ReplayEvent]] = {}
        for event in self._buffer:
            sessions.setdefault(event.session_id, []).append(event)

        # 刷新每个会话
        for session_id, events in sessions.items():
            self._buffer = events
            self._flush_to_disk(session_id)

        self._buffer.clear()


# ===== 便捷函数 =====
_default_engine: ReplayEngine | None = None


def get_replay_engine(state_dir: str = ".") -> ReplayEngine:
    """获取默认的回放引擎实例"""
    global _default_engine
    if _default_engine is None:
        _default_engine = ReplayEngine(state_dir)
    return _default_engine


def record_event(
    event_type: str | EventType,
    session_id: str,
    payload: dict[str, Any] = None,
    metadata: dict[str, Any] = None,
    state_dir: str = ".",
) -> ReplayEvent:
    """记录事件的便捷函数"""
    engine = get_replay_engine(state_dir)
    return engine.record_event(event_type, session_id, payload, metadata)


def replay_session(
    session_id: str,
    callback=None,
    state_dir: str = ".",
) -> list[ReplayEvent]:
    """重放会话的便捷函数"""
    engine = get_replay_engine(state_dir)
    return engine.replay_session(session_id, callback)


def get_session_summary(session_id: str, state_dir: str = ".") -> dict[str, Any]:
    """获取会话摘要的便捷函数"""
    engine = get_replay_engine(state_dir)
    return engine.get_session_summary(session_id)


# ===== 导出 =====
__all__ = [
    "EventType",
    "ReplayEngine",
    "ReplayEvent",
    "get_replay_engine",
    "get_session_summary",
    "record_event",
    "replay_session",
]

"""
Trace Server - 追踪服务器

从 oh-my-codex-main/src/mcp/trace-server.ts 转换。
提供执行追踪、日志记录和调试信息收集。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class TraceLevel(Enum):
    """追踪级别"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class TraceEntry:
    """追踪条目"""
    id: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    level: str = "info"
    message: str = ""
    source: str = ""
    metadata: dict = field(default_factory=dict)
    stack_trace: str = ""


@dataclass
class TraceSession:
    """追踪会话"""
    session_id: str
    entries: list[TraceEntry] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    ended_at: str = ""
    metadata: dict = field(default_factory=dict)


class TraceServer:
    """追踪服务器

    功能:
    - 追踪条目记录
    - 会话管理
    - 日志导出
    - 过滤搜索
    """

    def __init__(self, storage_dir: str | None = None):
        self.storage_dir = storage_dir
        self._sessions: dict[str, TraceSession] = {}
        self._current_session_id: str | None = None

    def start_session(self, session_id: str, metadata: dict | None = None) -> TraceSession:
        """开始追踪会话"""
        session = TraceSession(
            session_id=session_id,
            metadata=metadata or {},
        )
        self._sessions[session_id] = session
        self._current_session_id = session_id
        logger.info(f"[Trace] Started session: {session_id}")
        return session

    def end_session(self, session_id: str | None = None) -> bool:
        """结束追踪会话"""
        session_id = session_id or self._current_session_id
        if session_id and session_id in self._sessions:
            self._sessions[session_id].ended_at = datetime.now().isoformat()
            logger.info(f"[Trace] Ended session: {session_id}")
            return True
        return False

    def log(
        self,
        message: str,
        level: str = "info",
        source: str = "",
        metadata: dict | None = None,
        stack_trace: str = "",
    ) -> TraceEntry | None:
        """记录追踪条目"""
        session_id = self._current_session_id
        if not session_id or session_id not in self._sessions:
            logger.warning("[Trace] No active session")
            return None

        entry = TraceEntry(
            id=f"{session_id}_{len(self._sessions[session_id].entries)}",
            level=level,
            message=message,
            source=source,
            metadata=metadata or {},
            stack_trace=stack_trace,
        )

        self._sessions[session_id].entries.append(entry)
        return entry

    def get_session(self, session_id: str) -> TraceSession | None:
        """获取会话"""
        return self._sessions.get(session_id)

    def get_current_session(self) -> TraceSession | None:
        """获取当前会话"""
        if self._current_session_id:
            return self._sessions.get(self._current_session_id)
        return None

    def search(
        self,
        query: str,
        session_id: str | None = None,
        level: str | None = None,
    ) -> list[TraceEntry]:
        """搜索追踪"""
        sessions = [self._sessions[session_id]] if session_id else self._sessions.values()

        results = []
        for session in sessions:
            for entry in session.entries:
                if query.lower() not in entry.message.lower():
                    continue
                if level and entry.level != level:
                    continue
                results.append(entry)

        return results

    def export_session_json(self, session_id: str) -> str | None:
        """导出会话为 JSON"""
        session = self.get_session(session_id)
        if not session:
            return None

        return json.dumps({
            "session_id": session.session_id,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "metadata": session.metadata,
            "entries": [
                {
                    "id": e.id,
                    "timestamp": e.timestamp,
                    "level": e.level,
                    "message": e.message,
                    "source": e.source,
                    "metadata": e.metadata,
                    "stack_trace": e.stack_trace,
                }
                for e in session.entries
            ],
        }, indent=2, ensure_ascii=False)

    def save_to_file(self, path: str | None = None) -> bool:
        """保存到文件"""
        if not path:
            return False

        try:
            data = {
                session_id: {
                    "session_id": session.session_id,
                    "started_at": session.started_at,
                    "ended_at": session.ended_at,
                    "metadata": session.metadata,
                    "entries_count": len(session.entries),
                }
                for session_id, session in self._sessions.items()
            }
            Path(path).write_text(json.dumps(data, indent=2))
            logger.info(f"[Trace] Saved to {path}")
            return True
        except Exception as e:
            logger.error(f"[Trace] Save failed: {e}")
            return False

    def clear(self, session_id: str | None = None) -> None:
        """清除追踪"""
        if session_id:
            if session_id in self._sessions:
                del self._sessions[session_id]
                if self._current_session_id == session_id:
                    self._current_session_id = None
        else:
            self._sessions.clear()
            self._current_session_id = None


# 全局单例
_trace_server: TraceServer | None = None


def get_trace_server() -> TraceServer:
    """获取全局追踪服务器"""
    global _trace_server
    if _trace_server is None:
        _trace_server = TraceServer()
    return _trace_server


# ===== 导出 =====
__all__ = [
    "TraceEntry",
    "TraceLevel",
    "TraceServer",
    "TraceSession",
    "get_trace_server",
]

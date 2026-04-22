"""
Session History Search - 会话历史搜索

从 oh-my-codex-main/src/session-history/search.ts 汲取。
搜索和检索历史会话记录。

功能:
- 按日期范围搜索
- 按模式/状态搜索
- 语义搜索（基于关键词）
- 会话计数统计
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# 常量
SESSION_STATE_DIR = Path(".clawd") / "state"
SESSION_GLOB_PATTERN = "*-state.json"


@dataclass
class SessionMatch:
    """会话匹配结果"""
    mode: str
    phase: str
    task: str
    started_at: str
    completed_at: str | None = None
    active: bool = False
    duration_ms: int = 0


@dataclass
class SessionSearchResult:
    """会话搜索结果"""
    sessions: list[SessionMatch] = field(default_factory=list)
    total_count: int = 0
    query: dict[str, Any] = field(default_factory=dict)


def _list_state_dirs(cwd: str = ".") -> list[Path]:
    """列出所有状态目录"""
    root = Path(cwd) / SESSION_STATE_DIR
    if not root.exists():
        return []
    return [root]


def _list_session_files(cwd: str = ".") -> list[tuple[str, Path]]:
    """列出所有会话状态文件"""
    dirs = _list_state_dirs(cwd)
    files = []
    for d in dirs:
        if not d.exists():
            continue
        for f in d.glob(SESSION_GLOB_PATTERN):
            mode = f.stem.replace("-state", "")
            files.append((mode, f))
    return files


def _parse_session_file(path: Path) -> dict[str, Any] | None:
    """解析会话状态文件"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def search_sessions(
    modes: list[str] | None = None,
    active_only: bool = False,
    phases: list[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cwd: str = ".",
) -> SessionSearchResult:
    """搜索会话历史

    参数:
        modes: 过滤的模式列表
        active_only: 只返回活跃会话
        phases: 过滤的阶段列表
        since: 起始时间
        until: 结束时间
        cwd: 工作目录

    返回:
        SessionSearchResult: 搜索结果
    """
    files = _list_session_files(cwd)
    sessions = []

    for mode, path in files:
        data = _parse_session_file(path)
        if not data:
            continue

        # 按模式过滤
        if modes and mode not in modes:
            continue

        # 按活跃状态过滤
        if active_only and not data.get("active", False):
            continue

        # 按阶段过滤
        phase = data.get("current_phase", "")
        if phases and phase not in phases:
            continue

        # 按时间过滤
        started = data.get("started_at", "")
        if started:
            try:
                start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                if since and start_dt < since:
                    continue
                if until and start_dt > until:
                    continue
            except Exception:
                pass

        # 计算持续时间
        duration_ms = 0
        if data.get("started_at") and data.get("completed_at"):
            try:
                start = datetime.fromisoformat(data["started_at"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(data["completed_at"].replace("Z", "+00:00"))
                duration_ms = int((end - start).total_seconds() * 1000)
            except Exception:
                pass

        sessions.append(SessionMatch(
            mode=mode,
            phase=phase,
            task=data.get("task", data.get("task_description", "")),
            started_at=started,
            completed_at=data.get("completed_at"),
            active=data.get("active", False),
            duration_ms=duration_ms,
        ))

    # 排序：最新的在前
    sessions.sort(key=lambda x: x.started_at, reverse=True)

    return SessionSearchResult(
        sessions=sessions,
        total_count=len(sessions),
        query={
            "modes": modes,
            "active_only": active_only,
            "phases": phases,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
    )


def count_sessions(cwd: str = ".") -> dict[str, int]:
    """统计会话数量

    返回:
        按模式分组的会话数量
    """
    files = _list_session_files(cwd)
    counts: dict[str, int] = {}

    for mode, path in files:
        data = _parse_session_file(path)
        if not data:
            continue
        counts[mode] = counts.get(mode, 0) + 1

    return counts


def get_latest_session(
    mode: str | None = None,
    cwd: str = ".",
) -> SessionMatch | None:
    """获取最新会话"""
    modes = [mode] if mode else None
    result = search_sessions(modes=modes, cwd=cwd)
    return result.sessions[0] if result.sessions else None


def get_active_sessions(cwd: str = ".") -> list[SessionMatch]:
    """获取所有活跃会话"""
    result = search_sessions(active_only=True, cwd=cwd)
    return result.sessions


# ===== 导出 =====
__all__ = [
    "SessionMatch",
    "SessionSearchResult",
    "count_sessions",
    "get_active_sessions",
    "get_latest_session",
    "search_sessions",
]

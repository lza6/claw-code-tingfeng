"""
Subagent Tracker - 子智能体追踪系统

从 oh-my-codex-main/src/subagents/tracker.ts 汲取。
提供多智能体交互的可观测性,帮助调试和监控。

核心功能:
- 区分 leader 和 subagent 线程
- 追踪每个线程的活跃状态和轮次计数
- 会话级汇总统计
- 活跃窗口检测 (默认 120 秒超时)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ===== 数据类 =====

@dataclass
class TrackedSubagentThread:
    """被追踪的子智能体线程"""
    thread_id: str
    kind: str  # 'leader' | 'subagent'
    first_seen_at: str  # ISO timestamp
    last_seen_at: str   # ISO timestamp
    turn_count: int = 0
    mode: str | None = None  # 运行模式 (如 'team', 'ralph')
    status: str = "active"  # 'active' | 'idle' | 'completed'

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TrackedSubagentThread:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SubagentSessionSummary:
    """子智能体会话汇总统计"""
    session_id: str
    total_threads: int = 0
    leader_thread_id: str | None = None
    active_subagents: int = 0
    completed_subagents: int = 0
    total_turns: int = 0
    started_at: str | None = None
    last_activity_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ===== 追踪器 =====

class SubagentTracker:
    """
    子智能体追踪器

    负责追踪和管理多智能体系统中的线程活动。
    提供可观测性,帮助调试复杂的智能体交互。
    """

    def __init__(self, state_dir: str):
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._threads: dict[str, TrackedSubagentThread] = {}
        self._session_id: str | None = None
        self._load_state()

    def _get_state_file(self) -> Path:
        """获取状态文件路径"""
        session_suffix = f"-{self._session_id}" if self._session_id else ""
        return self._state_dir / f"subagent-tracker{session_suffix}.json"

    def _load_state(self) -> None:
        """从磁盘加载状态"""
        state_file = self._get_state_file()
        if not state_file.exists():
            return

        try:
            with open(state_file, encoding='utf-8') as f:
                data = json.load(f)

            self._session_id = data.get('session_id')
            threads_data = data.get('threads', {})
            self._threads = {
                tid: TrackedSubagentThread.from_dict(tdata)
                for tid, tdata in threads_data.items()
            }
            logger.debug(f"[SubagentTracker] Loaded {len(self._threads)} threads from {state_file}")
        except Exception as e:
            logger.warning(f"[SubagentTracker] Failed to load state: {e}")

    def _save_state(self) -> None:
        """保存状态到磁盘"""
        state_file = self._get_state_file()
        try:
            data = {
                'session_id': self._session_id,
                'updated_at': datetime.now().isoformat(),
                'threads': {tid: t.to_dict() for tid, t in self._threads.items()},
            }
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[SubagentTracker] Failed to save state: {e}")

    def set_session_id(self, session_id: str) -> None:
        """设置会话 ID"""
        self._session_id = session_id
        self._save_state()

    def register_thread(
        self,
        thread_id: str,
        kind: str = 'subagent',
        mode: str | None = None,
    ) -> TrackedSubagentThread:
        """
        注册一个新线程

        Args:
            thread_id: 线程 ID
            kind: 线程类型 ('leader' 或 'subagent')
            mode: 运行模式

        Returns:
            注册的线程对象
        """
        now = datetime.now().isoformat()

        if thread_id in self._threads:
            # 更新现有线程
            thread = self._threads[thread_id]
            thread.last_seen_at = now
            thread.turn_count += 1
            thread.status = 'active'
        else:
            # 创建新线程
            thread = TrackedSubagentThread(
                thread_id=thread_id,
                kind=kind,
                first_seen_at=now,
                last_seen_at=now,
                turn_count=1,
                mode=mode,
                status='active',
            )
            self._threads[thread_id] = thread

        self._save_state()
        logger.debug(f"[SubagentTracker] Registered {kind} thread: {thread_id}")
        return thread

    def mark_thread_idle(self, thread_id: str) -> None:
        """标记线程为空闲状态"""
        if thread_id in self._threads:
            self._threads[thread_id].status = 'idle'
            self._threads[thread_id].last_seen_at = datetime.now().isoformat()
            self._save_state()

    def mark_thread_completed(self, thread_id: str) -> None:
        """标记线程为完成状态"""
        if thread_id in self._threads:
            self._threads[thread_id].status = 'completed'
            self._threads[thread_id].last_seen_at = datetime.now().isoformat()
            self._save_state()

    def get_thread(self, thread_id: str) -> TrackedSubagentThread | None:
        """获取线程信息"""
        return self._threads.get(thread_id)

    def get_active_threads(self) -> list[TrackedSubagentThread]:
        """获取所有活跃线程"""
        return [t for t in self._threads.values() if t.status == 'active']

    def get_leader_thread(self) -> TrackedSubagentThread | None:
        """获取 leader 线程"""
        for t in self._threads.values():
            if t.kind == 'leader':
                return t
        return None

    def detect_inactive_threads(self, timeout_seconds: int = 120) -> list[str]:
        """
        检测不活跃的线程

        Args:
            timeout_seconds: 超时阈值 (默认 120 秒)

        Returns:
            不活跃线程 ID 列表
        """
        now = datetime.now()
        inactive = []

        for thread_id, thread in self._threads.items():
            if thread.status != 'active':
                continue

            last_seen = datetime.fromisoformat(thread.last_seen_at)
            if (now - last_seen).total_seconds() > timeout_seconds:
                inactive.append(thread_id)
                logger.info(
                    f"[SubagentTracker] Thread {thread_id} inactive for "
                    f"{(now - last_seen).total_seconds():.0f}s"
                )

        return inactive

    def get_summary(self) -> SubagentSessionSummary:
        """获取会话汇总统计"""
        threads = list(self._threads.values())

        if not threads:
            return SubagentSessionSummary(session_id=self._session_id or '')

        leader = next((t for t in threads if t.kind == 'leader'), None)
        active_count = sum(1 for t in threads if t.status == 'active')
        completed_count = sum(1 for t in threads if t.status == 'completed')
        total_turns = sum(t.turn_count for t in threads)

        timestamps = [t.first_seen_at for t in threads] + [t.last_seen_at for t in threads]
        timestamps.sort()

        return SubagentSessionSummary(
            session_id=self._session_id or '',
            total_threads=len(threads),
            leader_thread_id=leader.thread_id if leader else None,
            active_subagents=active_count,
            completed_subagents=completed_count,
            total_turns=total_turns,
            started_at=timestamps[0] if timestamps else None,
            last_activity_at=timestamps[-1] if timestamps else None,
        )

    def clear_completed(self) -> int:
        """清理已完成的线程记录"""
        before = len(self._threads)
        self._threads = {
            tid: t for tid, t in self._threads.items()
            if t.status != 'completed'
        }
        after = len(self._threads)
        removed = before - after

        if removed > 0:
            self._save_state()
            logger.info(f"[SubagentTracker] Cleared {removed} completed threads")

        return removed

    def reset(self) -> None:
        """重置追踪器"""
        self._threads.clear()
        self._save_state()
        logger.info("[SubagentTracker] Reset tracker")


# ===== 便捷函数 =====

def create_tracker(state_dir: str, session_id: str | None = None) -> SubagentTracker:
    """创建子智能体追踪器"""
    tracker = SubagentTracker(state_dir)
    if session_id:
        tracker.set_session_id(session_id)
    return tracker


def track_subagent_activity(
    tracker: SubagentTracker,
    thread_id: str,
    kind: str = 'subagent',
    mode: str | None = None,
) -> TrackedSubagentThread:
    """追踪子智能体活动的便捷函数"""
    return tracker.register_thread(thread_id, kind, mode)


# ===== 导出 =====
__all__ = [
    "SubagentSessionSummary",
    "SubagentTracker",
    "TrackedSubagentThread",
    "create_tracker",
    "track_subagent_activity",
]

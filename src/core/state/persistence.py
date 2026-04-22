"""状态持久化管理模块

负责状态的持久化、加载和快照管理。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# fcntl 仅在 Unix 上可用
try:
    import fcntl
except ImportError:
    fcntl = None

# 设置 logger
logger = __import__("logging").getLogger(__name__)


def _save_snapshot_file(snapshot, snapshot_file: Path) -> None:
    """保存快照到文件的内部方法"""
    snapshot_file.write_text(
        snapshot.to_json(indent=2),
        encoding="utf-8"
    )


class StateManager:
    """状态管理器

    负责状态的持久化、加载和快照管理。
    对应 omx-runtime-core 的持久化功能。
    """

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_file = self.state_dir / "snapshot.json"
        self._events_file = self.state_dir / "events.json"
        self._lock_file = self.state_dir / "engine.lock"

    def save_snapshot(self, snapshot: Any) -> None:
        """保存状态快照"""
        try:
            # 使用锁防止并发写入（仅在 Unix 上启用）
            if fcntl is not None:
                lock_path = self.state_dir / ".snapshot.lock"
                with lock_path.open("w") as lock_f:
                    fcntl.flock(lock_f, fcntl.LOCK_EX)
                    try:
                        _save_snapshot_file(snapshot, self._snapshot_file)
                    finally:
                        fcntl.flock(lock_f, fcntl.LOCK_UN)
            else:
                # Windows 上直接保存，无文件锁
                _save_snapshot_file(snapshot, self._snapshot_file)
            logger.debug(f"状态快照已保存: {self._snapshot_file}")
        except Exception as e:
            logger.error(f"保存状态快照失败: {e}")
            raise

    def load_snapshot(self) -> Any | None:
        """加载状态快照"""
        if not self._snapshot_file.exists():
            return None

        try:
            content = self._snapshot_file.read_text(encoding="utf-8")
            # 延迟导入，避免循环依赖
            from src.core.state.snapshot import SystemSnapshot
            snapshot = SystemSnapshot.from_json(content)
            logger.debug(f"状态快照已加载: {self._snapshot_file}")
            return snapshot
        except Exception as e:
            logger.error(f"加载状态快照失败: {e}")
            return None

    def save_events(self, events: list[dict[str, Any]]) -> None:
        """保存事件日志"""
        try:
            self._events_file.write_text(
                json.dumps(events, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            logger.debug(f"事件日志已保存: {len(events)} 条")
        except Exception as e:
            logger.error(f"保存事件日志失败: {e}")
            raise

    def load_events(self) -> list[dict[str, Any]]:
        """加载事件日志"""
        if not self._events_file.exists():
            return []

        try:
            content = self._events_file.read_text(encoding="utf-8")
            events = json.loads(content)
            logger.debug(f"事件日志已加载: {len(events)} 条")
            return events
        except Exception as e:
            logger.error(f"加载事件日志失败: {e}")
            return []

    def append_event(self, event: dict[str, Any]) -> None:
        """追加单个事件到日志"""
        events = self.load_events()
        events.append(event)
        self.save_events(events)

    def create_compatibility_view(self, snapshot: Any) -> None:
        """创建兼容性视图文件（用于外部工具读取）

        对应 omx-runtime-core 的 write_compatibility_view 方法。
        生成独立的 JSON 文件供 TypeScript 读取。
        """
        try:
            # 权限快照
            authority_file = self.state_dir / "authority.json"
            authority_file.write_text(
                json.dumps(snapshot.authority.to_dict(), indent=2),
                encoding="utf-8"
            )

            # 后台队列快照
            backlog_file = self.state_dir / "backlog.json"
            backlog_file.write_text(
                json.dumps(snapshot.backlog.to_dict(), indent=2),
                encoding="utf-8"
            )

            # 就绪状态快照
            readiness_file = self.state_dir / "readiness.json"
            readiness_file.write_text(
                json.dumps(snapshot.readiness.to_dict(), indent=2),
                encoding="utf-8"
            )

            # 重放快照
            replay_file = self.state_dir / "replay.json"
            replay_file.write_text(
                json.dumps(snapshot.replay.to_dict(), indent=2),
                encoding="utf-8"
            )

            # 调度记录（从事件中提取）
            events = self.load_events()
            dispatch_events = [
                e for e in events
                if e.get("type") in ["DispatchQueued", "DispatchNotified", "DispatchDelivered", "DispatchFailed"]
            ]
            if dispatch_events:
                dispatch_file = self.state_dir / "dispatch.json"
                dispatch_file.write_text(
                    json.dumps(dispatch_events, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )

            logger.debug("兼容性视图文件已生成")
        except Exception as e:
            logger.error(f"创建兼容性视图失败: {e}")

    def persist(self, snapshot: Any, events: list[dict[str, Any]]) -> None:
        """持久化完整状态（快照+事件）"""
        self.save_snapshot(snapshot)
        self.save_events(events)
        self.create_compatibility_view(snapshot)
        logger.info("状态持久化完成")

    def load(self) -> tuple[Any | None, list[dict[str, Any]]]:
        """加载完整状态"""
        snapshot = self.load_snapshot()
        events = self.load_events()
        return snapshot, events

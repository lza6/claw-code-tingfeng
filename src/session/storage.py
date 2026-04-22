"""Session Storage - 会话持久化存储

汲取 oh-my-codex-main/src/mcp/state-server.ts 的原子锁设计:
- 写入锁: 防止并发写入冲突
- 错误重试: 自动处理临时锁
- 原子操作: 通过临时文件+rename保证

加上 claude-code-rust-master 的优点:
- 独立的存储层,与业务逻辑分离
- 支持 JSON 序列化
- 异步 I/O 操作

存储路径: 项目目录/.clawd/sessions/
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from threading import Lock
from typing import Any

from ..core.project_context import ProjectContext
from .models import Session, SessionInfo

# 写入锁队列（借鉴OMX的stateWriteQueues）
_write_locks: dict[str, asyncio.Lock] = {}
_write_locks_lock = Lock()


def _get_write_lock(path: Path) -> asyncio.Lock:
    """获取指定路径的写入锁（线程安全）"""
    key = str(path.absolute())
    with _write_locks_lock:
        if key not in _write_locks:
            _write_locks[key] = asyncio.Lock()
        return _write_locks[key]


def _release_write_lock(path: Path) -> None:
    """释放写入锁"""
    key = str(path.absolute())
    # 不删除锁对象，避免竞态；锁会被重用于后续操作


class SessionStorage:
    """会话持久化存储

    负责将会话保存到文件系统,以及从文件系统加载会话。
    使用 JSON 格式存储,便于调试和迁移。
    借鉴OMX的原子写入和锁机制保证并发安全。

    """

    def __init__(self, sessions_dir: Path | None = None, project_ctx: ProjectContext | None = None) -> None:
        """初始化存储

        Args:
            sessions_dir: 会话存储目录（显式指定时优先使用）
            project_ctx: 项目上下文（用于自动推导路径）
        """
        if sessions_dir is not None:
            self.sessions_dir = sessions_dir
        elif project_ctx is not None:
            self.sessions_dir = project_ctx.sessions_dir
        else:
            self.sessions_dir = Path('.clawd') / 'sessions'

    def _ensure_dir(self) -> None:
        """确保存储目录存在"""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        """获取会话文件路径"""
        return self.sessions_dir / f"{session_id}.json"

    async def save(self, session: Session) -> Path:
        """保存会话（原子写入 + 并发锁）

        借鉴OMX的原子写入机制:
        1. 获取路径写入锁，防止并发冲突
        2. 写入临时文件
        3. fsync确保落盘
        4. atomic rename替换原文件

        Args:
            session: 要保存的会话对象

        Returns:
            保存的文件路径
        """
        self._ensure_dir()
        path = self._session_path(session.id)
        data = session.to_dict()
        json_str = json.dumps(data, indent=2, ensure_ascii=False)

        # 获取写入锁
        lock = _get_write_lock(path)

        async with lock:
            # 原子写入: temp file + fsync + rename
            tmp_path = path.with_suffix(f'.tmp.{time.time_ns()}.json')

            try:
                # 写入临时文件
                await asyncio.to_thread(
                    tmp_path.write_text,
                    json_str,
                    'utf-8'
                )

                # fsync确保数据落盘（Linux/macOS）
                try:
                    import os
                    with open(tmp_path, 'rb') as f:
                        await asyncio.to_thread(os.fsync, f.fileno())
                except (ImportError, OSError):
                    pass  # Windows或不可用则跳过

                # 原子rename
                await asyncio.to_thread(tmp_path.replace, path)

            except Exception:
                # 清理临时文件
                if tmp_path.exists():
                    await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
                raise
            finally:
                _release_write_lock(path)

        return path

    async def load(self, session_id: str) -> Session | None:
        """加载会话

        Args:
            session_id: 会话 ID

        Returns:
            Session 对象,如果不存在则返回 None
        """
        path = self._session_path(session_id)
        if not path.exists():
            return None

        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        data = json.loads(content)
        return Session.from_dict(data)

    async def delete(self, session_id: str) -> bool:
        """删除会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功删除
        """
        path = self._session_path(session_id)
        if path.exists():
            await asyncio.to_thread(path.unlink)
            return True
        return False

    async def list_sessions(self, limit: int = 50) -> list[SessionInfo]:
        """列出所有会话

        Args:
            limit: 返回数量限制

        Returns:
            SessionInfo 列表,按更新时间降序排列
        """
        if not self.sessions_dir.exists():
            return []

        def _list_dir() -> list[SessionInfo]:
            sessions: list[SessionInfo] = []
            for f in self.sessions_dir.glob("*.json"):
                try:
                    content = f.read_text(encoding="utf-8")
                    data = json.loads(content)
                    sessions.append(SessionInfo(
                        id=data.get("id", f.stem),
                        name=data.get("name", ""),
                        created_at=data.get("created_at", 0),
                        updated_at=data.get("updated_at", 0),
                        message_count=len(data.get("messages", [])),
                        model=data.get("model", ""),
                        total_cost=data.get("total_cost", 0.0),
                    ))
                except (json.JSONDecodeError, KeyError):
                    continue
            return sessions

        sessions = await asyncio.to_thread(_list_dir)
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions[:limit]

    async def exists(self, session_id: str) -> bool:
        """检查会话是否存在

        Args:
            session_id: 会话 ID

        Returns:
            是否存在
        """
        return self._session_path(session_id).exists()

    async def clear_all(self) -> int:
        """清空所有会话

        Returns:
            删除的会话数量
        """
        if not self.sessions_dir.exists():
            return 0

        def _clear() -> int:
            count = 0
            for f in self.sessions_dir.glob("*.json"):
                f.unlink()
                count += 1
            return count

        return await asyncio.to_thread(_clear)

    async def get_stats(self) -> dict[str, Any]:
        """获取存储统计信息

        Returns:
            统计信息字典
        """
        sessions = await self.list_sessions(limit=10000)
        total_size = 0

        if self.sessions_dir.exists():
            for f in self.sessions_dir.glob("*.json"):
                total_size += f.stat().st_size

        return {
            "session_count": len(sessions),
            "storage_size_bytes": total_size,
            "storage_dir": str(self.sessions_dir),
        }

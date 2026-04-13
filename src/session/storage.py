"""Session Storage - 会话持久化存储

从 claude-code-rust-master 汲取的架构优点:
- 独立的存储层,与业务逻辑分离
- 支持 JSON 序列化
- 异步 I/O 操作

存储路径: 项目目录/.clawd/sessions/
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from ..core.project_context import ProjectContext
from .models import Session, SessionInfo


class SessionStorage:
    """会话持久化存储

    负责将会话保存到文件系统,以及从文件系统加载会话。
    使用 JSON 格式存储,便于调试和迁移。

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
        """保存会话

        Args:
            session: 要保存的会话对象

        Returns:
            保存的文件路径
        """
        self._ensure_dir()
        path = self._session_path(session.id)
        data = session.to_dict()

        await asyncio.to_thread(
            path.write_text,
            json.dumps(data, indent=2, ensure_ascii=False),
            'utf-8',  # Explicit UTF-8 encoding for Unicode support
        )
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

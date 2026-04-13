"""TranscriptStore 增强版 — 支持磁盘持久化与跨 session 恢复"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TranscriptEntry:
    """单条对话记录"""
    timestamp: float
    role: str  # user | assistant | system
    content: str


@dataclass
class TranscriptStore:
    """带磁盘持久化的会话记录存储

    增强:
    - 自动序列化到 JSON 文件
    - 启动时自动恢复未完成 session
    - compact 时同步到磁盘
    - 线程安全（文件写入互斥）
    """

    entries: list[TranscriptEntry] = field(default_factory=list)
    flushed: bool = False
    persist_path: Path | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        """初始化时尝试从磁盘恢复"""
        if self.persist_path and self.persist_path.exists():
            self._load_from_disk()

    def append(self, entry: str | TranscriptEntry, role: str = 'user') -> None:
        """添加对话记录

        支持向后兼容：如果传入字符串，自动包装为 TranscriptEntry。
        """
        with self._lock:
            if isinstance(entry, str):
                entry = TranscriptEntry(
                    timestamp=time.time(),
                    role=role,
                    content=entry,
                )
            self.entries.append(entry)
            self.flushed = False

    def compact(self, keep_last: int = 10) -> None:
        """压缩历史记录并同步到磁盘"""
        with self._lock:
            if len(self.entries) > keep_last:
                self.entries[:] = self.entries[-keep_last:]
            self._save_to_disk()

    def replay(self) -> tuple[TranscriptEntry, ...]:
        """回放完整对话"""
        return tuple(self.entries)

    def flush(self, path: Path | None = None) -> None:
        """持久化到磁盘

        参数:
            path: 覆盖默认持久化路径
        """
        target = path or self.persist_path
        if target is None:
            return
        with self._lock:
            self.persist_path = target
            self._save_to_disk()
            self.flushed = True

    def restore(self) -> list[TranscriptEntry]:
        """从磁盘恢复最近的 session

        返回:
            最近一次的对话 entries
        """
        if self.persist_path and self.persist_path.exists():
            self._load_from_disk()
        return self.entries

    def _save_to_disk(self) -> None:
        """内部方法：序列化到 JSON"""
        if self.persist_path is None:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'version': 1,
                'entries': [
                    {
                        'timestamp': e.timestamp,
                        'role': e.role,
                        'content': e.content,
                    }
                    for e in self.entries
                ],
            }
            self.persist_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            pass  # 持久化失败不应阻塞主流程

    def _load_from_disk(self) -> None:
        """内部方法：从 JSON 反序列化"""
        if self.persist_path is None:
            return
        try:
            data = json.loads(self.persist_path.read_text())
            self.entries = [
                TranscriptEntry(
                    timestamp=e['timestamp'],
                    role=e['role'],
                    content=e['content'],
                )
                for e in data.get('entries', [])
            ]
        except Exception:
            pass


__all__ = ['TranscriptEntry', 'TranscriptStore']

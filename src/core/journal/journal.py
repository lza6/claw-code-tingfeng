"""Journal - 结构化执行日志管理器

从 GoalX journal.go 汲取的设计:
- JSONL 格式: 一行一条日志
- 支持 subagent 和 master 两种模式
- 自动摘要: 快速查看最新进展
- 容错: 跳过损坏的日志行
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from .entry import JournalEntry


def load_journal(path: Path) -> list[JournalEntry]:
    """加载 JSONL 格式的日志文件

    Args:
        path: 日志文件路径

    Returns:
        解析后的日志条目列表
    """
    if not path.exists():
        return []

    entries = []
    logger = logging.getLogger("core.journal")

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
                entries.append(JournalEntry.from_dict(data))
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug(f"跳过损坏的日志行 {line_num}: {e}")
                continue

    return entries


def save_journal(path: Path, entries: list[JournalEntry]) -> None:
    """保存日志到 JSONL 文件

    Args:
        path: 日志文件路径
        entries: 日志条目列表
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # 原子写入: 先写入临时文件，再重命名
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    # 原子重命名
    tmp_path.replace(path)


def append_journal_entry(path: Path, entry: JournalEntry) -> None:
    """追加单条日志条目

    Args:
        path: 日志文件路径
        entry: 日志条目
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")


def summary(entries: list[JournalEntry]) -> str:
    """返回日志摘要

    Args:
        entries: 日志条目列表

    Returns:
        一行摘要
    """
    if not entries:
        return "no entries"

    last = entries[-1]
    return last.summary()


class Journal:
    """Journal 管理器"""

    def __init__(self, path: Path):
        self.path = path
        self._entries: list[JournalEntry] = []
        self._logger = logging.getLogger("core.journal")

    def load(self) -> list[JournalEntry]:
        """加载日志"""
        self._entries = load_journal(self.path)
        return self._entries

    def save(self, entries: list[JournalEntry] | None = None) -> None:
        """保存日志 (覆盖写入)"""
        save_journal(self.path, entries or self._entries)

    def append(self, entry: JournalEntry) -> None:
        """追加日志条目"""
        append_journal_entry(self.path, entry)
        self._entries.append(entry)

    def entries(self) -> list[JournalEntry]:
        """获取所有日志条目"""
        return self._entries.copy()

    def last_entry(self) -> JournalEntry | None:
        """获取最新日志条目"""
        return self._entries[-1] if self._entries else None

    def summary(self) -> str:
        """获取日志摘要"""
        return summary(self._entries)

    def round_summary(self, round_num: int) -> list[JournalEntry]:
        """获取指定轮次的日志"""
        return [e for e in self._entries if e.round == round_num]

    def find_blocked(self) -> list[JournalEntry]:
        """查找被阻塞的日志条目"""
        return [e for e in self._entries if e.status == "stuck" and e.blocked_by]

    def find_dispatchable(self) -> list[JournalEntry]:
        """查找包含可执行步骤的日志条目"""
        return [e for e in self._entries if e.dispatchable_slices]
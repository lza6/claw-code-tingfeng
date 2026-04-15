"""Notepad - 结构化上下文与记事本管理系统
借鉴自 oh-my-codex-main (项目 B) 的优点。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.file_ops import atomic_write_json

logger = logging.getLogger(__name__)

@dataclass
class NotepadEntry:
    """记事本条目"""
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # 0: 普通, 1: 高优先级

class Notepad:
    """结构化记事本系统

    功能:
    - 维护 Priority Context (高优先级上下文)
    - 维护 Working Memory (动态运行记录)
    - 支持自动剪枝 (Pruning) 以节省 Token
    - 状态持久化
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path(".clawd/notepad.json")
        self.priority_context: List[NotepadEntry] = []
        self.working_logs: List[NotepadEntry] = []
        self.scratchpad: str = ""
        self._load()

    def add_priority(self, content: str, metadata: Optional[Dict] = None):
        """添加高优先级上下文（如当前任务目标）"""
        self.priority_context.append(NotepadEntry(content=content, metadata=metadata or {}, priority=1))
        self._save()

    def add_log(self, content: str, metadata: Optional[Dict] = None):
        """添加工作记录"""
        self.working_logs.append(NotepadEntry(content=content, metadata=metadata or {}))
        # 简单剪枝：保留最近 50 条
        if len(self.working_logs) > 50:
            self.prune(target_size=30)
        self._save()

    def update_scratchpad(self, content: str):
        """更新草稿纸"""
        self.scratchpad = content
        self._save()

    def prune(self, target_size: int = 20):
        """剪枝：将旧的工作记录摘要化或直接移除"""
        if len(self.working_logs) <= target_size:
            return

        logger.info(f"Notepad: 正在执行剪枝，当前记录数: {len(self.working_logs)}")
        # 保留最近的记录
        self.working_logs = self.working_logs[-target_size:]
        self._save()

    def get_context_for_prompt(self) -> str:
        """生成用于 LLM Prompt 的上下文字符串"""
        lines = ["### NOTEPAD CONTEXT ###"]

        if self.priority_context:
            lines.append("\n[Priority Objectives]")
            for entry in self.priority_context:
                lines.append(f"- {entry.content}")

        if self.working_logs:
            lines.append("\n[Recent Working Logs]")
            for entry in self.working_logs:
                ts = time.strftime("%H:%M:%S", time.localtime(entry.timestamp))
                lines.append(f"[{ts}] {entry.content}")

        if self.scratchpad:
            lines.append(f"\n[Scratchpad]\n{self.scratchpad}")

        return "\n".join(lines)

    def _save(self):
        """持久化到文件"""
        data = {
            "priority_context": [e.__dict__ for e in self.priority_context],
            "working_logs": [e.__dict__ for e in self.working_logs],
            "scratchpad": self.scratchpad,
            "updated_at": time.time()
        }
        try:
            atomic_write_json(self.storage_path, data)
        except Exception as e:
            logger.error(f"Notepad: 保存失败: {e}")

    def _load(self):
        """从文件加载"""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.scratchpad = data.get("scratchpad", "")
                self.priority_context = [NotepadEntry(**e) for e in data.get("priority_context", [])]
                self.working_logs = [NotepadEntry(**e) for e in data.get("working_logs", [])]
        except Exception as e:
            logger.error(f"Notepad: 加载失败: {e}")

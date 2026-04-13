"""Recency Tracker — Tracks recently modified files in the codebase.
Ported from Project B's store logic.
"""
from __future__ import annotations

import heapq
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

class RecencyTracker:
    """Tracks recently modified files using mtime.

    Maintains a list of files ordered by their last modification time.
    """

    def __init__(self, root_dir: str | Path, max_tracked: int = 1000):
        self.root_dir = Path(root_dir)
        self.max_tracked = max_tracked
        # path -> mtime
        self.file_mtimes: dict[str, float] = {}
        # path -> sequence (last access/index event)
        self.file_sequences: dict[str, int] = {}
        self.current_sequence = 0

    def scan(self, exclude_dirs: list[str] | None = None):
        """Perform a full scan of the root directory to build initial recency state."""
        if exclude_dirs is None:
            exclude_dirs = ['.git', '__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build']

        self.file_mtimes.clear()
        self.file_sequences.clear()
        self.current_sequence = 0

        for root, dirs, files in os.walk(self.root_dir):
            # Prune exclude_dirs
            dirs[:] = [d for d in dirs if d not in exclude_dirs]

            for file in files:
                file_path = Path(root) / file
                try:
                    rel_path = str(file_path.relative_to(self.root_dir))
                    mtime = file_path.stat().st_mtime
                    self.file_mtimes[rel_path] = mtime
                except (OSError, ValueError):
                    continue

    def touch(self, rel_path: str):
        """Mark a file as accessed in the current session (Logical Recency)."""
        self.current_sequence += 1
        self.file_sequences[rel_path] = self.current_sequence
        # Also ensure mtime is tracked if not already
        if rel_path not in self.file_mtimes:
            self.update_file(rel_path)

    def update_file(self, rel_path: str):
        """Update both mtime and session sequence for a file."""
        abs_path = self.root_dir / rel_path
        try:
            if abs_path.exists():
                self.file_mtimes[rel_path] = abs_path.stat().st_mtime
                self.touch(rel_path) # Logical update
            elif rel_path in self.file_mtimes:
                del self.file_mtimes[rel_path]
                self.file_sequences.pop(rel_path, None)
        except OSError:
            pass

    def get_hot_files(self, limit: int = 10) -> list[str]:
        """Returns the most recently modified or accessed files.
        排序策略: sequences (核心访问) > mtimes (物理更新)
        """
        def sort_key(item: tuple[str, float]):
            path, mtime = item
            seq = self.file_sequences.get(path, 0)
            if seq > 0:
                # 1e12 ensures sequences always outrank raw timestamps
                return 1e12 + seq
            return mtime

        hot = heapq.nlargest(limit, self.file_mtimes.items(), key=sort_key)
        return [path for path, mtime in hot]

    def get_stats(self) -> dict[str, Any]:
        """Get tracking statistics."""
        return {
            "total_files": len(self.file_mtimes),
            "tracked_sequences": len(self.file_sequences),
            "current_sequence": self.current_sequence,
            "root": str(self.root_dir)
        }

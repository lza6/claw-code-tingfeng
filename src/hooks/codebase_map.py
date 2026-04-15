"""
Codebase Map - 代码库地图构建

从 oh-my-codex-main/src/hooks/codebase-map.ts 转换。
提供代码库结构映射和文件关系图谱。
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


@dataclass
class FileNode:
    """文件节点"""
    path: str
    size: int = 0
    language: str = ""
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    last_modified: str = ""


@dataclass
class CodebaseMap:
    """代码库地图"""
    root: str
    files: dict[str, FileNode] = field(default_factory=dict)
    language_stats: dict[str, int] = field(default_factory=dict)
    total_files: int = 0
    total_size: int = 0
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class CodebaseMapper:
    """代码库映射器

    功能:
    - 扫描目录结构
    - 提取文件元数据
    - 构建依赖关系图
    - 统计语言分布
    """

    # 语言映射
    EXTENSION_LANGUAGE_MAP = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".cpp": "cpp",
        ".c": "c",
        ".cs": "csharp",
        ".rb": "ruby",
        ".go": "go",
        ".swift": "swift",
        ".kt": "kotlin",
    }

    # 忽略目录
    IGNORE_DIRS = {
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        "dist", "build", ".next", "target", ".cache",
    }

    # 忽略文件模式
    IGNORE_PATTERNS = {
        ".DS_Store", "Thumbs.db", "*.pyc", "*.pyo",
        "*.so", "*.dylib", "*.dll", "*.exe",
    }

    def __init__(self, root_path: str):
        self.root_path = Path(root_path).resolve()
        self._cache: Optional[CodebaseMap] = None

    def scan(self, max_depth: int = 10) -> CodebaseMap:
        """扫描代码库"""
        files: dict[str, FileNode] = {}
        language_stats: dict[str, int] = {}
        total_size = 0

        for root, dirs, filenames in os.walk(self.root_path):
            # 限制深度
            depth = len(Path(root).relative_to(self.root_path).parts)
            if depth > max_depth:
                dirs.clear()
                continue

            # 过滤忽略目录
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS]

            for filename in filenames:
                if self._should_ignore(filename):
                    continue

                filepath = Path(root) / filename
                try:
                    stat = filepath.stat()
                    size = stat.st_size
                    language = self._get_language(filename)

                    node = FileNode(
                        path=str(filepath.relative_to(self.root_path)),
                        size=size,
                        language=language,
                        last_modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    )

                    files[node.path] = node
                    total_size += size

                    # 统计语言
                    if language:
                        language_stats[language] = language_stats.get(language, 0) + 1

                except (OSError, PermissionError) as e:
                    logger.warning(f"Cannot access {filepath}: {e}")

        return CodebaseMap(
            root=str(self.root_path),
            files=files,
            language_stats=language_stats,
            total_files=len(files),
            total_size=total_size,
        )

    def _should_ignore(self, filename: str) -> bool:
        """检查是否应忽略"""
        if filename in self.IGNORE_PATTERNS:
            return True
        for pattern in self.IGNORE_PATTERNS:
            if pattern.startswith("*") and filename.endswith(pattern[1:]):
                return True
        return False

    def _get_language(self, filename: str) -> str:
        """获取语言"""
        ext = Path(filename).suffix.lower()
        return self.EXTENSION_LANGUAGE_MAP.get(ext, "")

    def get_map(self, force_refresh: bool = False) -> CodebaseMap:
        """获取地图（带缓存）"""
        if self._cache is None or force_refresh:
            self._cache = self.scan()
        return self._cache

    def find_by_language(self, language: str) -> list[FileNode]:
        """按语言查找文件"""
        code_map = self.get_map()
        return [n for n in code_map.files.values() if n.language == language]

    def find_large_files(self, min_size_kb: int = 100) -> list[FileNode]:
        """查找大文件"""
        code_map = self.get_map()
        min_bytes = min_size_kb * 1024
        return [n for n in code_map.files.values() if n.size >= min_bytes]

    def export_json(self) -> str:
        """导出 JSON"""
        code_map = self.get_map()
        return json.dumps({
            "root": code_map.root,
            "files": {
                k: {
                    "path": v.path,
                    "size": v.size,
                    "language": v.language,
                    "last_modified": v.last_modified,
                }
                for k, v in code_map.files.items()
            },
            "language_stats": code_map.language_stats,
            "total_files": code_map.total_files,
            "total_size": code_map.total_size,
            "generated_at": code_map.generated_at,
        }, indent=2, ensure_ascii=False)


# ===== 导出 =====
__all__ = [
    "FileNode",
    "CodebaseMap",
    "CodebaseMapper",
]

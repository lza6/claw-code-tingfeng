"""Git 数据类型"""

from dataclasses import dataclass


@dataclass
class CommitInfo:
    """Commit 信息"""
    sha: str
    message: str
    author: str
    is_merge: bool = False
    is_pushed: bool = False


@dataclass
class DiffResult:
    """Diff 结果"""
    files_changed: list[str]
    additions: int
    deletions: int
    diff_text: str

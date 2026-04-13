"""Git 子模块

包含:
- types: 数据类型 (CommitInfo, DiffResult)
- ignore: .clawdignore 支持
- diff: Diff 操作
- commit: Commit 操作
"""

from .commit import (
    create_commit,
    generate_commit_message,
    is_commit_pushed,
    undo_commit,
)
from .diff import get_diff, get_diff_since_commit, parse_diff_stats
from .ignore import is_file_ignored, is_path_within_subtree, load_ignore_spec
from .types import CommitInfo, DiffResult

__all__ = [
    'CommitInfo',
    'DiffResult',
    'create_commit',
    'generate_commit_message',
    'get_diff',
    'get_diff_since_commit',
    'is_commit_pushed',
    'is_file_ignored',
    'is_path_within_subtree',
    'load_ignore_spec',
    'parse_diff_stats',
    'undo_commit',
]

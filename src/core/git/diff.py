"""Git Diff 操作"""

import re
from typing import Any

from .types import DiffResult


def parse_diff_stats(stats: str) -> tuple[list[str], int, int]:
    """解析 git diff --stat 输出

    Returns:
        (files_changed, additions, deletions)
    """
    files_changed: list[str] = []
    additions = 0
    deletions = 0

    for line in stats.split('\n'):
        if '|' in line:
            parts = line.split('|')
            if parts:
                files_changed.append(parts[0].strip())
        m = re.search(r'(\d+) insertion', line)
        if m:
            additions += int(m.group(1))
        m = re.search(r'(\d+) deletion', line)
        if m:
            deletions += int(m.group(1))

    return files_changed, additions, deletions


def get_diff(repo: Any, staged_only: bool = False) -> DiffResult | None:
    """获取当前 diff

    Args:
        repo: GitPython Repo 实例
        staged_only: 仅获取已暂存的变更

    Returns:
        DiffResult 或 None
    """
    try:
        if staged_only:
            diff_text = repo.git.diff('--cached')
        else:
            diff_text = repo.git.diff('HEAD')

        if not diff_text:
            return None

        stats = repo.git.diff('--stat', 'HEAD' if not staged_only else '--cached')
        files_changed, additions, deletions = parse_diff_stats(stats)

        return DiffResult(
            files_changed=files_changed,
            additions=additions,
            deletions=deletions,
            diff_text=diff_text,
        )
    except Exception:
        return None


def get_diff_since_commit(repo: Any, base_sha: str) -> DiffResult | None:
    """获取自指定 commit 以来的 diff

    Args:
        repo: GitPython Repo 实例
        base_sha: 基准 commit SHA

    Returns:
        DiffResult 或 None
    """
    try:
        diff_text = repo.git.diff(base_sha)

        if not diff_text:
            return None

        stats = repo.git.diff('--stat', base_sha)
        files_changed, additions, deletions = parse_diff_stats(stats)

        return DiffResult(
            files_changed=files_changed,
            additions=additions,
            deletions=deletions,
            diff_text=diff_text,
        )
    except Exception:
        return None

"""Git ignore 支持 — 从 Aider .aiderignore 移植"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_ignore_spec(
    workdir: Path,
    clawdignore_file: str,
) -> tuple[Any | None, float]:
    """加载 .clawdignore 文件（带缓存）

    Args:
        workdir: 工作目录
        clawdignore_file: ignore 文件名

    Returns:
        (pathspec_spec, mtime)
    """

    ignore_path = workdir / clawdignore_file

    if not ignore_path.exists():
        return None, 0.0

    mtime = ignore_path.stat().st_mtime

    try:
        import pathspec

        patterns = ignore_path.read_text(encoding='utf-8', errors='replace').splitlines()
        spec = pathspec.PathSpec.from_lines(
            'gitwildmatch', [p for p in patterns if p.strip() and not p.startswith('#')]
        )
        logger.debug('[Git] 加载 .clawdignore: %d 条规则', len(patterns))
        return spec, mtime
    except ImportError:
        return None, 0.0
    except Exception as e:
        logger.debug('[Git] 加载 .clawdignore 失败: %s', e)
        return None, 0.0


def is_file_ignored(
    rel_path: str,
    ignore_spec: Any | None,
) -> bool:
    """检查文件是否被 .clawdignore 排除

    Args:
        rel_path: 相对于 workdir 的文件路径
        ignore_spec: 预加载的 pathspec 规范

    Returns:
        True 如果文件被忽略
    """
    if ignore_spec is None:
        return False

    # 规范化路径（使用 / 作为分隔符）
    normalized = rel_path.replace('\\', '/')
    return ignore_spec.match_file(normalized)


def is_path_within_subtree(
    rel_path: str,
    workdir: Path,
    repo: Any,
    subtree_only: bool,
) -> bool:
    """检查文件是否在子树范围内（subtree_only 模式）

    当 subtree_only=True 时，只允许操作 workdir 子目录下的文件。

    Args:
        rel_path: 相对于 git root 的文件路径
        workdir: 工作目录
        repo: GitPython Repo 实例
        subtree_only: 是否启用 subtree_only 模式

    Returns:
        True 如果文件在允许范围内
    """
    if not subtree_only:
        return True

    try:
        git_root = Path(repo.git.rev_parse('--show-toplevel'))
        workdir_rel = workdir.relative_to(git_root)

        # 规范化路径
        normalized = rel_path.replace('\\', '/')
        workdir_rel_str = str(workdir_rel).replace('\\', '/')

        # 检查文件路径是否以 workdir 相对路径为前缀
        return normalized.startswith(workdir_rel_str + '/') or normalized == workdir_rel_str
    except Exception:
        return True  # 出错时不过滤

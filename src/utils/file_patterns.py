"""File Pattern Utils — 文件模式工具（从 Aider help_pats.py 移植）

提供网站发布和文件过滤的模式定义。

用法:
    from src.utils.file_patterns import EXCLUDE_WEBSITE_PATTERNS, is_excluded

    if is_excluded("docs/benchmark.md"):
        print("Excluded from website")
"""
from __future__ import annotations

from pathlib import Path


def is_too_large_or_binary(file_path: str, max_size_mb: int = 1) -> bool:
    """检查文件是否过大或为二进制文件

    参数:
        file_path: 文件路径
        max_size_mb: 最大限制（MB）

    返回:
        True 如果应该排除
    """
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return False

    # 大文件检查
    try:
        if path.stat().st_size > max_size_mb * 1024 * 1024:
            return True
    except OSError:
        return True

    # 简单二进制检查 (读取前 1024 字节寻找空字节)
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            return b'\x00' in chunk
    except (OSError, UnicodeDecodeError):
        return True

    return False


# 网站发布排除模式（需与 MANIFEST.in 同步）
EXCLUDE_WEBSITE_PATTERNS: list[str] = [
    "**/.DS_Store",
    "examples/**",
    "_posts/**",
    "HISTORY.md",
    "docs/benchmarks*md",
    "docs/ctags.md",
    "docs/unified-diffs.md",
    "docs/leaderboards/index.md",
    "assets/**",
    ".jekyll-metadata",
    "Gemfile.lock",
    "Gemfile",
    "_config.yml",
    "**/OLD/**",
    "OLD/**",
]


def is_excluded(file_path: str, patterns: list[str] | None = None) -> bool:
    """检查文件是否应该被排除

    参数:
        file_path: 文件路径
        patterns: 模式列表（默认使用 EXCLUDE_WEBSITE_PATTERNS）

    返回:
        是否应该排除
    """
    import fnmatch

    patterns = patterns or EXCLUDE_WEBSITE_PATTERNS

    return any(fnmatch.fnmatch(file_path, pattern) for pattern in patterns)


def filter_files(file_paths: list[str], patterns: list[str] | None = None) -> list[str]:
    """过滤文件列表

    参数:
        file_paths: 文件路径列表
        patterns: 模式列表

    返回:
        过滤后的文件列表
    """
    return [f for f in file_paths if not is_excluded(f, patterns)]


# 额外的常用模式 (同步 Aider v0.50.0)
GITIGNORE_PATTERNS: list[str] = [
    "__pycache__/**",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".Python",
    "*.so",
    "*.egg",
    "*.egg-info",
    "dist/**",
    "build/**",
    "*.log",
    ".env",
    ".venv",
    "venv/**",
    "node_modules/**",
    ".git/**",
    ".svn",
    "*.swp",
    "*.swo",
    "*~",
    ".DS_Store",
    # 扩展现代工具模式 (Aider v0.50.0)
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".mypy_cache/**",
    ".next/**",
    ".tauri/**",
    "vendor/**",
    "*.exe", "*.dll", "*.dylib",
    "*.db", "*.sqlite", "*.sqlite3",
    ".clawd/**",  # 排除自身的持久化缓存
    # Aider 0.50.0 新增模式
    ".idea/**",
    ".vscode/**",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".tox/",
    ".nox/",
    ".coverage",
    "htmlcov/",
    ".history/",
    ".aider*",
    ".clawd*",
]


def is_gitignored(file_path: str) -> bool:
    """检查文件是否应该被 gitignore

    参数:
        file_path: 文件路径

    返回:
        是否应该忽略
    """
    if is_excluded(file_path, GITIGNORE_PATTERNS):
        return True

    return is_too_large_or_binary(file_path)


# 导出
__all__ = [
    "EXCLUDE_WEBSITE_PATTERNS",
    "GITIGNORE_PATTERNS",
    "filter_files",
    "is_excluded",
    "is_gitignored",
]

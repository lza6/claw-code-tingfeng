"""工具运行时 - 核心工具实现 + 注册中心

从 claude-code-rust-master 汲取的架构优点:
- ToolRegistry 统一工具注册、发现、执行
"""
from __future__ import annotations

from .ai_comment_watcher import AIComment, AICommentWatcher, format_comments_for_llm
from .base import BaseTool, ParameterSchema, ToolResult
from .bash_tool import BashTool
from .bundle_tool import BundleTool
from .clipboard_tool import ClipboardTool, ClipboardWatcher

# Code Edit Module (from Aider Coder strategy pattern)
from .code_edit import (
    BaseCoder,
    EditBlockCoder,
    EditResult,
    PatchCoder,
    UDiffCoder,
    WholeFileCoder,
    apply_edit,
    create_coder,
    perfect_replace,
    try_dotdotdots,
)
from .code_edit import (
    replace_most_similar_chunk as code_replace_most_similar_chunk,
)
from .dependency_tool import DependencyTool

# Edit Format Switcher (from Aider)
from .edit_format_switcher import (
    EDIT_FORMAT_CHOICES,
    EditFormatSwitcher,
    get_edit_format_switcher,
)
from .edit_parser import (
    count_edit_blocks,
    extract_shell_commands,
    find_filename,
    find_original_update_blocks,
    replace_most_similar_chunk,
    strip_quoted_wrapping,
    validate_edit_blocks,
)
from .file_edit_tool import FileEditTool
from .file_read_tool import FileReadTool
from .glob_tool import GlobTool
from .grep_tool import GrepTool
from .linter import Linter, LintResult, format_lint_result, lint_python_compile
from .path_utils import BINARY_EXTENSIONS, TEXT_EXTENSIONS, resolve_path
from .recency_tools import HotFilesTool
from .registry import ToolRegistry
from .scrape_tool import Scraper, ScrapeTool, detect_urls
from .search_replace import (
    RelativeIndenter,
    SearchResult,
    flexible_search_and_replace,
    search_and_replace,
)
from .udiff_parser import (
    SearchTextNotUnique,
    apply_hunks,
    find_diffs,
    hunk_to_before_after,
    normalize_hunk,
)
from .udiff_tool import UnifiedDiffTool
from .voice_tool import VoiceTool, get_available_devices
from .watch_tool import FileWatcher, WatchTool

__all__ = [
    'BINARY_EXTENSIONS',
    'EDIT_FORMAT_CHOICES',
    'TEXT_EXTENSIONS',
    'AIComment',
    # AI Comment Watcher
    'AICommentWatcher',
    # Code Edit Module (from Aider)
    'BaseCoder',
    'BaseTool',
    'BashTool',
    'BundleTool',
    # Clipboard (from aider)
    'ClipboardTool',
    'ClipboardWatcher',
    'DependencyTool',
    'EditBlockCoder',
    # Edit Format Switcher (from Aider)
    'EditFormatSwitcher',
    'EditResult',
    'FileEditTool',
    'FileReadTool',
    'FileWatcher',
    'GlobTool',
    'GrepTool',
    'HotFilesTool',
    'LintResult',
    # Lint
    'Linter',
    'ParameterSchema',
    'PatchCoder',
    'RelativeIndenter',
    # Scrape
    'ScrapeTool',
    'Scraper',
    'SearchResult',
    # UnifiedDiff (from aider)
    'SearchTextNotUnique',
    'ToolRegistry',
    'ToolResult',
    'UDiffCoder',
    'UnifiedDiffTool',
    # Voice (from aider)
    'VoiceTool',
    # Watch (from aider)
    'WatchTool',
    'WholeFileCoder',
    'apply_edit',
    'apply_hunks',
    'code_replace_most_similar_chunk',
    # 搜索替换 (from aider)
    'count_edit_blocks',
    'create_coder',
    'detect_urls',
    'extract_shell_commands',
    'find_diffs',
    'find_filename',
    'find_original_update_blocks',
    'flexible_search_and_replace',
    'format_comments_for_llm',
    'format_lint_result',
    'get_available_devices',
    'get_edit_format_switcher',
    'hunk_to_before_after',
    'lint_python_compile',
    'normalize_hunk',
    'perfect_replace',
    'replace_most_similar_chunk',
    'resolve_path',
    'search_and_replace',
    'strip_quoted_wrapping',
    'try_dotdotdots',
    'validate_edit_blocks',
]

"""FileWatcher - 文件变化监控与 AI 注释检测 — 从 Aider watch.py 移植

监控源代码文件变化，检测 AI 注释标记，自动触发代码修改或问题。

支持的 AI 注释模式:
- `# TODO AI:` 或 `// TODO AI:` — 触发代码修改
- `# AI?` 或 `// AI?` — 触发问题
- `# AI!` 或 `// AI!` — 紧急修改

用法:
    watcher = FileWatcher(coder, gitignores=['.gitignore'])
    watcher.start()
"""
from __future__ import annotations

import contextlib
import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ==================== AI 注释模式 ====================

# AI 注释正则表达式
AI_COMMENT_PATTERN = re.compile(
    r'(?:#|//|--|;+)\s*(ai\b.*|ai\b.*|.*\bai[?!]?)\s*$',
    re.IGNORECASE,
)

# AI 问题模式
AI_QUESTION_PATTERN = re.compile(
    r'(?:#|//|--|;+)\s*ai\?\s*$',
    re.IGNORECASE,
)

# AI 紧急模式
AI_URGENT_PATTERN = re.compile(
    r'(?:#|//|--|;+)\s*ai!\s*$',
    re.IGNORECASE,
)


# ==================== Gitignore 过滤器 ====================

def load_gitignores(gitignore_paths: list[Path]) -> Any:
    """加载多个 .gitignore 文件为单个 PathSpec

    参数:
        gitignore_paths: .gitignore 文件路径列表

    返回:
        PathSpec 对象，或 None
    """
    try:
        from pathspec import PathSpec
        from pathspec.patterns import GitWildMatchPattern
    except ImportError:
        return None

    patterns: list[str] = [
        '.aider*',
        '.git',
        # 常见备份和临时文件
        '*~',
        '*.bak',
        '*.swp',
        '*.swo',
        '*.tmp',
        '*.temp',
        '*.orig',
        '*.pyc',
        '__pycache__/',
        '.DS_Store',
        'Thumbs.db',
        '*.svg',
        '*.pdf',
        # IDE 文件
        '.idea/',
        '.vscode/',
        '*.sublime-*',
        '.project',
        '.settings/',
        # 环境文件
        '.env',
        '.venv/',
        'node_modules/',
        'vendor/',
        # 日志和缓存
        '*.log',
        '.cache/',
        '.pytest_cache/',
        'coverage/',
    ]

    for path in gitignore_paths:
        if path.exists():
            with contextlib.suppress(OSError):
                patterns.extend(path.read_text(encoding='utf-8').splitlines())

    return PathSpec.from_lines(GitWildMatchPattern, patterns) if patterns else None


# ==================== FileWatcher 类 ====================

class FileWatcher:
    """文件变化监控器

    监控源代码文件变化，检测 AI 注释并触发相应操作。
    """

    def __init__(
        self,
        coder: Any = None,
        gitignores: list[str] | None = None,
        verbose: bool = False,
        analytics: Any = None,
        root: str | Path | None = None,
        on_change: Callable[[str, str], None] | None = None,
    ) -> None:
        """初始化文件监控器

        参数:
            coder: Coder 实例（用于触发修改）
            gitignores: .gitignore 文件路径列表
            verbose: 详细输出
            analytics: 分析器实例
            root: 监控根目录
            on_change: 变化回调函数 (path, content) -> None
        """
        self.coder = coder
        self.io = getattr(coder, 'io', None) if coder else None
        self.root = Path(root) if root else (Path(coder.root) if coder else Path.cwd())
        self.verbose = verbose
        self.analytics = analytics
        self.on_change = on_change

        self.stop_event: threading.Event | None = None
        self.watcher_thread: threading.Thread | None = None
        self.changed_files: set[str] = set()

        # 加载 gitignore
        self.gitignores = gitignores or []
        self.gitignore_spec = load_gitignores(
            [Path(g) for g in self.gitignores] if self.gitignores else []
        )

        # 注册到 IO
        if self.io:
            self.io.file_watcher = self

    def start(self) -> None:
        """启动文件监控"""
        if self.watcher_thread and self.watcher_thread.is_alive():
            return

        self.stop_event = threading.Event()
        self.watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self.watcher_thread.start()
        logger.info('FileWatcher 已启动')

    def stop(self) -> None:
        """停止文件监控"""
        if self.stop_event:
            self.stop_event.set()
        if self.watcher_thread:
            self.watcher_thread.join(timeout=2)
        logger.info('FileWatcher 已停止')

    def _watch_loop(self) -> None:
        """监控循环"""
        try:
            from watchfiles import watch
        except ImportError:
            logger.warning('watchfiles 未安装，文件监控不可用')
            return

        try:
            for changes in watch(str(self.root), stop_event=self.stop_event):
                if self.stop_event and self.stop_event.is_set():
                    break

                for change_type, path in changes:
                    self._handle_change(change_type, path)
        except Exception as e:
            logger.error(f'文件监控错误: {e}')

    def _handle_change(self, change_type: Any, path: str) -> None:
        """处理文件变化

        参数:
            change_type: 变化类型 (watchfiles.Change)
            path: 文件路径
        """
        path_obj = Path(path)
        path_abs = path_obj.absolute()

        # 检查是否在监控范围内
        try:
            if not path_abs.is_relative_to(self.root.absolute()):
                return
        except (ValueError, TypeError):
            return

        # 检查是否被 gitignore 排除
        rel_path = path_abs.relative_to(self.root)
        if self.gitignore_spec and self.gitignore_spec.match_file(str(rel_path)):
            return

        # 检查文件扩展名
        if not self._is_source_file(path_obj):
            return

        if self.verbose:
            logger.debug(f'文件变化: {rel_path} ({change_type})')

        # 检查 AI 注释
        try:
            content = path_abs.read_text(encoding='utf-8', errors='replace')
            ai_comments = self._find_ai_comments(content)

            if ai_comments:
                self._handle_ai_comments(str(rel_path), ai_comments)
            elif self.on_change:
                self.on_change(str(rel_path), content)

        except OSError as e:
            logger.debug(f'无法读取文件: {path}: {e}')

    def _is_source_file(self, path: Path) -> bool:
        """检查是否为源代码文件"""
        source_extensions = {
            '.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java',
            '.c', '.cpp', '.h', '.hpp', '.rb', '.php', '.sh', '.bash',
            '.zsh', '.fish', '.lua', '.vim', '.el', '.scm', '.rkt',
            '.ml', '.hs', '.erl', '.ex', '.exs', '.swift', '.kt',
            '.scala', '.clj', '.cljs', '.sql', '.css', '.scss', '.less',
            '.html', '.htm', '.xml', '.yaml', '.yml', '.json', '.toml',
            '.md', '.rst', '.tex', '.dockerfile', '.makefile',
        }
        return path.suffix.lower() in source_extensions or path.name.lower() in {
            'dockerfile', 'makefile', 'rakefile', 'gemfile', 'podfile',
        }

    def _find_ai_comments(self, content: str) -> list[tuple[int, str, str]]:
        """查找 AI 注释

        返回:
            [(行号, 注释类型, 注释内容)] 列表
        """
        comments: list[tuple[int, str, str]] = []

        for i, line in enumerate(content.splitlines()):
            # 检查 AI 问题
            if AI_QUESTION_PATTERN.search(line):
                comments.append((i + 1, 'question', line.strip()))
                continue

            # 检查 AI 紧急
            if AI_URGENT_PATTERN.search(line):
                comments.append((i + 1, 'urgent', line.strip()))
                continue

            # 检查普通 AI 注释
            match = AI_COMMENT_PATTERN.search(line)
            if match:
                comment_text = match.group(1).strip()
                if comment_text.lower().startswith('ai'):
                    comments.append((i + 1, 'todo', comment_text))

        return comments

    def _handle_ai_comments(
        self,
        path: str,
        comments: list[tuple[int, str, str]],
    ) -> None:
        """处理 AI 注释

        参数:
            path: 文件路径
            comments: AI 注释列表
        """
        for line_no, comment_type, comment_text in comments:
            if comment_type == 'question':
                logger.info(f'AI 问题 [{path}:{line_no}]: {comment_text}')
                # 触发问题处理
                if self.coder:
                    self._trigger_question(path, line_no, comment_text)

            elif comment_type == 'urgent':
                logger.info(f'AI 紧急 [{path}:{line_no}]: {comment_text}')
                # 触发紧急修改
                if self.coder:
                    self._trigger_urgent_change(path, line_no, comment_text)

            else:
                logger.info(f'AI TODO [{path}:{line_no}]: {comment_text}')
                # 记录待处理
                self.changed_files.add(path)

    def _trigger_question(self, path: str, line_no: int, question: str) -> None:
        """触发问题处理"""
        # 由具体实现覆盖
        pass

    def _trigger_urgent_change(self, path: str, line_no: int, comment: str) -> None:
        """触发紧急修改"""
        # 由具体实现覆盖
        pass

    def get_changed_files(self) -> set[str]:
        """获取已变化的文件集合"""
        return self.changed_files.copy()

    def clear_changed_files(self) -> None:
        """清空已变化的文件集合"""
        self.changed_files.clear()

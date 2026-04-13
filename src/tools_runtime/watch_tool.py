"""WatchTool - 文件监控工具 — 从 Aider watch.py 移植

支持实时监控文件变化，检测 AI 注释并触发回调。

用法:
    tool = WatchTool()
    result = tool.execute(action='start', path='/path/to/project')
    result = tool.execute(action='stop')
    result = tool.execute(action='get_changes')

依赖:
    pip install watchfiles pathspec grep-ast
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from .base import BaseTool, ParameterSchema, ToolResult

logger = logging.getLogger(__name__)

# 默认忽略模式
DEFAULT_IGNORE_PATTERNS = [
    ".aider*",
    ".git",
    # 编辑器备份/临时文件
    "*~",
    "*.bak",
    "*.swp",
    "*.swo",
    "\\#*\\#",
    ".#*",
    "*.tmp",
    "*.temp",
    "*.orig",
    "*.pyc",
    "__pycache__/",
    ".DS_Store",
    "Thumbs.db",
    "*.svg",
    "*.pdf",
    # IDE 文件
    ".idea/",
    ".vscode/",
    "*.sublime-*",
    ".project",
    ".settings/",
    "*.code-workspace",
    # 环境文件
    ".env",
    ".venv/",
    "node_modules/",
    "vendor/",
    # 日志和缓存
    "*.log",
    ".cache/",
    ".pytest_cache/",
    "coverage/",
]


class FileWatcher:
    """文件监控器 — 监控源文件变化和 AI 注释

    功能:
    - 实时监控指定目录的文件变化
    - 检测 AI 注释（如 # ai!, # ai?）
    - 支持 gitignore 规则
    - 异步回调通知

    示例:
        >>> watcher = FileWatcher('/path/to/project')
        >>> watcher.start()
        >>> changes = watcher.get_changes()
        >>> watcher.stop()
    """

    # AI 注释模式（支持多种语言）
    AI_COMMENT_PATTERN = re.compile(
        r'(?:#|//|--|;+)\s*(ai\b.*|ai\b.*|.*\bai[?!]?)\s*$',
        re.IGNORECASE,
    )

    def __init__(
        self,
        root: str | Path,
        gitignores: list[str] | None = None,
        verbose: bool = False,
        max_file_size: int = 1024 * 1024,  # 1MB
    ) -> None:
        """初始化文件监控器

        参数:
            root: 监控根目录
            gitignores: gitignore 文件路径列表
            verbose: 是否输出详细日志
            max_file_size: 最大监控文件大小（字节）
        """
        self.root = Path(root).resolve()
        self.gitignores = gitignores or []
        self.verbose = verbose
        self.max_file_size = max_file_size

        self._stop_event: threading.Event | None = None
        self._watcher_thread: threading.Thread | None = None
        self._changed_files: set[str] = set()
        self._gitignore_spec = self._load_gitignores()

    def _load_gitignores(self) -> Any:
        """加载 gitignore 规则"""
        try:
            from pathspec import PathSpec
            from pathspec.patterns import GitWildMatchPattern
        except ImportError:
            logger.warning('pathspec 未安装，gitignore 规则将不生效')
            return None

        patterns = list(DEFAULT_IGNORE_PATTERNS)

        for gitignore_path in self.gitignores:
            path = Path(gitignore_path)
            if path.exists():
                with open(path) as f:
                    patterns.extend(f.readlines())

        if patterns:
            return PathSpec.from_lines(GitWildMatchPattern, patterns)
        return None

    def _filter_func(self, change_type: str, path: str) -> bool:
        """过滤函数，决定是否监控该文件"""
        path_obj = Path(path)
        path_abs = path_obj.absolute()

        # 检查是否在监控目录内
        try:
            if not path_abs.is_relative_to(self.root):
                return False
        except (ValueError, OSError):
            return False

        rel_path = path_abs.relative_to(self.root)

        if self.verbose:
            logger.debug(f'检查文件变化: {rel_path}')

        # 检查 gitignore 规则
        if self._gitignore_spec:
            try:
                is_dir = path_abs.is_dir()
                if self._gitignore_spec.match_file(
                    rel_path.as_posix() + ('/' if is_dir else '')
                ):
                    return False
            except Exception:
                pass

        # 检查文件大小
        if path_abs.is_file():
            try:
                if path_abs.stat().st_size > self.max_file_size:
                    return False
            except OSError:
                return False

        # 检查是否包含 AI 注释
        try:
            comments, _, _ = self.get_ai_comments(str(path_abs))
            return bool(comments)
        except Exception:
            return False

    def _get_roots_to_watch(self) -> list[str]:
        """获取需要监控的根路径列表"""
        if self._gitignore_spec:
            try:
                roots = [
                    str(path)
                    for path in self.root.iterdir()
                    if not self._gitignore_spec.match_file(
                        path.relative_to(self.root).as_posix() + ('/' if path.is_dir() else '')
                    )
                ]
                return roots if roots else [str(self.root)]
            except Exception:
                pass
        return [str(self.root)]

    def _watch_files(self) -> None:
        """监控文件变化（在独立线程中运行）"""
        try:
            from watchfiles import watch
        except ImportError:
            logger.error('watchfiles 未安装，无法监控文件')
            return

        roots_to_watch = self._get_roots_to_watch()

        try:
            for changes in watch(
                *roots_to_watch,
                watch_filter=self._filter_func,
                stop_event=self._stop_event,
                ignore_permission_denied=True,
            ):
                if self._handle_changes(changes):
                    return
        except Exception as e:
            if self.verbose:
                logger.error(f'文件监控错误: {e}')
            raise

    def _handle_changes(self, changes: list) -> bool:
        """处理检测到的变化"""
        if not changes:
            return False

        changed_files = {str(Path(change[1])) for change in changes}
        self._changed_files.update(changed_files)
        return True

    def start(self) -> None:
        """开始监控文件变化"""
        if self._watcher_thread and self._watcher_thread.is_alive():
            logger.warning('文件监控器已在运行')
            return

        self._stop_event = threading.Event()
        self._changed_files = set()

        self._watcher_thread = threading.Thread(target=self._watch_files, daemon=True)
        self._watcher_thread.start()

        if self.verbose:
            logger.info(f'开始监控目录: {self.root}')

    def stop(self) -> None:
        """停止监控文件变化"""
        if self._stop_event:
            self._stop_event.set()

        if self._watcher_thread:
            self._watcher_thread.join(timeout=5)
            self._watcher_thread = None
            self._stop_event = None

        if self.verbose:
            logger.info('文件监控已停止')

    def get_changes(self) -> set[str]:
        """获取已变化的文件集合"""
        return self._changed_files.copy()

    def clear_changes(self) -> None:
        """清除已记录的变化"""
        self._changed_files.clear()

    def get_ai_comments(self, filepath: str) -> tuple[list[int], list[str], str | None]:
        """从文件中提取 AI 注释

        参数:
            filepath: 文件路径

        返回:
            (行号列表, 注释列表, 动作类型)
            动作类型: None, '!' (执行), '?' (提问)
        """
        line_nums: list[int] = []
        comments: list[str] = []
        has_action: str | None = None

        try:
            content = Path(filepath).read_text(encoding='utf-8', errors='replace')
        except OSError:
            return [], [], None

        for i, line in enumerate(content.splitlines(), 1):
            if match := self.AI_COMMENT_PATTERN.search(line):
                comment = match.group(0).strip()
                if comment:
                    line_nums.append(i)
                    comments.append(comment)

                    comment_lower = comment.lower()
                    comment_lower = comment_lower.lstrip('/#-;').strip()

                    if comment_lower.startswith('ai!') or comment_lower.endswith('ai!'):
                        has_action = '!'
                    elif comment_lower.startswith('ai?') or comment_lower.endswith('ai?'):
                        has_action = '?'

        if not line_nums:
            return [], [], None

        return line_nums, comments, has_action

    def process_changes(self, tracked_files: set[str] | None = None) -> dict[str, Any]:
        """处理变化并返回结构化结果

        参数:
            tracked_files: 已跟踪的文件集合（可选）

        返回:
            {
                'changed_files': [...],
                'ai_comments': {filepath: [(line, comment), ...]},
                'actions': {filepath: action_type},
            }
        """
        result: dict[str, Any] = {
            'changed_files': list(self._changed_files),
            'ai_comments': {},
            'actions': {},
        }

        for fname in self._changed_files:
            line_nums, comments, action = self.get_ai_comments(fname)

            if line_nums and comments:
                result['ai_comments'][fname] = list(zip(line_nums, comments, strict=False))

            if action:
                result['actions'][fname] = action

        return result


class WatchTool(BaseTool):
    """文件监控工具

    功能:
    - 启动/停止文件监控
    - 获取变化的文件列表
    - 检测 AI 注释

    示例:
        >>> tool = WatchTool()
        >>> tool.execute(action='start', path='/path/to/project')
        >>> tool.execute(action='get_changes')
        >>> tool.execute(action='stop')
    """

    name = 'WatchTool'
    description = '监控文件变化，检测 AI 注释，支持 gitignore 规则'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='action',
            param_type='str',
            required=True,
            description='操作: start, stop, get_changes, process',
            allowed_values=('start', 'stop', 'get_changes', 'process'),
        ),
        ParameterSchema(
            name='path',
            param_type='str',
            required=False,
            description='监控路径（start 操作必需）',
        ),
        ParameterSchema(
            name='gitignore',
            param_type='str',
            required=False,
            description='gitignore 文件路径',
        ),
    )

    # 类级别的 watcher 实例缓存
    _watchers: dict[str, FileWatcher] = {}

    def execute(self, **kwargs) -> ToolResult:
        """执行文件监控操作"""
        action = kwargs.get('action', 'get_changes')

        if action == 'start':
            return self._start(**kwargs)
        elif action == 'stop':
            return self._stop(**kwargs)
        elif action == 'get_changes':
            return self._get_changes(**kwargs)
        elif action == 'process':
            return self._process(**kwargs)
        else:
            return ToolResult(
                success=False,
                output='',
                error=f'未知操作: {action}',
                exit_code=1,
            )

    def _start(self, **kwargs) -> ToolResult:
        """启动监控"""
        path = kwargs.get('path')
        if not path:
            return ToolResult(
                success=False,
                output='',
                error='start 操作需要 path 参数',
                exit_code=1,
            )

        path = str(Path(path).resolve())
        gitignore = kwargs.get('gitignore')
        gitignores = [gitignore] if gitignore else []

        # 检查是否已有监控器
        if path in self._watchers:
            watcher = self._watchers[path]
            if watcher._watcher_thread and watcher._watcher_thread.is_alive():
                return ToolResult(
                    success=True,
                    output=f'监控器已在运行: {path}',
                    exit_code=0,
                )

        try:
            watcher = FileWatcher(path, gitignores=gitignores, verbose=True)
            watcher.start()
            self._watchers[path] = watcher

            return ToolResult(
                success=True,
                output=f'已启动监控: {path}',
                exit_code=0,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=f'启动监控失败: {e}',
                exit_code=1,
            )

    def _stop(self, **kwargs) -> ToolResult:
        """停止监控"""
        path = kwargs.get('path')

        if path:
            path = str(Path(path).resolve())
            if path in self._watchers:
                self._watchers[path].stop()
                del self._watchers[path]
                return ToolResult(
                    success=True,
                    output=f'已停止监控: {path}',
                    exit_code=0,
                )
            else:
                return ToolResult(
                    success=False,
                    output='',
                    error=f'未找到监控器: {path}',
                    exit_code=1,
                )
        else:
            # 停止所有监控器
            count = len(self._watchers)
            for watcher in self._watchers.values():
                watcher.stop()
            self._watchers.clear()

            return ToolResult(
                success=True,
                output=f'已停止 {count} 个监控器',
                exit_code=0,
            )

    def _get_changes(self, **kwargs) -> ToolResult:
        """获取变化"""
        path = kwargs.get('path')

        if path:
            path = str(Path(path).resolve())
            if path not in self._watchers:
                return ToolResult(
                    success=False,
                    output='',
                    error=f'未找到监控器: {path}',
                    exit_code=1,
                )
            watcher = self._watchers[path]
            changes = watcher.get_changes()
        else:
            # 获取所有监控器的变化
            changes = {}
            for p, watcher in self._watchers.items():
                changes[p] = list(watcher.get_changes())

        import json
        return ToolResult(
            success=True,
            output=json.dumps(changes, ensure_ascii=False, indent=2),
            exit_code=0,
        )

    def _process(self, **kwargs) -> ToolResult:
        """处理变化"""
        path = kwargs.get('path')

        if path:
            path = str(Path(path).resolve())
            if path not in self._watchers:
                return ToolResult(
                    success=False,
                    output='',
                    error=f'未找到监控器: {path}',
                    exit_code=1,
                )
            watcher = self._watchers[path]
            result = watcher.process_changes()
        else:
            # 处理所有监控器的变化
            result = {}
            for p, watcher in self._watchers.items():
                result[p] = watcher.process_changes()

        import json
        return ToolResult(
            success=True,
            output=json.dumps(result, ensure_ascii=False, indent=2),
            exit_code=0,
        )

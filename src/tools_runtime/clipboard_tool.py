"""ClipboardTool - 剪贴板操作工具 — 从 Aider copypaste.py 移植

支持读取和写入系统剪贴板，监控剪贴板变化。

用法:
    tool = ClipboardTool()
    result = tool.execute(action='read')
    result = tool.execute(action='write', text='Hello World')
    result = tool.execute(action='watch_start')

依赖:
    pip install pyperclip
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .base import BaseTool, ParameterSchema, ToolResult

logger = logging.getLogger(__name__)


class ClipboardWatcher:
    """剪贴板监控器 — 监控剪贴板变化

    功能:
    - 实时监控剪贴板内容变化
    - 支持自定义回调
    - 多行内容自动格式化

    示例:
        >>> watcher = ClipboardWatcher()
        >>> watcher.start(on_change=lambda text: print(text))
        >>> # ... 用户复制内容 ...
        >>> watcher.stop()
    """

    def __init__(self, interval: float = 0.5, verbose: bool = False) -> None:
        """初始化监控器

        参数:
            interval: 检查间隔（秒）
            verbose: 是否输出详细日志
        """
        self.interval = interval
        self.verbose = verbose

        self._stop_event: threading.Event | None = None
        self._watcher_thread: threading.Thread | None = None
        self._last_clipboard: str | None = None
        self._on_change: Callable[[str], None] | None = None
        self._pyperclip = None

    def _load_pyperclip(self) -> Any:
        """加载 pyperclip"""
        if self._pyperclip is None:
            try:
                import pyperclip
                self._pyperclip = pyperclip
            except ImportError:
                raise ImportError('pyperclip 未安装，请运行: pip install pyperclip')
        return self._pyperclip

    def start(self, on_change: Callable[[str], None] | None = None) -> None:
        """开始监控剪贴板

        参数:
            on_change: 内容变化时的回调函数
        """
        if self._watcher_thread and self._watcher_thread.is_alive():
            logger.warning('剪贴板监控器已在运行')
            return

        pyperclip = self._load_pyperclip()
        self._on_change = on_change
        self._stop_event = threading.Event()
        self._last_clipboard = pyperclip.paste()

        def watch_clipboard():
            while not self._stop_event.is_set():
                try:
                    current = pyperclip.paste()
                    if current != self._last_clipboard:
                        self._last_clipboard = current

                        # 格式化多行内容
                        formatted = current
                        if len(current.splitlines()) > 1:
                            formatted = '\n' + current + '\n'

                        if self._on_change:
                            self._on_change(formatted)

                        if self.verbose:
                            logger.info(f'剪贴板内容已更新: {len(current)} 字符')

                    time.sleep(self.interval)

                except Exception as e:
                    if self.verbose:
                        logger.error(f'剪贴板监控错误: {e}')
                    continue

        self._watcher_thread = threading.Thread(target=watch_clipboard, daemon=True)
        self._watcher_thread.start()

        if self.verbose:
            logger.info('剪贴板监控已启动')

    def stop(self) -> None:
        """停止监控剪贴板"""
        if self._stop_event:
            self._stop_event.set()

        if self._watcher_thread:
            self._watcher_thread.join(timeout=2)
            self._watcher_thread = None
            self._stop_event = None

        if self.verbose:
            logger.info('剪贴板监控已停止')

    def get_last_content(self) -> str | None:
        """获取最后一次剪贴板内容"""
        return self._last_clipboard

    @property
    def is_running(self) -> bool:
        """检查监控器是否在运行"""
        return self._watcher_thread is not None and self._watcher_thread.is_alive()


class ClipboardTool(BaseTool):
    """剪贴板操作工具

    功能:
    - 读取剪贴板内容
    - 写入剪贴板内容
    - 监控剪贴板变化

    示例:
        >>> tool = ClipboardTool()
        >>> tool.execute(action='read')
        >>> tool.execute(action='write', text='Hello')
        >>> tool.execute(action='watch_start')
    """

    name = 'ClipboardTool'
    description = '操作系统剪贴板，支持读取、写入和监控'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='action',
            param_type='str',
            required=True,
            description='操作: read, write, watch_start, watch_stop, watch_status',
            allowed_values=('read', 'write', 'watch_start', 'watch_stop', 'watch_status'),
        ),
        ParameterSchema(
            name='text',
            param_type='str',
            required=False,
            description='要写入的文本（write 操作必需）',
        ),
        ParameterSchema(
            name='interval',
            param_type='float',
            required=False,
            description='监控间隔（秒，默认 0.5）',
            default=0.5,
            min_value=0.1,
            max_value=5.0,
        ),
    )

    # 类级别的 watcher 实例
    _watcher: ClipboardWatcher | None = None
    _last_change_callback: Callable[[str], None] | None = None

    def execute(self, **kwargs) -> ToolResult:
        """执行剪贴板操作"""
        action = kwargs.get('action', 'read')

        if action == 'read':
            return self._read()
        elif action == 'write':
            return self._write(**kwargs)
        elif action == 'watch_start':
            return self._watch_start(**kwargs)
        elif action == 'watch_stop':
            return self._watch_stop()
        elif action == 'watch_status':
            return self._watch_status()
        else:
            return ToolResult(
                success=False,
                output='',
                error=f'未知操作: {action}',
                exit_code=1,
            )

    def _get_pyperclip(self) -> Any:
        """获取 pyperclip 模块"""
        try:
            import pyperclip
            return pyperclip
        except ImportError:
            return None

    def _read(self) -> ToolResult:
        """读取剪贴板内容"""
        pyperclip = self._get_pyperclip()
        if pyperclip is None:
            return ToolResult(
                success=False,
                output='',
                error='pyperclip 未安装，请运行: pip install pyperclip',
                exit_code=1,
            )

        try:
            content = pyperclip.paste()
            return ToolResult(
                success=True,
                output=content,
                exit_code=0,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=f'读取剪贴板失败: {e}',
                exit_code=1,
            )

    def _write(self, **kwargs) -> ToolResult:
        """写入剪贴板内容"""
        text = kwargs.get('text')
        if text is None:
            return ToolResult(
                success=False,
                output='',
                error='write 操作需要 text 参数',
                exit_code=1,
            )

        pyperclip = self._get_pyperclip()
        if pyperclip is None:
            return ToolResult(
                success=False,
                output='',
                error='pyperclip 未安装，请运行: pip install pyperclip',
                exit_code=1,
            )

        try:
            pyperclip.copy(text)
            return ToolResult(
                success=True,
                output=f'已写入 {len(text)} 字符到剪贴板',
                exit_code=0,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=f'写入剪贴板失败: {e}',
                exit_code=1,
            )

    def _watch_start(self, **kwargs) -> ToolResult:
        """开始监控剪贴板"""
        interval = kwargs.get('interval', 0.5)

        if self._watcher and self._watcher.is_running:
            return ToolResult(
                success=True,
                output='剪贴板监控器已在运行',
                exit_code=0,
            )

        try:
            self._watcher = ClipboardWatcher(interval=interval, verbose=True)
            self._watcher.start()
            return ToolResult(
                success=True,
                output=f'剪贴板监控已启动（间隔 {interval}秒）',
                exit_code=0,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=f'启动监控失败: {e}',
                exit_code=1,
            )

    def _watch_stop(self) -> ToolResult:
        """停止监控剪贴板"""
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
            return ToolResult(
                success=True,
                output='剪贴板监控已停止',
                exit_code=0,
            )
        else:
            return ToolResult(
                success=True,
                output='剪贴板监控未在运行',
                exit_code=0,
            )

    def _watch_status(self) -> ToolResult:
        """获取监控状态"""
        import json

        status = {
            'running': self._watcher is not None and self._watcher.is_running,
            'last_content_length': len(self._watcher._last_clipboard) if self._watcher and self._watcher._last_clipboard else 0,
        }

        return ToolResult(
            success=True,
            output=json.dumps(status, ensure_ascii=False),
            exit_code=0,
        )

    def set_change_callback(self, callback: Callable[[str], None]) -> None:
        """设置剪贴板变化回调

        参数:
            callback: 回调函数，接收剪贴板内容
        """
        self._last_change_callback = callback
        if self._watcher:
            self._watcher._on_change = callback

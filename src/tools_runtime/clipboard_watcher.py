"""ClipboardWatcher - 剪贴板监控 — 从 Aider copypaste.py 移植

监控剪贴板变化，当检测到新内容时通知输入层更新占位符。

用法:
    watcher = ClipboardWatcher(on_clipboard_change=callback)
    watcher.start()
    # ... 用户复制内容 ...
    watcher.stop()

依赖:
    pip install pyperclip
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class ClipboardWatcher:
    """剪贴板监控器 — 检测剪贴板内容变化并触发回调

    功能:
        - 后台线程持续轮询剪贴板
        - 检测到内容变化时调用回调函数
        - 支持多行内容自动添加换行符包裹
        - 安全停止（daemon 线程 + 事件控制）
    """

    def __init__(
        self,
        on_clipboard_change: Callable[[str], None] | None = None,
        poll_interval: float = 0.5,
        verbose: bool = False,
    ) -> None:
        """初始化剪贴板监控器

        参数:
            on_clipboard_change: 剪贴板内容变化时的回调函数
            poll_interval: 轮询间隔（秒）
            verbose: 是否输出详细日志
        """
        self.on_clipboard_change = on_clipboard_change
        self.poll_interval = poll_interval
        self.verbose = verbose
        self._stop_event: threading.Event | None = None
        self._watcher_thread: threading.Thread | None = None
        self._last_clipboard: str | None = None

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return (
            self._stop_event is not None
            and not self._stop_event.is_set()
            and self._watcher_thread is not None
            and self._watcher_thread.is_alive()
        )

    def start(self) -> None:
        """启动剪贴板监控"""
        if self.is_running:
            logger.debug('ClipboardWatcher already running')
            return

        try:
            import pyperclip

            self._stop_event = threading.Event()
            self._last_clipboard = pyperclip.paste()

            def _watch() -> None:
                while not self._stop_event.is_set():  # type: ignore[union-attr]
                    try:
                        current = pyperclip.paste()
                        if current != self._last_clipboard:
                            self._last_clipboard = current
                            # 多行内容添加换行符包裹
                            if len(current.splitlines()) > 1:
                                formatted = '\n' + current + '\n'
                            else:
                                formatted = current

                            if self.on_clipboard_change:
                                self.on_clipboard_change(formatted)
                            if self.verbose:
                                logger.info('Clipboard changed: %d chars', len(current))

                    except Exception as e:
                        if self.verbose:
                            logger.debug('Clipboard poll error: %s', e)

                    self._stop_event.wait(self.poll_interval)  # type: ignore[union-attr]

            self._watcher_thread = threading.Thread(
                target=_watch, daemon=True, name='clipboard-watcher'
            )
            self._watcher_thread.start()
            logger.debug('ClipboardWatcher started')

        except ImportError:
            logger.warning('pyperclip not installed, clipboard watching disabled')

    def stop(self) -> None:
        """停止剪贴板监控"""
        if self._stop_event:
            self._stop_event.set()
        if self._watcher_thread and self._watcher_thread.is_alive():
            self._watcher_thread.join(timeout=2.0)
        self._watcher_thread = None
        self._stop_event = None
        logger.debug('ClipboardWatcher stopped')

    def get_last_content(self) -> str | None:
        """获取最近一次检测到的剪贴板内容"""
        return self._last_clipboard

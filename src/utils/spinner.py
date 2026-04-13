"""Spinner 等待动画工具 — 从 Aider waiting.py 移植

提供线程安全的终端等待动画，支持 ASCII 和 Unicode 两种模式。

用法:
    from src.utils.spinner import Spinner, WaitingSpinner

    # 手动控制
    spinner = Spinner("Processing...")
    while not done:
        spinner.step()
    spinner.end()

    # 上下文管理器（后台线程）
    with WaitingSpinner("Loading..."):
        result = long_operation()
"""
from __future__ import annotations

import sys
import threading
import time

from .colors import RESET as reset
from .colors import dim


class Spinner:
    """终端等待动画 — 扫描线效果

    功能:
        - Unicode/ASCII 自动检测
        - 预渲染帧动画
        - 延迟显示（0.5 秒后才出现，避免短任务闪烁）
        - 0.1 秒刷新间隔
        - 自动清屏恢复光标
    """

    last_frame_idx: int = 0  # 类变量，保持全局动画连续性

    def __init__(self, text: str = '', width: int = 7) -> None:
        self.text = text
        self.start_time = time.time()
        self.last_update = 0.0
        self.visible = False
        self.is_tty = sys.stdout.isatty()
        self.last_display_len = 0

        # 预渲染 ASCII 帧
        ascii_frames = [
            '#=        ',
            '=#        ',
            ' =#       ',
            '  =#      ',
            '   =#     ',
            '    =#    ',
            '     =#   ',
            '      =#  ',
            '       #= ',
            '        #=',
            '       #= ',
            '      #=  ',
            '     #=   ',
            '    #=    ',
            '   #=     ',
            '  #=      ',
            ' #=       ',
        ]

        self.frames = ascii_frames
        self.frame_idx = Spinner.last_frame_idx

    @property
    def terminal_width(self) -> int:
        try:
            return sys.stdout.columns() if hasattr(sys.stdout, 'columns') else 80
        except Exception:
            return 80

    def _next_frame(self) -> str:
        frame = self.frames[self.frame_idx]
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)
        Spinner.last_frame_idx = self.frame_idx
        return frame

    def step(self, text: str | None = None) -> None:
        """推进一帧动画"""
        if text is not None:
            self.text = text

        if not self.is_tty:
            return

        now = time.time()

        # 延迟 0.5 秒才显示
        if not self.visible and now - self.start_time >= 0.5:
            self.visible = True
            self.last_update = 0.0

        if not self.visible or now - self.last_update < 0.1:
            return

        self.last_update = now
        frame_str = self._next_frame()

        max_width = self.terminal_width - 2
        line = f'{dim}{frame_str}{reset} {self.text}'
        if len(line) > max_width:
            line = line[:max_width]

        len_line = len(line)
        padding = ' ' * max(0, self.last_display_len - len_line)
        sys.stdout.write(f'\r{line}{padding}')
        sys.stdout.flush()
        self.last_display_len = len_line

    def end(self) -> None:
        """结束动画，清屏恢复光标"""
        if self.visible and self.is_tty:
            clear = ' ' * self.last_display_len
            sys.stdout.write(f'\r{clear}\r')
            sys.stdout.flush()
        self.visible = False


class WaitingSpinner:
    """后台线程 Spinner — 可用作上下文管理器

    用法:
        with WaitingSpinner('Waiting for LLM'):
            result = llm.chat(messages)
    """

    def __init__(self, text: str = 'Waiting', delay: float = 0.15) -> None:
        self.spinner = Spinner(text)
        self.delay = delay
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True, name='spinner')

    def _spin(self) -> None:
        while not self._stop_event.is_set():
            self.spinner.step()
            self._stop_event.wait(self.delay)
        self.spinner.end()

    def start(self) -> None:
        if not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._spin, daemon=True, name='spinner')
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=self.delay)
        self.spinner.end()

    def __enter__(self) -> WaitingSpinner:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

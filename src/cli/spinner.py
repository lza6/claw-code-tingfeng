"""Waiting Spinner — 可终止的后台旋转动画（移植自 Aider waiting.py）

提供线程安全的等待动画，支持:
- ASCII/Unicode 自动检测
- 扫描线动画（aider 特色）
- 上下文管理器支持
- 线程安全的 start/stop

用法:
    from src.cli.spinner import WaitingSpinner

    spinner = WaitingSpinner("Waiting for LLM")
    spinner.start()
    ...  # 长任务
    spinner.stop()

    # 或使用上下文管理器
    with WaitingSpinner("Processing..."):
        do_something()
"""
from __future__ import annotations

import sys
import threading
import time

from rich.console import Console


class Spinner:
    """最小旋转动画 — 扫描线在括号间来回移动

    动画预渲染为帧列表。如果终端不支持 Unicode，自动降级为 ASCII。
    """

    last_frame_idx: int = 0  # 类变量，保证多个 Spinner 实例共享动画状态

    def __init__(self, text: str = "", width: int = 7) -> None:
        self.text = text
        self.start_time = time.time()
        self.last_update = 0.0
        self.visible = False
        self.is_tty = sys.stdout.isatty()
        self.console = Console()

        # 预渲染 ASCII 帧
        ascii_frames = [
            "#=        ",
            "=#        ",
            " =#       ",
            "  =#      ",
            "   =#     ",
            "    =#    ",
            "     =#   ",
            "      =#  ",
            "       =# ",
            "        =#",
            "        #=",
            "       #= ",
            "      #=  ",
            "     #=   ",
            "    #=    ",
            "   #=     ",
            "  #=      ",
            " #=       ",
        ]

        self.unicode_palette = "\u2591\u2588"  # ░█
        xlate_from, xlate_to = ("=#", self.unicode_palette)

        if self._supports_unicode():
            translation_table = str.maketrans(xlate_from, xlate_to)
            frames = [f.translate(translation_table) for f in ascii_frames]
            self.scan_char = xlate_to[xlate_from.find("#")]
        else:
            frames = ascii_frames
            self.scan_char = "#"

        self.frames = frames
        self.frame_idx = Spinner.last_frame_idx
        self.last_display_len = 0

    def _supports_unicode(self) -> bool:
        if not self.is_tty:
            return False
        try:
            out = self.unicode_palette
            out += "\b" * len(self.unicode_palette)
            out += " " * len(self.unicode_palette)
            out += "\b" * len(self.unicode_palette)
            sys.stdout.write(out)
            sys.stdout.flush()
            return True
        except (UnicodeEncodeError, Exception):
            return False

    def _next_frame(self) -> str:
        frame = self.frames[self.frame_idx]
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)
        Spinner.last_frame_idx = self.frame_idx
        return frame

    def step(self, text: str | None = None) -> None:
        """推进一帧动画

        参数:
            text: 可选的新文本
        """
        if text is not None:
            self.text = text

        if not self.is_tty:
            return

        now = time.time()
        if not self.visible and now - self.start_time >= 0.5:
            self.visible = True
            self.last_update = 0.0
            if self.is_tty:
                self.console.show_cursor(False)

        if not self.visible or now - self.last_update < 0.1:
            return

        self.last_update = now
        frame_str = self._next_frame()

        max_spinner_width = self.console.width - 2
        if max_spinner_width < 0:
            max_spinner_width = 0

        current_text_payload = f" {self.text}"
        line_to_display = f"{frame_str}{current_text_payload}"

        if len(line_to_display) > max_spinner_width:
            line_to_display = line_to_display[:max_spinner_width]

        len_line_to_display = len(line_to_display)
        padding_to_clear = " " * max(0, self.last_display_len - len_line_to_display)

        sys.stdout.write(f"\r{line_to_display}{padding_to_clear}")
        self.last_display_len = len_line_to_display

        scan_char_abs_pos = frame_str.find(self.scan_char)
        total_chars_written_on_line = len_line_to_display + len(padding_to_clear)
        num_backspaces = total_chars_written_on_line - scan_char_abs_pos
        sys.stdout.write("\b" * max(0, num_backspaces))
        sys.stdout.flush()

    def end(self) -> None:
        """结束动画，清理显示"""
        if self.visible and self.is_tty:
            clear_len = self.last_display_len
            sys.stdout.write("\r" + " " * clear_len + "\r")
            sys.stdout.flush()
            self.console.show_cursor(True)
        self.visible = False


class WaitingSpinner:
    """后台旋转动画 — 线程安全，支持 start/stop 和上下文管理器

    用法:
        with WaitingSpinner("Loading..."):
            load_data()
    """

    def __init__(self, text: str = "Waiting for LLM", delay: float = 0.15) -> None:
        self.spinner = Spinner(text)
        self.delay = delay
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self) -> None:
        while not self._stop_event.is_set():
            self.spinner.step()
            time.sleep(self.delay)
        self.spinner.end()

    def start(self) -> None:
        """启动后台动画"""
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        """停止后台动画"""
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=self.delay)
        self.spinner.end()

    def __enter__(self) -> WaitingSpinner:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

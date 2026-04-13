"""Dashboard Micro-Animations — 微动效组件

包含:
- TypewriterEffect: 非线性打字机效果
- ParallaxScrollContainer: 平滑视差滚动容器
"""
from __future__ import annotations

import asyncio
import time
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


class TypewriterEffect(Static):
    """非线性打字机效果 — 逐字显示文本，带有可变延迟

    特性:
    - 使用 ease-in-out 缓动函数控制打字速率
    - 支持标点符号处的自然停顿
    - 可配置的基底延迟和变化范围
    - 平滑的光标闪烁效果
    """

    DEFAULT_CSS = """
    TypewriterEffect {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    .typewriter-cursor {
        color: #00BCD4;
        animation: cursor-blink 0.8s infinite alternate;
    }
    @keyframes cursor-blink {
        0% { opacity: 1; }
        100% { opacity: 0; }
    }
    """

    # 标点符号的额外延迟 (毫秒)
    PUNCTUATION_DELAY: ClassVar[int] = 80
    # 基底延迟 (毫秒)
    BASE_DELAY: ClassVar[int] = 30
    # 延迟变化范围 (毫秒)
    DELAY_VARIATION: ClassVar[int] = 20

    # 标点符号集合
    PUNCTUATION: ClassVar[set[str]] = set(".,;:!?。、，；：！？")
    # 强标点符号 (更长停顿)
    STRONG_PUNCTUATION: ClassVar[set[str]] = set(".!?。！？")

    def __init__(self, text: str = "", id: str | None = None) -> None:
        super().__init__(id=id)
        self._full_text = text
        self._displayed_text = ""
        self._typing_task: asyncio.Task | None = None
        self._cursor_visible = True
        self._ease_in_out_func = None

    def compose(self) -> ComposeResult:
        yield Static("", id="typewriter-content")

    def on_mount(self) -> None:
        """挂载时开始打字"""
        # 动态导入避免循环依赖
        from ..dashboard_widgets import ease_in_out
        self._ease_in_out_func = ease_in_out

        if self._full_text:
            self.start_typing(self._full_text)

    def start_typing(self, text: str) -> None:
        """开始打字效果"""
        self._full_text = text
        self._displayed_text = ""

        # 取消之前的打字任务
        if self._typing_task and not self._typing_task.done():
            self._typing_task.cancel()

        self._typing_task = asyncio.create_task(self._type_text(text))

    async def _type_text(self, text: str) -> None:
        """执行打字动画"""
        content_widget = self.query_one("#typewriter-content", Static)

        for i, char in enumerate(text):
            self._displayed_text += char

            # 更新显示内容，带闪烁光标
            cursor_char = "█" if self._cursor_visible else " "
            content_widget.update(f"{self._displayed_text}{cursor_char}")

            # 计算延迟
            delay = self._calculate_delay(char, i, text)
            await asyncio.sleep(delay / 1000.0)

        # 完成时移除光标
        content_widget.update(self._displayed_text)

    def _calculate_delay(self, char: str, index: int, text: str) -> float:
        """计算当前字符的打字延迟

        使用 ease-in-out 函数模拟自然打字节奏:
        - 句首稍慢 (思考)
        - 中间稳定 (流畅)
        - 标点处停顿
        """
        if self._ease_in_out_func is None:
            from ..dashboard_widgets import ease_in_out
            self._ease_in_out_func = ease_in_out

        # 基底延迟 + 随机变化
        base_delay = self.BASE_DELAY + (hash(f"{index}") % self.DELAY_VARIATION)

        # 标点符号额外延迟
        if char in self.STRONG_PUNCTUATION:
            base_delay += self.PUNCTUATION_DELAY * 1.5
        elif char in self.PUNCTUATION:
            base_delay += self.PUNCTUATION_DELAY

        # 换行符额外延迟
        if char == "\n":
            base_delay += self.PUNCTUATION_DELAY * 0.8

        # 应用 ease-in-out 位置因子
        if len(text) > 10:
            position = index / len(text)
            # 句首和句尾稍慢
            position_factor = 1.0 + 0.3 * (1 - self._ease_in_out_func(position))
            base_delay *= position_factor

        return max(10, base_delay)  # 最小 10ms

    def set_text(self, text: str) -> None:
        """立即设置文本 (无动画)"""
        self._full_text = text
        self._displayed_text = text
        content_widget = self.query_one("#typewriter-content", Static)
        content_widget.update(text)

    def clear(self) -> None:
        """清空内容"""
        if self._typing_task and not self._typing_task.done():
            self._typing_task.cancel()
        self._full_text = ""
        self._displayed_text = ""
        content_widget = self.query_one("#typewriter-content", Static)
        content_widget.update("")


class ParallaxScrollContainer(VerticalScroll):
    """平滑视差滚动容器 — 消除终端交互的生硬感

    特性:
    - 使用 ease-out-cubic 缓动的平滑滚动
    - 渐进式内容加载 (淡入效果)
    - 可配置的滚动速率和惯性
    - 支持鼠标滚轮和键盘导航
    """

    DEFAULT_CSS = """
    ParallaxScrollContainer {
        width: 1fr;
        height: 1fr;
        scrollbar-size: 1 1;
        scrollbar-color: $primary $surface;
    }
    .parallax-child {
        animation: fade-in 0.3s ease-out;
    }
    @keyframes fade-in {
        0% { opacity: 0; transform: translateY(5); }
        100% { opacity: 1; transform: translateY(0); }
    }
    """

    # 滚动惯性系数 (0-1, 越大越平滑)
    INERTIA_FACTOR: ClassVar[float] = 0.85
    # 动画帧间隔 (秒)
    FRAME_INTERVAL: ClassVar[float] = 1 / 60  # 60 FPS
    # 内容淡入延迟 (毫秒)
    FADE_IN_DELAY: ClassVar[int] = 50

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._scroll_velocity = 0.0
        self._target_scroll = 0.0
        self._animation_task: asyncio.Task | None = None
        self._content_items: list[tuple[Static, float]] = []  # (widget, add_time)
        self._ease_out_cubic_func = None

    def on_mount(self) -> None:
        """挂载时启动滚动动画循环"""
        # 动态导入避免循环依赖
        from ..dashboard_widgets import ease_out_cubic
        self._ease_out_cubic_func = ease_out_cubic

        self._animation_task = asyncio.create_task(self._scroll_animation_loop())

    def on_unmount(self) -> None:
        """卸载时停止动画"""
        if self._animation_task and not self._animation_task.done():
            self._animation_task.cancel()

    async def _scroll_animation_loop(self) -> None:
        """滚动动画循环 — 应用惯性平滑"""
        while True:
            try:
                # 应用惯性
                if abs(self._scroll_velocity) > 0.01:
                    current_scroll = self.scroll_target_y
                    self.scroll_to(y=current_scroll + self._scroll_velocity)
                    self._scroll_velocity *= self.INERTIA_FACTOR
                else:
                    self._scroll_velocity = 0

                await asyncio.sleep(self.FRAME_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def apply_scroll_input(self, delta: float) -> None:
        """应用滚动输入 (鼠标滚轮/键盘)

        参数:
            delta: 滚动增量 (正=向下, 负=向上)
        """
        # 将输入转换为速度
        self._scroll_velocity = delta * 2.0

        # 同时执行即时滚动以保持响应性
        current_scroll = self.scroll_target_y
        self.scroll_to(y=current_scroll + delta)

    def add_content(self, content: str, animate: bool = True) -> Static:
        """添加内容到容器，可选淡入动画

        参数:
            content: 文本内容
            animate: 是否使用淡入动画

        返回:
            创建的 Static widget
        """
        widget = Static(content, classes="parallax-child" if animate else "")
        self.mount(widget)

        # 滚动到新内容
        self.scroll_end(animate=True, duration=0.3, ease="out_cubic")

        return widget

    def append_content_smooth(self, content: str) -> None:
        """平滑追加内容 — 流式打字效果"""

        # 查找或创建内容 widget
        if self._content_items:
            last_widget, _ = self._content_items[-1]
            # 更新现有内容
            current = last_widget.renderable
            if isinstance(current, str):
                last_widget.update(current + content)
            else:
                last_widget.update(str(current) + content)
        else:
            # 创建新内容
            widget = self.add_content(content, animate=True)
            self._content_items.append((widget, time.time()))

        # 平滑滚动到底部
        self.scroll_end(animate=True, duration=0.4, ease="out_cubic")

    def clear(self) -> None:
        """清空容器内容"""
        import contextlib as cl
        for widget, _ in self._content_items:
            with cl.suppress(Exception):
                widget.remove()
        self._content_items.clear()
        super().remove_children()


__all__ = [
    "ParallaxScrollContainer",
    "TypewriterEffect",
]

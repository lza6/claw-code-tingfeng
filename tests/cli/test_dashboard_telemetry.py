"""dashboard_widgets.telemetry 模块测试 — 遥测面板与进度条

覆盖:
- TelemetryPanel: 指标配置、Delta 更新（值变化才刷新）、格式化分支、RAG 指标
- AnimatedProgressBar: 初始化 / compose / on_mount / 进度钳制 / 动画循环 / pulse

已知 src 缺陷（用例内以断言固定当前行为，报告中记录）:
- ``TelemetryPanel.compose`` 在子 widget 未挂载时调用 ``row.query_one(...)``
  （telemetry.py:105 / :119），抛 ``NoMatches``，组件无法挂载。
- ``TelemetryPanel.DEFAULT_CSS`` 的 ``border-bottom: thin $accent``（telemetry.py:63）
  与 ``transition``（telemetry.py:47）不是合法 Textual 值/属性。
- ``set_progress``（telemetry.py:265）与 ``pulse``（telemetry.py:312）直接调用协程
  但未 await / 未 create_task，动画永不执行，``_animating`` 永久为 True。
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from src.cli.dashboard_widgets.telemetry import AnimatedProgressBar, TelemetryPanel
from textual.app import App
from textual.css.query import NoMatches
from textual.widgets import Label

# ====================================================================
# 测试脚手架
# ====================================================================

class _CssSafeTelemetryPanel(TelemetryPanel, inherit_css=False):
    """绕开非法 CSS（telemetry.py:47/63）并跳过致命 compose（telemetry.py:105）的派生类

    只用于验证 ``_update_metric_value`` 在“有 app 上下文”时的行为。
    """

    DEFAULT_CSS = ""

    def compose(self):
        return
        yield  # pragma: no cover


class _Host(App):
    def __init__(self, *widgets) -> None:
        super().__init__()
        self._widgets = widgets

    def compose(self):
        yield from self._widgets


def _plain(widget) -> str:
    rendered = widget.render()
    return str(getattr(rendered, "plain", rendered))


def _panel_with_labels(*keys: str) -> tuple[TelemetryPanel, dict[str, MagicMock]]:
    """构造未挂载的面板并注入可断言的 label 桩"""
    panel = TelemetryPanel()
    labels = {key: MagicMock(name=key) for key in keys}
    panel._value_labels.update(labels)
    return panel, labels


# ====================================================================
# TelemetryPanel — 配置与初始化
# ====================================================================

class TestTelemetryPanelConfig:

    def test_llm_metric_definitions(self):
        assert [m[0] for m in TelemetryPanel.LLM_METRICS] == [
            "total_tokens",
            "total_cost",
            "llm_calls",
            "cache_read_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "avg_latency_ms",
        ]
        assert {m[0] for m in TelemetryPanel.LLM_METRICS if m[2]} == {"total_tokens", "total_cost"}

    def test_rag_metric_definitions(self):
        assert [m[0] for m in TelemetryPanel.RAG_METRICS] == [
            "indexed_files",
            "total_terms",
            "coverage_percent",
        ]
        assert [m[2] for m in TelemetryPanel.RAG_METRICS] == [False, False, True]

    def test_init_state_is_all_defaults(self):
        panel = TelemetryPanel()

        assert panel._telemetry.total_tokens == 0
        assert panel._telemetry.total_cost == 0.0
        assert panel._telemetry.llm_calls == 0
        assert panel._rag_metrics.indexed_files == 0
        assert panel._rag_metrics.coverage_percent == 0.0
        assert panel._value_labels == {}

    def test_compose_raises_nomatches_before_mount(self):
        """缺陷记录: compose 内 query_one 查询尚未挂载的子节点（telemetry.py:105）"""
        panel = TelemetryPanel()

        with pytest.raises(NoMatches, match="metric-value-total_tokens"):
            list(panel.compose())


# ====================================================================
# TelemetryPanel — Delta 更新
# ====================================================================

class TestTelemetryPanelUpdate:

    def test_update_telemetry_stores_values(self):
        panel, _ = _panel_with_labels()

        panel.update_telemetry(total_tokens=1200, total_cost=0.25, llm_calls=3)

        assert panel._telemetry.total_tokens == 1200
        assert panel._telemetry.total_cost == 0.25
        assert panel._telemetry.llm_calls == 3

    def test_changed_value_updates_its_label(self):
        panel, labels = _panel_with_labels("total_cost")

        panel.update_telemetry(total_cost=1.23456)

        labels["total_cost"].update.assert_called_once_with("$1.2346")
        labels["total_cost"].add_class.assert_called_once_with("updated")

    def test_unchanged_value_skips_label_refresh(self):
        """默认 total_tokens 为 0，再写 0 属于无变化，不应触发重绘"""
        panel, labels = _panel_with_labels("total_tokens")

        panel.update_telemetry(total_tokens=0)

        labels["total_tokens"].update.assert_not_called()

    def test_key_without_label_still_updates_model(self):
        panel, labels = _panel_with_labels("total_tokens")

        panel.update_telemetry(llm_calls=7, tool_calls=2)

        assert panel._telemetry.llm_calls == 7
        assert panel._telemetry.tool_calls == 2
        labels["total_tokens"].update.assert_not_called()

    def test_update_rag_metrics_stores_and_formats(self):
        panel, labels = _panel_with_labels("indexed_files", "coverage_percent")

        panel.update_rag_metrics(indexed_files=12, coverage_percent=93.456)

        assert panel._rag_metrics.indexed_files == 12
        labels["indexed_files"].update.assert_called_once_with("12")
        labels["coverage_percent"].update.assert_called_once_with("93.5%")

    def test_update_rag_metrics_unchanged_skips_refresh(self):
        panel, labels = _panel_with_labels("indexed_files")

        panel.update_rag_metrics(indexed_files=0)

        labels["indexed_files"].update.assert_not_called()

    @pytest.mark.parametrize(
        ("key", "value", "expected"),
        [
            ("total_tokens", 1234567, "1,234,567"),
            ("cache_read_tokens", 42, "42"),
            ("cache_write_tokens", 7, "7"),
            ("reasoning_tokens", 1000, "1,000"),
            ("indexed_files", 12, "12"),
            ("total_terms", 5000, "5,000"),
            ("total_cost", 0.5, "$0.5000"),
            ("avg_latency_ms", 45.6, "46ms"),
            ("avg_latency_ms", 0.0, "0ms"),
            ("coverage_percent", 93.456, "93.5%"),
            ("llm_calls", 9, "9"),
        ],
    )
    def test_metric_value_formatting_table(self, key, value, expected):
        panel, labels = _panel_with_labels(key)

        panel._update_metric_value(key, value)

        assert labels[key].update.call_args.args == (expected,)

    def test_unknown_key_is_ignored(self):
        panel, _ = _panel_with_labels("total_tokens")

        panel._update_metric_value("no_such_metric", 1)  # 不应抛出

    def test_without_app_value_updates_but_class_stays(self):
        """无 app 上下文时 ``self.app`` 抛 NoActiveAppError，被宽 except 吞掉

        telemetry.py:177-180: 值已写入、class 已添加，但移除高亮的回调永远不会注册。
        """
        panel, labels = _panel_with_labels("total_cost")
        labels["total_cost"].update = MagicMock()
        labels["total_cost"].add_class = MagicMock()
        label = Label("init")
        panel._value_labels["total_cost"] = label

        panel._update_metric_value("total_cost", 2.5)

        assert _plain(label) == "$2.5000"
        assert "updated" in label.classes

    async def test_with_app_highlight_is_removed_later(self):
        panel = _CssSafeTelemetryPanel(id="tp")
        async with _Host(panel).run_test() as pilot:
            await pilot.pause()
            label = Label("init")
            panel._value_labels["total_cost"] = label

            panel._update_metric_value("total_cost", 3.25)
            assert "updated" in label.classes

            await pilot.pause()
            await asyncio.sleep(0.05)

            assert _plain(label) == "$3.2500"
            assert "updated" not in label.classes


# ====================================================================
# AnimatedProgressBar — 配置与生命周期
# ====================================================================

class TestAnimatedProgressBarLifecycle:

    def test_init_defaults(self):
        bar = AnimatedProgressBar()

        assert (bar._total, bar._current, bar._target) == (100.0, 0.0, 0.0)
        assert bar._show_percentage is True
        assert bar._animating is False
        assert bar._progress_bar is None
        assert bar._progress_label is None
        assert bar._progress_bar_id == "progress-bar-widget"

    def test_init_with_custom_id_total_and_no_percentage(self):
        bar = AnimatedProgressBar(total=10.0, show_percentage=False, id="bar")

        assert bar._total == 10.0
        assert bar._progress_bar_id == "progress-bar"
        assert bar._show_percentage is False

    def test_compose_yields_bar_and_percentage_labels(self):
        bar = AnimatedProgressBar(id="bar")

        labels = list(bar.compose())

        assert [label.id for label in labels] == ["progress-bar", "progress-label"]

    def test_compose_skips_percentage_label_when_disabled(self):
        bar = AnimatedProgressBar(show_percentage=False, id="bar")

        labels = list(bar.compose())

        assert [label.id for label in labels] == ["progress-bar"]

    async def test_on_mount_wires_labels_and_renders_zero(self):
        bar = AnimatedProgressBar(id="bar")
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()

            assert bar._progress_bar is not None
            assert bar._progress_label is not None
            assert _plain(bar._progress_bar) == "░" * 30 + " 0%"
            assert _plain(bar._progress_label) == "0.0%"

    async def test_on_mount_without_percentage_label(self):
        bar = AnimatedProgressBar(show_percentage=False, id="bar")
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()

            assert bar._progress_bar is not None
            assert bar._progress_label is None
            bar.set_progress(100, animate=False)
            assert _plain(bar._progress_bar) == "█" * 30 + " 100%"


# ====================================================================
# AnimatedProgressBar — 进度设置
# ====================================================================

class TestAnimatedProgressBarSetProgress:

    async def test_set_progress_without_animation_fills_bar(self):
        bar = AnimatedProgressBar(id="bar")
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()

            bar.set_progress(50, animate=False)

            assert bar._current == 50.0
            assert _plain(bar._progress_bar) == "█" * 15 + "░" * 15 + " 50%"
            assert _plain(bar._progress_label) == "50.0%"

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [(-20, 0.0), (0, 0.0), (33, 33.0), (100, 100.0), (250, 100.0)],
    )
    async def test_set_progress_clamps_to_total_bounds(self, requested, expected):
        bar = AnimatedProgressBar(id="bar")
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()

            bar.set_progress(requested, animate=False)

            assert bar._current == expected

    async def test_set_progress_respects_custom_total(self):
        bar = AnimatedProgressBar(total=10.0, id="bar")
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()

            bar.set_progress(5, animate=False)
            assert _plain(bar._progress_label) == "50.0%"

            bar.set_progress(50, animate=False)
            assert bar._current == 10.0
            assert _plain(bar._progress_label) == "100.0%"

    async def test_set_progress_while_animating_jumps_immediately(self):
        bar = AnimatedProgressBar(id="bar")
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()
            bar._animating = True

            bar.set_progress(30)  # animate 默认 True，但已在动画中 → 直接跳到目标

            assert bar._current == 30.0
            assert bar._animating is True

    def test_update_progress_bar_without_widget_is_noop(self):
        bar = AnimatedProgressBar()

        bar._update_progress_bar(50.0)  # 未挂载 → 直接返回，不应抛出

        assert bar._progress_bar is None


# ====================================================================
# AnimatedProgressBar — 动画（含缺陷记录）
# ====================================================================

class TestAnimatedProgressBarAnimation:

    async def test_set_progress_with_animation_never_advances(self):
        """缺陷记录: set_progress 丢弃动画协程（telemetry.py:265），进度条卡在 0%

        ``self._run_animation()`` 既没有 await 也没有 create_task，
        结果是 RuntimeWarning: coroutine ... was never awaited，且 ``_animating``
        永久为 True —— 后续所有 ``set_progress(animate=True)`` 都被短路成瞬时跳变。
        """
        bar = AnimatedProgressBar(id="bar")
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()

            with pytest.warns(RuntimeWarning, match="_run_animation"):
                bar.set_progress(100)

            assert bar._animating is True
            await asyncio.sleep(0.1)
            assert bar._current == 0.0
            assert _plain(bar._progress_bar) == "░" * 30 + " 0%"

    async def test_run_animation_advances_to_target_and_stops(self):
        """直接驱动动画协程（真实动画逻辑本身是正确的）"""
        bar = AnimatedProgressBar(id="bar")
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()
            bar._target = 100.0
            bar._animating = True

            await bar._run_animation()

            assert bar._animating is False
            assert bar._current == 100.0
            assert _plain(bar._progress_bar) == "█" * 30 + " 100%"
            assert _plain(bar._progress_label) == "100.0%"

    async def test_run_animation_interpolates_intermediate_frames(self):
        bar = AnimatedProgressBar(id="bar")
        recorded: list[float] = []
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()
            bar._update_progress_bar = recorded.append
            bar._current = 0.0
            bar._target = 100.0
            bar._animating = True
            bar.ANIMATION_DURATION = 0.02

            await bar._run_animation()

            assert len(recorded) > 1
            assert recorded[0] < recorded[-1] == 100.0
            assert all(0.0 <= value <= 100.0 for value in recorded)

    async def test_pulse_loop_oscillates_within_bounds(self):
        bar = AnimatedProgressBar(id="bar")
        recorded: list[float] = []
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()
            bar._update_progress_bar = recorded.append
            bar._animating = True

            task = asyncio.create_task(bar._pulse_animation())
            await asyncio.sleep(0.25)
            bar._animating = False
            await task

            assert len(recorded) >= 2
            assert all(0.0 <= value <= 100.0 for value in recorded)
            # 起点 50 递增 2 → 前几帧严格递增
            assert recorded[1] - recorded[0] == pytest.approx(2.0, abs=0.5)

    async def test_pulse_discards_its_coroutine(self):
        """缺陷记录: pulse 丢弃协程（telemetry.py:312），脉冲动画永远不会运行"""
        bar = AnimatedProgressBar(id="bar")
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()

            with pytest.warns(RuntimeWarning, match="_pulse_animation"):
                bar.pulse()

            assert bar._animating is True

    async def test_pulse_is_ignored_while_animating(self):
        bar = AnimatedProgressBar(id="bar")
        async with _Host(bar).run_test() as pilot:
            await pilot.pause()
            bar._animating = True

            bar.pulse()  # 已在动画中 → 直接返回，不再创建协程（不产生警告）

            assert bar._animating is True

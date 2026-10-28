"""dashboard.thinking 模块测试 — Textual 思维画布组件

覆盖:
- ReasoningChain: 步骤行渲染 / 长文本截断 / 状态与置信度更新 / 挂载失败容错
- ExecutionTree: Unicode 树前缀 / 步骤排序 / 40 字截断 / >50 步虚拟化
- ResourceMonitorChart: 指标行渲染 / 零值序列跳过 / 历史裁剪 / sparkline 边界
- ThinkingCanvas: 推理链 + 执行树 + 资源图三联联动

已知 src 缺陷（测试用 ``inherit_css=False`` 的子类绕开，缺陷本身在报告中记录）:
- ``ExecutionTree.DEFAULT_CSS`` 与 ``ResourceMonitorChart.DEFAULT_CSS`` 含
  ``font-family: monospace``（thinking.py:135 / :245），Textual 不支持该属性，
  原类挂载即 ``StylesheetParseError``。
- ``ThinkingCanvas.DEFAULT_CSS`` 含 ``title: "..."``（thinking.py:372/377/382），
  同样非法。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import src.cli.dashboard.thinking as thinking_module
from src.cli.dashboard.thinking import (
    ExecutionTree,
    ReasoningChain,
    ResourceMonitorChart,
    ThinkingCanvas,
)
from src.cli.dashboard_widgets.models import ReasoningStep
from textual.app import App

# ====================================================================
# 测试脚手架
# ====================================================================

class _CssSafeExecutionTree(ExecutionTree, inherit_css=False):
    """绕开非法 ``font-family``（thinking.py:135）的派生类，其余行为完全继承"""

    DEFAULT_CSS = ""


class _CssSafeResourceMonitorChart(ResourceMonitorChart, inherit_css=False):
    """绕开非法 ``font-family``（thinking.py:245）的派生类"""

    DEFAULT_CSS = ""


class _CssSafeThinkingCanvas(ThinkingCanvas, inherit_css=False):
    """绕开非法 ``title``（thinking.py:372+）的派生类"""

    DEFAULT_CSS = ""


class _Host(App):
    """只挂载单个组件的宿主机 App"""

    def __init__(self, widget) -> None:
        super().__init__()
        self._widget = widget

    def compose(self):
        yield self._widget


def _plain(widget) -> str:
    """取 widget 渲染后的纯文本（剥掉 Rich/Textual 标记）"""
    rendered = widget.render()
    return str(getattr(rendered, "plain", rendered))


def _step(step_id: int, **kwargs) -> ReasoningStep:
    kwargs.setdefault("thought", "analyze")
    return ReasoningStep(step_id=step_id, **kwargs)


# ====================================================================
# ReasoningChain
# ====================================================================

class TestReasoningChainRendering:
    """推理链行渲染"""

    async def test_add_step_mounts_one_row_with_thought_and_confidence(self):
        # Arrange
        chain = ReasoningChain(id="chain")

        # Act
        async with _Host(chain).run_test() as pilot:
            await pilot.pause()
            chain.add_step(_step(1, thought="read the config", confidence=0.87, status="running"))
            await pilot.pause()

            # Assert
            assert len(chain.children) == 1
            row = chain.children[0]
            assert _plain(row.children[0]) == "◉ Step 1: read the config"
            assert _plain(row.children[1]) == "87%"
            assert "step-running" in row.children[0].classes

    async def test_tool_name_is_swallowed_by_rich_markup(self):
        """缺陷记录: 工具名被方括号包裹，Label 默认 markup=True 把它当成 Rich 标记

        thinking.py:83（创建）与 thinking.py:105（更新）使用
        ``f" [{step.tool_name}]"``，``[grep]`` 被当作样式标签解析后从纯文本中消失，
        因此终端上看不到工具名。
        """
        chain = ReasoningChain(id="chain")

        async with _Host(chain).run_test() as pilot:
            await pilot.pause()
            chain.add_step(_step(1, thought="read", tool_name="grep", status="running"))
            await pilot.pause()

            rendered = _plain(chain.children[0].children[0])
            assert rendered.rstrip() == "◉ Step 1: read"
            assert "grep" not in rendered

    async def test_long_thought_is_truncated_to_60_chars_with_ellipsis(self):
        # Arrange
        chain = ReasoningChain(id="chain")

        async with _Host(chain).run_test() as pilot:
            await pilot.pause()

            # Act
            chain.add_step(_step(1, thought="x" * 70, status="pending"))
            await pilot.pause()

            # Assert
            assert _plain(chain.children[0].children[0]) == f"○ Step 1: {'x' * 60}..."

    async def test_step_without_tool_omits_tool_suffix(self):
        chain = ReasoningChain(id="chain")
        async with _Host(chain).run_test() as pilot:
            await pilot.pause()

            chain.add_step(_step(2, thought="think", tool_name="", status="pending"))
            await pilot.pause()

            assert _plain(chain.children[0].children[0]) == "○ Step 2: think"

    @pytest.mark.parametrize(
        ("status", "icon"),
        [("pending", "○"), ("running", "◉"), ("success", "✓"), ("error", "✗"), ("unknown", "·")],
    )
    async def test_status_maps_to_icon_and_css_class(self, status, icon):
        # Arrange
        chain = ReasoningChain(id="chain")

        # Act
        async with _Host(chain).run_test() as pilot:
            await pilot.pause()
            chain.add_step(_step(7, thought="t", status=status))
            await pilot.pause()
            row = chain._step_widgets[7]

            # Assert
            assert _plain(row.children[0]) == f"{icon} Step 7: t"
            assert f"step-{status}" in row.children[0].classes

    def test_add_step_without_app_still_records_state(self):
        """未挂载时 mount 失败被吞掉，但数据模型必须一致"""
        chain = ReasoningChain()

        chain.add_step(_step(3, thought="orphan"))

        assert len(chain._steps) == 1
        assert chain._steps[0].step_id == 3
        assert 3 in chain._step_widgets
        assert list(chain.children) == []


class TestReasoningChainUpdate:
    """推理链状态更新"""

    async def test_update_step_rewrites_labels_and_swaps_css_class(self):
        """更新时状态类挂在 row 上，而创建时挂在 label 上（缺陷，见下）"""
        chain = ReasoningChain(id="chain")
        async with _Host(chain).run_test() as pilot:
            await pilot.pause()
            chain.add_step(_step(1, thought="analyze", confidence=0.5, status="running"))
            await pilot.pause()
            row = chain.children[0]
            label = row.children[0]

            # Act
            chain.update_step(1, "success", 0.99)
            await pilot.pause()

            # Assert
            assert chain._steps[0].status == "success"
            assert chain._steps[0].confidence == 0.99
            assert _plain(label) == "✓ Step 1: analyze"
            assert _plain(row.children[1]) == "99%"
            # 缺陷: thinking.py:97 把新状态类加到 row，而 thinking.py:83 把旧状态类留在 label，
            # 导致 label 上的颜色类永远是创建时的旧状态
            assert "step-success" in row.classes
            assert "step-running" in label.classes
            assert "step-success" not in label.classes

    async def test_update_step_without_confidence_keeps_previous_value(self):
        chain = ReasoningChain(id="chain")
        async with _Host(chain).run_test() as pilot:
            await pilot.pause()
            chain.add_step(_step(1, thought="t", confidence=0.42, status="pending"))
            await pilot.pause()

            chain.update_step(1, "running")
            await pilot.pause()

            assert chain._steps[0].confidence == 0.42
            assert _plain(chain.children[0].children[1]) == "42%"

    async def test_update_unknown_step_is_noop(self):
        chain = ReasoningChain(id="chain")
        async with _Host(chain).run_test() as pilot:
            await pilot.pause()
            chain.add_step(_step(1, thought="t", confidence=0.1, status="pending"))
            await pilot.pause()

            chain.update_step(99, "success", 0.9)

            assert chain._steps[0].status == "pending"
            assert _plain(chain.children[0].children[0]) == "○ Step 1: t"

    def test_update_detached_widget_does_not_raise(self):
        """未挂载的 row（children 为空）更新时异常被吞掉，但模型状态已更新"""
        chain = ReasoningChain()
        chain.add_step(_step(1, thought="t", confidence=0.0, status="pending"))

        chain.update_step(1, "error", 0.3)  # 不应抛出

        assert chain._steps[0].status == "error"
        assert chain._steps[0].confidence == 0.3


# ====================================================================
# ExecutionTree
# ====================================================================

class TestExecutionTree:
    """执行树渲染"""

    async def test_steps_are_hidden_until_root_task_is_set(self):
        tree = _CssSafeExecutionTree(id="tree")

        async with _Host(tree).run_test() as pilot:
            await pilot.pause()

            tree.add_step(_step(1, thought="a", confidence=0.5, status="success"))
            await pilot.pause()
            assert len(tree._steps) == 1
            assert list(tree.children) == []

            tree.set_root_task("修复登录模块")
            await pilot.pause()
            assert tree._root_task == "修复登录模块"
            assert len(tree.children) == 2

    async def test_renders_root_step_and_tool_lines(self):
        tree = _CssSafeExecutionTree(id="tree")
        async with _Host(tree).run_test() as pilot:
            await pilot.pause()

            tree.set_root_task("Fix login")
            tree.add_step(_step(1, thought="analyze the problem", tool_name="grep", confidence=0.85, status="success"))
            await pilot.pause()

            lines = [_plain(child) for child in tree.children]
            assert lines == [
                "└── Task: Fix login",
                "    └── ✓ Step 1: analyze the problem (85%)",
                "    │   └── Tool: grep",
            ]

    async def test_non_last_step_uses_branch_prefixes(self):
        tree = _CssSafeExecutionTree(id="tree")
        async with _Host(tree).run_test() as pilot:
            await pilot.pause()

            tree.set_root_task("T")
            tree.add_step(_step(1, thought="first", tool_name="grep", confidence=0.5, status="running"))
            tree.add_step(_step(2, thought="second", confidence=0.0, status="pending"))
            await pilot.pause()

            lines = [_plain(child) for child in tree.children]
            assert lines[1] == "    ├── ◉ Step 1: first (50%)"
            assert lines[2] == "    │   ├── Tool: grep"
            assert lines[3] == "    └── ○ Step 2: second (0%)"

    async def test_steps_are_sorted_by_step_id(self):
        tree = _CssSafeExecutionTree(id="tree")
        async with _Host(tree).run_test() as pilot:
            await pilot.pause()

            tree.set_root_task("T")
            tree.add_step(_step(2, thought="second", status="pending"))
            tree.add_step(_step(1, thought="first", status="pending"))
            await pilot.pause()

            rendered = [_plain(child) for child in tree.children]
            assert "Step 1: first" in rendered[1]
            assert "Step 2: second" in rendered[2]

    async def test_thought_is_truncated_to_40_chars(self):
        tree = _CssSafeExecutionTree(id="tree")
        async with _Host(tree).run_test() as pilot:
            await pilot.pause()

            tree.set_root_task("T")
            tree.add_step(_step(1, thought="y" * 60, status="pending"))
            await pilot.pause()

            assert _plain(tree.children[1]) == f"    └── ○ Step 1: {'y' * 40} (0%)"

    async def test_update_step_refreshes_icon_percentage_and_class(self):
        tree = _CssSafeExecutionTree(id="tree")
        async with _Host(tree).run_test() as pilot:
            await pilot.pause()
            tree.set_root_task("T")
            tree.add_step(_step(1, thought="work", confidence=0.1, status="running"))
            await pilot.pause()

            tree.update_step(1, "error", 0.66)
            await pilot.pause()

            assert tree._steps[0].status == "error"
            assert _plain(tree.children[1]) == "    └── ✗ Step 1: work (66%)"
            assert "tree-error" in tree.children[1].classes

    async def test_update_unknown_step_still_refreshes_without_error(self):
        tree = _CssSafeExecutionTree(id="tree")
        async with _Host(tree).run_test() as pilot:
            await pilot.pause()
            tree.set_root_task("T")
            tree.add_step(_step(1, thought="work", status="pending"))
            await pilot.pause()
            before = len(tree.children)

            tree.update_step(42, "success", 0.9)
            await pilot.pause()

            assert len(tree.children) == before
            assert tree._steps[0].status == "pending"

    async def test_history_is_virtualized_to_last_50_steps(self):
        tree = _CssSafeExecutionTree(id="tree")
        async with _Host(tree).run_test() as pilot:
            await pilot.pause()
            tree.set_root_task("T")

            for i in range(1, 56):
                tree.add_step(_step(i, thought=f"step{i}", status="pending"))
            await pilot.pause()

            assert len(tree._steps) == 50
            assert tree._steps[0].step_id == 6
            assert tree._steps[-1].step_id == 55

    async def test_clearing_root_task_removes_all_children(self):
        tree = _CssSafeExecutionTree(id="tree")
        async with _Host(tree).run_test() as pilot:
            await pilot.pause()
            tree.set_root_task("T")
            tree.add_step(_step(1, thought="a", status="pending"))
            await pilot.pause()
            assert len(tree.children) == 2

            tree.set_root_task("")
            await pilot.pause()

            assert list(tree.children) == []


# ====================================================================
# ResourceMonitorChart
# ====================================================================

class TestResourceSparkline:
    """sparkline 纯函数边界"""

    def test_empty_values_render_empty_string(self):
        assert _CssSafeResourceMonitorChart()._render_sparkline([]) == ""

    def test_values_map_to_block_heights(self):
        chart = _CssSafeResourceMonitorChart()

        assert chart._render_sparkline([0.0, 0.5, 1.0]) == "▁▄█"

    def test_out_of_range_values_are_clamped(self):
        chart = _CssSafeResourceMonitorChart()

        assert chart._render_sparkline([-2.0, 5.0]) == "▁█"

    def test_renders_only_last_chart_width_values(self):
        chart = _CssSafeResourceMonitorChart()
        values = [0.0] * 60 + [1.0]

        rendered = chart._render_sparkline(values)

        assert len(rendered) == ResourceMonitorChart.CHART_WIDTH
        assert rendered == "▁" * 39 + "█"


class TestResourceMonitorChart:
    """资源指标行刷新"""

    def _metric(self, tokens_in=0, tokens_out=0, latency=0, memory=0):
        # 注意: 源码读取 tokens_input / tokens_output / latency_ms / memory_mb,
        # 而 models.ResourceMetrics 并无这些字段（见 test_real_model_mismatch 缺陷用例）
        return SimpleNamespace(
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            latency_ms=latency,
            memory_mb=memory,
        )

    async def test_add_metric_renders_one_row_per_non_zero_series(self):
        chart = _CssSafeResourceMonitorChart(id="rm")
        async with _Host(chart).run_test() as pilot:
            await pilot.pause()

            chart.add_metric(self._metric(tokens_in=10, tokens_out=20, latency=30, memory=40))
            await pilot.pause()

            assert len(chart.children) == 4
            rows = {_plain(row.children[0]): row for row in chart.children}
            assert set(rows) == {"Tokens In:", "Tokens Out:", "Latency:", "Memory:"}
            assert _plain(rows["Tokens In:"].children[1]) == "10"
            assert _plain(rows["Memory:"].children[1]) == "40"
            for row in chart.children:
                assert len(_plain(row.children[2])) == 1

    async def test_all_zero_series_are_skipped(self):
        chart = _CssSafeResourceMonitorChart(id="rm")
        async with _Host(chart).run_test() as pilot:
            await pilot.pause()

            chart.add_metric(self._metric(latency=45))
            await pilot.pause()

            assert len(chart.children) == 1
            assert _plain(chart.children[0].children[0]) == "Latency:"

    async def test_sparkline_length_tracks_metric_history(self):
        chart = _CssSafeResourceMonitorChart(id="rm")
        async with _Host(chart).run_test() as pilot:
            await pilot.pause()

            for value in (5, 10, 20):
                chart.add_metric(self._metric(tokens_in=value))
            await pilot.pause()

            row = chart.children[0]
            assert _plain(row.children[1]) == "20"  # 显示最新值
            assert _plain(row.children[2]) == "▂▄█"  # 归一化后 0.25/0.5/1.0

    def test_history_is_trimmed_to_max_40(self):
        chart = _CssSafeResourceMonitorChart()

        for value in range(45):
            chart.add_metric(self._metric(tokens_in=value))

        assert len(chart._metrics) == 40
        assert chart._metrics[-1].tokens_input == 44

    async def test_empty_chart_mounts_no_rows(self):
        chart = _CssSafeResourceMonitorChart(id="rm")
        async with _Host(chart).run_test() as pilot:
            await pilot.pause()

            chart._refresh_display()  # 无数据时提前返回，不产生任何行
            await pilot.pause()

            assert list(chart._metrics) == []
            assert list(chart.children) == []

    def test_real_resource_metrics_model_is_incompatible(self):
        """缺陷记录: 源码读取不存在字段，传入真实模型即 AttributeError

        见 ``src/cli/dashboard/thinking.py:288`` 附近（tokens_input / latency_ms /
        memory_mb 均不在 ``models.ResourceMetrics`` 上）。
        """
        from src.cli.dashboard_widgets.models import ResourceMetrics

        chart = _CssSafeResourceMonitorChart()

        with pytest.raises(AttributeError, match="tokens_input"):
            chart.add_metric(ResourceMetrics(cpu_percent=12.0, memory_percent=40.0))


# ====================================================================
# ThinkingCanvas（三组件联动）
# ====================================================================

@pytest.fixture
def css_safe_children(monkeypatch):
    """把思考画布内部的非法 CSS 子组件替换成等价的合法 CSS 派生类"""
    monkeypatch.setattr(thinking_module, "ExecutionTree", _CssSafeExecutionTree)
    monkeypatch.setattr(thinking_module, "ResourceMonitorChart", _CssSafeResourceMonitorChart)


@pytest.fixture
def canvas(css_safe_children):
    return _CssSafeThinkingCanvas(id="canvas")


class TestThinkingCanvas:
    """思维画布聚合行为"""

    async def test_composes_title_and_three_child_widgets(self, canvas):
        async with _Host(canvas).run_test() as pilot:
            await pilot.pause()

            assert _plain(canvas.query_one("#canvas-title")) == "🧠 Thinking Canvas"
            assert isinstance(canvas.query_one("#reasoning-chain"), ReasoningChain)
            assert isinstance(canvas.query_one("#execution-tree"), _CssSafeExecutionTree)
            assert isinstance(canvas.query_one("#resource-monitor"), _CssSafeResourceMonitorChart)

    async def test_add_reasoning_step_increments_id_and_syncs_both_children(self, canvas):
        async with _Host(canvas).run_test() as pilot:
            await pilot.pause()

            first = canvas.add_reasoning_step("think", tool_name="grep", confidence=0.4)
            second = canvas.add_reasoning_step("verify")
            await pilot.pause()

            reasoning = canvas.query_one("#reasoning-chain", ReasoningChain)
            tree = canvas.query_one("#execution-tree", _CssSafeExecutionTree)
            assert (first, second) == (1, 2)
            assert [s.step_id for s in reasoning._steps] == [1, 2]
            assert [s.step_id for s in tree._steps] == [1, 2]
            assert reasoning._steps[0].tool_name == "grep"
            assert reasoning._steps[1].tool_args == {}

    async def test_update_step_propagates_status_to_chain_and_tree(self, canvas):
        async with _Host(canvas).run_test() as pilot:
            await pilot.pause()
            step_id = canvas.add_reasoning_step("think", confidence=0.2)
            await pilot.pause()

            canvas.update_step(step_id, "success", 0.95)
            await pilot.pause()

            reasoning = canvas.query_one("#reasoning-chain", ReasoningChain)
            tree = canvas.query_one("#execution-tree", _CssSafeExecutionTree)
            assert reasoning._steps[0].status == "success"
            assert reasoning._steps[0].confidence == 0.95
            assert tree._steps[0].status == "success"
            assert tree._steps[0].confidence == 0.95

    async def test_set_root_task_delegates_to_tree(self, canvas):
        async with _Host(canvas).run_test() as pilot:
            await pilot.pause()

            canvas.set_root_task("重构鉴权")
            await pilot.pause()

            tree = canvas.query_one("#execution-tree", _CssSafeExecutionTree)
            assert tree._root_task == "重构鉴权"
            assert _plain(tree.children[0]) == "└── Task: 重构鉴权"

    async def test_add_resource_metric_delegates_to_monitor(self, canvas):
        async with _Host(canvas).run_test() as pilot:
            await pilot.pause()

            canvas.add_resource_metric(
                SimpleNamespace(tokens_input=3, tokens_output=4, latency_ms=5, memory_mb=6)
            )
            await pilot.pause()

            monitor = canvas.query_one("#resource-monitor", _CssSafeResourceMonitorChart)
            assert len(monitor._metrics) == 1
            assert len(monitor.children) == 4

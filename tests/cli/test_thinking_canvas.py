"""thinking_canvas 模块测试 — 思考过程可视化组件

覆盖:
- 数据模型 (RAGCitation, ExecutionStep, StepState)
- 渲染工具函数 (_conf_color_icon, _heat_bar, _render_sparkline, etc.)
- ThinkingCanvasRich (纯 Rich 独立模式)
- 状态管理
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.cli.tui.thinking_canvas import (
    RAGCitation,
    ExecutionStep,
    StepState,
    _conf_color_icon,
    _heat_bar,
    _render_sparkline,
    _step_type_color,
    _state_color,
    _weight_color_hex,
    ThinkingCanvasRich,
    STEP_ICONS,
    STATE_ICONS,
    CONF_RANGES,
    VBAR,
    HLINE,
    LJUNCT,
    LJUNCT_EXT,
    VBAR_SEP,
)


# ====================================================================
# 常量测试
# ====================================================================

class TestConstants:
    """模块常量测试"""

    def test_conf_ranges_coverage(self):
        """置信度范围应覆盖 0~1"""
        assert CONF_RANGES[0][0] == 0.8  # green
        assert CONF_RANGES[-1][0] == 0.0  # red
        assert len(CONF_RANGES) == 3

    def test_step_icons_complete(self):
        """步骤类型图标应覆盖所有类型"""
        expected_types = {"goal", "thought", "tool_call", "observation", "recovery"}
        assert set(STEP_ICONS.keys()) == expected_types

    def test_state_icons_complete(self):
        """状态图标应覆盖所有状态"""
        expected_states = {
            StepState.PENDING, StepState.RUNNING, StepState.SUCCESS,
            StepState.ERROR, StepState.RECOVERING,
        }
        assert set(STATE_ICONS.keys()) == expected_states

    def test_unicode_constants(self):
        """Unicode 常量应有正确值"""
        assert VBAR == "\u2502"    # │
        assert HLINE == "\u2500"   # ─
        assert LJUNCT == "\u2514"  # └
        assert LJUNCT_EXT.startswith(LJUNCT)


# ====================================================================
# 渲染工具函数测试
# ====================================================================

class TestRenderFunctions:
    """渲染工具函数测试"""

    def test_conf_color_icon_high(self):
        """高置信度返回绿色图标"""
        assert _conf_color_icon(0.9) == "\U0001f7e2"
        assert _conf_color_icon(1.0) == "\U0001f7e2"

    def test_conf_color_icon_medium(self):
        """中置信度返回黄色图标"""
        assert _conf_color_icon(0.6) == "\U0001f7e1"
        assert _conf_color_icon(0.79) == "\U0001f7e1"

    def test_conf_color_icon_low(self):
        """低置信度返回红色图标"""
        assert _conf_color_icon(0.1) == "\U0001f534"
        assert _conf_color_icon(0.49) == "\U0001f534"

    def test_conf_color_icon_out_of_range(self):
        """超出范围的置信度返回白色图标"""
        assert _conf_color_icon(-1.0) == "\u26aa"
        assert _conf_color_icon(2.0) == "\u26aa"

    def test_heat_bar_full(self):
        """满值热力条"""
        result = _heat_bar(1.0, width=10)
        assert result == "\u2588" * 10

    def test_heat_bar_empty(self):
        """零值热力条"""
        result = _heat_bar(0.0, width=10)
        assert result == "\u2591" * 10

    def test_heat_bar_partial(self):
        """部分热力条"""
        result = _heat_bar(0.5, width=10)
        assert result.count("\u2588") == 5
        assert result.count("\u2591") == 5

    def test_heat_bar_min_width(self):
        """最小宽度为 1"""
        result = _heat_bar(1.0, width=0)
        assert len(result) == 1

    def test_heat_bar_clamped(self):
        """热力条宽度应被限制"""
        result = _heat_bar(2.0, width=5)  # value > 1.0
        assert len(result) == 5

    def test_render_sparkline_basic(self):
        """基本 sparkline 渲染"""
        result = _render_sparkline([0.0, 0.5, 1.0], width=3)
        assert len(result) == 3
        # 值越大字符越高
        assert result[0] < result[2]

    def test_render_sparkline_empty(self):
        """空列表 sparkline"""
        result = _render_sparkline([], width=5)
        assert result == " " * 5

    def test_render_sparkline_downsample(self):
        """过多值时降采样"""
        values = [float(i) / 100 for i in range(50)]
        result = _render_sparkline(values, width=10)
        assert len(result) == 10

    def test_render_sparkline_pad_zeros(self):
        """值不足时补零"""
        result = _render_sparkline([0.5], width=5)
        assert len(result) == 5

    def test_step_type_color_known(self):
        """已知步骤类型颜色"""
        assert _step_type_color("goal") == "#00BCD4"
        assert _step_type_color("thought") == "#9D4BDB"
        assert _step_type_color("tool_call") == "#FFC107"
        assert _step_type_color("observation") == "#4CAF50"
        assert _step_type_color("recovery") == "#F44336"

    def test_step_type_color_unknown(self):
        """未知步骤类型默认颜色"""
        assert _step_type_color("unknown") == "#607D8B"

    def test_state_color_all(self):
        """所有状态颜色"""
        assert _state_color(StepState.PENDING) == "#6B7B8D"
        assert _state_color(StepState.RUNNING) == "#9D4BDB"
        assert _state_color(StepState.SUCCESS) == "#4CAF50"
        assert _state_color(StepState.ERROR) == "#F44336"
        assert _state_color(StepState.RECOVERING) == "#FF9800"

    def test_weight_color_hex(self):
        """权重颜色 HEX"""
        assert _weight_color_hex(0.9) == "#4CAF50"
        assert _weight_color_hex(0.6) == "#FFC107"
        assert _weight_color_hex(0.1) == "#F44336"


# ====================================================================
# 数据模型测试
# ====================================================================

class TestDataModels:
    """数据模型测试"""

    def test_rag_citation_defaults(self):
        """RAGCitation 默认值"""
        citation = RAGCitation(symbol_name="Test", file_path="test.py")
        assert citation.weight == 0.0
        assert citation.relation == ""
        assert citation.line == 0
        assert citation.confidence == 0.0

    def test_rag_citation_custom(self):
        """RAGCitation 自定义值"""
        citation = RAGCitation(
            symbol_name="UserService",
            file_path="src/auth.py",
            weight=0.92,
            relation="calls",
            line=42,
            confidence=0.88,
        )
        assert citation.weight == 0.92
        assert citation.relation == "calls"
        assert citation.line == 42

    def test_execution_step_defaults(self):
        """ExecutionStep 默认值"""
        step = ExecutionStep(step_type="goal", label="test")
        assert step.state == StepState.PENDING
        assert step.confidence == 0.0
        assert step.elapsed_ms == 0.0
        assert step.tool_name == ""
        assert step.rag_citations == []
        assert step.children == []
        assert step.parent_id is None
        assert step.step_id == -1

    def test_execution_step_custom(self):
        """ExecutionStep 自定义值"""
        step = ExecutionStep(
            step_type="tool_call",
            label="run test",
            detail="detail text",
            state=StepState.RUNNING,
            confidence=0.8,
            tool_name="pytest",
        )
        assert step.step_type == "tool_call"
        assert step.state == StepState.RUNNING
        assert step.confidence == 0.8
        assert step.tool_name == "pytest"

    def test_execution_step_timestamp_auto(self):
        """ExecutionStep 时间戳自动生成"""
        before = time.time()
        step = ExecutionStep(step_type="goal", label="test")
        after = time.time()
        assert before <= step.timestamp <= after

    def test_step_state_enum(self):
        """StepState 枚举值"""
        assert StepState.PENDING.value == "pending"
        assert StepState.RUNNING.value == "running"
        assert StepState.SUCCESS.value == "success"
        assert StepState.ERROR.value == "error"
        assert StepState.RECOVERING.value == "recovering"


# ====================================================================
# ThinkingCanvasRich 测试 — 生命周期
# ====================================================================

class TestThinkingCanvasRichLifecycle:
    """ThinkingCanvasRich 生命周期测试"""

    def test_init_default(self):
        """默认初始化"""
        canvas = ThinkingCanvasRich()
        assert canvas._rag_citations == []
        assert canvas._steps == {}
        assert canvas._next_id == 0
        assert canvas._live is None

    def test_init_with_console(self):
        """使用自定义 Console 初始化"""
        from rich.console import Console
        console = Console(force_terminal=True, width=80)
        canvas = ThinkingCanvasRich(console=console)
        assert canvas._console is console

    def test_start_stop(self):
        """启动和停止"""
        canvas = ThinkingCanvasRich()
        canvas.start()
        assert canvas._live is not None
        canvas.stop()
        assert canvas._live is None

    def test_stop_without_start(self):
        """未启动时停止不应报错"""
        canvas = ThinkingCanvasRich()
        canvas.stop()  # should not raise


# ====================================================================
# ThinkingCanvasRich 测试 — RAG 引用
# ====================================================================

class TestThinkingCanvasRichRAG:
    """ThinkingCanvasRich RAG 引用测试"""

    def test_push_rag_citations(self):
        """推送 RAG 引用"""
        canvas = ThinkingCanvasRich()
        citations = [
            RAGCitation(symbol_name="A", file_path="a.py", weight=0.5),
            RAGCitation(symbol_name="B", file_path="b.py", weight=0.9),
        ]
        canvas.push_rag_citations(citations)
        # 应按权重降序排列
        assert canvas._rag_citations[0].symbol_name == "B"
        assert canvas._rag_citations[1].symbol_name == "A"

    def test_push_rag_updates_sparkline(self):
        """推送 RAG 应更新 sparkline 历史"""
        canvas = ThinkingCanvasRich()
        canvas.push_rag_citations([
            RAGCitation(symbol_name="A", file_path="a.py", weight=0.5),
        ])
        assert len(canvas._spark_history) == 1
        assert canvas._spark_history[0] == 0.5

    def test_push_rag_sparkline_limit(self):
        """sparkline 历史最多保留 20 条"""
        canvas = ThinkingCanvasRich()
        for i in range(25):
            canvas.push_rag_citations([
                RAGCitation(symbol_name="A", file_path="a.py", weight=float(i) / 100),
            ])
        assert len(canvas._spark_history) == 20

    def test_push_empty_rag_citations(self):
        """推送空引用列表"""
        canvas = ThinkingCanvasRich()
        canvas.push_rag_citations([])
        assert canvas._rag_citations == []

    def test_clear_rag(self):
        """清空 RAG 数据"""
        canvas = ThinkingCanvasRich()
        canvas.push_rag_citations([
            RAGCitation(symbol_name="A", file_path="a.py", weight=0.5),
        ])
        canvas._spark_history.append(0.5)
        canvas.clear_rag()
        assert canvas._rag_citations == []
        assert canvas._spark_history == []


# ====================================================================
# ThinkingCanvasRich 测试 — 执行流步骤
# ====================================================================

class TestThinkingCanvasRichSteps:
    """ThinkingCanvasRich 执行流步骤测试"""

    def test_add_step(self):
        """添加步骤"""
        canvas = ThinkingCanvasRich()
        sid = canvas.add_step(step_type="goal", label="start")
        assert sid == 0
        assert 0 in canvas._steps
        assert canvas._steps[0].step_type == "goal"
        assert canvas._next_id == 1

    def test_add_multiple_steps(self):
        """添加多个步骤"""
        canvas = ThinkingCanvasRich()
        s0 = canvas.add_step(step_type="goal", label="g1")
        s1 = canvas.add_step(step_type="thought", label="t1")
        s2 = canvas.add_step(step_type="tool_call", label="tc1")
        assert s0 == 0
        assert s1 == 1
        assert s2 == 2

    def test_update_step(self):
        """更新步骤"""
        canvas = ThinkingCanvasRich()
        sid = canvas.add_step(step_type="goal", label="start", state=StepState.PENDING)
        result = canvas.update_step(sid, state=StepState.SUCCESS)
        assert result is True
        assert canvas._steps[sid].state == StepState.SUCCESS

    def test_update_nonexistent_step(self):
        """更新不存在的步骤返回 False"""
        canvas = ThinkingCanvasRich()
        result = canvas.update_step(999, state=StepState.SUCCESS)
        assert result is False

    def test_clear_flow(self):
        """清空执行流"""
        canvas = ThinkingCanvasRich()
        canvas.add_step(step_type="goal", label="g1")
        canvas.add_step(step_type="thought", label="t1")
        canvas.clear_flow()
        assert canvas._steps == {}
        assert canvas._next_id == 0

    def test_parent_child_relationship(self):
        """父子步骤关系"""
        canvas = ThinkingCanvasRich()
        parent_id = canvas.add_step(step_type="goal", label="parent")
        child_id = canvas.add_step(step_type="thought", label="child", parent_id=parent_id)
        assert child_id in canvas._steps[parent_id].children
        assert canvas._steps[child_id].parent_id == parent_id

    def test_parent_id_not_in_steps(self):
        """父步骤不存在时不报错"""
        canvas = ThinkingCanvasRich()
        # 父步骤尚未添加
        canvas.add_step(step_type="thought", label="orphan", parent_id=999)
        # 不应抛出异常


# ====================================================================
# ThinkingCanvasRich 测试 — 便捷方法
# ====================================================================

class TestThinkingCanvasRichConvenience:
    """ThinkingCanvasRich 便捷方法测试"""

    def test_add_thought(self):
        """添加思考节点"""
        canvas = ThinkingCanvasRich()
        sid = canvas.add_thought("analyze code", confidence=0.8, detail="reviewing")
        step = canvas._steps[sid]
        assert step.step_type == "thought"
        assert step.confidence == 0.8
        assert step.detail == "reviewing"
        assert step.state == StepState.RUNNING

    def test_add_tool_call(self):
        """添加工具调用节点"""
        canvas = ThinkingCanvasRich()
        sid = canvas.add_tool_call("run grep", tool_name="grep", confidence=0.9)
        step = canvas._steps[sid]
        assert step.step_type == "tool_call"
        assert step.tool_name == "grep"
        assert step.state == StepState.RUNNING

    def test_add_observation(self):
        """添加观察节点"""
        canvas = ThinkingCanvasRich()
        sid = canvas.add_observation("found 3 matches", confidence=0.7)
        step = canvas._steps[sid]
        assert step.step_type == "observation"
        assert step.state == StepState.SUCCESS

    def test_add_recovery(self):
        """添加恢复节点"""
        canvas = ThinkingCanvasRich()
        sid = canvas.add_recovery("retry connection", detail="connection reset")
        step = canvas._steps[sid]
        assert step.step_type == "recovery"
        assert step.state == StepState.RECOVERING
        assert step.detail == "connection reset"


# ====================================================================
# ThinkingCanvasRich 测试 — 渲染
# ====================================================================

class TestThinkingCanvasRichRendering:
    """ThinkingCanvasRich 渲染测试"""

    def test_render_rag_empty(self):
        """渲染空 RAG 数据"""
        canvas = ThinkingCanvasRich()
        panel = canvas._render_rag()
        assert panel.title is not None
        assert "RAG Heatmap" in str(panel.title)

    def test_render_rag_with_data(self):
        """渲染 RAG 数据"""
        canvas = ThinkingCanvasRich()
        canvas.push_rag_citations([
            RAGCitation(symbol_name="UserService", file_path="src/auth.py", weight=0.9, confidence=0.8),
        ])
        panel = canvas._render_rag()
        assert "UserService" in str(panel.renderable)

    def test_render_rag_with_sparkline(self):
        """渲染含 sparkline 的 RAG"""
        canvas = ThinkingCanvasRich()
        for w in [0.1, 0.5, 0.9]:
            canvas.push_rag_citations([
                RAGCitation(symbol_name="A", file_path="a.py", weight=w),
            ])
        panel = canvas._render_rag()
        assert "权重趋势" in str(panel.renderable)

    def test_render_flow_empty(self):
        """渲染空执行流"""
        canvas = ThinkingCanvasRich()
        panel = canvas._render_flow()
        assert "Execution Flow" in str(panel.title)

    def test_render_flow_with_steps(self):
        """渲染含步骤的执行流"""
        canvas = ThinkingCanvasRich()
        canvas.add_step(step_type="goal", label="Start task")
        canvas.add_step(step_type="thought", label="Analyzing", parent_id=0)
        panel = canvas._render_flow()
        content = str(panel.renderable)
        assert "Start task" in content

    def test_render_flow_with_tool(self):
        """渲染含工具调用的执行流"""
        canvas = ThinkingCanvasRich()
        canvas.add_tool_call("Run tests", tool_name="pytest")
        panel = canvas._render_flow()
        content = str(panel.renderable)
        assert "pytest" in content

    def test_render_flow_with_rag_citations(self):
        """渲染含 RAG 引用的步骤"""
        canvas = ThinkingCanvasRich()
        citations = [RAGCitation(symbol_name="MyClass", file_path="src/m.py", weight=0.8)]
        canvas.add_step(
            step_type="thought",
            label="Check ref",
            rag_citations=citations,
        )
        panel = canvas._render_flow()
        content = str(panel.renderable)
        assert "MyClass" in content

    def test_render_full_layout(self):
        """渲染完整布局"""
        canvas = ThinkingCanvasRich()
        layout = canvas._render()
        # layout.children 是 Layout 对象列表，检查 name 属性
        names = [child.name for child in layout.children]
        assert "rag" in names
        assert "flow" in names

    def test_render_flow_node_with_children(self):
        """渲染含子节点的步骤"""
        canvas = ThinkingCanvasRich()
        root = canvas.add_step(step_type="goal", label="Root")
        canvas.add_step(step_type="thought", label="Child", parent_id=root)
        canvas.add_step(step_type="tool_call", label="Grandchild", parent_id=1, tool_name="grep")

        lines = canvas._render_flow_node(canvas._steps[root], depth=0)
        assert len(lines) >= 1


# ====================================================================
# ThinkingCanvasRich 测试 — 渲染边界条件
# ====================================================================

class TestThinkingCanvasRichRenderingEdgeCases:
    """ThinkingCanvasRich 渲染边界条件测试"""

    def test_render_flow_node_with_elapsed(self):
        """渲染含耗时的步骤"""
        canvas = ThinkingCanvasRich()
        canvas.add_step(
            step_type="tool_call",
            label="Slow tool",
            tool_name="build",
            elapsed_ms=1500,
        )
        lines = canvas._render_flow()
        content = str(lines.renderable)
        assert "ms" in content

    def test_render_rag_location_without_line(self):
        """RAG 渲染无行号的位置"""
        canvas = ThinkingCanvasRich()
        canvas.push_rag_citations([
            RAGCitation(symbol_name="X", file_path="path/to/file.py", weight=0.5, line=0),
        ])
        panel = canvas._render_rag()
        content = str(panel.renderable)
        assert "file.py" in content
        assert ":0" not in content

    def test_render_rag_location_with_line(self):
        """RAG 渲染带行号的位置"""
        canvas = ThinkingCanvasRich()
        canvas.push_rag_citations([
            RAGCitation(symbol_name="X", file_path="path/to/file.py", weight=0.5, line=42),
        ])
        panel = canvas._render_rag()
        content = str(panel.renderable)
        assert "file.py:42" in content

    def test_render_flow_node_no_relation(self):
        """RAG 引用无关系字段"""
        canvas = ThinkingCanvasRich()
        canvas.push_rag_citations([
            RAGCitation(symbol_name="A", file_path="a.py", weight=0.5, relation=""),
        ])
        panel = canvas._render_rag()
        # 应正常渲染不报错
        assert panel is not None

    def test_render_multiple_citations_per_step(self):
        """步骤含多个 RAG 引用时只显示前 3 个"""
        canvas = ThinkingCanvasRich()
        citations = [
            RAGCitation(symbol_name=f"Sym{i}", file_path=f"f{i}.py", weight=0.5)
            for i in range(5)
        ]
        canvas.add_step(step_type="thought", label="ref", rag_citations=citations)
        lines = canvas._render_flow_node(canvas._steps[0], depth=0)
        # 只渲染前 3 个引用
        citation_lines = [l for l in lines if "Sym" in l]
        assert len(citation_lines) <= 3

    def test_render_flow_node_with_nonexistent_child(self):
        """子步骤 ID 不存在时跳过"""
        canvas = ThinkingCanvasRich()
        step = ExecutionStep(step_type="goal", label="root", children=[999])
        canvas._steps[0] = step
        lines = canvas._render_flow_node(step, depth=0)
        assert len(lines) >= 1


# ====================================================================
# ThinkingCanvasRich 测试 — 渲染完整流程
# ====================================================================

class TestThinkingCanvasRichFullWorkflow:
    """ThinkingCanvasRich 完整工作流测试"""

    def test_full_workflow(self):
        """完整工作流: 添加目标 -> 思考 -> 工具 -> 观察"""
        canvas = ThinkingCanvasRich()
        canvas.start()

        goal_id = canvas.add_thought("Fix bug in auth", confidence=0.9)
        tool_id = canvas.add_tool_call("grep 'auth'", tool_name="grep", parent=goal_id)
        obs_id = canvas.add_observation("Found 5 matches", parent=tool_id)

        # 验证结构
        assert canvas._steps[goal_id].step_type == "thought"
        assert canvas._steps[tool_id].step_type == "tool_call"
        assert canvas._steps[obs_id].step_type == "observation"

        # 验证父子关系
        assert tool_id in canvas._steps[goal_id].children
        assert obs_id in canvas._steps[tool_id].children

        canvas.stop()

    def test_full_workflow_with_rag(self):
        """完整工作流含 RAG"""
        canvas = ThinkingCanvasRich()
        canvas.start()

        canvas.push_rag_citations([
            RAGCitation(symbol_name="AuthService", file_path="src/auth.py", weight=0.95, confidence=0.9),
            RAGCitation(symbol_name="TokenValidator", file_path="src/validate.py", weight=0.7, confidence=0.6),
        ])

        canvas.add_thought("Review auth implementation")
        canvas.add_recovery("Retry failed request", detail="503 Service Unavailable")

        layout = canvas._render()
        assert layout is not None

        canvas.stop()

    def test_update_step_state(self):
        """更新步骤状态反映进度"""
        canvas = ThinkingCanvasRich()
        sid = canvas.add_thought("Working...")
        assert canvas._steps[sid].state == StepState.RUNNING

        canvas.update_step(sid, state=StepState.SUCCESS)
        assert canvas._steps[sid].state == StepState.SUCCESS

    def test_multiple_iterations(self):
        """多次迭代应累积正确数量的步骤"""
        canvas = ThinkingCanvasRich()
        for i in range(10):
            canvas.add_thought(f"Thought {i}")
        assert len(canvas._steps) == 10
        assert canvas._next_id == 10

"""Textual TUI Dashboard — 全屏事件驱动终端界面

功能:
- 多窗格布局: 对话区 / 任务树 / 遥测指标
- 呼吸灯效果: HSL 颜色平滑过渡 (Cyan → Deep Purple)
- 实时流式 Markdown 渲染
- 工作流步骤可视化
- Token 成本实时追踪
- 系统资源监控
- Delta Rendering: 增量渲染减少闪烁
- Micro-Animations: 非线性步进动画 (Ease-in-out)
- Error Visualization: Diff View + 信心渐变 (红→绿)
- Typewriter Effect: 非线性打字机效果 (可变延迟)
- Parallax Scrolling: 平滑视差滚动 (惯性滑动)

设计原则:
- 事件驱动架构 (非轮询)
- 响应式布局 (自适应终端大小)
- 优雅降级 (无 Textual 时回退 Rich)
- 增量渲染 (减少重绘开销)
- 平滑动画 (Ease-in-out 节奏)
- 微动效 (消除终端交互生硬感)

向后兼容性:
- 所有原有导入路径保持不变
- 组件已模块化到 src/cli/dashboard/ 子模块
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Input, Label

# 从 screens 模块导入 Omni-Glow 组件
from ..screens.omni_glow_widgets import (
    MirrorPane,
    RiskIndicator,
)
from ..screens.omni_glow_widgets import (
    ThinkingTree as ThinkingTreeWidget,
)

# 从 dashboard 模块导入组件
from .dashboard import (
    AnimatedProgressBar,
    BreathingPanel,
    ParallaxScrollContainer,
    SelfHealingPanel,
    SelfHealingStatsPanel,
    StepTracker,
    TelemetryPanel,
    TypewriterEffect,
)

# 从 dashboard_widgets 模块导入数据模型和工具

# ============================================================================
# 主 Dashboard 应用
# ============================================================================

class DashboardApp(App):
    """Textual TUI Dashboard — 全屏终端界面

    布局:
    ┌─────────────────────────────────────────────────────┐
    │  Header (模型、状态)                                │
    ├──────────────────────────┬──────────────────────────┤
    │  对话区 (Markdown)       │  侧边栏                  │
    │                          │  ├─ 步骤追踪器           │
    │                          │  ├─ 遥测面板             │
    │                          │  └─ 工具调用             │
    ├──────────────────────────┴──────────────────────────┤
    │  输入框 + 进度条                                    │
    │  Footer (快捷键)                                    │
    └─────────────────────────────────────────────────────┘
    """

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-container {
        height: 1fr;
        layout: horizontal;
    }

    #conversation-panel {
        width: 65%;
        height: 1fr;
        border: solid #00BCD4;
        padding: 0 1;
    }

    #sidebar {
        width: 35%;
        height: 1fr;
        layout: vertical;
    }

    #step-tracker-container {
        height: 40%;
        border: solid #607D8B;
        title: "Step Tracker";
    }

    #telemetry-container {
        height: 35%;
        border: solid #607D8B;
        title: "Telemetry";
    }

    #tools-container {
        height: 25%;
        border: solid #607D8B;
        title: "Active Tools";
    }

    #input-container {
        height: auto;
        padding: 0 1;
    }

    #user-input {
        width: 1fr;
    }

    #progress-container {
        height: auto;
        padding: 0 1;
    }

    .breathing {
        border: solid #00BCD4;
        animation: breathe 2s infinite alternate;
    }

    @keyframes breathe {
        0% {
            border: solid #00BCD4;
        }
        100% {
            border: solid #673AB7;
        }
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("clear", "clear", "Clear"),
        ("status", "status", "Status"),
        ("ctrl+b", "break_execution", "中断执行"),
    ]

    # 响应式状态
    current_phase: reactive[str] = reactive("idle")
    iteration: reactive[int] = reactive(0)
    max_iterations: reactive[int] = reactive(10)
    show_healing: reactive[bool] = reactive(False)
    show_thinking_tree: reactive[bool] = reactive(True)

    def watch_show_healing(self, show: bool) -> None:
        """根据是否有自愈事件动态切换侧边栏视图"""
        try:
            tracker = self.query_one("#step-tracker-container")
            healing = self.query_one("#healing-panel-container")
            healing_stats = self.query_one("#healing-stats-container")
            if show:
                tracker.display = False
                healing.display = True
                healing_stats.display = True
            else:
                tracker.display = True
                healing.display = False
                healing_stats.display = False
        except Exception:
            pass

    def watch_show_thinking_tree(self, show: bool) -> None:
        """动态显示/隐藏思维树"""
        try:
            container = self.query_one("#thinking-tree-container")
            container.display = show
        except Exception:
            pass

    def __init__(
        self,
        workdir: str | None = None,
        max_iterations: int = 10,
        engine_factory: Callable | None = None,
    ) -> None:
        super().__init__()
        self.workdir = workdir
        self.max_iterations = max_iterations
        self.engine_factory = engine_factory
        self.engine = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None

    def on_mount(self) -> None:
        """应用挂载时初始化"""
        self.title = "Clawd Code — AI 编程代理"
        self.sub_title = "Textual TUI Dashboard"
        self._setup_event_handlers()

    def _setup_event_handlers(self) -> None:
        """设置全局事件处理器"""
        from ..core.events import EventType, get_event_bus
        bus = get_event_bus()

        @bus.on(EventType.HEALING_EVENT)
        def on_healing(event):
            self.call_from_thread(self._handle_healing_event, event.data)

        @bus.on(EventType.HEALING_STATS_UPDATE)
        def on_healing_stats(event):
            self.call_from_thread(self._handle_healing_stats, event.data)

        @bus.on(EventType.RAG_INDEX_UPDATED)
        def on_rag_update(event):
            self.call_from_thread(self._handle_rag_metrics, event.data)

    def _handle_healing_event(self, data: dict) -> None:
        """处理自愈事件"""
        from .dashboard_widgets.models import HealingEvent, DiffLine
        event = HealingEvent(
            error_type=data.get('error_type', 'unknown'),
            error_message=data.get('error_message', ''),
            fix_strategy=data.get('fix_strategy', ''),
            confidence=data.get('confidence', 0.5),
            attempts=data.get('attempts', 1),
        )
        # 简单转换 fix_applied 到 DiffLine (示例逻辑)
        if 'fix_applied' in data:
            event.diff_lines = [DiffLine(type="header", content=f"Fix applied via {data['fix_applied']}")]

        self.show_healing = True
        self.query_one("#healing-panel", SelfHealingPanel).report_healing(event)

    def _handle_healing_stats(self, data: dict) -> None:
        """处理自愈统计更新"""
        self.query_one("#healing-stats", SelfHealingStatsPanel).update_stats(**data)

    def _handle_rag_metrics(self, data: dict) -> None:
        """处理 RAG 指标更新"""
        self.query_one("#telemetry-panel", TelemetryPanel).update_rag_metrics(**data)

    def compose(self) -> ComposeResult:
        """构建 UI 布局 — V5.0 Omni-Glow 增强版"""
        yield Header()

        # 主容器
        with Container(id="main-container"):
            # 左侧: 对话区 (带平滑视差滚动)
            with BreathingPanel(
                ParallaxScrollContainer(id="conversation-scroll"),
                id="conversation-panel",
                title="Conversation",
                state="idle",
            ):
                pass

            # 右侧: 侧边栏 + Shadow Preview
            with Vertical(id="sidebar"):
                # V5.0: Thinking Tree
                with Vertical(id="thinking-tree-container"):
                    yield Label("🧠 Thinking Tree", classes="section-title")
                    yield ThinkingTreeWidget(id="thinking-tree")

                with Vertical(id="step-tracker-container"):
                    yield Label("📋 Step Tracker", classes="section-title")
                    yield StepTracker(id="step-tracker")

                with Vertical(id="telemetry-container"):
                    yield Label("📊 Telemetry", classes="section-title")
                    yield TelemetryPanel(id="telemetry-panel")

                with Vertical(id="healing-stats-container"):
                    yield Label("🛠️ Healing Metrics", classes="section-title")
                    yield SelfHealingStatsPanel(id="healing-stats")

                with Vertical(id="healing-panel-container"):
                    yield Label("🛡️ Healing Status", classes="section-title")
                    yield SelfHealingPanel(id="healing-panel")

                with Vertical(id="tools-container"):
                    yield Label("🔧 Active Tools", classes="section-title")
                    yield DataTable(id="tools-table")

        # Shadow Preview MirrorPane (右侧弹出 40%)
        yield MirrorPane(id="mirror-pane")

        # 底部: 输入区
        with Vertical(id="input-container"):
            yield Input(id="user-input", placeholder="输入任务描述，按 Enter 发送... (Ctl+B 中断)")

        # 进度条 (Animated with ease-in-out)
        with Vertical(id="progress-container"):
            yield AnimatedProgressBar(id="progress-bar")

        # 隐藏的组件容器 (仅用于在切换时保证组件已被挂载)
        with Vertical(id="hidden-widgets", display=False):
            yield ThinkingTreeWidget(id="thinking-tree-hidden")

        # V5.0: SIP 风险指示器
        yield RiskIndicator(id="risk-indicator")

        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """处理用户输入提交"""
        if event.input.id == "user-input":
            user_input = event.value.strip()
            if user_input:
                event.input.value = ""  # 清空输入框
                self._handle_user_input(user_input)

    def _handle_user_input(self, text: str) -> None:
        """处理用户输入"""
        # 处理内置命令
        if text.startswith("/"):
            self._handle_builtin(text)
            return

        # 更新对话区 (使用平滑滚动容器)
        scroll_container = self.query_one("#conversation-scroll", ParallaxScrollContainer)
        scroll_container.append_content_smooth(f"\n\n## User\n\n{text}\n\n## Assistant\n\n")

        # 更新状态为 thinking
        self._set_phase("thinking", "AI 正在思考...")

        # 启动 Agent 任务
        self._run_agent_task(text)

    def _handle_builtin(self, cmd: str) -> None:
        """处理内置命令"""
        cmd_lower = cmd.strip().lower()
        scroll_container = self.query_one("#conversation-scroll", ParallaxScrollContainer)

        if cmd_lower in ("/q", "/quit", "/exit"):
            self.exit()
        elif cmd_lower == "/clear":
            scroll_container.clear()
        elif cmd_lower == "/status":
            scroll_container.append_content_smooth(
                f"\n\n**Status**: {self.current_phase} | Iteration: {self.iteration}/{self.max_iterations}\n\n"
            )
        else:
            scroll_container.append_content_smooth(f"\n\n**Unknown command**: {cmd}\n\n")

    def _set_phase(self, phase: str, message: str = "") -> None:
        """设置当前阶段 (Animated Progress)"""
        self.current_phase = phase

        # 更新面板样式
        panel = self.query_one("#conversation-panel", BreathingPanel)
        panel.panel_state = phase

        # 更新进度条 (带动画)
        progress = self.query_one("#progress-bar", AnimatedProgressBar)
        if phase == "thinking":
            progress.set_progress(0, animate=False)  # 不确定模式
        elif phase == "executing":
            progress.set_progress(50, label="执行中")
        elif phase == "done":
            progress.set_progress(100, label="完成")
        else:
            progress.set_progress(0, label=message or "就绪")

    def _run_agent_task(self, goal: str) -> None:
        """运行 Agent 任务"""
        if self.engine is None:
            self._init_engine()

        # 取消之前的任务
        if self._task and not self._task.done():
            self._task.cancel()

        # 创建新任务
        self._task = asyncio.create_task(self._execute_task(goal))

    async def _execute_task(self, goal: str) -> None:
        """执行 Agent 任务"""
        try:
            if self.engine is None:
                return

            scroll_container = self.query_one("#conversation-scroll", ParallaxScrollContainer)
            typewriter = self.query_one("#typewriter-output", TypewriterEffect)
            step_tracker = self.query_one("#step-tracker", StepTracker)
            telemetry = self.query_one("#telemetry-panel", TelemetryPanel)

            # 累积的 AI 响应文本
            accumulated_response = ""

            def on_chunk(chunk: str) -> None:
                """流式 chunk 回调 — 使用打字机效果"""
                nonlocal accumulated_response
                accumulated_response += chunk
                # 使用打字机效果显示
                self.call_from_thread(typewriter.start_typing, accumulated_response)

            def on_step(step: Any, session: Any) -> None:
                """步骤回调"""
                iteration = getattr(step, 'iteration', 0)
                self.call_from_thread(self._update_iteration, iteration)

                step_type = getattr(step, 'step_type', '')
                action = getattr(step, 'action', '')

                if step_type == 'llm':
                    self.call_from_thread(self._set_phase, "thinking", action)
                elif step_type == 'execute':
                    self.call_from_thread(self._set_phase, "executing", action)
                    self.call_from_thread(step_tracker.add_step, step_type, "running", action)
                elif step_type == 'report':
                    success = getattr(step, 'success', True)
                    if success:
                        self.call_from_thread(self._set_phase, "done", "任务完成")
                        self.call_from_thread(step_tracker.update_step, step_type, "success", action)
                        # 将打字机输出追加到滚动容器
                        self.call_from_thread(scroll_container.append_content_smooth, accumulated_response)
                    else:
                        self.call_from_thread(self._set_phase, "error", action)
                        self.call_from_thread(step_tracker.update_step, step_type, "error", action)

                # 更新遥测
                summary = self.engine.get_cost_summary()
                if summary:
                    self.call_from_thread(telemetry.update_telemetry,
                        total_tokens=summary.get('total_tokens', 0),
                        total_cost=summary.get('total_cost', 0),
                        llm_calls=summary.get('total_calls', 0),
                        cache_read_tokens=summary.get('total_cache_read_tokens', 0),
                        cache_write_tokens=summary.get('total_cache_write_tokens', 0),
                        reasoning_tokens=summary.get('total_reasoning_tokens', 0),
                    )

            # 执行任务
            self._set_phase("thinking", "正在分析任务...")
            await self.engine.run(goal, on_step=on_step, on_chunk=on_chunk)

        except asyncio.CancelledError:
            self._set_phase("idle", "任务已取消")
        except Exception as e:
            self._set_phase("error", str(e))

    def _update_iteration(self, iteration: int) -> None:
        """更新迭代计数"""
        self.iteration = iteration

    def _init_engine(self) -> None:
        """初始化 AgentEngine"""
        if self.engine is not None:
            return

        if self.engine_factory:
            self.engine = self.engine_factory(
                workdir=self.workdir,
                max_iterations=self.max_iterations,
            )
        else:
            from ..agent.factory import create_agent_engine
            self.engine = create_agent_engine(
                workdir=self.workdir,
                max_iterations=self.max_iterations,
            )

    def action_clear(self) -> None:
        """清除对话"""
        scroll_container = self.query_one("#conversation-scroll", ParallaxScrollContainer)
        scroll_container.clear()
        self._set_phase("idle", "对话已清除")

    def action_status(self) -> None:
        """显示状态"""
        scroll_container = self.query_one("#conversation-scroll", ParallaxScrollContainer)
        scroll_container.append_content_smooth(
            f"\n\n**Status**: {self.current_phase} | Iteration: {self.iteration}/{self.max_iterations}\n\n"
        )

    def action_break_execution(self) -> None:
        """Ctl+B 中断当前执行 — V5.0 Omni-Glow"""
        self.notify("⛔ 已中断当前操作", title="中断", severity="warning")
        self._set_phase("idle", "用户中断")

        # 取消正在运行的任务
        if self._task and not self._task.done():
            self._task.cancel()

        # 清空 MirrorPane
        try:
            mirror = self.query_one("#mirror-pane", MirrorPane)
            mirror.clear()
        except Exception:
            pass

        # 清除风险警示
        try:
            risk = self.query_one("#risk-indicator", RiskIndicator)
            risk.clear_alert()
        except Exception:
            pass


# ============================================================================
# 启动函数
# ============================================================================

def start_textual_tui(
    workdir: str | None = None,
    max_iterations: int = 10,
    engine_factory: Callable | None = None,
) -> int:
    """启动 Textual TUI 仪表盘

    参数:
        workdir: 工作目录
        max_iterations: 最大迭代次数
        engine_factory: AgentEngine 工厂函数

    返回:
        退出码
    """
    app = DashboardApp(
        workdir=workdir,
        max_iterations=max_iterations,
        engine_factory=engine_factory,
    )
    app.run()
    return 0

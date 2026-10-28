"""textual_dashboard 模块测试 — 全屏 TUI 仪表盘的控制器逻辑

覆盖:
- DashboardApp 初始化 / 响应式默认值 / 绑定表
- 阶段状态机 ``_set_phase``（idle / thinking / executing / done / error）
- 内置命令路由 ``_handle_builtin`` 与输入事件 ``on_input_submitted``
- 自愈 / RAG 事件处理器与事件总线接线 ``_setup_event_handlers``
- Agent 任务编排 ``_run_agent_task`` / ``_execute_task``（成功 / 失败 / 取消）
- 动作方法 ``action_clear`` / ``action_status`` / ``action_break_execution``
- 启动包装 ``start_textual_tui``

已知 src 缺陷（用例内以断言固定当前行为，报告中记录）:
- ``DashboardApp.CSS`` 使用 Textual 不支持的 ``@keyframes``（textual_dashboard.py:143）
  与 ``animation``（:140），CSS 解析直接抛 ``TokenError`` —— 整个 App 无法挂载。
  另有 ``title:`` 非法属性（:109/:115/:121）。因此本文件的用例以
  ``query_one`` 打桩驱动控制器逻辑，不做真实挂载。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import src.cli.textual_dashboard as textual_dashboard_module
from src.cli.textual_dashboard import DashboardApp, start_textual_tui
from src.core.events import Event, EventBus, EventType
from textual.css.query import NoMatches

# ====================================================================
# 测试脚手架
# ====================================================================

QUERY_SELECTORS = (
    "#conversation-scroll",
    "#conversation-panel",
    "#progress-bar",
    "#step-tracker",
    "#telemetry-panel",
    "#typewriter-output",
    "#healing-panel",
    "#healing-stats",
    "#mirror-pane",
    "#risk-indicator",
)


@pytest.fixture
def app_and_stubs(monkeypatch):
    """构造 DashboardApp 并把 ``query_one`` 换成按选择器返回桩值的实现"""
    app = DashboardApp(workdir="/tmp/project", max_iterations=7)
    stubs: dict[str, MagicMock] = {selector: MagicMock(name=selector) for selector in QUERY_SELECTORS}

    def fake_query_one(selector, expect_type=None):
        if selector not in stubs:
            stubs[selector] = MagicMock(name=selector)
        return stubs[selector]

    monkeypatch.setattr(app, "query_one", fake_query_one)
    return app, stubs


@pytest.fixture
def app(app_and_stubs):
    return app_and_stubs[0]


def _submitted(value: str, input_id: str = "user-input"):
    """模拟 textual Input.Submitted 事件对象"""
    input_widget = SimpleNamespace(id=input_id, value=value)
    return SimpleNamespace(input=input_widget, value=value)


# ====================================================================
# 初始化与静态配置
# ====================================================================

class TestDashboardAppInit:

    def test_stores_constructor_arguments(self):
        factory = MagicMock()
        app = DashboardApp(workdir="/work", max_iterations=3, engine_factory=factory)

        assert app.workdir == "/work"
        assert app.max_iterations == 3
        assert app.engine_factory is factory
        assert app.engine is None
        assert app._task is None
        assert app._loop is None

    def test_defaults_for_reactive_state(self):
        app = DashboardApp()

        assert app.current_phase == "idle"
        assert app.iteration == 0
        assert app.max_iterations == 10
        assert app.show_healing is False
        assert app.show_thinking_tree is True

    def test_bindings_cover_expected_actions(self):
        bindings = {(key, action) for key, action, _description in DashboardApp.BINDINGS}

        assert ("q", "quit") in bindings
        assert ("ctrl+c", "quit") in bindings
        assert ("clear", "clear") in bindings
        assert ("status", "status") in bindings
        assert ("ctrl+b", "break_execution") in bindings

    def test_stylesheet_contains_unsupported_at_rule(self):
        """缺陷记录: Textual 不支持 @keyframes（textual_dashboard.py:143）

        该 CSS 会让 ``Stylesheet.parse`` 抛 ``TokenError``，App 无法挂载。
        """
        assert "@keyframes breathe" in DashboardApp.CSS


# ====================================================================
# 阶段状态机
# ====================================================================

class TestSetPhase:

    @pytest.mark.parametrize(
        ("phase", "message", "expected_args", "expected_kwargs"),
        [
            ("thinking", "AI 正在思考...", (0,), {"animate": False}),
            ("executing", "", (50,), {"label": "执行中"}),
            ("done", "", (100,), {"label": "完成"}),
            ("error", "boom", (0,), {"label": "boom"}),
            ("idle", "", (0,), {"label": "就绪"}),
        ],
    )
    def test_phase_drives_panel_and_progress_bar(
        self, app_and_stubs, phase, message, expected_args, expected_kwargs
    ):
        # Arrange
        app, stubs = app_and_stubs

        # Act
        app._set_phase(phase, message)

        # Assert
        assert app.current_phase == phase
        assert stubs["#conversation-panel"].panel_state == phase
        stubs["#progress-bar"].set_progress.assert_called_once_with(*expected_args, **expected_kwargs)


# ====================================================================
# 内置命令与输入处理
# ====================================================================

class TestBuiltinCommands:

    @pytest.mark.parametrize("command", ["/q", "/quit", "/exit", "  /QUIT  "])
    def test_quit_variants_call_exit(self, app_and_stubs, monkeypatch, command):
        app, stubs = app_and_stubs
        monkeypatch.setattr(app, "exit", MagicMock())

        app._handle_builtin(command)

        app.exit.assert_called_once_with()
        stubs["#conversation-scroll"].append_content_smooth.assert_not_called()

    def test_clear_empties_conversation(self, app_and_stubs):
        app, stubs = app_and_stubs

        app._handle_builtin("/clear")

        stubs["#conversation-scroll"].clear.assert_called_once_with()

    def test_status_appends_phase_and_iteration(self, app_and_stubs):
        app, stubs = app_and_stubs
        app.current_phase = "executing"
        app.iteration = 2

        app._handle_builtin("/status")

        stubs["#conversation-scroll"].append_content_smooth.assert_called_once_with(
            "\n\n**Status**: executing | Iteration: 2/7\n\n"
        )

    def test_unknown_command_is_echoed(self, app_and_stubs):
        app, stubs = app_and_stubs

        app._handle_builtin("/dance")

        stubs["#conversation-scroll"].append_content_smooth.assert_called_once_with(
            "\n\n**Unknown command**: /dance\n\n"
        )


class TestInputHandling:

    def test_submitted_input_is_dispatched_and_cleared(self, app_and_stubs, monkeypatch):
        app, _stubs = app_and_stubs
        handled: list[str] = []
        monkeypatch.setattr(app, "_handle_user_input", handled.append)
        event = _submitted("  修复登录 bug  ")

        app.on_input_submitted(event)

        assert handled == ["修复登录 bug"]
        assert event.input.value == ""

    def test_blank_submission_is_ignored(self, app_and_stubs, monkeypatch):
        app, _stubs = app_and_stubs
        handled: list[str] = []
        monkeypatch.setattr(app, "_handle_user_input", handled.append)
        event = _submitted("   ")

        app.on_input_submitted(event)

        assert handled == []
        assert event.input.value == "   "

    def test_other_input_widget_is_ignored(self, app_and_stubs, monkeypatch):
        app, _stubs = app_and_stubs
        handled: list[str] = []
        monkeypatch.setattr(app, "_handle_user_input", handled.append)

        app.on_input_submitted(_submitted("hello", input_id="other-input"))

        assert handled == []

    def test_slash_input_routes_to_builtin(self, app_and_stubs, monkeypatch):
        app, stubs = app_and_stubs
        builtin: list[str] = []
        monkeypatch.setattr(app, "_handle_builtin", builtin.append)
        tasks: list[str] = []
        monkeypatch.setattr(app, "_run_agent_task", tasks.append)

        app._handle_user_input("/status")

        assert builtin == ["/status"]
        assert tasks == []
        stubs["#conversation-scroll"].append_content_smooth.assert_not_called()

    def test_plain_input_echoes_and_starts_agent_task(self, app_and_stubs, monkeypatch):
        app, stubs = app_and_stubs
        tasks: list[str] = []
        monkeypatch.setattr(app, "_run_agent_task", tasks.append)

        app._handle_user_input("重构鉴权")

        stubs["#conversation-scroll"].append_content_smooth.assert_called_once_with(
            "\n\n## User\n\n重构鉴权\n\n## Assistant\n\n"
        )
        assert app.current_phase == "thinking"
        assert tasks == ["重构鉴权"]


# ====================================================================
# 响应式 watcher
# ====================================================================

class TestWatchers:

    def test_show_healing_true_swaps_sidebar_view(self, app_and_stubs):
        app, stubs = app_and_stubs

        app.watch_show_healing(True)

        assert stubs["#step-tracker-container"].display is False
        assert stubs["#healing-panel-container"].display is True
        assert stubs["#healing-stats-container"].display is True

    def test_show_healing_false_restores_tracker(self, app_and_stubs):
        app, stubs = app_and_stubs

        app.watch_show_healing(False)

        assert stubs["#step-tracker-container"].display is True
        assert stubs["#healing-panel-container"].display is False
        assert stubs["#healing-stats-container"].display is False

    def test_show_healing_swallows_missing_widgets(self):
        """未挂载时 query_one 抛 NoMatches → 静默跳过（textual_dashboard.py:182）"""
        app = DashboardApp()

        app.watch_show_healing(True)  # 不应抛出

    def test_show_thinking_tree_toggles_display(self, app_and_stubs):
        app, stubs = app_and_stubs

        app.watch_show_thinking_tree(False)
        assert stubs["#thinking-tree-container"].display is False

        app.watch_show_thinking_tree(True)
        assert stubs["#thinking-tree-container"].display is True

    def test_show_thinking_tree_swallows_missing_widgets(self):
        DashboardApp().watch_show_thinking_tree(False)  # 不应抛出


# ====================================================================
# 自愈 / RAG 事件处理
# ====================================================================

class TestEventHandlers:

    def test_healing_event_builds_model_and_shows_panel(self, app_and_stubs):
        app, stubs = app_and_stubs

        app._handle_healing_event(
            {
                "error_type": "ImportError",
                "error_message": "cannot import name 'x'",
                "fix_strategy": "add missing import",
                "confidence": 0.83,
                "attempts": 2,
                "fix_applied": "patch_engine",
            }
        )

        event = stubs["#healing-panel"].report_healing.call_args.args[0]
        assert event.error_type == "ImportError"
        assert event.error_message == "cannot import name 'x'"
        assert event.fix_strategy == "add missing import"
        assert event.confidence == 0.83
        assert event.attempts == 2
        assert [line.type for line in event.diff_lines] == ["header"]
        assert event.diff_lines[0].content == "Fix applied via patch_engine"
        assert app.show_healing is True

    def test_healing_event_without_fix_applied_has_no_diff(self, app_and_stubs):
        app, stubs = app_and_stubs

        app._handle_healing_event({"error_type": "ValueError"})

        event = stubs["#healing-panel"].report_healing.call_args.args[0]
        assert event.error_message == ""
        assert event.fix_strategy == ""
        assert event.confidence == 0.5
        assert event.attempts == 1
        assert event.diff_lines == []

    def test_healing_stats_forwarded_as_kwargs(self, app_and_stubs):
        app, stubs = app_and_stubs

        app._handle_healing_stats({"total_errors_detected": 4, "success_rate": 0.75})

        stubs["#healing-stats"].update_stats.assert_called_once_with(
            total_errors_detected=4, success_rate=0.75
        )

    def test_rag_metrics_forwarded_as_kwargs(self, app_and_stubs):
        app, stubs = app_and_stubs

        app._handle_rag_metrics({"indexed_files": 12, "coverage_percent": 88.5})

        stubs["#telemetry-panel"].update_rag_metrics.assert_called_once_with(
            indexed_files=12, coverage_percent=88.5
        )


class TestEventBusWiring:

    @pytest.fixture
    def wired_app(self, app_and_stubs, monkeypatch):
        """把事件总线换成独立实例，并让 call_from_thread 同步执行"""
        app, stubs = app_and_stubs
        bus = EventBus()
        monkeypatch.setattr("src.core.events.get_event_bus", lambda: bus)
        monkeypatch.setattr(app, "call_from_thread", lambda callback, *a, **k: callback(*a, **k))
        app._setup_event_handlers()
        return app, stubs, bus

    def test_on_mount_sets_titles_and_registers_handlers(self, monkeypatch):
        bus = EventBus()
        monkeypatch.setattr("src.core.events.get_event_bus", lambda: bus)
        app = DashboardApp()

        app.on_mount()

        assert app.title == "Clawd Code — AI 编程代理"
        assert app.sub_title == "Textual TUI Dashboard"
        assert bus._sync_handlers[EventType.HEALING_EVENT]
        assert bus._sync_handlers[EventType.HEALING_STATS_UPDATE]
        assert bus._sync_handlers[EventType.RAG_INDEX_UPDATED]

    def test_healing_event_from_bus_reaches_panel(self, wired_app):
        app, stubs, bus = wired_app

        bus.publish(Event(type=EventType.HEALING_EVENT, data={"error_type": "TimeoutError"}))

        event = stubs["#healing-panel"].report_healing.call_args.args[0]
        assert event.error_type == "TimeoutError"
        assert app.show_healing is True

    def test_healing_stats_event_from_bus_reaches_panel(self, wired_app):
        _app, stubs, bus = wired_app

        bus.publish(Event(type=EventType.HEALING_STATS_UPDATE, data={"total_fixes_successful": 3}))

        stubs["#healing-stats"].update_stats.assert_called_once_with(total_fixes_successful=3)

    def test_rag_update_event_from_bus_reaches_panel(self, wired_app):
        _app, stubs, bus = wired_app

        bus.publish(Event(type=EventType.RAG_INDEX_UPDATED, data={"total_terms": 900}))

        stubs["#telemetry-panel"].update_rag_metrics.assert_called_once_with(total_terms=900)

    def test_unrelated_event_is_ignored(self, wired_app):
        _app, stubs, bus = wired_app

        bus.publish(Event(type=EventType.COST_RECORDED, data={"cost": 1.0}))

        stubs["#healing-panel"].report_healing.assert_not_called()
        stubs["#telemetry-panel"].update_rag_metrics.assert_not_called()


# ====================================================================
# Agent 引擎与任务编排
# ====================================================================

class TestEngineInitialisation:

    def test_existing_engine_is_not_replaced(self, app_and_stubs):
        app, _stubs = app_and_stubs
        existing = MagicMock()
        app.engine = existing

        app._init_engine()

        assert app.engine is existing

    def test_engine_factory_receives_workdir_and_iterations(self, monkeypatch):
        factory = MagicMock(return_value="engine-from-factory")
        app = DashboardApp(workdir="/work", max_iterations=4, engine_factory=factory)

        app._init_engine()

        factory.assert_called_once_with(workdir="/work", max_iterations=4)
        assert app.engine == "engine-from-factory"

    def test_default_factory_is_used_when_none_given(self, monkeypatch):
        created = MagicMock(return_value="default-engine")
        monkeypatch.setattr("src.agent.factory.create_agent_engine", created)
        app = DashboardApp(workdir="/work", max_iterations=5)

        app._init_engine()

        created.assert_called_once_with(workdir="/work", max_iterations=5)
        assert app.engine == "default-engine"


class TestRunAgentTask:

    async def test_creates_task_and_cancels_previous_one(self, app_and_stubs, monkeypatch):
        app, _stubs = app_and_stubs
        app.engine = MagicMock()
        started: list[str] = []

        async def fake_execute(goal: str) -> None:
            started.append(goal)

        monkeypatch.setattr(app, "_execute_task", fake_execute)
        previous = asyncio.create_task(asyncio.sleep(10))
        app._task = previous

        app._run_agent_task("目标一")

        assert app._task is not previous
        await asyncio.sleep(0)
        assert previous.cancelled() is True
        assert started == ["目标一"]

    async def test_initialises_engine_when_missing(self, app_and_stubs, monkeypatch):
        app, _stubs = app_and_stubs
        init_calls: list[int] = []
        monkeypatch.setattr(app, "_init_engine", lambda: init_calls.append(1))

        async def fake_execute(goal: str) -> None:
            return None

        monkeypatch.setattr(app, "_execute_task", fake_execute)

        app._run_agent_task("目标")

        assert init_calls == [1]
        await asyncio.sleep(0)


class TestExecuteTask:

    @staticmethod
    def _engine(summary=None, steps=(), chunks=(), error=None):
        """构造可控的 AgentEngine 桩"""

        class _Engine:
            def __init__(self) -> None:
                self.goal = None

            async def run(self, goal, on_step=None, on_chunk=None):
                self.goal = goal
                for chunk in chunks:
                    on_chunk(chunk)
                for step in steps:
                    on_step(step, None)
                if error is not None:
                    raise error

            def get_cost_summary(self):
                return summary

        return _Engine()

    @staticmethod
    def _step(iteration, step_type, action, success=True):
        return SimpleNamespace(iteration=iteration, step_type=step_type, action=action, success=success)

    async def test_no_engine_returns_without_touching_ui(self, app_and_stubs):
        app, stubs = app_and_stubs
        app.engine = None

        await app._execute_task("目标")

        assert app.current_phase == "idle"
        assert all(stub.method_calls == [] for stub in stubs.values())

    async def test_successful_run_streams_and_updates_every_panel(self, app_and_stubs, monkeypatch):
        # Arrange
        app, stubs = app_and_stubs
        summary = {
            "total_tokens": 120,
            "total_cost": 0.5,
            "total_calls": 3,
            "total_cache_read_tokens": 7,
            "total_cache_write_tokens": 8,
            "total_reasoning_tokens": 9,
        }
        engine = self._engine(
            summary=summary,
            steps=[
                self._step(1, "llm", "规划"),
                self._step(2, "execute", "运行 grep"),
                self._step(3, "report", "完成"),
            ],
            chunks=["hello ", "world"],
        )
        app.engine = engine
        monkeypatch.setattr(app, "call_from_thread", lambda callback, *a, **k: callback(*a, **k))

        # Act
        await app._execute_task("修 bug")

        # Assert
        assert engine.goal == "修 bug"
        assert app.current_phase == "done"
        assert app.iteration == 3
        stubs["#typewriter-output"].start_typing.assert_called_with("hello world")
        stubs["#step-tracker"].add_step.assert_called_once_with("execute", "running", "运行 grep")
        stubs["#step-tracker"].update_step.assert_called_once_with("report", "success", "完成")
        stubs["#conversation-scroll"].append_content_smooth.assert_called_once_with("hello world")
        stubs["#telemetry-panel"].update_telemetry.assert_called_with(
            total_tokens=120,
            total_cost=0.5,
            llm_calls=3,
            cache_read_tokens=7,
            cache_write_tokens=8,
            reasoning_tokens=9,
        )

    async def test_failed_report_marks_phase_error(self, app_and_stubs, monkeypatch):
        app, stubs = app_and_stubs
        app.engine = self._engine(
            summary=None,
            steps=[self._step(1, "report", "失败了", success=False)],
        )
        monkeypatch.setattr(app, "call_from_thread", lambda callback, *a, **k: callback(*a, **k))

        await app._execute_task("目标")

        assert app.current_phase == "error"
        stubs["#step-tracker"].update_step.assert_called_once_with("report", "error", "失败了")
        stubs["#telemetry-panel"].update_telemetry.assert_not_called()

    async def test_cancellation_resets_phase_to_idle(self, app_and_stubs, monkeypatch):
        app, stubs = app_and_stubs
        app.engine = self._engine(error=asyncio.CancelledError())
        monkeypatch.setattr(app, "call_from_thread", lambda callback, *a, **k: callback(*a, **k))

        await app._execute_task("目标")

        assert app.current_phase == "idle"
        stubs["#progress-bar"].set_progress.assert_called_with(0, label="任务已取消")

    async def test_engine_exception_is_surfaced_as_error_phase(self, app_and_stubs, monkeypatch):
        app, stubs = app_and_stubs
        app.engine = self._engine(error=RuntimeError("boom"))
        monkeypatch.setattr(app, "call_from_thread", lambda callback, *a, **k: callback(*a, **k))

        await app._execute_task("目标")

        assert app.current_phase == "error"
        stubs["#progress-bar"].set_progress.assert_called_with(0, label="boom")

    def test_update_iteration_sets_reactive(self, app):
        app._update_iteration(6)

        assert app.iteration == 6


# ====================================================================
# 动作方法
# ====================================================================

class TestActions:

    def test_clear_empties_conversation_and_resets_phase(self, app_and_stubs):
        app, stubs = app_and_stubs
        app.current_phase = "executing"

        app.action_clear()

        stubs["#conversation-scroll"].clear.assert_called_once_with()
        assert app.current_phase == "idle"
        stubs["#progress-bar"].set_progress.assert_called_once_with(0, label="对话已清除")

    def test_status_appends_current_state(self, app_and_stubs):
        app, stubs = app_and_stubs
        app.current_phase = "thinking"
        app.iteration = 3

        app.action_status()

        stubs["#conversation-scroll"].append_content_smooth.assert_called_once_with(
            "\n\n**Status**: thinking | Iteration: 3/7\n\n"
        )

    async def test_break_execution_notifies_and_resets(self, app_and_stubs, monkeypatch):
        app, stubs = app_and_stubs
        monkeypatch.setattr(app, "notify", MagicMock())
        app.current_phase = "executing"
        pending = asyncio.create_task(asyncio.sleep(10))
        app._task = pending

        app.action_break_execution()

        app.notify.assert_called_once()
        assert app.current_phase == "idle"
        stubs["#mirror-pane"].clear.assert_called_once_with()
        stubs["#risk-indicator"].clear_alert.assert_called_once_with()
        await asyncio.sleep(0)
        assert pending.cancelled() is True

    def test_break_execution_swallows_missing_widgets(self, app_and_stubs, monkeypatch):
        """MirrorPane / RiskIndicator 缺失时静默跳过（textual_dashboard.py:499-510）"""
        app, stubs = app_and_stubs
        monkeypatch.setattr(app, "notify", MagicMock())

        def query_one_or_miss(selector, expect_type=None):
            if selector in ("#mirror-pane", "#risk-indicator"):
                raise NoMatches(selector)
            return stubs[selector]

        monkeypatch.setattr(app, "query_one", query_one_or_miss)

        app.action_break_execution()  # 不应抛出

        assert app.current_phase == "idle"
        stubs["#progress-bar"].set_progress.assert_called_once_with(0, label="用户中断")


# ====================================================================
# 启动包装
# ====================================================================

class TestStartTextualTui:

    def test_builds_app_forwards_arguments_and_returns_zero(self, monkeypatch):
        fake_app = MagicMock()
        monkeypatch.setattr(textual_dashboard_module, "DashboardApp", MagicMock(return_value=fake_app))
        factory = MagicMock()

        exit_code = start_textual_tui(workdir="/work", max_iterations=3, engine_factory=factory)

        textual_dashboard_module.DashboardApp.assert_called_once_with(
            workdir="/work", max_iterations=3, engine_factory=factory
        )
        fake_app.run.assert_called_once_with()
        assert exit_code == 0

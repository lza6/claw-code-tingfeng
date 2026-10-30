"""`src/cli/entrypoint.py` 的参数解析与命令分发测试。

被测单元是 **Typer 装配层本身**：
- 每个子命令必须真的把 CLI 参数**原样翻译**成被调函数的入参（含默认值省略规则）
- 退出码契约（成功 0 / 失败 1 / 业务错误码）
- 异常分支（ClawdError / 未预期异常）必须转成用户可读输出 + 非零退出码

所有外部能力（REPL、工作流引擎、服务端、reason handler、配置注入器等）
都用 fake 替换：这些命令一旦跑真实实现就会连网络 / 起服务 / 写盘。
被测的是"分发是否正确"，不是被调模块的内部实现。

共同前提：`initialize()` 会加载 `.env` 并改写 stdout 编码，测试里统一置空，
避免把用户环境带进断言。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from src.cli import entrypoint
from src.core.exceptions import ClawdError, ErrorCode

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_initialize(monkeypatch):
    """阻断回调里的 .env 加载 / stdout 重配置（与被测分发逻辑无关）。"""
    monkeypatch.setattr(entrypoint, "initialize", lambda: None)


@pytest.fixture
def healthy_doctor(monkeypatch):
    """把 doctor 的体检结果钉成"全绿"，让退出码不随宿主机环境漂移。

    为什么必须这么做（实测过的假红）：`doctor` 的退出码取 `collect_doctor_report()["ready"]`，
    而 `_no_initialize` 挡住了 `.env` 加载 —— 于是本文件单独跑时进程里没有 API Key，
    doctor 判 fail 返回 1，测试就红了；整套一起跑时别的模块先把 `.env` 读进 os.environ，
    同样的断言又变绿。**同一段测试两种结果**，属于测试自身的环境依赖（不是被测代码的缺陷）。
    这里只替换"外部体检"这一层，测的仍然是"分发是否正确"。
    """
    from src.cli import repl_commands

    report = {
        "ready": True,
        "count": 1,
        "failed": 0,
        "checks": [{"section": "env", "level": "pass", "text": "stub"}],
    }
    monkeypatch.setattr(repl_commands, "collect_doctor_report", lambda: dict(report))
    return report


def invoke(*args: str):
    return runner.invoke(entrypoint.app, list(args))


def invoke_ok(*args: str):
    result = invoke(*args)
    assert result.exit_code == 0, f"stdout={result.output!r} exc={result.exception!r}"
    return result


# ==========================================================================
# 顶层回调
# ==========================================================================


class TestCallback:
    def test_version_flag_prints_version_and_exits_zero(self):
        from src import __version__

        result = invoke_ok("--version")

        assert __version__ in result.output

    def test_version_short_flag(self):
        from src import __version__

        assert __version__ in invoke_ok("-v").output

    def test_version_callback_does_nothing_when_false(self):
        # 不传 --version 时 callback 收到 None，不得退出
        entrypoint.version_callback(None)

    def test_initialize_runs_for_every_command(self, monkeypatch, healthy_doctor):
        calls: list[int] = []
        monkeypatch.setattr(entrypoint, "initialize", lambda: calls.append(1))

        invoke_ok("doctor")

        assert calls == [1]


# ==========================================================================
# chat
# ==========================================================================


class TestChatCommand:
    @pytest.fixture(autouse=True)
    def _stub_project_ctx(self, monkeypatch, tmp_path):
        class _Ctx:
            def __init__(self, workdir=None):
                self.workdir = workdir

            def ensure_dirs(self) -> None:
                pass

        monkeypatch.setattr("src.core.project_context.ProjectContext", _Ctx)

    def test_passes_defaults_to_start_repl(self, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_start_repl(**kwargs):
            captured.update(kwargs)
            return 0

        monkeypatch.setattr("src.cli.repl.start_repl", fake_start_repl)

        invoke_ok("chat")

        assert captured["max_iterations"] == 10
        assert captured["use_textual_tui"] is False
        assert isinstance(captured["workdir"], Path)

    def test_options_are_translated(self, monkeypatch):
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "src.cli.repl.start_repl", lambda **kw: captured.update(kw) or 0
        )

        invoke_ok("chat", "--max-iterations", "3", "--tui")

        assert captured["max_iterations"] == 3
        assert captured["use_textual_tui"] is True

    def test_non_zero_exit_code_is_propagated(self, monkeypatch):
        monkeypatch.setattr("src.cli.repl.start_repl", lambda **kw: 7)

        assert invoke("chat").exit_code == 7

    def test_exception_becomes_exit_code_one(self, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("REPL 崩了")

        monkeypatch.setattr("src.cli.repl.start_repl", boom)

        result = invoke("chat")

        assert result.exit_code == 1
        assert "REPL 崩了" in result.output


# ==========================================================================
# run（5 阶段工作流）
# ==========================================================================


class TestRunCommand:
    @pytest.fixture
    def fake_engine(self, monkeypatch):
        state: dict[str, Any] = {"instances": [], "ran": [], "set_config": []}

        class _Engine:
            def __init__(self, workdir=None, max_iterations=3, budget_str=None):
                self.workdir = workdir
                self.max_iterations = max_iterations
                self.budget_str = budget_str
                self._use_isolation = None
                self.report = "REPORT-BODY"
                self.status = "completed"
                state["instances"].append(self)

            async def run(self, goal, recover: bool = False):
                state["ran"].append({"goal": goal, "recover": recover})
                return self

        monkeypatch.setattr("src.workflow.engine.WorkflowEngine", _Engine)
        monkeypatch.setattr(
            "src.core.config.injector.set_config",
            lambda k, v: state["set_config"].append((k, v)),
        )
        return state

    def test_defaults_and_isolation_flag(self, fake_engine):
        result = invoke_ok("run", "实现登录")

        engine = fake_engine["instances"][0]
        assert engine.max_iterations == 3
        assert engine.budget_str is None
        assert engine._use_isolation is True
        assert fake_engine["ran"] == [{"goal": "实现登录", "recover": False}]
        assert "REPORT-BODY" in result.output

    def test_options_are_translated(self, fake_engine):
        invoke_ok(
            "run",
            "实现登录",
            "--iterations",
            "5",
            "--no-isolation",
            "--budget",
            "1h",
            "--recover",
            "--intent",
            "debate",
            "--dimension",
            "creative",
            "--dimension",
            "audit",
        )

        engine = fake_engine["instances"][0]
        assert engine.max_iterations == 5
        assert engine._use_isolation is False
        assert engine.budget_str == "1h"
        assert fake_engine["ran"] == [{"goal": "实现登录", "recover": True}]
        assert fake_engine["set_config"] == [("dimensions", ["creative", "audit"])]

    def test_intent_is_exported_to_env(self, fake_engine, monkeypatch):
        invoke_ok("run", "目标", "--intent", "explore")

        import os

        assert os.environ["CLAWD_WORKFLOW_INTENT"] == "explore"

    def test_failed_status_exits_one(self, fake_engine, monkeypatch):
        class _Engine:
            def __init__(self, **kwargs):
                self.report = "REPORT"
                self.status = "failed"

            async def run(self, goal, recover=False):
                return self

        monkeypatch.setattr("src.workflow.engine.WorkflowEngine", _Engine)

        assert invoke("run", "目标").exit_code == 1

    def test_clawd_error_prints_code_and_exits_one(self, fake_engine, monkeypatch):
        class _Engine:
            def __init__(self, **kwargs):
                pass

            async def run(self, goal, recover=False):
                raise ClawdError(ErrorCode.VALIDATION_ERROR, "预算格式非法")

        monkeypatch.setattr("src.workflow.engine.WorkflowEngine", _Engine)

        result = invoke("run", "目标")

        assert result.exit_code == 1
        assert "预算格式非法" in result.output

    def test_unexpected_error_exits_one(self, fake_engine, monkeypatch):
        class _Engine:
            def __init__(self, **kwargs):
                pass

            async def run(self, goal, recover=False):
                raise RuntimeError("引擎内部错误")

        monkeypatch.setattr("src.workflow.engine.WorkflowEngine", _Engine)

        result = invoke("run", "目标")

        assert result.exit_code == 1
        assert "引擎内部错误" in result.output


# ==========================================================================
# server
# ==========================================================================


class TestServerCommand:
    @pytest.fixture
    def fake_server(self, monkeypatch):
        state: dict[str, Any] = {"kwargs": None, "run_forever_calls": 0}

        class _Srv:
            host = "127.0.0.1"
            port = 8765

            async def start(self):
                return "127.0.0.1", 9999

            async def run_forever(self):
                state["run_forever_calls"] += 1

        def fake_create_server(**kwargs):
            state["kwargs"] = kwargs
            return _Srv()

        monkeypatch.setattr("src.server.create_server", fake_create_server)
        return state

    def test_generates_token_when_env_missing(self, fake_server, monkeypatch):
        monkeypatch.delenv("AGENT_SERVER_TOKEN", raising=False)

        result = invoke_ok("server", "--port", "8765", "--host", "0.0.0.0")

        kwargs = fake_server["kwargs"]
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 8765
        assert kwargs["developer_mode"] is False
        assert len(kwargs["token"]) >= 20
        assert "已生成本次一次性令牌" in result.output
        assert "127.0.0.1:9999" in result.output
        assert fake_server["run_forever_calls"] == 1

    def test_uses_env_token_when_present(self, fake_server, monkeypatch):
        monkeypatch.setenv("AGENT_SERVER_TOKEN", "env-token")

        result = invoke_ok("server")

        assert fake_server["kwargs"]["token"] == "env-token"
        assert "已生成本次一次性令牌" not in result.output

    def test_cli_token_wins_over_env(self, fake_server, monkeypatch):
        monkeypatch.setenv("AGENT_SERVER_TOKEN", "env-token")

        invoke_ok("server", "--token", "cli-token")

        assert fake_server["kwargs"]["token"] == "cli-token"

    def test_developer_mode_flag(self, fake_server, monkeypatch):
        monkeypatch.setenv("AGENT_SERVER_TOKEN", "t")

        invoke_ok("server", "--developer-mode")

        assert fake_server["kwargs"]["developer_mode"] is True

    def test_keyboard_interrupt_is_reported_cleanly(self, monkeypatch):
        class _Srv:
            host = "h"
            port = 1

            async def start(self):
                return "h", 1

            async def run_forever(self):
                raise KeyboardInterrupt

        monkeypatch.setattr("src.server.create_server", lambda **k: _Srv())
        monkeypatch.setenv("AGENT_SERVER_TOKEN", "t")

        result = invoke("server")

        assert result.exit_code == 0
        assert "服务端已停止" in result.output


# ==========================================================================
# doctor / reason / serve / explore
# ==========================================================================


class TestSimpleDelegations:
    def test_doctor_calls_handler(self, monkeypatch, healthy_doctor):
        calls: list[int] = []
        monkeypatch.setattr(
            "src.cli.repl_commands._handle_doctor", lambda: calls.append(1)
        )

        invoke_ok("doctor")

        assert calls == [1]

    def test_reason_passes_only_non_default_options(self, monkeypatch):
        captured: list[list[str]] = []
        monkeypatch.setattr(
            "src.cli_handlers.reason_handler.cmd_reason",
            lambda argv: captured.append(argv) or 0,
        )

        invoke_ok("reason", "reflexion", "找出 bug")

        assert captured == [["reflexion", "找出 bug"]]

    def test_reason_passes_all_options(self, monkeypatch):
        captured: list[list[str]] = []
        monkeypatch.setattr(
            "src.cli_handlers.reason_handler.cmd_reason",
            lambda argv: captured.append(argv) or 0,
        )

        invoke_ok(
            "reason",
            "lats",
            "任务",
            "--conclusion",
            "结论",
            "--branching",
            "5",
            "--depth",
            "4",
            "--rounds",
            "3",
            "--max-iterations",
            "9",
            "--json",
        )

        assert captured == [
            [
                "lats",
                "任务",
                "--conclusion",
                "结论",
                "--branching",
                "5",
                "--depth",
                "4",
                "--rounds",
                "3",
                "--max-iterations",
                "9",
                "--json",
            ]
        ]

    def test_reason_non_zero_code_becomes_exit_code(self, monkeypatch):
        monkeypatch.setattr("src.cli_handlers.reason_handler.cmd_reason", lambda argv: 2)

        assert invoke("reason", "debate", "x").exit_code == 2

    def test_serve_passes_only_given_options(self, monkeypatch):
        captured: list[list[str]] = []
        monkeypatch.setattr(
            "src.server.host_entry.cmd_serve", lambda argv: captured.append(argv) or 0
        )

        invoke_ok("serve", "--port", "9000", "--workdir", "d", "--env-file", "e")

        assert captured == [["--port", "9000", "--workdir", "d", "--env-file", "e"]]

    def test_serve_without_options_passes_empty_argv(self, monkeypatch):
        captured: list[list[str]] = []
        monkeypatch.setattr(
            "src.server.host_entry.cmd_serve", lambda argv: captured.append(argv) or 0
        )

        invoke_ok("serve")

        assert captured == [[]]

    def test_serve_non_zero_code_becomes_exit_code(self, monkeypatch):
        monkeypatch.setattr("src.server.host_entry.cmd_serve", lambda argv: 3)

        assert invoke("serve").exit_code == 3

    def test_explore_delegates_with_format(self, monkeypatch):
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "src.cli.commands.explore.explore_command",
            lambda **kw: captured.update(kw),
        )

        invoke_ok("explore", "分析架构", "--depth", "4", "--format", "json")

        assert captured == {
            "goal": "分析架构",
            "depth": 4,
            "output_format": "json",
            # v0.89.0：explore 也接入了 --json 契约（as_json 由开关透传）
            "as_json": False,
        }

    def test_explore_defaults(self, monkeypatch):
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "src.cli.commands.explore.explore_command",
            lambda **kw: captured.update(kw),
        )

        invoke_ok("explore", "目标")

        assert captured["depth"] == 2
        assert captured["output_format"] == "markdown"


# ==========================================================================
# pipeline / ralplan
# ==========================================================================


class TestPipelineCommand:
    @pytest.fixture
    def fake_pipeline(self, monkeypatch):
        state: dict[str, Any] = {"stages": None, "status": "completed"}

        monkeypatch.setattr(
            "src.workflow.pipeline.create_ralplan_stage", lambda: "STAGE-RALPLAN"
        )
        monkeypatch.setattr(
            "src.workflow.pipeline.create_team_exec_stage", lambda: "STAGE-TEAM"
        )
        monkeypatch.setattr(
            "src.workflow.pipeline.create_ralph_verify_stage", lambda: "STAGE-RALPH"
        )

        class _Orchestrator:
            def __init__(self, config, cwd=None):
                self.config = config
                self.cwd = cwd

            async def run(self):
                return SimpleNamespace(
                    status=state["status"],
                    duration_ms=1500,
                    failed_stage="ralph" if state["status"] != "completed" else None,
                    error="验证失败" if state["status"] != "completed" else "",
                    stage_results={
                        "ralplan": SimpleNamespace(
                            status=SimpleNamespace(value="completed")
                        )
                    },
                )

        def fake_config(task, stages, cwd):
            state["stages"] = stages
            return SimpleNamespace(task=task, stages=stages, cwd=cwd)

        monkeypatch.setattr(
            "src.workflow.pipeline_orchestrator.PipelineOrchestrator", _Orchestrator
        )
        monkeypatch.setattr(
            "src.workflow.pipeline_orchestrator.create_autopilot_pipeline_config",
            fake_config,
        )
        return state

    def test_all_stages_included_by_default(self, fake_pipeline):
        result = invoke_ok("pipeline", "目标")

        assert fake_pipeline["stages"] == [
            "STAGE-RALPLAN",
            "STAGE-TEAM",
            "STAGE-RALPH",
        ]
        assert "completed" in result.output
        assert "1.50s" in result.output

    def test_skip_flags_drop_stages(self, fake_pipeline):
        invoke_ok("pipeline", "目标", "--no-team", "--no-ralph")

        assert fake_pipeline["stages"] == ["STAGE-RALPLAN"]

    def test_failed_pipeline_exits_one_and_shows_stage(self, fake_pipeline):
        fake_pipeline["status"] = "failed"

        result = invoke("pipeline", "目标")

        assert result.exit_code == 1
        assert "失败阶段: ralph" in result.output
        assert "验证失败" in result.output

    def test_budget_option_warns_it_is_ignored(self, fake_pipeline):
        result = invoke_ok("pipeline", "目标", "--budget", "1h")

        assert "暂不支持 --budget" in result.output


class TestRalplanCommand:
    def test_prints_plan_summary(self, monkeypatch):
        captured: dict[str, Any] = {}

        class _Engine:
            def __init__(self, workdir, max_rounds, min_confidence):
                captured["init"] = {
                    "workdir": workdir,
                    "max_rounds": max_rounds,
                    "min_confidence": min_confidence,
                }

            async def run(self, goal):
                return SimpleNamespace(
                    goal=goal,
                    objective="拆成三个子任务",
                    confidence=0.85,
                    tasks=[1, 2, 3],
                    risks=["风险A"],
                    validator="architect",
                    chosen_option=SimpleNamespace(
                        name="方案B", pros=["快", "稳"], cons=["贵"]
                    ),
                )

        monkeypatch.setattr("src.workflow.ralplan.RalplanEngine", _Engine)

        result = invoke_ok("ralplan", "目标", "--rounds", "4", "--min-confidence", "0.9")

        assert captured["init"]["max_rounds"] == 4
        assert captured["init"]["min_confidence"] == 0.9
        assert "0.85" in result.output
        assert "方案B" in result.output
        assert "风险数: 1" in result.output

    def test_plan_without_chosen_option(self, monkeypatch):
        class _Engine:
            def __init__(self, *a, **k):
                pass

            async def run(self, goal):
                return SimpleNamespace(
                    goal=goal,
                    objective="o",
                    confidence=0.5,
                    tasks=[],
                    risks=[],
                    validator="v",
                    chosen_option=None,
                )

        monkeypatch.setattr("src.workflow.ralplan.RalplanEngine", _Engine)

        result = invoke_ok("ralplan", "目标")

        assert "方案选择" not in result.output


# ==========================================================================
# quality-gate / hud / config
# ==========================================================================


class TestQualityGateCommand:
    def test_pass_exits_zero_and_prints_summary(self, monkeypatch):
        captured: dict[str, Any] = {}

        class _Gate:
            def __init__(self, workdir, level=None, strict=False):
                captured["level"] = level
                captured["strict"] = strict
                self.overall = SimpleNamespace(value="pass")

            def run(self):
                return SimpleNamespace(summary="GATE-SUMMARY")

        monkeypatch.setattr("src.core.quality_gate.QualityGate", _Gate)
        monkeypatch.setattr(
            "src.core.quality_gate.GateLevel", lambda level: f"level:{level}"
        )

        result = invoke_ok("quality-gate", "--level", "phase", "--strict")

        assert captured == {"level": "level:phase", "strict": True}
        assert "GATE-SUMMARY" in result.output

    def test_fail_exits_one(self, monkeypatch):
        class _Gate:
            def __init__(self, *a, **k):
                self.overall = SimpleNamespace(value="fail")

            def run(self):
                return SimpleNamespace(summary="FAIL-SUMMARY")

        monkeypatch.setattr("src.core.quality_gate.QualityGate", _Gate)

        result = invoke("quality-gate")

        assert result.exit_code == 1
        assert "FAIL-SUMMARY" in result.output

    def test_invalid_level_surfaces_error(self):
        """非法 --level 目前直接抛 ValueError（未做校验）→ 退出码 1。"""
        result = invoke("quality-gate", "--level", "nope")

        assert result.exit_code != 0


class TestHudCommand:
    def test_one_shot_with_message(self, monkeypatch):
        captured: list[str] = []

        class _Hud:
            def one_shot(self, message: str) -> None:
                captured.append(message)

        monkeypatch.setattr("src.cli.hud_improved.get_hud", lambda: _Hud())

        result = invoke_ok("hud", "--mode", "one-shot", "--message", "构建完成")

        assert captured == ["构建完成"]
        assert "live 模式暂未完全集成" not in result.output

    def test_live_mode_falls_back_to_hint(self, monkeypatch):
        monkeypatch.setattr(
            "src.cli.hud_improved.get_hud", lambda: SimpleNamespace(one_shot=lambda m: None)
        )

        result = invoke_ok("hud")

        assert "live 模式暂未完全集成" in result.output

    def test_one_shot_without_message_falls_back(self, monkeypatch):
        monkeypatch.setattr(
            "src.cli.hud_improved.get_hud", lambda: SimpleNamespace(one_shot=lambda m: None)
        )

        result = invoke_ok("hud", "--mode", "one-shot")

        assert "live 模式暂未完全集成" in result.output


class TestConfigCommand:
    def test_web_starts_web_config(self, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr(
            "src.cli.web_config.start_web_config", lambda: calls.append(1)
        )

        invoke_ok("config", "--web")

        assert calls == [1]

    def test_reset_clears_runtime_overrides(self, monkeypatch):
        calls: list[int] = []

        class _Injector:
            def clear_runtime_overrides(self) -> None:
                calls.append(1)

        monkeypatch.setattr(
            "src.core.config.injector.get_config_injector", lambda: _Injector()
        )

        result = invoke_ok("config", "--reset")

        assert calls == [1]
        assert "运行时覆盖配置已重置" in result.output

    def test_generate_calls_generator_with_flag_translation(self, monkeypatch):
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "src.core.config.generator.config_generate_command",
            lambda **kw: captured.update(kw),
        )

        invoke_ok("config", "--generate", "--path", "out.toml")

        assert captured["config_path"] == Path("out.toml")
        assert captured["dry_run"] is False
        assert captured["verbose"] is True

    def test_report_is_default(self, monkeypatch):
        monkeypatch.setattr(
            "src.core.config.runtime.get_config_priority_report",
            lambda: "PRIORITY-REPORT",
        )

        result = invoke_ok("config")

        assert "PRIORITY-REPORT" in result.output
        assert "config --web" in result.output

    def test_report_can_be_disabled(self, monkeypatch):
        monkeypatch.setattr(
            "src.core.config.runtime.get_config_priority_report",
            lambda: pytest.fail("--no-report 时不应读取配置报告"),
        )

        invoke_ok("config", "--no-report")


# ==========================================================================
# main() 装配
# ==========================================================================


class TestMain:
    def test_main_registers_hooks_and_invokes_app(self, monkeypatch):
        """显式开启（CLAWD_ENABLE_HOOKS_CONFIG=1）时才会加载项目 hooks 配置

        安全默认：不自动加载 CWD 的 hooks/config.toml（审计 P1-4：该文件可随仓库分发，
        自动加载等于"克隆仓库就跑它的命令"）。
        """
        monkeypatch.setenv("CLAWD_ENABLE_HOOKS_CONFIG", "1")
        events: list[str] = []

        monkeypatch.setattr(
            entrypoint, "_register_shutdown_hooks", lambda: events.append("atexit")
        )
        monkeypatch.setattr(
            "src.core.hooks_config.load_hooks_config",
            lambda path: events.append(f"hooks:{Path(path).name}"),
        )

        class _Dispatcher:
            @staticmethod
            def get():
                return _Dispatcher()

            async def start(self):
                events.append("dispatcher")

        monkeypatch.setattr(
            "src.core.notifications.dispatcher.NotificationDispatcher", _Dispatcher
        )
        monkeypatch.setattr(entrypoint, "app", lambda: events.append("app"))

        entrypoint.main()

        # atexit 由 CPython 在进程退出时触发，这里只确认已注册
        assert "app" in events
        assert any(e.startswith("hooks:") for e in events)
        assert "dispatcher" in events

    def test_main_does_not_autoload_hooks_by_default(self, monkeypatch):
        """安全默认回归：未开启时不得加载（否则克隆即执行）"""
        monkeypatch.delenv("CLAWD_ENABLE_HOOKS_CONFIG", raising=False)
        loaded: list[str] = []
        monkeypatch.setattr(entrypoint, "_register_shutdown_hooks", lambda: None)
        monkeypatch.setattr(
            "src.core.hooks_config.load_hooks_config",
            lambda path: loaded.append(str(path)),
        )

        class _NoopDispatcher:
            @staticmethod
            def get():
                return _NoopDispatcher()

            async def start(self):
                return None

        monkeypatch.setattr(
            "src.core.notifications.dispatcher.NotificationDispatcher", _NoopDispatcher
        )
        monkeypatch.setattr(entrypoint, "app", lambda: None)
        import warnings as _w

        with _w.catch_warnings():
            _w.simplefilter("ignore")
            entrypoint.main()

        assert loaded == [], f"默认不应加载 hooks 配置，实际加载了: {loaded}"

    def test_main_survives_hooks_and_dispatcher_failures(self, monkeypatch):
        monkeypatch.setenv("CLAWD_ENABLE_HOOKS_CONFIG", "1")
        events: list[str] = []

        monkeypatch.setattr(entrypoint, "_register_shutdown_hooks", lambda: None)

        def boom(path):
            raise RuntimeError("hooks 配置损坏")

        monkeypatch.setattr("src.core.hooks_config.load_hooks_config", boom)

        class _Dispatcher:
            @staticmethod
            def get():
                raise RuntimeError("分发器不可用")

        monkeypatch.setattr(
            "src.core.notifications.dispatcher.NotificationDispatcher", _Dispatcher
        )
        monkeypatch.setattr(entrypoint, "app", lambda: events.append("app"))

        with pytest.warns(UserWarning):
            entrypoint.main()

        # 两个可选组件都失败，CLI 仍必须启动
        assert events == ["app"]

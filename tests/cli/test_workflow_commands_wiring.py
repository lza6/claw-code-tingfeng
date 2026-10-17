"""`workflow` 命令组的**命令体**可执行性回归。

## 背景

v0.57.0 修好了"命令组注册"，但四个命令的**函数体**引用了一批不存在的符号：

- `SwarmOrchestrator`（真实是 `OrchestratorAgent` / `SwarmEngine`）
- `RalphLedger`（真实是 `RalphProgressLedger`）
- `RalplanWorkflow`（真实是 `RalplanEngine`）
- `create_autopilot_pipeline_config` —— 竟然是从**自身模块**导入

结果：`--help` 能显示（注册成功），但一执行就 ImportError。
"注册成功"不等于"命令可用" —— 本文件用替身驱动命令体，确保这条不变量。

## 方法

monkeypatch 真实引擎类为轻量替身，直接调用 Typer 命令回调，
断言：不抛 ImportError/AttributeError、返回码正确、产物落盘。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from src.agent.swarm.engine import SwarmResult
from src.workflow.ralplan import ConsensusPlan


def _cmd(module, name):
    return next(
        c.callback for c in module.app.registered_commands
        if (c.name or "") == name
    )


@pytest.fixture
def wf(tmp_path, monkeypatch):
    """切到临时工作目录，避免把 .clawd 写进仓库。"""
    monkeypatch.chdir(tmp_path)
    import src.cli.commands.workflow_commands as m
    return m


class _FakeSwarm:
    last_goal: str | None = None

    def __init__(self, config=None, workdir=None, intent="implement", **_kw):
        self.workdir = workdir

    async def run(self, goal):
        _FakeSwarm.last_goal = goal
        return SwarmResult(
            success=True,
            goal=goal,
            final_result="fake swarm done",
            code_changes=[],
            audit_report="",
            gate_results={},
            task_stats={},
            elapsed_seconds=0.1,
            errors=[],
        )


class TestRalphBody:
    def test_runs_without_import_error(self, wf, monkeypatch):
        import src.agent.swarm.engine as eng
        monkeypatch.setattr(eng, "SwarmEngine", _FakeSwarm)

        cb = _cmd(wf, "ralph")
        with pytest.raises(typer.Exit) as ei:
            cb(goal="do it", iterations=1, verify=True, recover=False, agent="executor")
        assert ei.value.exit_code == 0
        assert _FakeSwarm.last_goal == "do it"

        ledger = Path(".clawd/ralph/ledger.json")
        assert ledger.exists(), "ralph 未写出进度账本"
        data = json.loads(ledger.read_text(encoding="utf-8"))
        assert data["entries"][0]["success"] is True


class TestTeamBody:
    def test_runs_without_import_error(self, wf, monkeypatch):
        import src.agent.swarm.engine as eng
        monkeypatch.setattr(eng, "SwarmEngine", _FakeSwarm)

        cb = _cmd(wf, "team")
        with pytest.raises(typer.Exit) as ei:
            cb(goal="team goal", workers=2, agent_type="executor",
               parallel=True, decompose=True, session=None)
        assert ei.value.exit_code == 0


class TestRalplanBody:
    def test_runs_and_writes_plan(self, wf, monkeypatch):
        import src.workflow.ralplan as rp

        class FakeEngine:
            def __init__(self, workdir, max_rounds=3, **_kw):
                pass

            async def run(self, goal):
                return ConsensusPlan(
                    goal=goal, objective="obj", context={},
                    chosen_option="A", tasks=[{"t": 1}], prd="prd",
                    architecture="arch", risks=[], mitigations=[],
                    confidence=0.9, created_at="2026-01-01T00:00:00",
                    version=1, validator="fake",
                )

        monkeypatch.setattr(rp, "RalplanEngine", FakeEngine)

        cb = _cmd(wf, "ralplan")
        with pytest.raises(typer.Exit) as ei:
            cb(task="plan this", output=None, max_iterations=2,
               no_critic=False, no_architect=False)
        assert ei.value.exit_code == 0

        out = Path(".clawd/plans/ralplan.json")
        assert out.exists(), "ralplan 未写出计划文件"
        assert json.loads(out.read_text(encoding="utf-8"))["chosen_option"] == "A"


class TestAutopilotBody:
    def test_runs_without_import_error(self, wf, monkeypatch):
        import src.workflow.pipeline_orchestrator as po

        captured = {}

        class FakeOrch:
            def __init__(self, config, cwd=".", validate=True):
                captured["config"] = config

            async def run(self):
                from src.workflow.types import PipelineResult
                return PipelineResult(
                    status="completed", stage_results={}, duration_ms=1,
                    artifacts={}, error=None, failed_stage=None,
                )

        monkeypatch.setattr(po, "PipelineOrchestrator", FakeOrch)
        monkeypatch.setattr(wf, "can_resume_pipeline", lambda *a, **k: False)

        cb = _cmd(wf, "autopilot")
        # 成功路径不抛 Exit（只有失败才 raise typer.Exit(1)）；
        # 这里断言"跑完且确实把 goal 交给编排器"。
        cb(goal="auto goal", workers=2, ralph_iterations=1,
           no_plan=True, recover=False, verbose=False)
        assert captured["config"].task == "auto goal"


class TestPipelineCommandBody:
    """`clawd pipeline` 也曾是"注册成功但运行即崩"。

    原实现：`PipelineConfig(use_team=..., use_ralph=..., budget=...)`
    —— 三个参数都不存在；`PipelineOrchestrator(Path.cwd(), config)` 参数顺序反了；
    `orchestrator.execute()` 也不存在。实测 `TypeError` 立即抛出。
    """

    def test_runs_without_import_error(self, wf, monkeypatch):
        import src.cli.entrypoint as entry
        import src.workflow.pipeline_orchestrator as po

        captured = {}

        class FakeOrch:
            def __init__(self, config, cwd=".", validate=True):
                captured["config"] = config
                captured["cwd"] = cwd

            async def run(self):
                from src.workflow.types import PipelineResult
                return PipelineResult(
                    status="completed", stage_results={}, duration_ms=1,
                    artifacts={}, error=None, failed_stage=None,
                )

        monkeypatch.setattr(po, "PipelineOrchestrator", FakeOrch)

        cb = _cmd(entry, "pipeline")
        with pytest.raises(typer.Exit) as ei:
            cb(goal="pipe goal", no_team=True, no_ralph=True, budget=None)
        assert ei.value.exit_code == 0
        assert captured["config"].task == "pipe goal"

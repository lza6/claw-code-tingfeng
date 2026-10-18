"""`pipeline.py` 四个阶段工厂的执行回归。

## 背景

1. 四个内嵌阶段类都用 `self._logger`，而基类 `PipelineStage` 没有该属性 ——
   真实执行第一个阶段就 `AttributeError`。此前只测过构造，从未跑过阶段。
2. `ralplan` / `team-exec` 曾是占位实现：返回 `"<未实现>"` 却报 `SUCCESS`。
3. `stages/ralph_verify_stage.py` 用配置默认 `"."` 而不是 `ctx.cwd` 做验证目录。

本文件用替身驱动四个阶段的 `run()`，锁定上述三点。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.workflow.pipeline import (
    create_precontext_intake_stage,
    create_ralph_verify_stage,
    create_ralplan_stage,
    create_team_exec_stage,
)
from src.workflow.types import StageContext, StageStatus


def _ctx(tmp_path: Path) -> StageContext:
    return StageContext(task="do something", cwd=tmp_path)


class TestRalplanStage:
    @pytest.mark.asyncio
    async def test_real_engine_is_used(self, tmp_path, monkeypatch):
        import src.workflow.ralplan as rp

        class FakeOption:
            name = "Option-A"

        class FakePlan:
            chosen_option = FakeOption()
            prd = {"summary": "p"}
            tasks = [{"id": 1}]
            confidence = 0.9
            risks = ["r1"]

        class FakeEngine:
            def __init__(self, workdir, max_rounds=1, **_kw):
                assert Path(workdir) == tmp_path

            async def run(self, goal):
                assert goal == "do something"
                return FakePlan()

        monkeypatch.setattr(rp, "RalplanEngine", FakeEngine)

        result = await create_ralplan_stage().run(_ctx(tmp_path))
        assert result.status == StageStatus.SUCCESS
        assert result.artifacts["plan_implemented"] is True
        assert result.artifacts["plan"] == "Option-A"
        assert result.artifacts["plan"] != "<未实现>"

    @pytest.mark.asyncio
    async def test_engine_failure_marks_stage_failed(self, tmp_path, monkeypatch):
        import src.workflow.ralplan as rp

        class BoomEngine:
            def __init__(self, **_kw):
                pass

            async def run(self, goal):
                raise RuntimeError("llm down")

        monkeypatch.setattr(rp, "RalplanEngine", BoomEngine)

        result = await create_ralplan_stage().run(_ctx(tmp_path))
        assert result.status == StageStatus.FAILED
        assert "llm down" in (result.error or "")


class TestTeamExecStage:
    @pytest.mark.asyncio
    async def test_real_engine_is_used(self, tmp_path, monkeypatch):
        import src.agent.swarm.engine as eng

        class FakeResult:
            success = True
            final_result = "did the work"
            elapsed_seconds = 1.5
            errors: list[str] = []

        class FakeSwarm:
            def __init__(self, config=None, workdir=None, intent="implement", **_kw):
                assert Path(workdir) == tmp_path

            async def run(self, goal):
                return FakeResult()

        monkeypatch.setattr(eng, "SwarmEngine", FakeSwarm)

        result = await create_team_exec_stage(worker_count=2).run(_ctx(tmp_path))
        assert result.status == StageStatus.SUCCESS
        assert result.artifacts["execution_implemented"] is True
        assert result.artifacts["execution_completed"] is True
        assert result.artifacts["execution_result"] == "did the work"

    @pytest.mark.asyncio
    async def test_swarm_failure_marks_stage_failed(self, tmp_path, monkeypatch):
        import src.agent.swarm.engine as eng

        class FakeResult:
            success = False
            final_result = ""
            elapsed_seconds = 0.1
            errors = ["worker crashed"]

        class FakeSwarm:
            def __init__(self, **_kw):
                pass

            async def run(self, goal):
                return FakeResult()

        monkeypatch.setattr(eng, "SwarmEngine", FakeSwarm)

        result = await create_team_exec_stage().run(_ctx(tmp_path))
        assert result.status == StageStatus.FAILED
        assert "worker crashed" in (result.error or "")


class TestRalphVerifyUsesContextCwd:
    @pytest.mark.asyncio
    async def test_verification_runs_in_ctx_cwd_not_config_default(
        self, tmp_path, monkeypatch
    ):
        """回归：曾用 `self._config.cwd`（默认 "."）而不是 `ctx.cwd`。

        后果：若阶段被挂进管道，会在**进程当前目录**跑测试，
        可能对另一个项目报 passed —— 正是本项目修复过的那类假验证。
        """
        import src.workflow.verification_runner as vr

        seen: dict[str, Path] = {}

        class FakeRun:
            status = "passed"
            verified = True
            command = "fake"
            exit_code = 0
            duration_ms = 1
            reason = ""

            def to_artifacts(self):
                return {"verification_result": "passed", "verified": True}

            class result:  # noqa: N801 - 模拟既有接口
                @staticmethod
                def to_dict():
                    return {"passed": True, "evidence": []}

        def fake_run(workdir, **_kw):
            seen["workdir"] = Path(workdir)
            return FakeRun()

        monkeypatch.setattr(vr, "run_verification", fake_run)

        result = await create_ralph_verify_stage(max_iterations=1).run(_ctx(tmp_path))
        assert result.status == StageStatus.SUCCESS
        assert seen["workdir"] == tmp_path


class TestPrecontextStage:
    @pytest.mark.asyncio
    async def test_scans_target_directory(self, tmp_path):
        """真实的最小扫描：统计源码文件与行数，而不是返回占位字符串。

        历史：该阶段 `from .intake import IntakeGate`，而 `src/workflow/intake.py`
        **从未存在** —— 导入异常被吞后仍返回 SUCCESS。
        """
        (tmp_path / "a.py").write_text("x = 1\n" * 10, encoding="utf-8")
        (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")

        result = await create_precontext_intake_stage().run(_ctx(tmp_path))
        assert result.status == StageStatus.SUCCESS
        assert result.artifacts["intake_completed"] is True
        assert result.artifacts["file_count"] == 2
        assert result.artifacts["line_count"] == 11
        assert "a.py" in result.artifacts["key_files"]
        assert "codebase_summary" in result.artifacts

    @pytest.mark.asyncio
    async def test_failure_is_skipped_not_success(self, tmp_path, monkeypatch):
        """扫描失败时不应报 SUCCESS（那会让人以为上下文已收集）。"""
        def boom(self, pattern):
            raise OSError("disk gone")

        monkeypatch.setattr(Path, "rglob", boom)

        result = await create_precontext_intake_stage().run(_ctx(tmp_path))
        assert result.status == StageStatus.SKIPPED
        assert result.artifacts["intake_failed"] is True

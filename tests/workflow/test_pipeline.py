"""`src/workflow/pipeline.py` 的真实行为测试。

覆盖 `PipelineModeState` 序列化、`PipelineOrchestrator` 的阶段编排/跳过/失败/
持久化/恢复/状态查询/取消，以及四个阶段工厂的判定分支与配置工厂。

阶段一律用本文件内的桩对象驱动：不触网、不调 LLM、不跑真实验证命令。

四条 `xfail(strict=True)` 记录本轮发现的真实缺陷（未修改 `src/`）：

1. `run(task=...)` 的任务文本从未传给阶段 —— `StageContext.task` 拿到的是
   `session_id`（`:340`），且 `PipelineModeState` 没有 task 字段，恢复后原任务丢失；
2. 失败即 `active=False`，而 `run(resume=True)` 要求 `active=True` —— 失败后
   「恢复」会静默从头重跑（`:239`+`:205`）；
3. `_emit_event` 调用 `EventBus.emit()`，该方法不存在（只有 `publish`/
   `publish_async`），且 `"pipeline.start"` 等事件名不在 `EventType` 里 ——
   所有 pipeline 事件被 except 静默丢弃（`:456-466`）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.exceptions import ClawdError
from src.workflow.pipeline import (
    PipelineModeState,
    PipelineOrchestrator,
    create_autopilot_pipeline_config,
    create_precontext_intake_stage,
    create_ralph_verify_stage,
    create_ralplan_stage,
    create_team_exec_stage,
    run_pipeline,
)
from src.workflow.types import (
    PipelineStage,
    StageContext,
    StageResult,
    StageStatus,
)


# ==========================================================================
# 桩阶段
# ==========================================================================


class _StubStage(PipelineStage):
    """可编排的阶段桩：按需返回成功/失败、抛异常、跳过，并记录所见上下文。"""

    def __init__(
        self,
        stage_name: str,
        *,
        artifacts: dict | None = None,
        status: StageStatus = StageStatus.SUCCESS,
        error: str | None = None,
        raises: BaseException | None = None,
        skip: bool = False,
        captured: list | None = None,
    ):
        self._name = stage_name
        self._artifacts = artifacts or {}
        self._status = status
        self._error = error
        self._raises = raises
        self._skip_when = skip
        self.captured = captured if captured is not None else []
        self.run_count = 0

    @property
    def name(self) -> str:
        return self._name

    def can_skip(self, ctx: StageContext) -> bool:
        return self._skip_when

    async def run(self, ctx: StageContext) -> StageResult:
        self.run_count += 1
        self.captured.append(ctx)
        if self._raises is not None:
            raise self._raises
        return StageResult(
            status=self._status, artifacts=dict(self._artifacts), error=self._error
        )


def _orchestrator(tmp_path: Path, stages: list[PipelineStage], **kwargs) -> PipelineOrchestrator:
    return PipelineOrchestrator(workdir=tmp_path, **kwargs).configure(stages)


def _state_file(tmp_path: Path) -> Path:
    return tmp_path / ".clawd" / "state" / "pipeline.json"


# ==========================================================================
# PipelineModeState
# ==========================================================================


class TestPipelineModeState:
    def _state(self, **overrides) -> PipelineModeState:
        payload = {
            "active": True,
            "pipeline_name": "default",
            "pipeline_stages": ["a", "b"],
            "pipeline_stage_index": 0,
            "pipeline_stage_results": {},
            "current_phase": "stage:a",
            "session_id": "sess-1",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        payload.update(overrides)
        return PipelineModeState(**payload)

    def test_defaults(self):
        state = self._state()

        assert state.artifacts == {}
        assert state.max_ralph_iterations == 10
        assert state.worker_count == 2
        assert state.agent_type == "executor"
        assert state.version == "1.0"

    def test_updated_at_initialized_from_created_at(self):
        state = self._state()

        assert state.updated_at == state.created_at

    def test_touch_updates_timestamp(self):
        state = self._state()

        state.touch()

        assert state.updated_at != state.created_at
        assert state.updated_at.startswith("20")

    def test_dict_round_trip(self):
        state = self._state(artifacts={"x": 1}, pipeline_stage_results={"a": {"status": "success"}})

        restored = PipelineModeState.from_dict(state.to_dict())

        assert restored == state
        assert restored.artifacts == {"x": 1}


# ==========================================================================
# 编排器：配置与前置校验
# ==========================================================================


class TestOrchestratorConfiguration:
    def test_configure_is_chainable_and_lists_stages(self, tmp_path):
        orch = PipelineOrchestrator(workdir=tmp_path)

        returned = orch.configure([_StubStage("one"), _StubStage("two")])

        assert returned is orch
        assert orch.list_stages() == ["one", "two"]

    async def test_run_without_stages_fails_loudly(self, tmp_path):
        """未配置阶段时不得"空跑成功"——必须报错。

        2026-10-28 修复：原代码引用不存在的 ErrorCode.INVALID_PARAMETER（AttributeError），
        改为既有枚举 CONFIG_MISSING（"未配置"语义最贴切）。
        """
        orch = PipelineOrchestrator(workdir=tmp_path)

        with pytest.raises(Exception) as excinfo:
            await orch.run("do something")

        # ClawdError.__str__ 用枚举 value（E4001），非枚举名
        assert "E4001" in str(excinfo.value)
        assert "not configured" in str(excinfo.value)

    async def test_run_without_stages_raises_clawd_error(self, tmp_path):
        """2026-10-28 已修复：原 :184 引用不存在的 ErrorCode.INVALID_PARAMETER、:390 引用
        不存在的 ErrorCode.TASK_FAILED，导致契约承诺的 ClawdError 从未抛出（实际
        AttributeError，调用方的 except ClawdError 收不到）。现分别改为 CONFIG_MISSING /
        WORKFLOW_EXECUTION_ERROR。"""

        orch = PipelineOrchestrator(workdir=tmp_path)

        with pytest.raises(ClawdError):
            await orch.run("do something")

    def test_state_file_location(self, tmp_path):
        orch = PipelineOrchestrator(workdir=tmp_path)

        assert orch._state_file == tmp_path / ".clawd" / "state" / "pipeline.json"


# ==========================================================================
# 编排器：顺序执行
# ==========================================================================


class TestOrchestratorExecution:
    async def test_runs_all_stages_and_merges_artifacts(self, tmp_path):
        captured: list[StageContext] = []
        orch = _orchestrator(
            tmp_path,
            [
                _StubStage("first", artifacts={"a": 1}, captured=captured),
                _StubStage("second", artifacts={"b": 2}, captured=captured),
            ],
        )

        artifacts = await orch.run("go")

        assert artifacts == {"a": 1, "b": 2}, "各阶段 artifacts 必须合并进最终结果"
        assert [s.name for s in orch._stages] == ["first", "second"]
        assert orch.get_status()["current_phase"] == "complete"
        assert orch._total_stages_executed == 2

    async def test_artifacts_visible_to_later_stages(self, tmp_path):
        captured: list[StageContext] = []
        orch = _orchestrator(
            tmp_path,
            [
                _StubStage("producer", artifacts={"shared": "value"}, captured=captured),
                _StubStage("consumer", captured=captured),
            ],
        )

        await orch.run("go")

        assert captured[1].artifacts == {"shared": "value"}, "后续阶段必须看到前序产出"

    async def test_initial_artifacts_seeded_into_state(self, tmp_path):
        captured: list[StageContext] = []
        orch = _orchestrator(tmp_path, [_StubStage("only", captured=captured)])

        artifacts = await orch.run("go", initial_artifacts={"seed": True})

        assert captured[0].artifacts == {"seed": True}
        assert artifacts == {"seed": True}

    async def test_stage_cwd_and_session_id_from_orchestrator(self, tmp_path):
        captured: list[StageContext] = []
        orch = _orchestrator(tmp_path, [_StubStage("only", captured=captured)])

        await orch.run("go")

        assert captured[0].cwd == tmp_path
        assert captured[0].session_id == orch._session_id

    async def test_skip_records_skipped_status(self, tmp_path):
        skipped = _StubStage("skipped", skip=True)
        orch = _orchestrator(tmp_path, [skipped, _StubStage("after")])

        artifacts = await orch.run("go")

        assert skipped.run_count == 0, "can_skip 为真的阶段不得被调用"
        assert orch._state.pipeline_stage_results["skipped"]["status"] == "skipped"
        assert artifacts == {}

    async def test_stage_exception_becomes_failed_and_raises(self, tmp_path):
        orch = _orchestrator(
            tmp_path,
            [
                _StubStage("ok", artifacts={"x": 1}),
                _StubStage("boom", raises=RuntimeError("kaboom")),
                _StubStage("never"),
            ],
        )

        with pytest.raises(ClawdError):
            await orch.run("go")

        status = orch.get_status()
        assert status["current_phase"] == "failed"
        assert status["completed_stages"] == ["ok", "boom"]
        assert orch._stages[2].run_count == 0, "失败后不得继续执行后续阶段"

    async def test_explicit_failed_result_also_aborts(self, tmp_path):
        orch = _orchestrator(
            tmp_path,
            [
                _StubStage("bad", status=StageStatus.FAILED, error="assertion failed"),
                _StubStage("never"),
            ],
        )

        with pytest.raises(ClawdError):
            await orch.run("go")

        assert orch._stages[1].run_count == 0
        record = orch._state.pipeline_stage_results["bad"]
        assert record["error"] == "assertion failed"
        assert record["status"] == "failed"

    async def test_stage_durations_are_recorded(self, tmp_path):
        orch = _orchestrator(tmp_path, [_StubStage("only")])

        await orch.run("go")

        record = orch._state.pipeline_stage_results["only"]
        assert record["duration_ms"] >= 0

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "缺陷 src/workflow/pipeline.py:340：StageContext.task 传的是 self._state.session_id，"
            "用户 task 文本从未进入管道；PipelineModeState 也没有 task 字段，"
            "因此 ralplan/team-exec 都在对一个 session id 做规划"
        ),
    )
    async def test_stage_receives_user_task(self, tmp_path):
        captured: list[StageContext] = []
        orch = _orchestrator(tmp_path, [_StubStage("only", captured=captured)])

        await orch.run("重构配置模块")

        assert captured[0].task == "重构配置模块"


# ==========================================================================
# 编排器：持久化与恢复
# ==========================================================================


class TestOrchestratorPersistence:
    async def test_state_file_written_with_progress(self, tmp_path):
        orch = _orchestrator(tmp_path, [_StubStage("only", artifacts={"k": "v"})])

        await orch.run("go")

        payload = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
        assert payload["active"] is False
        assert payload["current_phase"] == "complete"
        assert payload["pipeline_stages"] == ["only"]
        assert payload["artifacts"] == {"k": "v"}
        assert payload["pipeline_stage_results"]["only"]["status"] == "success"

    async def test_persistence_disabled_writes_nothing(self, tmp_path):
        orch = _orchestrator(tmp_path, [_StubStage("only")], enable_persistence=False)

        await orch.run("go")

        assert not _state_file(tmp_path).exists()

    async def test_corrupted_state_file_falls_back_to_fresh_run(self, tmp_path):
        state_file = _state_file(tmp_path)
        state_file.parent.mkdir(parents=True)
        state_file.write_text("{not json", encoding="utf-8")
        stage = _StubStage("only")
        orch = _orchestrator(tmp_path, [stage])

        await orch.run("go", resume=True)

        assert stage.run_count == 1, "状态读不出来时应从头跑一轮，而不是崩溃"

    async def test_resume_starts_at_persisted_stage_index(self, tmp_path):
        """进程中断（state 里 active=True）后必须从记录的下一个阶段继续。"""
        state_file = _state_file(tmp_path)
        state_file.parent.mkdir(parents=True)
        state_file.write_text(
            json.dumps(
                {
                    "active": True,
                    "pipeline_name": "default",
                    "pipeline_stages": ["first", "second"],
                    "pipeline_stage_index": 1,
                    "pipeline_stage_results": {"first": {"status": "success"}},
                    "current_phase": "stage:second",
                    "session_id": "crashed-session",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "artifacts": {"from_first": 1},
                }
            ),
            encoding="utf-8",
        )
        first = _StubStage("first")
        second = _StubStage("second", artifacts={"done": True})
        orch = _orchestrator(tmp_path, [first, second])

        artifacts = await orch.run("go", resume=True)

        assert first.run_count == 0, "已完成的阶段不得重跑"
        assert second.run_count == 1
        assert artifacts == {"from_first": 1, "done": True}, "恢复时要带上历史 artifacts"

    async def test_resume_without_state_runs_fresh(self, tmp_path):
        stage = _StubStage("only")
        orch = _orchestrator(tmp_path, [stage])

        await orch.run("go", resume=True)

        assert stage.run_count == 1

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "缺陷 src/workflow/pipeline.py:239 + :205：失败时写 active=False，而 resume 要求 "
            "active=True —— 失败后 resume=True 会静默重跑已成功的阶段，恢复语义形同虚设"
        ),
    )
    async def test_resume_after_failure_skips_completed_stages(self, tmp_path):
        first = _StubStage("first")
        second = _StubStage("second", raises=RuntimeError("first attempt fails"))
        orch = _orchestrator(tmp_path, [first, second])

        with pytest.raises(ClawdError):
            await orch.run("go")
        second._raises = None
        await orch.run("go", resume=True)

        assert first.run_count == 1, "恢复时重跑了已成功的第一阶段"


# ==========================================================================
# 编排器：状态查询与取消
# ==========================================================================


class TestOrchestratorStatus:
    def test_status_before_run(self, tmp_path):
        orch = PipelineOrchestrator(workdir=tmp_path)

        assert orch.get_status() == {"active": False, "message": "No pipeline running"}

    async def test_status_reports_progress_fields(self, tmp_path):
        orch = _orchestrator(tmp_path, [_StubStage("a"), _StubStage("b")])

        await orch.run("go")

        status = orch.get_status()
        assert status["active"] is False
        assert status["total_stages"] == 2
        assert status["completed_stages"] == ["a", "b"]
        assert status["progress"] == "1/2", "阶段索引语义是「当前正在跑的下标」"

    async def test_status_marks_current_stage_during_run(self, tmp_path):
        seen: dict = {}

        class _Inspecting(_StubStage):
            async def run(self, ctx):
                seen.update(orch.get_status())
                return await super().run(ctx)

        orch = _orchestrator(tmp_path, [_Inspecting("running")])
        await orch.run("go")

        assert seen["current_stage"] == "running"
        assert seen["active"] is True

    async def test_cancel_marks_state_cancelled(self, tmp_path):
        orch = _orchestrator(tmp_path, [_StubStage("only")])
        await orch.run("go")

        orch.cancel()

        assert orch._state.active is False
        assert orch._state.current_phase == "cancelled"
        payload = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
        assert payload["current_phase"] == "cancelled"

    def test_cancel_before_run_is_noop(self, tmp_path):
        orch = PipelineOrchestrator(workdir=tmp_path)

        orch.cancel()

        assert orch._state is None

    async def test_get_artifact_returns_value_and_default(self, tmp_path):
        orch = _orchestrator(tmp_path, [_StubStage("only", artifacts={"k": "v"})])
        await orch.run("go")

        assert orch.get_artifact("k") == "v"
        assert orch.get_artifact("missing", "fallback") == "fallback"

    def test_get_artifact_without_state(self, tmp_path):
        orch = PipelineOrchestrator(workdir=tmp_path)

        assert orch.get_artifact("k", 42) == 42


# ==========================================================================
# 事件
# ==========================================================================


class TestPipelineEvents:
    async def test_emit_event_never_raises(self, tmp_path):
        """事件发送失败不得中断管道（当前实现因此把事件全部丢了，见下方 xfail）。"""
        orch = _orchestrator(tmp_path, [_StubStage("only")])

        await orch._emit_event("pipeline.start", {"x": 1})

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "缺陷 src/workflow/pipeline.py:456-466：EventBus 没有 emit()（只有 publish/"
            "publish_async），且 'pipeline.start'/'pipeline.complete'/'pipeline.failed' 不在 "
            "EventType 枚举里 —— 每个事件都抛异常后被 except 静默吞掉，外部订阅者永远收不到"
        ),
    )
    async def test_events_reach_subscribers(self, tmp_path):
        received: list = []

        class _RecordingBus:
            async def emit(self, event):
                received.append(event)

        orch = PipelineOrchestrator(workdir=tmp_path, event_bus=_RecordingBus())
        orch.configure([_StubStage("only")])

        await orch.run("go")

        assert {e.type for e in received} >= {"pipeline.start", "pipeline.complete"}


# ==========================================================================
# 阶段工厂：判定分支
# ==========================================================================


class TestRalphVerifyStageBranches:
    def _ctx(self, tmp_path: Path) -> StageContext:
        return StageContext(task="t", cwd=tmp_path)

    def _patch_run(self, monkeypatch, **status_kwargs):
        import src.workflow.verification_runner as vr

        class FakeRun:
            status = status_kwargs["status"]
            verified = status_kwargs["verified"]
            command = "pytest"
            exit_code = status_kwargs.get("exit_code", 0)
            duration_ms = 5
            reason = status_kwargs.get("reason", "")

            def to_artifacts(self):
                return {"verification_result": self.status, "verified": self.verified}

            class result:  # noqa: N801 - 复刻既有接口
                @staticmethod
                def to_dict():
                    return {"passed": status_kwargs["verified"]}

        monkeypatch.setattr(vr, "run_verification", lambda workdir, **kw: FakeRun())
        return FakeRun

    async def test_failed_verification_fails_stage(self, tmp_path, monkeypatch):
        self._patch_run(monkeypatch, status="failed", verified=False, exit_code=1, reason="1 failed")

        result = await create_ralph_verify_stage().run(self._ctx(tmp_path))

        assert result.status == StageStatus.FAILED
        assert result.error == "1 failed"
        assert result.artifacts["verification_result"] == "failed"
        assert result.artifacts["verification_completed"] is True

    async def test_timeout_fails_stage(self, tmp_path, monkeypatch):
        self._patch_run(monkeypatch, status="timeout", verified=False, exit_code=None)

        result = await create_ralph_verify_stage().run(self._ctx(tmp_path))

        assert result.status == StageStatus.FAILED, "超时不能被当成通过"

    async def test_not_configured_is_skipped(self, tmp_path, monkeypatch):
        self._patch_run(monkeypatch, status="not_configured", verified=False, reason="no command")

        result = await create_ralph_verify_stage().run(self._ctx(tmp_path))

        assert result.status == StageStatus.SKIPPED
        assert result.skipped_reason == "no command"
        assert result.artifacts["verification_completed"] is False

    async def test_retry_note_only_when_configured_more_than_once(self, tmp_path, monkeypatch):
        self._patch_run(monkeypatch, status="passed", verified=True)

        single = await create_ralph_verify_stage(max_iterations=1).run(self._ctx(tmp_path))
        many = await create_ralph_verify_stage(max_iterations=5).run(self._ctx(tmp_path))

        assert "note" not in single.artifacts
        assert "note" in many.artifacts
        assert many.artifacts["iterations"] == 1
        assert many.artifacts["max_iterations"] == 5


class TestTeamExecStageSkip:
    async def test_skips_when_execution_result_present(self, tmp_path):
        stage = create_team_exec_stage(worker_count=3, agent_type="auditor")
        ctx = StageContext(task="t", cwd=tmp_path, artifacts={"execution_result": "already"})

        assert stage.name == "team-exec"
        assert stage.can_skip(ctx) is True
        assert stage.can_skip(StageContext(task="t", cwd=tmp_path)) is False
        assert stage.worker_count == 3
        assert stage.agent_type == "auditor"


class TestPrecontextStageLimits:
    async def test_reports_largest_files_first(self, tmp_path):
        (tmp_path / "small.py").write_text("a = 1\n", encoding="utf-8")
        (tmp_path / "big.py").write_text("b = 1\n" * 50, encoding="utf-8")

        result = await create_precontext_intake_stage().run(
            StageContext(task="t", cwd=tmp_path)
        )

        assert result.artifacts["key_files"][0] == "big.py", "key_files 应按体积倒序"
        assert result.artifacts["line_count"] == 51


class TestStageNames:
    def test_factory_names_are_stable(self):
        assert create_ralplan_stage().name == "ralplan"
        assert create_team_exec_stage().name == "team-exec"
        assert create_ralph_verify_stage().name == "ralph-verify"
        assert create_precontext_intake_stage().name == "precontext-intake"


# ==========================================================================
# 配置工厂与便捷入口
# ==========================================================================


class TestAutopilotConfig:
    def test_default_stage_sequence(self):
        config = create_autopilot_pipeline_config(task="do it")

        assert [s.name for s in config["stages"]] == [
            "precontext-intake",
            "ralplan",
            "team-exec",
            "ralph-verify",
        ]
        assert config["task"] == "do it"
        assert config["session_id"] and len(config["session_id"]) == 12

    def test_intake_can_be_disabled(self):
        config = create_autopilot_pipeline_config(task="do it", enable_intake=False)

        assert [s.name for s in config["stages"]] == ["ralplan", "team-exec", "ralph-verify"]

    def test_custom_stages_are_used_as_is(self):
        stages = [_StubStage("custom")]

        config = create_autopilot_pipeline_config(task="t", stages=stages)

        assert config["stages"] is stages

    def test_options_are_echoed(self):
        config = create_autopilot_pipeline_config(
            task="t", worker_count=7, max_ralph_iterations=3
        )

        assert config["worker_count"] == 7
        assert config["max_ralph_iterations"] == 3
        assert config["created_at"].startswith("20")


class TestRunPipelineHelper:
    async def test_runs_configured_stages_end_to_end(self, tmp_path, monkeypatch):
        """`run_pipeline` 必须把配置里的 stages 真的挂到编排器并跑完。"""
        import src.workflow.pipeline as pipeline_mod

        monkeypatch.setattr(
            pipeline_mod,
            "create_autopilot_pipeline_config",
            lambda **kwargs: {
                "task": kwargs["task"],
                "stages": [_StubStage("stub-a", artifacts={"a": 1}), _StubStage("stub-b", artifacts={"b": 2})],
            },
        )

        result = await run_pipeline("do it", workdir=tmp_path)

        assert result == {"a": 1, "b": 2}
        payload = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
        assert payload["current_phase"] == "complete"

    async def test_forwards_orchestrator_kwargs(self, tmp_path, monkeypatch):
        import src.workflow.pipeline as pipeline_mod

        monkeypatch.setattr(
            pipeline_mod,
            "create_autopilot_pipeline_config",
            lambda **kwargs: {"task": kwargs["task"], "stages": [_StubStage("only")]},
        )

        await run_pipeline("do it", workdir=tmp_path, enable_persistence=False)

        assert not _state_file(tmp_path).exists(), "**kwargs 必须透传给 PipelineOrchestrator"

"""Pipeline Orchestrator 测试套件。

## 重要背景（为什么这个文件被整体重写）

本文件最初从模板生成，**从初始提交起就没有通过过**。它引用了一套
从未存在于本仓库的 API：

| 测试里的写法 | 仓库真实情况 |
|:---|:---|
| `StageStatus.COMPLETED` | 真实枚举只有 `SUCCESS / SKIPPED / FAILED` |
| `StageResult("completed", ...)` | 第一个位置参数是 `status: StageStatus` |
| `PipelineConfig(..., state_file=...)` | 该参数不存在 |
| `PipelineState.load()` 抛 `ValueError` | 实际返回 `None`（日志记录错误） |
| `orchestrator.cancel()` 后 `await` 抛 `CancelledError` | 实际在阶段间检查标志并返回 `status="cancelled"` |
| `create_pipeline(stages=[裸函数])` 可运行 | 实际 `_validate_config` 访问 `s.name` 立刻 AttributeError |

重写原则：**保留每个用例原本要验证的行为意图**，只把调用面换成真实 API；
不删除场景、不放宽断言。重写过程中顺带修掉了 4 个真实缺陷（见各用例注释）：

1. `PipelineState.save(state_file)` 忽略传入路径
2. `PipelineState.can_resume()` 恒为 False（阶段列表永远存空）
3. `PipelineConfig.cwd` 从未生效
4. `create_pipeline()` 不接受裸可调用对象
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from src.workflow.pipeline_orchestrator import (
    PipelineOrchestrator,
    PipelineState,
    StageAdapter,
    create_pipeline,
)
from src.workflow.types import PipelineConfig, StageContext, StageResult, StageStatus


def _ok(artifacts: dict | None = None, ms: int = 1) -> StageResult:
    return StageResult(
        status=StageStatus.SUCCESS,
        artifacts=artifacts or {},
        duration_ms=ms,
    )


@pytest.fixture
def temp_workspace():
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)


# ==========================================================================
# PipelineState
# ==========================================================================


class TestPipelineState:
    def test_save_and_load_round_trip(self, temp_workspace):
        """状态写入指定路径后必须能从该路径读回。

        这条用例同时是 `save(state_file=...)` 的回归：
        修复前该参数被完全忽略，文件永远写到 `<cwd>/.clawd/pipeline/`。
        """
        state_file = temp_workspace / "test_state.json"
        state = PipelineState(
            pipeline_name="test_pipeline",
            current_stage_index=2,
            stage_results={
                "stage1": _ok({"a": 1}, 10),
                "stage2": _ok({"b": 2}, 20),
            },
            artifacts={"global": "data"},
            stage_names=["stage1", "stage2", "stage3"],
        )
        state.save(str(state_file))

        assert state_file.exists(), "save(state_file=...) 未写入指定路径"

        loaded = PipelineState.load(str(state_file))
        assert loaded is not None
        assert loaded.pipeline_name == "test_pipeline"
        assert loaded.current_stage_index == 2
        assert loaded.stage_results["stage1"].status == StageStatus.SUCCESS
        assert loaded.stage_results["stage1"].artifacts == {"a": 1}
        # artifacts 必须往返（原实现 save/load 都不带它，会静默丢失）
        assert loaded.artifacts == {"global": "data"}
        # 阶段名必须往返：can_resume 依赖它
        assert loaded.stage_names == ["stage1", "stage2", "stage3"]

    def test_load_then_save_keeps_resumable(self, temp_workspace):
        """`load → save` 后 can_resume 不得由 True 变 False。

        这是"只修了写出侧、没修读入侧"的回归探针：load 若不恢复
        stage_names，再 save 会把 pipeline_stages 写成 []，续跑能力丢失。
        """
        state_file = temp_workspace / "resumable.json"
        PipelineState(
            pipeline_name="p",
            current_stage_index=1,
            stage_results={"s0": _ok()},
            stage_names=["s0", "s1"],
        ).save(str(state_file))
        assert PipelineState.can_resume(str(state_file)) is True

        loaded = PipelineState.load(str(state_file))
        assert loaded is not None
        loaded.save(str(state_file))

        assert PipelineState.can_resume(str(state_file)) is True, (
            "load→save 之后失去了续跑能力"
        )

    def test_load_missing_file_returns_none(self, temp_workspace):
        assert PipelineState.load(str(temp_workspace / "nope.json")) is None

    def test_load_invalid_file_returns_none_and_logs(self, temp_workspace, caplog):
        """损坏的 JSON 不应把异常抛给调用方，而是返回 None 并记录错误。

        原测试期望 `ValueError` —— 那是想象中的契约。真实实现选择
        "读不到就当没有状态"，这是更安全的恢复语义（pipeline 从头跑）。
        """
        invalid = temp_workspace / "invalid.json"
        invalid.write_text("not json", encoding="utf-8")

        assert PipelineState.load(str(invalid)) is None
        assert any("Failed to load pipeline state" in r.getMessage() for r in caplog.records)

    def test_save_is_atomic_enough(self, temp_workspace):
        """保存后不应残留临时文件，主文件必须存在。"""
        state_file = temp_workspace / "state.json"
        PipelineState(pipeline_name="atomic_test").save(str(state_file))

        assert state_file.exists()
        assert list(temp_workspace.glob("*.tmp")) == []

    def test_can_resume_true_when_stages_remain(self, temp_workspace):
        state_file = temp_workspace / "resume.json"
        PipelineState(
            pipeline_name="resume_test",
            current_stage_index=1,
            stage_results={"stage0": _ok()},
            stage_names=["stage0", "stage1"],
        ).save(str(state_file))

        assert PipelineState.can_resume(str(state_file)) is True

    def test_can_resume_false_when_all_stages_done(self, temp_workspace):
        state_file = temp_workspace / "completed.json"
        PipelineState(
            pipeline_name="completed_test",
            current_stage_index=2,
            stage_results={"stage0": _ok(), "stage1": _ok()},
            stage_names=["stage0", "stage1"],
        ).save(str(state_file))

        assert PipelineState.can_resume(str(state_file)) is False

    def test_can_resume_false_for_missing_file(self, temp_workspace):
        assert PipelineState.can_resume(str(temp_workspace / "missing.json")) is False

    def test_get_resume_index(self, temp_workspace):
        state_file = temp_workspace / "resume_index.json"
        PipelineState(
            pipeline_name="index_test",
            current_stage_index=2,
            stage_results={"stage0": _ok(), "stage1": _ok()},
            stage_names=["stage0", "stage1", "stage2"],
        ).save(str(state_file))

        assert PipelineState.get_resume_index(str(state_file)) == 2

    def test_clear_removes_file(self, temp_workspace):
        state_file = temp_workspace / "clear.json"
        state = PipelineState(pipeline_name="clear_test")
        state.save(str(state_file))
        assert state_file.exists()

        state.clear(str(state_file))
        assert not state_file.exists()


# ==========================================================================
# StageAdapter
# ==========================================================================


class TestStageAdapter:
    @pytest.mark.asyncio
    async def test_adapt_async_function(self):
        async def my_stage(ctx: StageContext) -> StageResult:
            return _ok({"result": "ok"}, 5)

        adapter = StageAdapter("async_stage", my_stage)
        ctx = StageContext(task="test", cwd=Path("/tmp"))
        result = await adapter.run(ctx)

        assert adapter.name == "async_stage"
        assert result.status == StageStatus.SUCCESS
        assert result.artifacts["result"] == "ok"

    @pytest.mark.asyncio
    async def test_adapt_sync_function(self):
        def my_sync_stage(ctx: StageContext) -> StageResult:
            return _ok({"sync": True}, 3)

        adapter = StageAdapter("sync_stage", my_sync_stage)
        ctx = StageContext(task="test", cwd=Path("/tmp"))
        result = await adapter.run(ctx)

        assert result.status == StageStatus.SUCCESS
        assert result.artifacts["sync"] is True

    def test_can_skip_default_false(self):
        async def stage(ctx: StageContext) -> StageResult:
            return _ok()

        adapter = StageAdapter("test", stage)
        ctx = StageContext(task="test", cwd=Path("/tmp"))
        assert adapter.can_skip(ctx) is False

    def test_can_skip_custom(self):
        async def stage(ctx: StageContext) -> StageResult:
            return _ok()

        adapter = StageAdapter(
            "test",
            stage,
            can_skip=lambda ctx: ctx.artifacts.get("skip_me") is True,
        )

        assert adapter.can_skip(StageContext(task="t", cwd=Path("/tmp"), artifacts={"skip_me": True})) is True
        assert adapter.can_skip(StageContext(task="t", cwd=Path("/tmp"))) is False


# ==========================================================================
# PipelineOrchestrator
# ==========================================================================


class TestPipelineOrchestrator:
    @pytest.mark.asyncio
    async def test_basic_pipeline_execution(self, temp_workspace):
        async def stage1(ctx):
            return _ok({"stage1": "done"}, 10)

        async def stage2(ctx):
            return _ok({"stage2": "executed"}, 10)

        config = PipelineConfig(
            name="basic_test",
            task="test task",
            stages=[StageAdapter("stage1", stage1), StageAdapter("stage2", stage2)],
        )
        result = await PipelineOrchestrator(config, cwd=str(temp_workspace)).run()

        assert result.status == "completed"
        assert len(result.stage_results) == 2
        assert result.stage_results["stage1"].status == StageStatus.SUCCESS
        assert result.stage_results["stage2"].status == StageStatus.SUCCESS
        # PipelineResult.artifacts 是**扁平合并**（各阶段 artifacts 依次 update）。
        # 按阶段分组的数据在 stage_results[name].artifacts 里。
        assert result.artifacts == {"stage1": "done", "stage2": "executed"}
        assert result.stage_results["stage1"].artifacts == {"stage1": "done"}
        assert result.stage_results["stage2"].artifacts == {"stage2": "executed"}

    @pytest.mark.asyncio
    async def test_stage_failure_stops_pipeline(self, temp_workspace):
        async def stage1(ctx):
            return _ok({"stage1": "done"})

        async def stage_bad(ctx):
            raise ValueError("intentional failure")

        async def stage3(ctx):
            return _ok({"stage3": "should_not_run"})

        config = PipelineConfig(
            name="failure_test",
            task="test task",
            stages=[
                StageAdapter("stage1", stage1),
                StageAdapter("stage2", stage_bad),
                StageAdapter("stage3", stage3),
            ],
        )
        result = await PipelineOrchestrator(config, cwd=str(temp_workspace)).run()

        assert result.status == "failed"
        assert result.failed_stage == "stage2"
        assert result.stage_results["stage2"].status == StageStatus.FAILED
        assert "intentional failure" in (result.stage_results["stage2"].error or "")
        assert "stage3" not in result.stage_results

    @pytest.mark.asyncio
    async def test_cancel_returns_cancelled_status(self, temp_workspace):
        """取消语义：阶段之间检查标志并返回 status="cancelled"。

        原测试期望 `await task` 抛 `CancelledError` —— 真实实现是协作式取消，
        不抛异常。这不改变"取消后停止执行后续阶段"的核心意图。
        """
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_stage(ctx):
            started.set()
            await release.wait()
            return _ok({"slow": True})

        async def never_stage(ctx):
            return _ok({"never": True})

        config = PipelineConfig(
            name="cancel_test",
            task="test task",
            stages=[StageAdapter("slow", slow_stage), StageAdapter("never", never_stage)],
        )
        orch = PipelineOrchestrator(config, cwd=str(temp_workspace))
        task = asyncio.create_task(orch.run())
        await started.wait()
        orch.cancel()
        release.set()

        result = await task
        assert result.status == "cancelled"
        assert "never" not in result.stage_results

    @pytest.mark.asyncio
    async def test_stage_transition_callback(self, temp_workspace):
        transitions = []

        async def stage1(ctx):
            return _ok()

        async def stage2(ctx):
            return _ok()

        config = PipelineConfig(
            name="callback_test",
            task="test task",
            stages=[StageAdapter("stage1", stage1), StageAdapter("stage2", stage2)],
            on_stage_transition=lambda a, b: transitions.append((a, b)),
        )
        result = await PipelineOrchestrator(config, cwd=str(temp_workspace)).run()

        assert result.status == "completed"
        assert transitions == [("stage1", "stage2")]

    @pytest.mark.asyncio
    async def test_conditional_skip(self, temp_workspace):
        executed = []

        async def stage1(ctx):
            executed.append("stage1")
            return _ok({"stage1": True})

        class SkippingStage:
            name = "stage2"

            async def run(self, ctx):
                executed.append("stage2")
                return _ok({"stage2": True})

            def can_skip(self, ctx):
                return bool(ctx.artifacts.get("stage1"))

        config = PipelineConfig(
            name="skip_test",
            task="test task",
            stages=[StageAdapter("stage1", stage1), SkippingStage()],
        )
        result = await PipelineOrchestrator(config, cwd=str(temp_workspace)).run()

        assert result.status == "completed"
        assert executed == ["stage1"]
        # 被跳过的阶段会记录为 SKIPPED，而不是"不存在"
        assert result.stage_results["stage2"].status == StageStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_artifacts_propagation(self, temp_workspace):
        seen = {}

        async def stage1(ctx):
            return _ok({"data": "from_stage1"})

        async def stage2(ctx):
            seen.update(ctx.artifacts)
            return _ok({"stage2": True})

        config = PipelineConfig(
            name="artifacts_test",
            task="test task",
            stages=[StageAdapter("stage1", stage1), StageAdapter("stage2", stage2)],
        )
        result = await PipelineOrchestrator(config, cwd=str(temp_workspace)).run()

        assert result.status == "completed"
        # 阶段间传递的是嵌套结构：{上一阶段名: 其 artifacts}
        assert seen["stage1"] == {"data": "from_stage1"}
        # 最终结果是扁平合并
        assert result.artifacts["data"] == "from_stage1"
        assert result.artifacts["stage2"] is True

    @pytest.mark.asyncio
    async def test_duration_calculation(self, temp_workspace):
        async def fast(ctx):
            return _ok({}, 1)

        config = PipelineConfig(
            name="duration_test",
            task="test task",
            stages=[StageAdapter("fast", fast)],
        )
        result = await PipelineOrchestrator(config, cwd=str(temp_workspace)).run()

        assert result.duration_ms >= 0
        assert result.stage_results["fast"].duration_ms >= 0

    def test_empty_stages_rejected(self):
        """空阶段列表必须在**配置校验**阶段被拒绝。

        原测试期望"空 pipeline 正常完成"——那会让调用方以为跑过了实际什么也没做。
        真实实现选择显式报错，这是更安全的行为，故按真实契约断言。
        """
        with pytest.raises(ValueError, match="at least one stage"):
            PipelineOrchestrator(
                PipelineConfig(name="empty", task="t", stages=[])
            )

    @pytest.mark.asyncio
    async def test_multiple_failures_stop_at_first(self, temp_workspace):
        async def fail_stage(ctx):
            raise ValueError("failed")

        async def succeed(ctx):
            return _ok()

        config = PipelineConfig(
            name="multi_fail_test",
            task="test task",
            stages=[
                StageAdapter("fail1", fail_stage),
                StageAdapter("succeed", succeed),
                StageAdapter("fail2", fail_stage),
            ],
        )
        result = await PipelineOrchestrator(config, cwd=str(temp_workspace)).run()

        assert result.status == "failed"
        assert result.failed_stage == "fail1"
        assert "succeed" not in result.stage_results
        assert "fail2" not in result.stage_results

    @pytest.mark.asyncio
    async def test_resume_after_failure(self, temp_workspace):
        """失败后第二次运行必须从**失败的那一个阶段**继续。

        这是旧测试文件里 `test_resume_after_failure` 的等价实现。
        重写时曾遗漏该场景，而它恰好暴露了两个真实缺陷：

        1. `run()` 先 `start_mode()`（写 index=0）再 `can_resume()`，
           永远读到 0 → 从头重跑；
        2. `_complete_pipeline("failed")` 写 `active=False` + phase `"failed"`，
           而 `can_resume()` 排除 `"failed"` → 失败后永不可恢复。
        """
        calls = {"s1": 0, "s2": 0, "s3": 0}

        async def s1(ctx):
            calls["s1"] += 1
            return _ok({"s1": calls["s1"]})

        async def s2(ctx):
            calls["s2"] += 1
            if calls["s2"] == 1:
                raise ValueError("first attempt fails")
            return _ok({"s2": calls["s2"]})

        async def s3(ctx):
            calls["s3"] += 1
            return _ok({"s3": calls["s3"]})

        cfg = PipelineConfig(
            name="resume_test",
            task="test task",
            stages=[
                StageAdapter("s1", s1),
                StageAdapter("s2", s2),
                StageAdapter("s3", s3),
            ],
        )

        first = await PipelineOrchestrator(cfg, cwd=str(temp_workspace)).run()
        assert first.status == "failed"
        assert first.failed_stage == "s2"
        assert calls == {"s1": 1, "s2": 1, "s3": 0}

        second = await PipelineOrchestrator(cfg, cwd=str(temp_workspace)).run()
        assert second.status == "completed"
        # s1 已完成 → 不得重跑；s2 失败 → 必须重试；s3 首次执行
        assert calls["s1"] == 1, "恢复时重跑了已完成的阶段"
        assert calls["s2"] == 2, "失败阶段未被重试"
        assert calls["s3"] == 1

    @pytest.mark.asyncio
    async def test_completed_pipeline_is_not_resumed(self, temp_workspace):
        """已完成的 pipeline 不得被当作可恢复状态。"""
        calls = {"n": 0}

        async def only(ctx):
            calls["n"] += 1
            return _ok()

        cfg = PipelineConfig(
            name="done_test", task="t", stages=[StageAdapter("only", only)]
        )
        await PipelineOrchestrator(cfg, cwd=str(temp_workspace)).run()
        await PipelineOrchestrator(cfg, cwd=str(temp_workspace)).run()
        # 第二次是全新运行（因为第一次已完成），所以执行两次
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_custom_cwd_and_session_id(self, temp_workspace):
        """`PipelineConfig.cwd` 必须真正传到 StageContext。

        修复前 `_build_context` 只读构造器参数 `self._cwd`，
        `config.cwd` 被完全忽略。
        """
        custom = str(temp_workspace / "custom")
        captured = {}

        async def check(ctx):
            captured["cwd"] = str(ctx.cwd)
            captured["session"] = ctx.session_id
            return _ok()

        config = PipelineConfig(
            name="ctx_test",
            task="test task",
            stages=[StageAdapter("check", check)],
            cwd=custom,
            session_id="session-123",
        )
        result = await PipelineOrchestrator(config, cwd=str(temp_workspace)).run()

        assert result.status == "completed"
        assert captured["cwd"] == custom
        assert captured["session"] == "session-123"

    @pytest.mark.asyncio
    async def test_state_is_written_to_mode_state(self, temp_workspace):
        """pipeline 运行后 ModeStateManager 中应留下真实阶段进度。"""
        from src.workflow.pipeline_orchestrator import read_pipeline_state

        async def stage1(ctx):
            return _ok({"value": 1}, 10)

        config = PipelineConfig(
            name="persistence_test",
            task="test task",
            stages=[StageAdapter("stage1", stage1)],
        )
        result = await PipelineOrchestrator(config, cwd=str(temp_workspace)).run()
        assert result.status == "completed"

        ext = read_pipeline_state(str(temp_workspace))
        assert ext is not None
        assert ext.pipeline_name == "persistence_test"
        assert ext.pipeline_stage_index == 1
        assert "stage1" in ext.pipeline_stage_results


# ==========================================================================
# create_pipeline
# ==========================================================================


class TestCreatePipeline:
    @pytest.mark.asyncio
    async def test_create_from_bare_functions(self):
        """裸可调用对象应被自动包装成 StageAdapter。

        修复前 `create_pipeline(stages=[func])` 会在 `_validate_config`
        访问 `s.name` 时抛 AttributeError。
        """
        async def stage1(ctx):
            return _ok({"step": 1})

        async def stage2(ctx):
            return _ok({"step": 2})

        pipeline = create_pipeline(name="function_stages", task="test", stages=[stage1, stage2])

        assert pipeline.config.name == "function_stages"
        assert [s.name for s in pipeline.config.stages] == ["stage1", "stage2"]

        result = await pipeline.run()
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_create_from_pipeline_stage_objects(self):
        class MyStage:
            name = "mystage"

            async def run(self, ctx):
                return _ok()

        pipeline = create_pipeline(name="object_stages", task="test", stages=[MyStage()])

        assert len(pipeline.config.stages) == 1
        assert isinstance(pipeline.config.stages[0], MyStage)

        result = await pipeline.run()
        assert result.status == "completed"

    def test_create_rejects_invalid_stage(self):
        with pytest.raises(TypeError, match=r"stages\[0\]"):
            create_pipeline(name="bad", task="t", stages=[object()])

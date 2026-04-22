"""
Pipeline Orchestrator 完整测试套件

覆盖：
- 状态持久化（PipelineState）
- 恢复机制
- 条件跳过
- 阶段失败处理
- 取消功能
- StageAdapter 适配器
"""

import asyncio
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List

import pytest

from src.workflow.types import (
    StageContext,
    StageResult,
    PipelineStage,
    PipelineConfig,
    PipelineResult,
    StageStatus,
)
from src.workflow.pipeline_orchestrator import (
    PipelineState,
    PipelineOrchestrator,
    StageAdapter,
    create_pipeline,
)


# ========== Fixtures ==========

@pytest.fixture
def temp_workspace():
    """临时工作目录"""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir)


@pytest.fixture
def sample_stages():
    """示例阶段列表"""
    stages = []
    
    # 阶段 1: 快速成功
    async def stage1(ctx: StageContext) -> StageResult:
        await asyncio.sleep(0.01)
        return StageResult(
            status=StageStatus.COMPLETED,
            artifacts={"stage1": "done"},
            duration_ms=10,
        )
    
    # 阶段 2: 可跳过（检查 artifacts）
    class Stage2:
        name = "stage2"
        
        async def run(self, ctx: StageContext) -> StageResult:
            await asyncio.sleep(0.01)
            return StageResult(
                status=StageStatus.COMPLETED,
                artifacts={"stage2": "executed"},
                duration_ms=10,
            )
        
        def can_skip(self, ctx: StageContext) -> bool:
            return ctx.artifacts and "stage1" in ctx.artifacts
    
    # 阶段 3: 失败
    async def stage3(ctx: StageContext) -> StageResult:
        raise ValueError(" intentional failure")
    
    # 阶段 4: 取消后执行
    async def stage4(ctx: StageContext) -> StageResult:
        await asyncio.sleep(0.01)
        return StageResult(
            status=StageStatus.COMPLETED,
            artifacts={"stage4": "should_not_run"},
            duration_ms=10,
        )
    
    stages = [
        StageAdapter("stage1", stage1),
        Stage2(),
        stage3,
        StageAdapter("stage4", stage4),
    ]
    return stages


# ========== PipelineState 测试 ==========

class TestPipelineState:
    """PipelineState 状态持久化管理器测试"""

    def test_save_and_load(self, temp_workspace):
        """测试状态保存和加载"""
        state_file = temp_workspace / "test_state.json"
        
        state = PipelineState(
            pipeline_name="test_pipeline",
            current_stage_index=2,
            stage_results={
                "stage1": StageResult("completed", {"a": 1}, 10),
                "stage2": StageResult("completed", {"b": 2}, 20),
            },
            artifacts={"global": "data"},
        )
        
        # 保存
        state.save(str(state_file))
        assert state_file.exists()
        
        # 加载
        loaded = PipelineState.load(str(state_file))
        assert loaded.pipeline_name == "test_pipeline"
        assert loaded.current_stage_index == 2
        assert loaded.stage_results["stage1"].status == "completed"
        assert loaded.artifacts["global"] == "data"

    def test_load_invalid_file(self, temp_workspace):
        """测试加载无效状态文件"""
        invalid_file = temp_workspace / "invalid.json"
        invalid_file.write_text("not json")
        
        with pytest.raises(ValueError, match="Invalid pipeline state file"):
            PipelineState.load(str(invalid_file))

    def test_save_atomic(self, temp_workspace):
        """测试原子写入（.tmp 临时文件）"""
        state_file = temp_workspace / "state.json"
        
        state = PipelineState(pipeline_name="atomic_test")
        state.save(str(state_file))
        
        # 不应存在 .tmp 文件
        tmp_files = list(temp_workspace.glob("*.tmp"))
        assert len(tmp_files) == 0
        
        # 主文件应存在
        assert state_file.exists()

    def test_can_resume_true(self, temp_workspace):
        """测试可恢复状态"""
        state_file = temp_workspace / "resume.json"
        
        state = PipelineState(
            pipeline_name="resume_test",
            current_stage_index=1,  # 未完成
            stage_results={"stage0": StageResult("completed", {}, 10)},
        )
        state.save(str(state_file))
        
        assert PipelineState.can_resume(str(state_file)) is True

    def test_can_resume_false_completed(self, temp_workspace):
        """测试已完成 pipeline 不可恢复"""
        state_file = temp_workspace / "completed.json"
        
        state = PipelineState(
            pipeline_name="completed_test",
            current_stage_index=3,
            stage_results={
                "stage0": StageResult("completed", {}, 10),
                "stage1": StageResult("completed", {}, 10),
                "stage2": StageResult("completed", {}, 10),
            },
        )
        state.save(str(state_file))
        
        assert PipelineState.can_resume(str(state_file)) is False

    def test_get_resume_index(self, temp_workspace):
        """测试获取恢复索引"""
        state_file = temp_workspace / "resume_index.json"
        
        state = PipelineState(
            pipeline_name="index_test",
            current_stage_index=2,
            stage_results={
                "stage0": StageResult("completed", {}, 10),
                "stage1": StageResult("completed", {}, 10),
            },
        )
        state.save(str(state_file))
        
        assert PipelineState.get_resume_index(str(state_file)) == 2


# ========== StageAdapter 测试 ==========

class TestStageAdapter:
    """StageAdapter 适配器测试"""

    @pytest.mark.asyncio
    async def test_adapt_async_function(self):
        """测试适配异步函数"""
        async def my_stage(ctx: StageContext) -> StageResult:
            return StageResult("completed", {"result": "ok"}, 5)
        
        adapter = StageAdapter("async_stage", my_stage)
        
        ctx = StageContext(task="test", cwd="/tmp")
        result = await adapter.run(ctx)
        
        assert adapter.name == "async_stage"
        assert result.status == "completed"
        assert result.artifacts["result"] == "ok"

    @pytest.mark.asyncio
    async def test_adapt_sync_function(self):
        """测试适配同步函数"""
        def my_sync_stage(ctx: StageContext) -> StageResult:
            return StageResult("completed", {"sync": True}, 3)
        
        adapter = StageAdapter("sync_stage", my_sync_stage)
        
        ctx = StageContext(task="test", cwd="/tmp")
        result = await adapter.run(ctx)
        
        assert result.status == "completed"
        assert result.artifacts["sync"] is True

    def test_can_skip_default_false(self):
        """测试默认 can_skip 返回 False"""
        async def stage(ctx: StageContext) -> StageResult:
            return StageResult("completed", {}, 1)
        
        adapter = StageAdapter("test", stage)
        ctx = StageContext(task="test", cwd="/tmp")
        
        assert adapter.can_skip(ctx) is False

    def test_can_skip_custom(self):
        """测试自定义 can_skip"""
        async def stage(ctx: StageContext) -> StageResult:
            return StageResult("completed", {}, 1)
        
        def custom_can_skip(ctx: StageContext) -> bool:
            return ctx.artifacts.get("skip_me") is True
        
        adapter = StageAdapter("test", stage, can_skip=custom_can_skip)
        
        ctx1 = StageContext(task="test", cwd="/tmp", artifacts={"skip_me": True})
        assert adapter.can_skip(ctx1) is True
        
        ctx2 = StageContext(task="test", cwd="/tmp")
        assert adapter.can_skip(ctx2) is False


# ========== PipelineOrchestrator 测试 ==========

class TestPipelineOrchestrator:
    """PipelineOrchestrator 编排器测试"""

    @pytest.mark.asyncio
    async def test_basic_pipeline_execution(self, sample_stages):
        """测试基础 pipeline 执行"""
        config = PipelineConfig(
            name="basic_test",
            task="test task",
            stages=sample_stages[:2],  # 只取前两个成功阶段
        )
        
        orchestrator = PipelineOrchestrator(config)
        result = await orchestrator.run()
        
        assert result.status == StageStatus.COMPLETED
        assert len(result.stage_results) == 2
        assert result.stage_results["stage1"].status == "completed"
        assert result.stage_results["stage2"].status == "completed"
        assert result.artifacts["stage1"]["stage1"] == "done"
        assert result.artifacts["stage2"]["stage2"] == "executed"

    @pytest.mark.asyncio
    async def test_stage_failure_stops_pipeline(self, sample_stages):
        """测试阶段失败时 pipeline 停止"""
        config = PipelineConfig(
            name="failure_test",
            task="test task",
            stages=sample_stages[:3],  # 包含失败的 stage3
        )
        
        orchestrator = PipelineOrchestrator(config)
        result = await orchestrator.run()
        
        assert result.status == StageStatus.FAILED
        assert result.failed_stage == "stage3"
        assert len(result.stage_results) == 3
        assert result.stage_results["stage3"].status == "failed"
        assert "intentional failure" in result.stage_results["stage3"].error

    @pytest.mark.asyncio
    async def test_cancel_pipeline(self, sample_stages):
        """测试取消 pipeline"""
        config = PipelineConfig(
            name="cancel_test",
            task="test task",
            stages=sample_stages,  # 包含 stage4（不应执行）
        )
        
        orchestrator = PipelineOrchestrator(config)
        
        # 启动 pipeline（后台运行）
        task = asyncio.create_task(orchestrator.run())
        
        # 等待第一个阶段完成
        await asyncio.sleep(0.02)
        
        # 取消
        orchestrator.cancel()
        
        with pytest.raises(asyncio.CancelledError):
            await task
        
        # 验证当前阶段是 stage1（已完成的第一个阶段）
        assert orchestrator.state.current_stage_index == 0

    @pytest.mark.asyncio
    async def test_stage_transition_callback(self, sample_stages):
        """测试阶段转换回调"""
        transitions = []
        
        def on_transition(from_stage: str, to_stage: str):
            transitions.append((from_stage, to_stage))
        
        config = PipelineConfig(
            name="callback_test",
            task="test task",
            stages=sample_stages[:2],
            on_stage_transition=on_transition,
        )
        
        orchestrator = PipelineOrchestrator(config)
        result = await orchestrator.run()
        
        assert result.status == StageStatus.COMPLETED
        # 应有两次转换："" -> stage1, stage1 -> stage2
        assert len(transitions) == 2
        assert transitions[0] == ("", "stage1")
        assert transitions[1] == ("stage1", "stage2")

    @pytest.mark.asyncio
    async def test_conditional_skip(self):
        """测试条件跳过"""
        executed = []
        
        # stage1: 总是执行
        async def stage1(ctx: StageContext) -> StageResult:
            executed.append("stage1")
            return StageResult("completed", {"stage1": True}, 1)
        
        # stage2: 可跳过
        class SkippingStage:
            name = "stage2"
            
            async def run(self, ctx: StageContext) -> StageResult:
                executed.append("stage2")
                return StageResult("completed", {"stage2": True}, 1)
            
            def can_skip(self, ctx: StageContext) -> bool:
                # 当 stage1 的 artifacts 存在时跳过
                return bool(ctx.artifacts.get("stage1"))
        
        config = PipelineConfig(
            name="skip_test",
            task="test task",
            stages=[
                StageAdapter("stage1", stage1),
                SkippingStage(),
            ],
        )
        
        orchestrator = PipelineOrchestrator(config)
        result = await orchestrator.run()
        
        assert result.status == StageStatus.COMPLETED
        assert executed == ["stage1"]  # stage2 被跳过
        assert "stage2" not in result.stage_results

    @pytest.mark.asyncio
    async def test_resume_after_failure(self, temp_workspace):
        """测试失败后恢复"""
        state_file = temp_workspace / "resume_state.json"
        
        # 阶段 1: 成功
        async def stage1(ctx: StageContext) -> StageResult:
            return StageResult("completed", {"stage1": True}, 1)
        
        # 阶段 2: 失败（前两次），第三次成功
        attempt = {"count": 0}
        
        async def stage2(ctx: StageContext) -> StageResult:
            attempt["count"] += 1
            if attempt["count"] < 3:
                raise ValueError("fail")
            return StageResult("completed", {"stage2": True}, 1)
        
        # 阶段 3: 成功
        async def stage3(ctx: StageContext) -> StageResult:
            return StageResult("completed", {"stage3": True}, 1)
        
        stages = [
            StageAdapter("stage1", stage1),
            StageAdapter("stage2", stage2),
            StageAdapter("stage3", stage3),
        ]
        
        # 第一次运行（失败）
        config1 = PipelineConfig(
            name="resume_test",
            task="test task",
            stages=stages,
            state_file=str(state_file),
        )
        orchestrator1 = PipelineOrchestrator(config1)
        result1 = await orchestrator1.run()
        assert result1.status == StageStatus.FAILED
        assert result1.failed_stage == "stage2"
        
        # 第二次运行（恢复并成功）
        config2 = PipelineConfig(
            name="resume_test",
            task="test task",
            stages=stages,
            state_file=str(state_file),
        )
        orchestrator2 = PipelineOrchestrator(config2)
        result2 = await orchestrator2.run()
        
        assert result2.status == StageStatus.COMPLETED
        assert result2.stage_results["stage1"].status == "completed"
        assert result2.stage_results["stage2"].status == "completed"
        assert result2.stage_results["stage3"].status == "completed"

    @pytest.mark.asyncio
    async def test_artifacts_propagation(self):
        """测试 artifacts 传播"""
        async def stage1(ctx: StageContext) -> StageResult:
            return StageResult("completed", {"data": "from_stage1"}, 1)
        
        async def stage2(ctx: StageContext) -> StageResult:
            # 检查 artifacts 包含 stage1 的数据
            assert ctx.artifacts["data"] == "from_stage1"
            return StageResult("completed", {"stage2": True}, 1)
        
        config = PipelineConfig(
            name="artifacts_test",
            task="test task",
            stages=[
                StageAdapter("stage1", stage1),
                StageAdapter("stage2", stage2),
            ],
        )
        
        orchestrator = PipelineOrchestrator(config)
        result = await orchestrator.run()
        
        assert result.status == StageStatus.COMPLETED
        assert result.artifacts["data"] == "from_stage1"
        assert result.artifacts["stage2"] is True

    @pytest.mark.asyncio
    async def test_duration_calculation(self):
        """测试执行时间计算"""
        async def fast_stage(ctx: StageContext) -> StageResult:
            return StageResult("completed", {}, 1)
        
        config = PipelineConfig(
            name="duration_test",
            task="test task",
            stages=[StageAdapter("fast", fast_stage)],
        )
        
        orchestrator = PipelineOrchestrator(config)
        result = await orchestrator.run()
        
        assert result.duration_ms >= 0
        assert result.stage_results["fast"].duration_ms >= 0

    @pytest.mark.asyncio
    async def test_empty_stages(self):
        """测试空阶段列表"""
        config = PipelineConfig(
            name="empty_test",
            task="test task",
            stages=[],
        )
        
        orchestrator = PipelineOrchestrator(config)
        result = await orchestrator.run()
        
        assert result.status == StageStatus.COMPLETED
        assert len(result.stage_results) == 0

    @pytest.mark.asyncio
    async def test_multiple_failures(self):
        """测试多个阶段失败"""
        async def fail_stage(ctx: StageContext) -> StageResult:
            raise ValueError("failed")
        
        async def succeed(ctx: StageContext) -> StageResult:
            return StageResult("completed", {}, 1)
        
        config = PipelineConfig(
            name="multi_fail_test",
            task="test task",
            stages=[
                StageAdapter("fail1", fail_stage),
                StageAdapter("succeed", succeed),
                StageAdapter("fail2", fail_stage),
            ],
        )
        
        orchestrator = PipelineOrchestrator(config)
        result = await orchestrator.run()
        
        assert result.status == StageStatus.FAILED
        assert result.failed_stage == "fail1"
        # 后续阶段不应执行
        assert "succeed" not in result.stage_results
        assert "fail2" not in result.stage_results

    @pytest.mark.asyncio
    async def test_state_persistence_integration(self, temp_workspace):
        """测试状态持久化集成"""
        state_file = temp_workspace / "integration.json"
        
        async def stage1(ctx: StageContext) -> StageResult:
            return StageResult("completed", {"value": 1}, 10)
        
        async def stage2(ctx: StageContext) -> StageResult:
            return StageResult("completed", {"value": 2}, 10)
        
        config = PipelineConfig(
            name="persistence_test",
            task="test task",
            stages=[
                StageAdapter("stage1", stage1),
                StageAdapter("stage2", stage2),
            ],
            state_file=str(state_file),
        )
        
        # 第一次执行
        orchestrator = PipelineOrchestrator(config)
        result1 = await orchestrator.run()
        assert result1.status == StageStatus.COMPLETED
        
        # 状态文件应存在
        assert state_file.exists()
        
        # 加载状态并验证
        state = PipelineState.load(str(state_file))
        assert state.pipeline_name == "persistence_test"
        assert state.current_stage_index == 2
        assert len(state.stage_results) == 2

    @pytest.mark.asyncio
    async def test_custom_cwd_and_session_id(self):
        """测试自定义 cwd 和 session_id"""
        async def check_ctx(ctx: StageContext) -> StageResult:
            assert ctx.cwd == "/custom/path"
            assert ctx.session_id == "session-123"
            return StageResult("completed", {}, 1)
        
        config = PipelineConfig(
            name="ctx_test",
            task="test task",
            stages=[StageAdapter("check", check_ctx)],
            cwd="/custom/path",
            session_id="session-123",
        )
        
        orchestrator = PipelineOrchestrator(config)
        result = await orchestrator.run()
        assert result.status == StageStatus.COMPLETED


# ========== create_pipeline 便捷函数测试 ==========

class TestCreatePipeline:
    """create_pipeline 便捷函数测试"""

    @pytest.mark.asyncio
    async def test_create_from_stage_functions(self):
        """测试从函数式阶段创建 pipeline"""
        async def stage1(ctx: StageContext) -> StageResult:
            return StageResult("completed", {"step": 1}, 1)
        
        async def stage2(ctx: StageContext) -> StageResult:
            return StageResult("completed", {"step": 2}, 1)
        
        pipeline = create_pipeline(
            name="function_stages",
            task="test",
            stages=[stage1, stage2],
        )
        
        assert pipeline.config.name == "function_stages"
        assert len(pipeline.config.stages) == 2
        assert pipeline.config.stages[0].name == "stage1"
        assert pipeline.config.stages[1].name == "stage2"
        
        result = await pipeline.run()
        assert result.status == StageStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_create_from_pipeline_stage_objects(self):
        """测试从 PipelineStage 对象创建"""
        class MyStage:
            name = "mystage"
            
            async def run(self, ctx: StageContext) -> StageResult:
                return StageResult("completed", {}, 1)
        
        pipeline = create_pipeline(
            name="object_stages",
            task="test",
            stages=[MyStage()],
        )
        
        assert len(pipeline.config.stages) == 1
        assert isinstance(pipeline.config.stages[0], MyStage)
        
        result = await pipeline.run()
        assert result.status == StageStatus.COMPLETED
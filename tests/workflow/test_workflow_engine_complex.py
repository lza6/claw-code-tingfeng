"""src/workflow/engine.py 的复杂任务转换逻辑测试 - 恢复、拓扑执行、合同、辩论"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workflow.engine import WorkflowEngine
from src.workflow.models import (
    WorkflowIntent,
    WorkflowPhase,
    WorkflowStatus,
    WorkflowTask,
)


@pytest.fixture
def mock_managers(tmp_path):
    """模拟所有管理器和外部依赖"""
    with patch("src.workflow.engine.RunStateManager") as mock_state_mgr, \
         patch("src.workflow.engine.AssuranceManager") as mock_assurance_mgr, \
         patch("src.workflow.engine.ContractManager") as mock_contract_mgr, \
         patch("src.workflow.engine.WorktreeManager") as mock_wt_mgr, \
         patch("src.llm.prompts.protocol_manager.ProtocolManager") as mock_proto_mgr, \
         patch("src.workflow.engine.ResourceMonitor") as mock_res_mon:

        # 模拟 ContractManager.sign_contract
        mock_contract_mgr.return_value.sign_contract = AsyncMock(return_value=MagicMock())

        # 模拟 RunStateManager
        state_mgr_inst = mock_state_mgr.return_value
        state_mgr_inst.run_dir = tmp_path / ".clawd" / "runs" / "test_run"
        state_mgr_inst.load.return_value = None
        state_mgr_inst.load_contract.return_value = None

        # 模拟 WorktreeManager
        wt_mgr_inst = mock_wt_mgr.return_value
        wt_mgr_inst.create.return_value = tmp_path / "worktree"
        wt_mgr_inst.integrate.return_value = (True, "")

        # 模拟 ResourceMonitor
        res_mon_inst = mock_res_mon.return_value
        health = MagicMock()
        health.is_healthy = True
        res_mon_inst.check_health.return_value = health

        yield {
            "state_mgr": state_mgr_inst,
            "assurance_mgr": mock_assurance_mgr.return_value,
            "contract_mgr": mock_contract_mgr.return_value,
            "wt_mgr": wt_mgr_inst,
            "proto_mgr": mock_proto_mgr.return_value,
        }


@pytest.mark.asyncio
async def test_workflow_recover_logic(tmp_path, mock_managers):
    """测试工作流恢复逻辑"""
    mgrs = mock_managers
    state_mgr = mgrs["state_mgr"]

    # 设置模拟恢复数据
    state_mgr.load.return_value = {
        "state": {
            "goal": "recovered goal",
            "intent": "implement",
            "iteration": 1,
            "tasks": [
                {
                    "task_id": "task-001",
                    "title": "Task 1",
                    "description": "Desc",
                    "status": "pending",
                    "phase": "execute"
                }
            ]
        }
    }

    # 模拟 runs 目录
    runs_dir = tmp_path / ".clawd" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "20260101_000000").mkdir()

    engine = WorkflowEngine(workdir=tmp_path)

    # 注入模拟的子组件
    engine._phase_identify = AsyncMock(return_value={"issues": []})
    engine._phase_plan = AsyncMock(return_value=[])
    engine._phase_execute_isolated = AsyncMock(return_value="done")
    engine._phase_review = AsyncMock(return_value="reviewed")
    engine._phase_discover = AsyncMock(return_value=[])

    result = await engine.run("original goal", recover=True)

    assert result.status == WorkflowStatus.COMPLETED
    state_mgr.load.assert_called_once()


@pytest.mark.asyncio
async def test_topological_execution_logic(tmp_path, mock_managers):
    """测试任务拓扑排序执行逻辑"""
    engine = WorkflowEngine(workdir=tmp_path)

    # 创建有依赖的任务
    task1 = WorkflowTask(task_id="t1", phase=WorkflowPhase.EXECUTE, title="T1", description="D1", depends_on=[])
    task2 = WorkflowTask(task_id="t2", phase=WorkflowPhase.EXECUTE, title="T2", description="D2", depends_on=["t1"])

    executor = MagicMock()
    # 记录执行顺序
    execution_order = []

    async def mock_execute(t):
        execution_order.append(t.task_id)
        return "ok", WorkflowStatus.COMPLETED, False

    executor.execute_with_healing = AsyncMock(side_effect=mock_execute)
    engine._get_executor = MagicMock(return_value=executor)
    engine.state_manager = MagicMock()

    await engine._phase_execute([task1, task2])

    assert execution_order == ["t1", "t2"]


@pytest.mark.asyncio
async def test_deadlock_detection(tmp_path, mock_managers):
    """测试任务依赖死锁检测"""
    engine = WorkflowEngine(workdir=tmp_path)

    # 循环依赖
    task1 = WorkflowTask(task_id="t1", phase=WorkflowPhase.EXECUTE, title="T1", description="D1", depends_on=["t2"])
    task2 = WorkflowTask(task_id="t2", phase=WorkflowPhase.EXECUTE, title="T2", description="D2", depends_on=["t1"])

    engine.state_manager = MagicMock()
    engine._publish = MagicMock()

    result_str = await engine._phase_execute([task1, task2])

    assert "0/2 completed" in result_str
    # 验证任务被取消
    engine.state_manager.update_task.assert_any_call("t1", WorkflowStatus.CANCELLED, "Detected deadlock")
    engine.state_manager.update_task.assert_any_call("t2", WorkflowStatus.CANCELLED, "Detected deadlock")


@pytest.mark.asyncio
async def test_debate_trigger_on_critical_issue(tmp_path, mock_managers):
    """测试检测到 Critical 问题时触发辩论引擎"""
    engine = WorkflowEngine(workdir=tmp_path)

    from src.workflow.code_scanner import CodeIssue
    critical_issue = CodeIssue(
        category="architecture",
        severity="critical",
        file="core.py",
        line=1,
        description="Architecture risk"
    )

    # 模拟辩论引擎
    mock_debate = AsyncMock()
    mock_debate.conduct_debate.return_value = "Debate consensus"

    with patch("src.workflow.engine.DebateEngine", return_value=mock_debate), \
         patch("src.workflow.engine.OrchestratorAgent"), \
         patch("src.workflow.engine.MessageBus"), \
         patch("src.workflow.engine.RepositoryWorldModel"):

        tasks = await engine._phase_plan([critical_issue])

        mock_debate.conduct_debate.assert_called_once()
        assert len(tasks) > 0


@pytest.mark.asyncio
async def test_budget_exhaustion_during_iteration(tmp_path, mock_managers):
    """测试在迭代过程中预算耗尽的处理"""
    engine = WorkflowEngine(workdir=tmp_path, max_iterations=3)

    # 模拟预算耗尽
    engine.budget_guard.check = MagicMock(side_effect=[False, True]) # 第一轮不耗尽，第二轮耗尽
    engine.budget_guard.exhaustion_reason = "Token limit"

    engine._phase_identify = AsyncMock(return_value={"issues": []})
    engine._phase_plan = AsyncMock(return_value=[])
    engine._phase_execute_isolated = AsyncMock(return_value="ok")
    engine._phase_review = AsyncMock(return_value="reviewed")
    engine._phase_discover = AsyncMock(return_value=["new point"])

    # 非 EVOLVE 模式下预算耗尽应抛出异常
    engine.intent = WorkflowIntent.IMPLEMENT
    with pytest.raises(ClawdError) as exc:
        await engine.run("test goal")
    assert "Budget exhausted" in str(exc.value)

    # EVOLVE 模式下应优雅退出
    engine.intent = WorkflowIntent.EVOLVE
    engine.budget_guard.check = MagicMock(side_effect=[False, True])
    result = await engine.run("test goal")
    assert result.status == WorkflowStatus.COMPLETED
    assert engine.budget_guard.check.call_count >= 2

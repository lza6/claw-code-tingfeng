import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from src.workflow.healable_executor import HealableExecutor
from src.workflow.models import WorkflowTask, WorkflowStatus, WorkflowPhase

@pytest.mark.asyncio
async def test_execute_with_healing_success():
    workdir = Path(".")
    executor = HealableExecutor(workdir=workdir)

    # Mock strategy
    executor._execute_task = AsyncMock(return_value="Success Result")

    task = WorkflowTask(
        task_id="test-task",
        phase=WorkflowPhase.EXECUTE,
        title="Test Task",
        description="Just a test"
    )

    result, status, healed = await executor.execute_with_healing(task)

    assert status == WorkflowStatus.COMPLETED
    assert "Success Result" in result
    assert healed is False

@pytest.mark.asyncio
async def test_execute_with_healing_with_retry():
    workdir = Path(".")
    executor = HealableExecutor(workdir=workdir)

    # Mock to fail once then succeed
    executor._execute_task = AsyncMock(side_effect=[ValueError("First Fail"), "Success after heal"])
    executor._build_heal_strategy = MagicMock(return_value={'strategy': 'diagnosis', 'action': 'Retry'})
    executor._execute_heal_strategy = AsyncMock(return_value="Success after heal")

    task = WorkflowTask(
        task_id="test-task-retry",
        phase=WorkflowPhase.EXECUTE,
        title="Test Task Retry",
        description="Just a test"
    )

    result, status, healed = await executor.execute_with_healing(task)

    assert status == WorkflowStatus.COMPLETED
    assert "Success after heal" in result
    assert healed is True

@pytest.mark.asyncio
async def test_proof_gap_detection():
    workdir = Path(".")
    executor = HealableExecutor(workdir=workdir)

    # 模拟一个修复任务，但结果中没有任何证据或成功的关键词
    executor._execute_task = AsyncMock(return_value="I did nothing special")
    executor._extract_evidence = MagicMock(return_value=[]) # 强制为空

    task = WorkflowTask(
        task_id="test-proof-gap",
        phase=WorkflowPhase.EXECUTE,
        title="Fix bug X", # 包含 fix 关键词，会触发证据校验
        description="文件: src/missing.py"
    )

    result, status, healed = await executor.execute_with_healing(task)
    print(f"DEBUG_RESULT: {result}")
    print(f"DEBUG_STATUS: {status}")

    # 应该因为 Proof Gap 而失败
    assert status == WorkflowStatus.FAILED
    assert "Proof Gap" in result

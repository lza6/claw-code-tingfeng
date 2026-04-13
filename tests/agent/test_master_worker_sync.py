"""
Tests for Master-Worker status synchronization
"""

import pytest
import asyncio
import os
from pathlib import Path
import tempfile
import shutil
import json
from unittest.mock import MagicMock

from src.agent.swarm.message_bus import AgentMessage, MessageType
from src.agent.swarm.persistent_message_bus import PersistentMessageBus
from src.agent.swarm.orchestrator import OrchestratorAgent
from src.agent.swarm.engine import SwarmEngine
from src.agent.swarm.integrator import AtomicIntegrator
from src.agent.swarm.task_registry import TaskStatus


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.mark.asyncio
async def test_master_worker_sync_flow(temp_dir):
    """测试 Master-Worker 同步流"""
    storage_dir = temp_dir / "control"
    bus = PersistentMessageBus(storage_dir=storage_dir)

    # 1. 创建 Orchestrator (Master)
    orchestrator = OrchestratorAgent(
        agent_id="master",
        message_bus=bus
    )

    # 模拟 Worker 发送状态同步消息
    sync_msg = AgentMessage(
        sender="worker-1",
        recipient="master",
        message_type=MessageType.SYNC_STATE,
        content="Task T1 completed",
        metadata={
            "task_id": "T1",
            "status": TaskStatus.COMPLETED.value,
            "result_summary": "Success result"
        }
    )

    # 2. 发布消息并持久化
    await bus.publish(sync_msg)

    # 3. 模拟 Master 重启，通过 catch_up 订阅恢复状态
    recovered_states = []

    async def on_sync(msg):
        recovered_states.append(msg)

    # 新的总线实例，模拟重启
    new_bus = PersistentMessageBus(storage_dir=storage_dir)
    new_bus.subscribe(
        MessageType.SYNC_STATE,
        on_sync,
        catch_up=True,
        recipient_id="master"
    )

    # 等待异步 catch-up 处理
    await asyncio.sleep(0.5)

    assert len(recovered_states) == 1
    assert recovered_states[0].metadata["task_id"] == "T1"
    assert recovered_states[0].metadata["status"] == TaskStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_swarm_engine_recovery(temp_dir):
    """测试 SwarmEngine 启动时的状态恢复"""
    # 准备环境，预先存入一些 Worker 同步消息
    control_dir = temp_dir / ".clawd" / "control"
    bus = PersistentMessageBus(storage_dir=control_dir)

    # 模拟 Worker 之前的运行痕迹
    await bus.publish(AgentMessage(
        sender="worker-logic",
        recipient="orchestrator-1",
        message_type=MessageType.SYNC_STATE,
        content="Recover me",
        metadata={"task_id": "T-RECOVERY", "status": TaskStatus.COMPLETED.value}
    ))

    # 启动 SwarmEngine
    engine = SwarmEngine(workdir=temp_dir)
    engine._init_agents()

    # 手动触发订阅逻辑（在 engine.run 内部会执行，这里为了单元测试模拟）
    engine.message_bus.subscribe(
        MessageType.SYNC_STATE,
        engine._on_worker_sync,
        catch_up=True,
        recipient_id=engine.orchestrator.agent_id
    )

    # 等待恢复
    await asyncio.sleep(0.5)

    # 验证任务是否已出现在 TaskRegistry 中
    task = engine.task_registry.get_task("T-RECOVERY")
    assert task is not None
    assert task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_integrator_transaction_sync(temp_dir):
    """测试 Integrator 事务同步消息广播"""
    storage_dir = temp_dir / "control"
    bus = PersistentMessageBus(storage_dir=storage_dir)
    integrator = AtomicIntegrator(workdir=temp_dir, message_bus=bus)

    # 1. 开启事务
    await integrator.start_transaction()

    # 2. 模拟变更
    test_file = "test.txt"
    await integrator.integrate_batch({test_file: "new content"})

    # 3. 提交事务
    await integrator.commit()

    # 验证持久化总线中是否存在 TX_SYNC 消息
    history = bus.get_persistent_history("orchestrator-1")
    tx_msgs = [msg for msg in history if msg.metadata.get("message_type") == MessageType.TX_SYNC.value]

    assert len(tx_msgs) >= 3  # start, integrate_batch, commit
    actions = [msg.metadata.get("action") for msg in tx_msgs]
    assert "start" in actions
    assert "integrate_batch" in actions
    assert "commit" in actions

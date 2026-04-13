"""
Phase 2 Integration Tests - Durable Surfaces 集成到现有系统

测试:
1. RunStateManager + SurfaceManager 集成
2. PersistentMessageBus 功能
3. WorkflowEngine + Durable Surfaces 集成
"""

import pytest
import asyncio
from pathlib import Path
import tempfile
import shutil

from src.core.persistence.run_state import (
    RunStateManager,
    _DURABLE_SURFACES_AVAILABLE,
)
from src.workflow.models import (
    WorkflowTask,
    WorkflowPhase,
    WorkflowStatus,
)


@pytest.fixture
def temp_run_dir():
    """Create a temporary run directory."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def run_state_manager(temp_run_dir):
    """Create a RunStateManager with durable surfaces."""
    return RunStateManager(temp_run_dir, run_id="test-run-1")


@pytest.mark.skipif(not _DURABLE_SURFACES_AVAILABLE, reason="Durable surfaces not available")
class TestRunStateManagerDurableIntegration:
    """测试 RunStateManager + Durable Surfaces 集成"""

    def test_surface_manager_available(self, run_state_manager):
        """测试 SurfaceManager 可用"""
        assert run_state_manager.surface_manager is not None

    def test_update_status_summary(self, run_state_manager):
        """测试更新状态摘要"""
        run_state_manager.update_status_summary(
            phase="executing",
            current_activity="Running tasks",
            active_sessions=2,
            blocked_sessions=0,
            progress_percentage=50.0,
            obligations_satisfied=5,
            obligations_total=10,
            summary="Half done",
        )

        # 直接读取 JSON 文件验证
        import json
        status_file = run_state_manager.run_dir / "surfaces" / "status_summary.json"
        assert status_file.exists()
        with open(status_file) as f:
            data = json.load(f)
        assert data["phase"] == "executing"
        assert data["active_sessions"] == 2
        assert data["progress_percentage"] == 50.0

    def test_add_evidence_entry(self, run_state_manager):
        """测试添加证据条目"""
        run_state_manager.add_evidence_entry(
            evidence_id="ev-test-1",
            evidence_type="test_result",
            description="Unit tests passed",
            obligation_id="obl-1",
            scenario_id="scenario-1",
            data={"passed": True, "count": 42},
            artifacts=["tests/test_foo.py"],
            recorded_by="workflow_engine",
        )

        # 验证证据已持久化
        import json
        evidence_file = run_state_manager.run_dir / "surfaces" / "evidence_log.json"
        assert evidence_file.exists()
        with open(evidence_file) as f:
            data = json.load(f)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["id"] == "ev-test-1"
        assert data["entries"][0]["obligation_id"] == "obl-1"

    def test_update_coordination_session(self, run_state_manager):
        """测试更新会话协调状态"""
        run_state_manager.update_coordination_session(
            session_id="session-1",
            state="executing",
            assigned_obligations=["obl-1", "obl-2"],
            worktree_path="/tmp/worktree-1",
            progress_notes="Working on task",
        )

        # 验证协调状态已持久化
        import json
        coord_file = run_state_manager.run_dir / "surfaces" / "coordination_state.json"
        assert coord_file.exists()
        with open(coord_file) as f:
            data = json.load(f)
        assert "session-1" in data["sessions"]
        assert data["sessions"]["session-1"]["state"] == "executing"

    def test_assign_obligation_to_session(self, run_state_manager):
        """测试分配义务到会话"""
        # 先创建会话
        run_state_manager.update_coordination_session(
            session_id="session-2",
            state="idle",
        )

        # 分配义务
        run_state_manager.assign_obligation_to_session("session-2", "obl-3")

        # 验证覆盖映射
        import json
        coord_file = run_state_manager.run_dir / "surfaces" / "coordination_state.json"
        with open(coord_file) as f:
            data = json.load(f)
        assert "obl-3" in data["coverage_map"]
        assert "session-2" in data["coverage_map"]["obl-3"]

    def test_multiple_evidence_entries(self, run_state_manager):
        """测试添加多个证据条目"""
        for i in range(3):
            run_state_manager.add_evidence_entry(
                evidence_id=f"ev-{i}",
                evidence_type="test_result",
                description=f"Test {i}",
                obligation_id=f"obl-{i}",
            )

        import json
        evidence_file = run_state_manager.run_dir / "surfaces" / "evidence_log.json"
        with open(evidence_file) as f:
            data = json.load(f)
        assert len(data["entries"]) == 3

    def test_existing_behavior_preserved(self, run_state_manager):
        """测试现有行为保持不变"""
        # 确保现有 sync/load 方法仍然工作
        run_state_manager.sync({
            "goal": "Test goal",
            "intent": "deliver",
            "iteration": 0,
            "tasks": [],
            "optimization_points": [],
        })

        loaded = run_state_manager.load()
        assert loaded is not None
        assert loaded["goal"] == "Test goal"
        assert loaded["iteration"] == 0


class TestRunStateManagerWithoutDurableSurfaces:
    """测试在没有 Durable Surfaces 时的降级行为"""

    def test_surface_manager_none_when_unavailable(self, temp_run_dir):
        """测试在不导入时 surface_manager 为 None"""
        # 使用标准 run_id 创建管理器
        rsm = RunStateManager(temp_run_dir, run_id="test-no-durable")
        # 如果 durable surfaces 可用，surface_manager 不为 None
        if not _DURABLE_SURFACES_AVAILABLE:
            assert rsm.surface_manager is None
        else:
            assert rsm.surface_manager is not None

    def test_sync_still_works(self, temp_run_dir):
        """测试 sync 方法仍然工作"""
        rsm = RunStateManager(temp_run_dir, run_id="test-sync")
        rsm.sync({
            "goal": "Sync test",
            "intent": "deliver",
            "iteration": 1,
            "tasks": [],
            "optimization_points": [],
        })

        loaded = rsm.load()
        assert loaded["goal"] == "Sync test"


class TestPersistentMessageBus:
    """测试 PersistentMessageBus 集成"""

    @pytest.fixture
    def storage_dir(self, temp_run_dir):
        """Create storage directory."""
        return temp_run_dir / "control"

    @pytest.fixture
    def persistent_bus(self, storage_dir):
        """Create a PersistentMessageBus."""
        from src.agent.swarm.persistent_message_bus import PersistentMessageBus
        return PersistentMessageBus(storage_dir=storage_dir)

    @pytest.mark.asyncio
    async def test_publish_persists_to_disk(self, persistent_bus, storage_dir):
        """测试发布消息时持久化到磁盘"""
        from src.agent.swarm.message_bus import AgentMessage, MessageType

        msg = AgentMessage(
            sender="master",
            recipient="session-1",
            message_type=MessageType.TASK_ASSIGN,
            content="Do task X",
        )

        await persistent_bus.publish(msg)

        # 验证消息已持久化
        inbox_file = storage_dir / "inbox" / "session-1.jsonl"
        assert inbox_file.exists()

        with open(inbox_file) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_get_unread_messages(self, persistent_bus):
        """测试获取未读消息"""
        from src.agent.swarm.message_bus import AgentMessage, MessageType

        msg = AgentMessage(
            sender="session-1",
            recipient="master",
            message_type=MessageType.STATUS_UPDATE,
            content="Task completed",
        )

        await persistent_bus.publish(msg)

        unread = persistent_bus.get_unread_messages("master")
        assert len(unread) == 1
        assert unread[0].content == "Task completed"

    @pytest.mark.asyncio
    async def test_urgent_messages_detection(self, persistent_bus):
        """测试紧急消息检测"""
        from src.agent.swarm.message_bus import AgentMessage, MessageType

        # 发送错误消息 (映射为 CRITICAL 优先级)
        msg = AgentMessage(
            sender="session-1",
            recipient="master",
            message_type=MessageType.ERROR,
            content="Build failed!",
        )

        await persistent_bus.publish(msg)

        assert persistent_bus.has_urgent("master")
        urgent = persistent_bus.get_urgent_messages("master")
        assert len(urgent) == 1
        assert urgent[0].content == "Build failed!"

    @pytest.mark.asyncio
    async def test_broadcast(self, persistent_bus, storage_dir):
        """测试广播消息"""
        from src.agent.swarm.message_bus import MessageType

        messages = persistent_bus.broadcast(
            from_id="master",
            recipient_ids=["session-1", "session-2"],
            content="Pause work",
            message_type=MessageType.STATUS_UPDATE,
        )

        assert len(messages) == 2

        # 验证两个收件人都有消息
        assert persistent_bus.get_unread_count("session-1") == 1
        assert persistent_bus.get_unread_count("session-2") == 1

    def test_without_storage_dir(self):
        """测试没有存储目录时降级为内存模式"""
        from src.agent.swarm.persistent_message_bus import PersistentMessageBus

        bus = PersistentMessageBus(storage_dir=None)

        assert bus.control_system is None
        assert bus.get_unread_count("master") == 0
        assert bus.get_unread_messages("master") == []
        assert not bus.has_urgent("master")

    @pytest.mark.asyncio
    async def test_subscribe_still_works(self, persistent_bus):
        """测试订阅仍然工作"""
        from src.agent.swarm.message_bus import AgentMessage, MessageType

        received = []

        def callback(msg):
            received.append(msg)

        persistent_bus.subscribe(MessageType.TASK_ASSIGN, callback)

        msg = AgentMessage(
            sender="master",
            recipient="worker-1",
            message_type=MessageType.TASK_ASSIGN,
            content="Test",
        )

        await persistent_bus.publish(msg)

        assert len(received) == 1
        assert received[0].content == "Test"

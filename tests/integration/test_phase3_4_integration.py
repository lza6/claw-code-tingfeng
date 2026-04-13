"""
Phase 3 & 4 Integration Tests - Worktree 增强与运行时监控
"""

import pytest
import asyncio
import os
from pathlib import Path
import tempfile
import shutil

from src.core.git.worktree import WorktreeManager
from src.core.runtime.host import RuntimeHost
from src.core.runtime.lease import RuntimeLease, LeaseMonitor


@pytest.fixture
def temp_repo():
    """Create a temporary git repository."""
    temp_dir = Path(tempfile.mkdtemp())
    import subprocess
    subprocess.run(["git", "init"], cwd=temp_dir, check=True)
    # 必须有一个 commit 才能创建 worktree
    (temp_dir / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=temp_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=temp_dir, check=True)
    yield temp_dir

    # Windows git cleanup helper
    import stat
    def on_rm_error(func, path, exc_info):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(temp_dir, onerror=on_rm_error)


class TestWorktreeEnhancement:
    """测试 WorktreeManager 增强功能"""

    def test_partial_adopt(self, temp_repo):
        """测试部分采纳合并策略"""
        manager = WorktreeManager(temp_repo)
        session_id = "test-partial"

        # 1. 创建工作树
        worktree_path = manager.create(session_id)
        assert worktree_path.exists()

        # 2. 在工作树中修改文件
        new_file = worktree_path / "new_feature.py"
        new_file.write_text("print('hello')")

        # 3. 执行部分采纳
        success, msg = manager.integrate(session_id, method="partial_adopt")
        assert success
        assert "手动同步" in msg

        # 4. 验证文件已同步回主仓库
        expected_file = temp_repo / "new_feature.py"
        assert expected_file.exists()
        assert expected_file.read_text() == "print('hello')"

        # 5. 清理
        manager.remove(session_id, force=True)


class TestRuntimeMonitoring:
    """测试运行时监控系统 (Phase 4)"""

    @pytest.mark.asyncio
    async def test_runtime_host_lease(self, temp_repo):
        """测试 RuntimeHost 和 Lease 系统"""
        run_dir = temp_repo / ".clawd" / "runs" / "test-run"
        run_dir.mkdir(parents=True, exist_ok=True)

        host = RuntimeHost(run_dir, "session-1")

        # 1. 启动 Host
        await host.start()
        assert host._is_running

        # 2. 验证租约文件已创建
        lease_file = run_dir / "runtime" / "lease-session-1.json"
        assert lease_file.exists()

        # 3. 验证 Monitor 能看到活跃会话
        monitor = LeaseMonitor(run_dir)
        active = monitor.get_active_sessions()
        assert "session-1" in active
        assert active["session-1"]["pid"] == os.getpid()

        # 4. 停止 Host
        await host.stop()
        assert not host._is_running
        assert not lease_file.exists()

    @pytest.mark.asyncio
    async def test_lease_expiration(self, temp_repo):
        """测试租约过期清理"""
        run_dir = temp_repo / ".clawd" / "runs" / "test-expire"
        run_dir.mkdir(parents=True, exist_ok=True)

        lease = RuntimeLease(run_dir, "dead-session")
        lease.beat()
        # 强制修改最后心跳时间为 2 分钟前
        import json
        import time
        with open(lease.lease_file, "r") as f:
            data = json.load(f)
        data["last_beat"] = time.time() - 120
        with open(lease.lease_file, "w") as f:
            json.dump(data, f)

        monitor = LeaseMonitor(run_dir)
        active = monitor.get_active_sessions()

        # 应检测到过期并清理
        assert "dead-session" not in active
        assert not lease.lease_file.exists()


class TestSwarmPhase4Integration:
    """测试 Swarm 引擎对 Phase 4 组件的集成"""

    @pytest.mark.asyncio
    async def test_swarm_runtime_integration(self, temp_repo):
        """测试 SwarmEngine 自动管理 RuntimeHost 和 CoordinationState"""
        from src.agent.swarm.engine import SwarmEngine
        from src.agent.swarm.config import SwarmConfig
        from src.agent.swarm.message_bus import AgentMessage, MessageType

        config = SwarmConfig(
            enable_runtime_host=True,
            enable_coordination_state=True
        )
        engine = SwarmEngine(config=config, workdir=temp_repo)
        engine._init_agents()

        # 1. 验证初始化
        assert engine.runtime_host is not None
        assert engine.coordination_state is not None
        assert engine.surface_manager is not None

        # 2. 模拟运行 (由于 run 是长耗时，我们手动触发关键生命周期)
        await engine.runtime_host.start()
        try:
            # 验证租约已创建
            lease_path = temp_repo / ".clawd" / "runtime" / f"lease-{engine.runtime_host.session_id}.json"
            assert lease_path.exists()

            # 3. 模拟 Worker 同步消息，验证 CoordinationState 更新
            sync_msg = AgentMessage(
                sender="worker-alpha",
                recipient=engine.orchestrator.agent_id,
                message_type=MessageType.SYNC_STATE,
                content="Working on task T1",
                metadata={"task_id": "T1", "status": "in_progress"}
            )
            await engine._on_worker_sync(sync_msg)

            # 验证协作状态
            state = engine.coordination_state
            assert "worker-alpha" in state.sessions
            assert state.sessions["worker-alpha"].state.value == "executing"
            assert "T1" in state.sessions["worker-alpha"].assigned_obligations

            # 验证持久化
            surface_file = temp_repo / ".clawd" / "surfaces" / "coordination_state.json"
            assert surface_file.exists()

        finally:
            await engine.runtime_host.stop()
            assert not lease_path.exists()

"""Command-Event-Snapshot 三元架构测试 - TDD 驱动

测试覆盖：
1. RuntimeCommand 创建/序列化/反序列化
2. RuntimeEvent 生成/审计日志
3. RuntimeSnapshot 快照持久化
4. RuntimeEventLog JSONL 写入与重放
5. RuntimeStateEngine 端到端流程
"""

import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

from src.core.state.command_event import (
    CommandType,
    EventType,
    RuntimeCommand,
    RuntimeEvent,
    RuntimeSnapshot,
    AuthoritySnapshot,
    BacklogSnapshot,
    ReadinessSnapshot,
    RuntimeEventLog,
    RuntimeStateEngine,
)
from src.core.state.authority import AuthorityLease, LeaseInfo
from src.core.state.authority import AuthorityLease, LeaseInfo


# ========== RuntimeCommand 测试 ==========

class TestRuntimeCommand:
    """命令对象测试"""

    def test_create_command(self):
        """工厂方法创建命令"""
        cmd = RuntimeCommand.create(
            command_type=CommandType.ACQUIRE_AUTHORITY,
            payload={'owner': 'worker-1', 'ttl': 300},
            source='orchestrator',
            correlation_id='chain-123'
        )
        assert cmd.command_type == CommandType.ACQUIRE_AUTHORITY
        assert cmd.payload['owner'] == 'worker-1'
        assert cmd.source == 'orchestrator'
        assert cmd.correlation_id == 'chain-123'
        assert isinstance(cmd.timestamp, datetime)
        assert len(cmd.command_id) == 36  # UUID v4

    def test_command_serialization(self):
        """序列化与反序列化"""
        cmd = RuntimeCommand.create(
            command_type=CommandType.QUEUE_DISPATCH,
            payload={'request_id': 'req-1', 'target': 'worker-1'},
            source='api'
        )
        serialized = cmd.serialize()
        assert isinstance(serialized, str)
        data = json.loads(serialized)
        assert data['command_type'] == 'QUEUE_DISPATCH'
        assert data['source'] == 'api'

    def test_command_deserialization(self):
        """JSONL反序列化恢复命令"""
        original = RuntimeCommand.create(
            command_type=CommandType.MARK_DELIVERED,
            payload={'request_id': 'req-abc'},
            source='worker-1'
        )
        json_str = original.serialize()
        restored = RuntimeCommand.deserialize(json_str)
        assert restored.command_id == original.command_id
        assert restored.command_type == original.command_type
        assert restored.payload == original.payload


# ========== RuntimeEvent 测试 ==========

class TestRuntimeEvent:
    """事件对象测试"""

    def test_event_from_command(self):
        """从命令创建事件"""
        cmd = RuntimeCommand.create(
            command_type=CommandType.ACQUIRE_AUTHORITY,
            payload={'owner': 'worker-1'},
            source='orchestrator'
        )
        event = RuntimeEvent.from_command(
            cmd,
            EventType.AUTHORITY_ACQUIRED,
            {'lease_id': 'lease-123'}
        )
        assert event.event_type == EventType.AUTHORITY_ACQUIRED
        assert event.source_command == cmd.command_id
        assert event.payload['lease_id'] == 'lease-123'
        assert len(event.event_id) == 36

    def test_event_to_audit_log(self):
        """转换为审计日志格式"""
        cmd = RuntimeCommand.create(
            command_type=CommandType.MARK_FAILED,
            payload={'request_id': 'req-1', 'reason': 'timeout'},
            source='worker-1'
        )
        event = RuntimeEvent.from_command(cmd, EventType.DISPATCH_FAILED, {})
        audit = event.to_audit_log()
        assert 'event_id' in audit
        assert audit['event_type'] == 'DISPATCH_FAILED'
        assert audit['source_command'] == cmd.command_id


# ========== RuntimeSnapshot 测试 ==========

class TestRuntimeSnapshot:
    """快照结构测试"""

    def test_default_snapshot(self):
        """默认快照初始值"""
        snap = RuntimeSnapshot()
        assert snap.schema_version == 1
        assert isinstance(snap.authority, AuthoritySnapshot)
        assert isinstance(snap.backlog, BacklogSnapshot)
        assert snap.replay_cursor == 0
        assert isinstance(snap.readiness, ReadinessSnapshot)

    def test_snapshot_to_dict_and_back(self):
        """快照序列化"""
        snap = RuntimeSnapshot(
            authority=AuthoritySnapshot(
                owner="worker-1",
                lease_id="lease-123",
                leased_until="2026-01-15T10:30:00Z",
                is_stale=False
            ),
            backlog=BacklogSnapshot(pending=10, notified=5, delivered=3, failed=2),
            replay_cursor=100,
            readiness=ReadinessSnapshot(is_ready=True)
        )
        d = snap.to_dict()
        assert d['schema_version'] == 1
        assert d['authority']['owner'] == 'worker-1'
        assert d['backlog']['pending'] == 10

        restored = RuntimeSnapshot.from_dict(d)
        assert restored.authority.owner == 'worker-1'
        assert restored.backlog.pending == 10
        assert restored.replay_cursor == 100

    def test_snapshot_save_and_load(self, tmp_path):
        """快照文件持久化"""
        snap = RuntimeSnapshot(
            authority=AuthoritySnapshot(owner="w1"),
            backlog=BacklogSnapshot(pending=5),
            replay_cursor=42
        )
        file = tmp_path / "snapshot.json"
        snap.save(file)

        loaded = RuntimeSnapshot.load(file)
        assert loaded.authority.owner == "w1"
        assert loaded.backlog.pending == 5
        assert loaded.replay_cursor == 42


# ========== RuntimeEventLog 测试 ==========

class TestRuntimeEventLog:
    """事件日志测试"""

    def test_append_and_load_all(self, tmp_path):
        """追加事件并全部加载"""
        log_dir = tmp_path / "state"
        log = RuntimeEventLog(log_dir)

        cmd = RuntimeCommand.create(
            CommandType.ACQUIRE_AUTHORITY,
            {'owner': 'w1'},
            'orchestrator'
        )
        event = RuntimeEvent.from_command(cmd, EventType.AUTHORITY_ACQUIRED, {})

        log.append(event)

        events = log.load_all()
        assert len(events) == 1
        assert events[0].event_id == event.event_id

    def test_append_persists_to_disk(self, tmp_path):
        """追加同时写入文件"""
        log_dir = tmp_path / "state"
        log = RuntimeEventLog(log_dir)

        cmd = RuntimeCommand.create(
            CommandType.QUEUE_DISPATCH,
            {'request_id': 'req-1'},
            'api'
        )
        event = RuntimeEvent.from_command(cmd, EventType.DISPATCH_QUEUED, {})
        log.append(event)

        # 检查文件存在且内容可解析
        events_file = log_dir / "events.jsonl"
        assert events_file.exists()
        lines = events_file.read_text().strip().split('\n')
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data['event_type'] == 'DISPATCH_QUEUED'

    def test_replay_from_cursor(self, tmp_path):
        """从游标重放事件"""
        log_dir = tmp_path / "state"
        log = RuntimeEventLog(log_dir)

        events = []
        for i in range(5):
            cmd = RuntimeCommand.create(
                CommandType.QUEUE_DISPATCH,
                {'idx': i},
                'test'
            )
            evt = RuntimeEvent.from_command(cmd, EventType.DISPATCH_QUEUED, {})
            log.append(evt)
            events.append(evt)

        # 从游标 2 开始重放
        replayed = log.replay_from(cursor=2)
        assert len(replayed) == 3
        assert replayed[0].event_id == events[2].event_id

    def test_clear_log(self, tmp_path):
        """清空日志"""
        log_dir = tmp_path / "state"
        log = RuntimeEventLog(log_dir)
        log.append(RuntimeEvent.from_command(
            RuntimeCommand.create(CommandType.ACQUIRE_AUTHORITY, {}, 'test'),
            EventType.AUTHORITY_ACQUIRED, {}
        ))
        log.clear()
        assert log.get_cursor() == 0
        assert not log.events_file.exists()


# ========== RuntimeStateEngine 测试 ==========

class TestRuntimeStateEngine:
    """状态引擎端到端测试"""

    def test_engine_initialization_creates_snapshot(self, tmp_path):
        """初始化引擎创建默认快照"""
        state_dir = tmp_path / "engine"
        engine = RuntimeStateEngine(state_dir)
        snap = engine.get_snapshot()
        assert snap.schema_version == 1
        assert not snap.authority.owner

    def test_execute_acquire_authority(self, tmp_path):
        """执行 ACQUIRE_AUTHORITY 命令"""
        state_dir = tmp_path / "engine"
        engine = RuntimeStateEngine(state_dir)

        cmd = RuntimeCommand.create(
            CommandType.ACQUIRE_AUTHORITY,
            {'owner': 'worker-1', 'leased_until': '2026-01-15T10:35:00Z'},
            source='orchestrator'
        )
        event = engine.execute(cmd)

        assert event.event_type == EventType.AUTHORITY_ACQUIRED
        assert engine.get_snapshot().authority.owner == 'worker-1'

    def test_execute_dispatch_commands(self, tmp_path):
        """执行调度相关命令"""
        state_dir = tmp_path / "engine"
        engine = RuntimeStateEngine(state_dir)

        # QUEUE
        cmd1 = RuntimeCommand.create(
            CommandType.QUEUE_DISPATCH,
            {'request_id': 'req-1', 'target': 'worker-1'},
            'api'
        )
        evt1 = engine.execute(cmd1)
        assert evt1.event_type == EventType.DISPATCH_QUEUED

        # NOTIFIED
        cmd2 = RuntimeCommand.create(
            CommandType.MARK_NOTIFIED,
            {'request_id': 'req-1', 'channel': 'push'},
            'orchestrator'
        )
        evt2 = engine.execute(cmd2)
        assert evt2.event_type == EventType.DISPATCH_NOTIFIED

        # DELIVERED
        cmd3 = RuntimeCommand.create(
            CommandType.MARK_DELIVERED,
            {'request_id': 'req-1'},
            'worker-1'
        )
        evt3 = engine.execute(cmd3)
        assert evt3.event_type == EventType.DISPATCH_DELIVERED

    def test_events_persisted_to_disk(self, tmp_path):
        """事件持久化到磁盘"""
        state_dir = tmp_path / "engine"
        engine = RuntimeStateEngine(state_dir)

        cmd = RuntimeCommand.create(
            CommandType.ACQUIRE_AUTHORITY,
            {'owner': 'w1'},
            'test'
        )
        engine.execute(cmd)

        events_file = state_dir / "events.jsonl"
        assert events_file.exists()
        content = events_file.read_text()
        assert 'AUTHORITY_ACQUIRED' in content

    def test_snapshot_persisted(self, tmp_path):
        """快照持久化"""
        state_dir = tmp_path / "engine"
        engine = RuntimeStateEngine(state_dir)

        engine.execute(RuntimeCommand.create(
            CommandType.ACQUIRE_AUTHORITY,
            {'owner': 'w1'},
            'test'
        ))
        engine.persist_snapshot()

        snap_file = state_dir / "snapshot.json"
        assert snap_file.exists()

    def test_load_and_replay_restores_state(self, tmp_path):
        """从磁盘加载并重放恢复状态"""
        state_dir = tmp_path / "engine"
        engine1 = RuntimeStateEngine(state_dir)

        # 执行3个命令
        for i in range(3):
            engine1.execute(RuntimeCommand.create(
                CommandType.QUEUE_DISPATCH,
                {'request_id': f'req-{i}'},
                'api'
            ))
        engine1.persist_snapshot()

        # 新实例恢复
        engine2 = RuntimeStateEngine.load(state_dir)
        snap = engine2.get_snapshot()
        assert snap.replay_cursor == 3

    def test_is_ready(self, tmp_path):
        """系统就绪度检查"""
        state_dir = tmp_path / "engine"
        engine = RuntimeStateEngine(state_dir)

        assert not engine.is_ready()

        engine.execute(RuntimeCommand.create(
            CommandType.ACQUIRE_AUTHORITY,
            {'owner': 'w1'},
            'test'
        ))
        # acquire 后系统就绪（当前逻辑）
        assert engine.is_ready()

    def test_unknown_command_handled(self, tmp_path):
        """未知命令类型返回失败事件"""
        state_dir = tmp_path / "engine"
        engine = RuntimeStateEngine(state_dir)

        # 通过直接构造而非 create 来绕过校验
        cmd = RuntimeCommand(
            command_id='test-unknown',
            command_type=CommandType.REQUEST_REPLAY,  # _process_command 中没有处理
            timestamp=datetime.now(timezone.utc),
            payload={},
            source='test'
        )
        event = engine.execute(cmd)
        assert event.event_type == EventType.DISPATCH_FAILED
        assert 'unknown' in event.payload.get('error', '').lower()

    def test_authority_renew_and_release(self, tmp_path):
        """测试 authority 续期和释放命令"""
        state_dir = tmp_path / "engine"
        engine = RuntimeStateEngine(state_dir)

        # Acquire
        acquire_cmd = RuntimeCommand.create(
            CommandType.ACQUIRE_AUTHORITY,
            {'owner': 'worker-1', 'ttl': 300},
            'orchestrator'
        )
        acquire_evt = engine.execute(acquire_cmd)
        assert acquire_evt.event_type == EventType.AUTHORITY_ACQUIRED
        assert engine.get_snapshot().authority.owner == 'worker-1'

        # Renew
        renew_cmd = RuntimeCommand.create(
            CommandType.RENEW_AUTHORITY,
            {'owner': 'worker-1', 'ttl': 300},
            'orchestrator'
        )
        renew_evt = engine.execute(renew_cmd)
        assert renew_evt.event_type == EventType.AUTHORITY_RENEWED

        # Release
        release_cmd = RuntimeCommand.create(
            CommandType.RELEASE_AUTHORITY,
            {'owner': 'worker-1'},
            'orchestrator'
        )
        release_evt = engine.execute(release_cmd)
        assert release_evt.event_type == EventType.AUTHORITY_RELEASED
        assert engine.get_snapshot().authority.owner is None

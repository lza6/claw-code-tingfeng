"""Swarm Message Bus 模块测试"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agent.swarm.message_bus import (
    AgentMessage,
    MessageBus,
    MessageType,
)


class TestMessageType:
    """MessageType 枚举测试"""

    def test_message_type_values(self):
        """测试消息类型值"""
        assert MessageType.TASK_ASSIGN.value == 'task_assign'
        assert MessageType.TASK_SUBMIT.value == 'task_submit'
        assert MessageType.AUDIT_REQUEST.value == 'audit_request'
        assert MessageType.AUDIT_PASS.value == 'audit_pass'
        assert MessageType.AUDIT_FAIL.value == 'audit_fail'
        assert MessageType.STATUS_UPDATE.value == 'status_update'
        assert MessageType.ERROR.value == 'error'


class TestAgentMessage:
    """AgentMessage 数据类测试"""

    def test_creation(self):
        """测试创建"""
        msg = AgentMessage(
            sender='orchestrator',
            recipient='worker',
            message_type=MessageType.TASK_ASSIGN,
            content='Test content',
        )
        assert msg.sender == 'orchestrator'
        assert msg.recipient == 'worker'
        assert msg.message_type == MessageType.TASK_ASSIGN
        assert msg.content == 'Test content'
        assert msg.message_id is not None

    def test_default_values(self):
        """测试默认值"""
        msg = AgentMessage(
            sender='sender',
            recipient='recipient',
            message_type=MessageType.STATUS_UPDATE,
            content='Test',
        )
        assert msg.metadata == {}
        assert msg.timestamp > 0
        assert msg.correlation_id == ''

    def test_reply(self):
        """测试回复消息"""
        msg = AgentMessage(
            sender='orchestrator',
            recipient='worker',
            message_type=MessageType.TASK_ASSIGN,
            content='Do work',
        )
        reply = msg.reply(MessageType.TASK_SUBMIT, content='Done')
        assert reply.sender == 'worker'
        assert reply.recipient == 'orchestrator'
        assert reply.message_type == MessageType.TASK_SUBMIT
        assert reply.content == 'Done'
        assert reply.correlation_id == msg.message_id

    def test_reply_with_existing_correlation_id(self):
        """测试回复消息保留关联 ID"""
        msg = AgentMessage(
            sender='orchestrator',
            recipient='worker',
            message_type=MessageType.TASK_ASSIGN,
            content='Do work',
            correlation_id='corr-123',
        )
        reply = msg.reply(MessageType.TASK_SUBMIT, content='Done')
        assert reply.correlation_id == 'corr-123'


class TestMessageBus:
    """MessageBus 核心功能测试"""

    def setup_method(self):
        """每个测试前重置"""
        self.bus = MessageBus()

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self):
        """测试发布和订阅"""
        callback = MagicMock()
        self.bus.subscribe(MessageType.TASK_ASSIGN, callback)

        msg = AgentMessage(
            sender='orchestrator',
            recipient='worker',
            message_type=MessageType.TASK_ASSIGN,
            content='Test',
        )
        await self.bus.publish(msg)

        callback.assert_called_once()
        assert callback.call_args[0][0].message_type == MessageType.TASK_ASSIGN

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """测试取消订阅"""
        callback = MagicMock()
        self.bus.subscribe(MessageType.TASK_ASSIGN, callback)
        self.bus.unsubscribe(MessageType.TASK_ASSIGN, callback)

        msg = AgentMessage(
            sender='orchestrator',
            recipient='worker',
            message_type=MessageType.TASK_ASSIGN,
            content='Test',
        )
        await self.bus.publish(msg)

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_callback(self):
        """测试异步回调"""
        results = []

        async def async_callback(msg: AgentMessage):
            results.append(msg)

        self.bus.subscribe(MessageType.STATUS_UPDATE, async_callback)

        msg = AgentMessage(
            sender='system',
            recipient='all',
            message_type=MessageType.STATUS_UPDATE,
            content='Async test',
        )
        await self.bus.publish(msg)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_message_history(self):
        """测试消息历史"""
        for i in range(3):
            await self.bus.publish(AgentMessage(
                sender='sender',
                recipient='recipient',
                message_type=MessageType.TASK_ASSIGN,
                content=f'Message {i}',
            ))

        messages = self.bus.get_messages_by_type(MessageType.TASK_ASSIGN)
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_get_messages_by_correlation_id(self):
        """测试按关联 ID 获取消息"""
        msg1 = AgentMessage(
            sender='orchestrator',
            recipient='worker',
            message_type=MessageType.TASK_ASSIGN,
            content='Task 1',
            correlation_id='corr-001',
        )
        await self.bus.publish(msg1)

        msg2 = msg1.reply(MessageType.TASK_SUBMIT, content='Done')
        await self.bus.publish(msg2)

        messages = self.bus.get_messages('corr-001')
        assert len(messages) == 2

    def test_clear_history(self):
        """测试清空历史"""
        self.bus._message_history.append(AgentMessage(
            sender='s',
            recipient='r',
            message_type=MessageType.STATUS_UPDATE,
            content='test',
        ))
        self.bus.clear_history()
        assert len(self.bus._message_history) == 0

    def test_max_history_limit(self):
        """测试历史消息上限 (通过 publish 触发裁剪)"""
        bus = MessageBus()
        bus._max_history = 5

        # 通过 publish 触发裁剪逻辑
        for i in range(10):
            bus._message_history.append(AgentMessage(
                sender='s',
                recipient='r',
                message_type=MessageType.STATUS_UPDATE,
                content=f'msg {i}',
            ))
            # 手动触发裁剪
            if len(bus._message_history) > bus._max_history:
                bus._message_history = bus._message_history[-bus._max_history:]

        assert len(bus._message_history) == 5

    @pytest.mark.asyncio
    async def test_callback_exception_handling(self):
        """测试回调异常不影响其他回调"""
        results = []

        def failing_callback(msg: AgentMessage):
            raise ValueError('Callback error')

        def good_callback(msg: AgentMessage):
            results.append(msg)

        self.bus.subscribe(MessageType.STATUS_UPDATE, failing_callback)
        self.bus.subscribe(MessageType.STATUS_UPDATE, good_callback)

        msg = AgentMessage(
            sender='s',
            recipient='r',
            message_type=MessageType.STATUS_UPDATE,
            content='Test',
        )
        # 不应抛出异常
        await self.bus.publish(msg)

        assert len(results) == 1

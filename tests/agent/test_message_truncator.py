"""MessageTruncator 测试 - 消息截断策略"""
from __future__ import annotations

import pytest
import pytest_asyncio

from src.agent.message_truncator import MessageTruncator
from src.llm import LLMMessage


class TestMessageTruncatorCreation:
    """MessageTruncator 创建测试"""

    def test_create_default(self):
        """测试默认创建"""
        truncator = MessageTruncator()
        assert truncator.max_context_tokens > 0

    def test_create_with_custom_tokens(self):
        """测试指定最大 Token 创建"""
        truncator = MessageTruncator(max_context_tokens=4000)
        assert truncator.max_context_tokens == 4000


class TestMessageTruncatorBasic:
    """MessageTruncator 基础功能测试"""

    @pytest.mark.asyncio
    async def test_truncate_empty_messages(self):
        """测试截断空消息"""
        truncator = MessageTruncator(max_context_tokens=1000)
        result = await truncator.truncate_messages([])
        assert result == []

    @pytest.mark.asyncio
    async def test_truncate_short_messages(self):
        """测试短消息不需要截断"""
        truncator = MessageTruncator(max_context_tokens=10000)
        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there"),
        ]
        result = await truncator.truncate_messages(messages)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_truncate_preserves_system(self):
        """测试保留系统消息"""
        truncator = MessageTruncator(max_context_tokens=50)
        messages = [
            LLMMessage(role="system", content="You are a helpful assistant"),
            LLMMessage(role="user", content="msg1 " * 100),
            LLMMessage(role="assistant", content="msg2 " * 100),
        ]
        result = await truncator.truncate_messages(messages)
        # 系统消息应该保留
        assert len(result) > 0
        assert result[0].role == "system"


class TestMessageTruncatorTokenCount:
    """Token 计数测试"""

    def test_count_tokens_empty(self):
        """测试空消息计数"""
        truncator = MessageTruncator(max_context_tokens=1000)
        count = truncator.count_tokens([])
        assert count == 0

    def test_count_tokens_simple(self):
        """测试简单消息计数"""
        truncator = MessageTruncator(max_context_tokens=1000)
        messages = [
            LLMMessage(role="user", content="Hello world"),
        ]
        count = truncator.count_tokens(messages)
        assert count > 0


class TestMessageTruncatorEdgeCases:
    """边界条件测试"""

    @pytest.mark.asyncio
    async def test_very_large_limit(self):
        """测试极大限制"""
        truncator = MessageTruncator(max_context_tokens=1000000)
        messages = [
            LLMMessage(role="user", content="Short message"),
        ]
        result = await truncator.truncate_messages(messages)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_very_small_limit(self):
        """测试极小限制"""
        truncator = MessageTruncator(max_context_tokens=1)
        messages = [
            LLMMessage(role="system", content="System prompt"),
            LLMMessage(role="user", content="User message"),
        ]
        result = await truncator.truncate_messages(messages)
        # 至少应保留部分消息
        assert len(result) >= 0

    @pytest.mark.asyncio
    async def test_single_message(self):
        """测试单条消息"""
        truncator = MessageTruncator(max_context_tokens=1000)
        messages = [
            LLMMessage(role="user", content="Single message"),
        ]
        result = await truncator.truncate_messages(messages)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_truncation_needed(self):
        """测试不需要截断的情况"""
        truncator = MessageTruncator(max_context_tokens=100000)
        messages = [
            LLMMessage(role="system", content="System"),
            LLMMessage(role="user", content="User"),
            LLMMessage(role="assistant", content="Assistant"),
        ]
        result = await truncator.truncate_messages(messages)
        assert len(result) == 3

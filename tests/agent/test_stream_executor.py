"""StreamExecutor 模块测试 — 组合模式 LLM 结构化输出执行器"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from src.agent._stream_executor import StreamExecutor
from src.llm import LLMResponse


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture
def mock_llm_provider():
    provider = MagicMock()
    provider.chat_structured = AsyncMock()
    provider.chat = AsyncMock()
    return provider


@pytest.fixture
def mock_run_coroutine():
    return AsyncMock()


@pytest.fixture
def executor(mock_llm_provider, mock_run_coroutine):
    return StreamExecutor(llm_provider=mock_llm_provider, run_coroutine=mock_run_coroutine)


@pytest.fixture
def executor_no_provider(mock_run_coroutine):
    return StreamExecutor(llm_provider=None, run_coroutine=mock_run_coroutine)


# ====================================================================
# __init__ 测试
# ====================================================================

class TestStreamExecutorInit:
    """StreamExecutor 初始化测试"""

    def test_stores_llm_provider(self, mock_llm_provider, mock_run_coroutine):
        """存储 LLM 提供商"""
        e = StreamExecutor(llm_provider=mock_llm_provider, run_coroutine=mock_run_coroutine)
        assert e._llm_provider is mock_llm_provider

    def test_stores_run_coroutine(self, mock_llm_provider, mock_run_coroutine):
        """存储 run_coroutine"""
        e = StreamExecutor(llm_provider=mock_llm_provider, run_coroutine=mock_run_coroutine)
        assert e._run_coroutine is mock_run_coroutine

    def test_none_llm_provider(self, mock_run_coroutine):
        """None LLM 提供商"""
        e = StreamExecutor(llm_provider=None, run_coroutine=mock_run_coroutine)
        assert e._llm_provider is None

    def test_none_run_coroutine(self, mock_llm_provider):
        """None run_coroutine"""
        e = StreamExecutor(llm_provider=mock_llm_provider, run_coroutine=None)
        assert e._run_coroutine is None


# ====================================================================
# run_structured 测试 - 成功路径
# ====================================================================

class TestRunStructured:
    """run_structured 测试"""

    @pytest.mark.asyncio
    async def test_calls_chat_structured(self, executor, mock_llm_provider):
        """调用 chat_structured 方法"""
        mock_llm_provider.chat_structured.return_value = LLMResponse(
            content='{"key": "value"}',
            model='gpt-4',
            usage={'total_tokens': 50},
        )
        result = await executor.run_structured("extract data", {"type": "object"})

        mock_llm_provider.chat_structured.assert_called_once()
        call_args = mock_llm_provider.chat_structured.call_args
        assert call_args.kwargs['messages'] == [{"role": "user", "content": "extract data"}]
        assert call_args.kwargs['response_schema'] == {"type": "object"}

    @pytest.mark.asyncio
    async def test_returns_structured_response(self, executor, mock_llm_provider):
        """返回结构化响应"""
        expected = LLMResponse(
            content='{"name": "test"}',
            model='gpt-4',
            usage={'total_tokens': 30},
        )
        mock_llm_provider.chat_structured.return_value = expected

        result = await executor.run_structured("task", {})

        assert result is expected

    @pytest.mark.asyncio
    async def test_passes_correct_schema(self, executor, mock_llm_provider):
        """传递正确的 schema"""
        mock_llm_provider.chat_structured.return_value = LLMResponse(
            content='{}', model='gpt-4', usage={},
        )
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        await executor.run_structured("task", schema)

        call_args = mock_llm_provider.chat_structured.call_args
        assert call_args.kwargs['response_schema'] == schema


# ====================================================================
# run_structured 测试 - 降级路径 (无 chat_structured)
# ====================================================================

class TestRunStructuredFallback:
    """run_structured 降级路径测试"""

    @pytest.mark.asyncio
    async def test_falls_back_to_chat(self, mock_llm_provider, mock_run_coroutine):
        """降级到普通 chat 方法"""
        # 移除 chat_structured
        del mock_llm_provider.chat_structured
        mock_llm_provider.chat.return_value = LLMResponse(
            content='plain text',
            model='gpt-3.5',
            usage={'total_tokens': 20},
        )
        executor = StreamExecutor(llm_provider=mock_llm_provider, run_coroutine=mock_run_coroutine)

        result = await executor.run_structured("task", {})

        mock_llm_provider.chat.assert_called_once()
        call_args = mock_llm_provider.chat.call_args
        assert call_args.kwargs['messages'] == [{"role": "user", "content": "task"}]

    @pytest.mark.asyncio
    async def test_fallback_does_not_call_structured(self, mock_llm_provider, mock_run_coroutine):
        """降级时不调用 chat_structured"""
        del mock_llm_provider.chat_structured
        mock_llm_provider.chat.return_value = LLMResponse(content='r', model='m', usage={})
        executor = StreamExecutor(llm_provider=mock_llm_provider, run_coroutine=mock_run_coroutine)

        await executor.run_structured("task", {})

        assert not hasattr(mock_llm_provider, 'chat_structured') or not mock_llm_provider.chat.called


# ====================================================================
# run_structured 测试 - 无提供商
# ====================================================================

class TestRunStructuredNoProvider:
    """无 LLM 提供商时的 run_structured 测试"""

    @pytest.mark.asyncio
    async def test_returns_error_response(self, executor_no_provider):
        """返回错误响应"""
        result = await executor_no_provider.run_structured("task", {})

        assert '"error"' in result.content
        assert 'LLM 提供商未配置' in result.content
        assert result.model == 'none'
        assert result.usage['total_tokens'] == 0

    @pytest.mark.asyncio
    async def test_zero_usage(self, executor_no_provider):
        """零用量"""
        result = await executor_no_provider.run_structured("task", {})

        assert result.usage == {'total_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0}

    @pytest.mark.asyncio
    async def test_ignores_schema(self, executor_no_provider):
        """忽略 schema"""
        complex_schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        result = await executor_no_provider.run_structured("task", complex_schema)

        assert '"error"' in result.content


# ====================================================================
# has_structured_support 测试
# ====================================================================

class TestHasStructuredSupport:
    """has_structured_support 测试"""

    def test_true_when_provider_has_chat_structured(self, executor):
        """提供商有 chat_structured 时返回 True"""
        assert executor.has_structured_support() is True

    def test_false_when_provider_is_none(self, executor_no_provider):
        """提供商为 None 时返回 False"""
        assert executor_no_provider.has_structured_support() is False

    def test_false_when_provider_lacks_method(self, mock_run_coroutine):
        """提供商缺少 chat_structured 时返回 False"""
        provider = MagicMock(spec=[])  # 空 spec
        e = StreamExecutor(llm_provider=provider, run_coroutine=mock_run_coroutine)
        assert e.has_structured_support() is False


# ====================================================================
# Edge cases
# ====================================================================

class TestEdgeCases:
    """边界条件测试"""

    @pytest.mark.asyncio
    async def test_empty_goal(self, executor, mock_llm_provider):
        """空目标"""
        mock_llm_provider.chat_structured.return_value = LLMResponse(
            content='{}', model='gpt-4', usage={},
        )
        await executor.run_structured("", {})

        call_args = mock_llm_provider.chat_structured.call_args
        assert call_args.kwargs['messages'] == [{"role": "user", "content": ""}]

    @pytest.mark.asyncio
    async def test_unicode_goal(self, executor, mock_llm_provider):
        """Unicode 目标"""
        mock_llm_provider.chat_structured.return_value = LLMResponse(
            content='{}', model='gpt-4', usage={},
        )
        await executor.run_structured("提取数据", {})

        call_args = mock_llm_provider.chat_structured.call_args
        assert call_args.kwargs['messages'] == [{"role": "user", "content": "提取数据"}]

    @pytest.mark.asyncio
    async def test_empty_schema(self, executor, mock_llm_provider):
        """空 schema"""
        mock_llm_provider.chat_structured.return_value = LLMResponse(
            content='{}', model='gpt-4', usage={},
        )
        await executor.run_structured("task", {})

        call_args = mock_llm_provider.chat_structured.call_args
        assert call_args.kwargs['response_schema'] == {}

    @pytest.mark.asyncio
    async def test_complex_schema(self, executor, mock_llm_provider):
        """复杂 schema"""
        mock_llm_provider.chat_structured.return_value = LLMResponse(
            content='{}', model='gpt-4', usage={},
        )
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name"],
        }
        await executor.run_structured("task", schema)

        call_args = mock_llm_provider.chat_structured.call_args
        assert call_args.kwargs['response_schema'] == schema

    @pytest.mark.asyncio
    async def test_llm_provider_raises_exception(self, executor, mock_llm_provider):
        """LLM 提供商抛出异常"""
        mock_llm_provider.chat_structured.side_effect = RuntimeError("API error")

        with pytest.raises(RuntimeError, match="API error"):
            await executor.run_structured("task", {})

    @pytest.mark.asyncio
    async def test_chat_structured_returns_none(self, executor, mock_llm_provider):
        """chat_structured 返回 None"""
        mock_llm_provider.chat_structured.return_value = None

        result = await executor.run_structured("task", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_run_coroutine_not_used(self, executor, mock_run_coroutine, mock_llm_provider):
        """run_coroutine 不被使用"""
        mock_llm_provider.chat_structured.return_value = LLMResponse(
            content='{}', model='gpt-4', usage={},
        )
        await executor.run_structured("task", {})

        mock_run_coroutine.assert_not_called()


# ====================================================================
# Integration-style tests
# ====================================================================

class TestIntegrationStyle:
    """集成风格测试"""

    @pytest.mark.asyncio
    async def test_full_flow_with_mock(self, mock_llm_provider, mock_run_coroutine):
        """完整流程"""
        mock_llm_provider.chat_structured.return_value = LLMResponse(
            content='{"result": "success"}',
            model='gpt-4',
            usage={'total_tokens': 100, 'prompt_tokens': 50, 'completion_tokens': 50},
        )
        executor = StreamExecutor(llm_provider=mock_llm_provider, run_coroutine=mock_run_coroutine)

        result = await executor.run_structured("analyze code", {"type": "object"})

        assert result.content == '{"result": "success"}'
        assert result.model == 'gpt-4'
        assert result.usage['total_tokens'] == 100
        assert executor.has_structured_support() is True

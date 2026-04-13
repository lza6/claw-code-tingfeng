"""工具执行器测试"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.tool_executor import (
    ParallelToolResult,
    check_tool_call_loop,
    execute_tool,
    execute_tools_parallel,
    get_tool_timeout,
    parse_tool_calls,
)
from src.core.exceptions import ToolExecutionError, ToolInvalidArgsError, ToolNotFoundError
from src.tools_runtime.base import BaseTool, ToolResult


class MockTool(BaseTool):
    """模拟工具"""

    def __init__(self, should_fail: bool = False, delay: float = 0):
        self.should_fail = should_fail
        self.delay = delay
        self.description = 'Mock tool for testing'
        self.call_count = 0

    def execute(self, **kwargs) -> ToolResult:
        import time
        time.sleep(self.delay)
        self.call_count += 1
        if self.should_fail:
            return ToolResult(success=False, output='', error='模拟失败')
        return ToolResult(success=True, output='模拟成功')

    def validate(self, **kwargs) -> tuple[bool, str]:
        if 'invalid_arg' in kwargs:
            return False, '参数无效'
        return True, ''


class TestParseToolCalls:
    """parse_tool_calls 测试"""

    def test_parse_json_format(self):
        """测试 JSON 格式解析"""
        content = '<tool>{"name": "BashTool", "args": {"command": "ls"}}</tool>'
        calls = parse_tool_calls(content)
        assert len(calls) == 1
        assert calls[0] == ('BashTool', {'command': 'ls'})

    def test_parse_multiple_calls(self):
        """测试多次调用"""
        content = """
        <tool>{"name": "BashTool", "args": {"command": "ls"}}</tool>
        <tool>{"name": "FileReadTool", "args": {"path": "test.py"}}</tool>
        """
        calls = parse_tool_calls(content)
        assert len(calls) == 2
        assert calls[0][0] == 'BashTool'
        assert calls[1][0] == 'FileReadTool'

    def test_parse_invalid_json(self):
        """测试无效 JSON"""
        content = '<tool>not json</tool>'
        calls = parse_tool_calls(content)
        assert len(calls) == 0

    def test_parse_missing_name(self):
        """测试缺少 name"""
        content = '<tool>{"args": {"command": "ls"}}</tool>'
        calls = parse_tool_calls(content)
        assert len(calls) == 0

    def test_parse_empty_content(self):
        """测试空内容"""
        calls = parse_tool_calls('')
        assert len(calls) == 0


class TestGetToolTimeout:
    """get_tool_timeout 测试"""

    def test_default_timeout(self):
        """测试默认超时"""
        with patch.dict(os.environ, {}, clear=True):
            # 清除其他环境变量干扰
            for key in list(os.environ.keys()):
                if key.startswith('TOOL_TIMEOUT') or key == 'COMMAND_TIMEOUT':
                    del os.environ[key]
            timeout = get_tool_timeout('UnknownTool')
            assert timeout == 30  # DEFAULT_TIMEOUTS['default']

    def test_bash_timeout(self):
        """测试 Bash 超时"""
        with patch.dict(os.environ, {}, clear=True):
            for key in list(os.environ.keys()):
                if key.startswith('TOOL_TIMEOUT') or key == 'COMMAND_TIMEOUT':
                    del os.environ[key]
            timeout = get_tool_timeout('BashTool')
            assert timeout == 60  # DEFAULT_TIMEOUTS['bash']

    def test_env_override_json(self):
        """测试 JSON 环境变量覆盖"""
        with patch.dict(os.environ, {'TOOL_TIMEOUTS': '{"BashTool": 120}'}):
            timeout = get_tool_timeout('BashTool')
            assert timeout == 120

    def test_env_override_individual(self):
        """测试单独环境变量覆盖"""
        with patch.dict(os.environ, {'TOOL_TIMEOUT_BASH': '90'}):
            timeout = get_tool_timeout('BashTool')
            assert timeout == 90

    def test_env_override_command_timeout(self):
        """测试 COMMAND_TIMEOUT 覆盖"""
        with patch.dict(os.environ, {'COMMAND_TIMEOUT': '45'}):
            for key in list(os.environ.keys()):
                if key.startswith('TOOL_TIMEOUT'):
                    del os.environ[key]
            timeout = get_tool_timeout('UnknownTool')
            assert timeout == 45


class TestExecuteTool:
    """execute_tool 测试"""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """测试执行成功"""
        tools = {'MockTool': MockTool()}
        result = await execute_tool(tools, 'MockTool', {'arg': 'value'})
        assert result.success is True
        assert result.output == '模拟成功'

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self):
        """测试工具未找到"""
        tools: dict[str, BaseTool] = {}
        with pytest.raises(ToolNotFoundError):
            await execute_tool(tools, 'NonExistent', {})

    @pytest.mark.asyncio
    async def test_execute_invalid_args(self):
        """测试参数无效"""
        tools = {'MockTool': MockTool()}
        with pytest.raises(ToolInvalidArgsError):
            await execute_tool(tools, 'MockTool', {'invalid_arg': 'value'})

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        """测试执行超时"""
        tools = {'SlowTool': MockTool(delay=2)}
        with pytest.raises(ToolExecutionError) as exc_info:
            await execute_tool(tools, 'SlowTool', {}, timeout=1)
        assert '超时' in str(exc_info.value.message)


class TestCheckToolCallLoop:
    """check_tool_call_loop 测试"""

    def test_no_loop(self):
        """测试无循环"""
        history = [('BashTool', '{"command": "ls"}')]
        is_loop, _ = check_tool_call_loop(history, 'BashTool', {'command': 'ls'}, 3)
        assert is_loop is False

    def test_loop_detected(self):
        """测试检测到循环"""
        history = [
            ('BashTool', '{"command": "ls"}'),
            ('BashTool', '{"command": "ls"}'),
            ('BashTool', '{"command": "ls"}'),
        ]
        is_loop, msg = check_tool_call_loop(history, 'BashTool', {'command': 'ls'}, 3)
        assert is_loop is True
        # 消息中包含重复次数（history.count 返回 3，repeat_count >= max_repeat_calls 触发）
        assert '4' in msg or '3' in msg


class TestExecuteToolsParallel:
    """execute_tools_parallel 测试"""

    @pytest.mark.asyncio
    async def test_parallel_success(self):
        """测试并行成功"""
        tools = {
            'Tool1': MockTool(),
            'Tool2': MockTool(),
        }
        calls = [('Tool1', {}), ('Tool2', {})]
        results = await execute_tools_parallel(tools, calls)
        assert len(results) == 2
        assert all(r.is_error is False for r in results)

    @pytest.mark.asyncio
    async def test_parallel_one_fails(self):
        """测试一个失败不影响其他"""
        # MockTool 返回 success=False 不算异常，需要抛出异常才算 is_error=True
        class FailingTool(BaseTool):
            def __init__(self):
                self.description = 'Failing tool'

            def execute(self, **kwargs) -> ToolResult:
                raise RuntimeError('模拟工具异常')

            def validate(self, **kwargs) -> tuple[bool, str]:
                return True, ''

        tools = {
            'GoodTool': MockTool(),
            'BadTool': FailingTool(),
        }
        calls = [('GoodTool', {}), ('BadTool', {})]
        results = await execute_tools_parallel(tools, calls)
        assert len(results) == 2
        assert results[0].is_error is False
        assert results[1].is_error is True

    @pytest.mark.asyncio
    async def test_parallel_empty(self):
        """测试空调用列表"""
        results = await execute_tools_parallel({}, [])
        assert results == []


class TestParallelToolResult:
    """ParallelToolResult 测试"""

    def test_creation(self):
        """测试创建"""
        result = ParallelToolResult(
            tool_name='TestTool',
            tool_args={'arg': 'value'},
            result=ToolResult(success=True, output='ok'),
            elapsed=1.5,
        )
        assert result.tool_name == 'TestTool'
        assert result.elapsed == 1.5
        assert result.is_error is False

"""原生 function calling 回归测试（P1-1）。

覆盖：
- provider 层消息序列化与 tool_calls 提取
- Agent 循环在原生调用下使用 role=tool + tool_call_id 回传结果
- 开关关闭时不生成 tool schema（保持文本协议）
"""
from __future__ import annotations

import pytest

from src.agent.engine import AgentEngine
from src.agent.engine_loop import AgentLoopConfig, _run_agent_loop
from src.llm.config import LLMResponse
from src.llm.providers.openai import _extract_native_tool_calls, _serialize_messages
from src.llm.config import LLMMessage
from src.tools_runtime.base import BaseTool, ToolResult


class _BashLike(BaseTool):
    name = 'BashTool'
    description = 'run command'
    risk_kind = 'exec'

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output='ok')


def test_serialize_messages_keeps_tool_fields():
    messages = [
        LLMMessage(role='assistant', content='', tool_calls=[{'id': 'c1'}]),
        LLMMessage(role='tool', content='result', tool_call_id='c1', name='BashTool'),
        LLMMessage(role='user', content='hi'),
    ]
    serialized = _serialize_messages(messages)

    assert serialized[0]['tool_calls'] == [{'id': 'c1'}]
    assert serialized[1]['tool_call_id'] == 'c1'
    assert serialized[1]['name'] == 'BashTool'
    assert 'tool_calls' not in serialized[2]
    assert set(serialized[2]) == {'role', 'content'}


def test_extract_native_tool_calls_handles_missing():
    class Empty:
        tool_calls = None

    assert _extract_native_tool_calls(Empty()) is None


def test_extract_native_tool_calls_shape():
    class Fn:
        name = 'BashTool'
        arguments = '{"command": "ls"}'

    class Call:
        id = 'call_1'
        type = 'function'
        function = Fn()

    class Message:
        tool_calls = [Call()]

    calls = _extract_native_tool_calls(Message())
    assert calls == [{
        'id': 'call_1',
        'type': 'function',
        'function': {'name': 'BashTool', 'arguments': '{"command": "ls"}'},
    }]


def test_build_tool_schemas_is_off_by_default(monkeypatch):
    monkeypatch.delenv('CLAWD_NATIVE_TOOLS', raising=False)
    engine = AgentEngine.__new__(AgentEngine)
    engine.tools = {'BashTool': _BashLike()}
    assert engine._build_tool_schemas() is None


def test_build_tool_schemas_when_enabled(monkeypatch):
    monkeypatch.setenv('CLAWD_NATIVE_TOOLS', '1')
    engine = AgentEngine.__new__(AgentEngine)
    engine.tools = {'BashTool': _BashLike()}
    schemas = engine._build_tool_schemas()

    assert schemas and schemas[0]['type'] == 'function'
    assert schemas[0]['function']['name'] == 'BashTool'
    assert schemas[0]['function']['parameters']['type'] == 'object'


class _FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[list[LLMMessage], dict]] = []
        self.responses = [
            LLMResponse(
                content='',
                model='fake',
                finish_reason='tool_calls',
                tool_calls=[{
                    'id': 'call_1',
                    'type': 'function',
                    'function': {'name': 'BashTool', 'arguments': '{"command": "echo hi"}'},
                }],
            ),
            LLMResponse(content='done', model='fake', finish_reason='stop'),
        ]

    async def chat(self, messages, **kwargs):
        self.calls.append((list(messages), dict(kwargs)))
        return self.responses[0] if len(self.responses) == 1 else self.responses.pop(0)


@pytest.mark.asyncio
async def test_malformed_arguments_get_tool_error_message():
    """参数解析失败也必须回一条 tool 消息，不能留下悬空 tool_call_id。"""
    provider = _FakeProvider()
    provider.responses = [
        LLMResponse(
            content='',
            model='fake',
            finish_reason='tool_calls',
            tool_calls=[{
                'id': 'call_bad',
                'type': 'function',
                'function': {'name': 'BashTool', 'arguments': 'not-json'},
            }],
        ),
        LLMResponse(content='done', model='fake', finish_reason='stop'),
    ]

    async def execute_tool(name: str, args: dict):
        raise AssertionError('参数无效的调用不应被执行')

    config = AgentLoopConfig(
        goal='test',
        llm_provider=provider,
        messages=[],
        max_iterations=2,
        system_prompt='system',
        tools={},
        _execute_tool=execute_tool,
        tool_schemas=[{'type': 'function', 'function': {'name': 'BashTool'}}],
    )

    await _run_agent_loop(config=config)

    tool_msgs = [m for m in config.messages if m.role == 'tool']
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == 'call_bad'
    assert '参数无效' in tool_msgs[0].content


@pytest.mark.asyncio
async def test_filtered_duplicate_calls_get_tool_messages():
    """被 max_repeat_calls 过滤的调用也必须回 tool 消息，不能留悬空 id。"""
    provider = _FakeProvider()
    provider.responses = [
        LLMResponse(
            content='',
            model='fake',
            finish_reason='tool_calls',
            tool_calls=[
                {'id': 'call_1', 'type': 'function', 'function': {'name': 'BashTool', 'arguments': '{"command": "echo hi"}'}},
                {'id': 'call_2', 'type': 'function', 'function': {'name': 'BashTool', 'arguments': '{"command": "echo hi"}'}},
            ],
        ),
        LLMResponse(content='done', model='fake', finish_reason='stop'),
    ]

    executed: list[str] = []

    async def execute_tool(name: str, args: dict):
        executed.append(name)
        return ToolResult(success=True, output='hi')

    config = AgentLoopConfig(
        goal='test',
        llm_provider=provider,
        messages=[],
        max_iterations=2,
        system_prompt='system',
        tools={},
        _execute_tool=execute_tool,
        max_repeat_calls=1,
        tool_schemas=[{'type': 'function', 'function': {'name': 'BashTool'}}],
    )

    await _run_agent_loop(config=config)

    assert executed == ['BashTool']
    tool_msgs = [m for m in config.messages if m.role == 'tool']
    # OpenAI 协议只要求每个 tool_call_id 都有对应响应，不要求顺序一致。
    assert len(tool_msgs) == 2
    assert {m.tool_call_id for m in tool_msgs} == {'call_1', 'call_2'}
    content_by_id = {m.tool_call_id: m.content for m in tool_msgs}
    assert '重复调用已跳过' in content_by_id['call_2']
    assert '重复调用已跳过' not in content_by_id['call_1']


@pytest.mark.asyncio
async def test_duplicate_signatures_get_distinct_tool_call_ids():
    """同一 (name, args) 出现两次时，两条 tool 消息必须使用不同的 id。"""
    provider = _FakeProvider()
    provider.responses = [
        LLMResponse(
            content='',
            model='fake',
            finish_reason='tool_calls',
            tool_calls=[
                {'id': 'call_1', 'type': 'function', 'function': {'name': 'BashTool', 'arguments': '{"command": "echo hi"}'}},
                {'id': 'call_2', 'type': 'function', 'function': {'name': 'BashTool', 'arguments': '{"command": "echo hi"}'}},
            ],
        ),
        LLMResponse(content='done', model='fake', finish_reason='stop'),
    ]

    async def execute_tool(name: str, args: dict):
        return ToolResult(success=True, output='hi')

    config = AgentLoopConfig(
        goal='test',
        llm_provider=provider,
        messages=[],
        max_iterations=2,
        system_prompt='system',
        tools={},
        _execute_tool=execute_tool,
        tool_schemas=[{'type': 'function', 'function': {'name': 'BashTool'}}],
    )

    await _run_agent_loop(config=config)

    tool_ids = [m.tool_call_id for m in config.messages if m.role == 'tool']
    assert tool_ids == ['call_1', 'call_2']


@pytest.mark.asyncio
async def test_agent_loop_uses_native_calls_and_returns_tool_messages():
    provider = _FakeProvider()
    executed: list[tuple[str, dict]] = []

    async def execute_tool(name: str, args: dict):
        executed.append((name, args))
        return ToolResult(success=True, output='hi')

    config = AgentLoopConfig(
        goal='test',
        llm_provider=provider,
        messages=[],
        max_iterations=2,
        system_prompt='system',
        tools={},
        _execute_tool=execute_tool,
        tool_schemas=[{'type': 'function', 'function': {'name': 'BashTool'}}],
    )

    result = await _run_agent_loop(config=config)

    assert executed == [('BashTool', {'command': 'echo hi'})]
    assert provider.calls, 'provider 应被调用'
    # 第一轮必须把 tools schema 透传给 provider
    assert provider.calls[0][1].get('tools') == config.tool_schemas

    roles = [m.role for m in config.messages]
    assert 'assistant' in roles
    assert 'tool' in roles
    tool_msg = next(m for m in config.messages if m.role == 'tool')
    assert tool_msg.tool_call_id == 'call_1'
    assert tool_msg.name == 'BashTool'
    assert result['session'].is_complete is True

"""Protocol Converter 专项测试 — 验证跨模型协议转换准确性"""
import pytest
import json
from src.llm.protocol_converter import ProtocolConverter

def test_openai_to_claude_basic():
    """测试基础文本消息转换"""
    req = {
        "messages": [
            {"role": "system", "content": "You are a helper"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ],
        "temperature": 0.5
    }

    claude_req = ProtocolConverter.openai_to_claude(req)

    assert claude_req["system"] == "You are a helper"
    assert len(claude_req["messages"]) == 2
    assert claude_req["messages"][0]["role"] == "user"
    assert claude_req["messages"][1]["content"] == "Hi there"
    assert claude_req["temperature"] == 0.5

def test_openai_to_claude_tool_calls():
    """测试 OpenAI Tool Calls 到 Claude Tool Use 的转换"""
    req = {
        "messages": [
            {
                "role": "assistant",
                "content": "I will run a tool",
                "tool_calls": [{
                    "id": "call_123",
                    "function": {"name": "get_weather", "arguments": '{"city": "Shanghai"}'}
                }]
            }
        ]
    }

    claude_req = ProtocolConverter.openai_to_claude(req)
    msg = claude_req["messages"][0]

    assert msg["role"] == "assistant"
    assert isinstance(msg["content"], list)
    assert msg["content"][0]["text"] == "I will run a tool"
    assert msg["content"][1]["type"] == "tool_use"
    assert msg["content"][1]["name"] == "get_weather"
    assert msg["content"][1]["input"] == {"city": "Shanghai"}

def test_openai_to_claude_tool_result():
    """测试 OpenAI Tool Result 响应转换"""
    req = {
        "messages": [
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "content": "Sunny, 25C"
            }
        ]
    }

    claude_req = ProtocolConverter.openai_to_claude(req)
    msg = claude_req["messages"][0]

    assert msg["role"] == "user"
    assert msg["content"][0]["type"] == "tool_result"
    assert msg["content"][0]["tool_use_id"] == "call_123"
    assert msg["content"][0]["content"] == "Sunny, 25C"

def test_claude_to_openai_response():
    """测试 Claude 响应转 OpenAI 格式"""
    claude_resp = {
        "id": "msg_01",
        "model": "claude-3-opus",
        "content": [
            {"type": "text", "text": "Thought..."},
            {"type": "tool_use", "id": "tc_01", "name": "ls", "input": {"path": "."}}
        ],
        "usage": {"input_tokens": 10, "output_tokens": 20}
    }

    openai_resp = ProtocolConverter.claude_to_openai(claude_resp)

    assert openai_resp["id"] == "msg_01"
    assert openai_resp["choices"][0]["message"]["content"] == "Thought..."
    tool_call = openai_resp["choices"][0]["message"]["tool_calls"][0]
    assert tool_call["function"]["name"] == "ls"
    assert json.loads(tool_call["function"]["arguments"]) == {"path": "."}
    assert openai_resp["usage"]["total_tokens"] == 30

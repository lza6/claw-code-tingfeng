"""core MCP stdio 服务器测试（回归：四个 server 模块没有 `__main__`，`python -m` 静默退出）

生成配置把 `src.core.mcp.{state,memory,trace,team}_server` 当 MCP 服务器登记，
但它们原先没有入口 —— `python -m` 会 exit 0 且零输出，客户端只看到 EOF。

这里用内存 stdin/stdout 直接驱动协议循环（不起子进程，快），
覆盖 initialize / tools=list / tools=call / 未知工具 / 通知 / 坏 JSON。
"""

from __future__ import annotations

import io
import json

from dataclasses import dataclass, field
from typing import Any

from src.core.mcp.stdio_server import PROTOCOL_VERSION, handle_request, serve
from src.core.mcp.state_server import STATE_SERVER_TOOLS, create_state_server
from src.core.mcp.trace_server import TRACE_SERVER_TOOLS


@dataclass
class _Entity:
    id: str
    name: str
    metadata: dict[str, Any] = field(default_factory=dict)


class _FakeServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def echo(self, text: str) -> dict:
        self.calls.append(("echo", {"text": text}))
        return {"echo": text}

    def fail(self) -> None:
        raise RuntimeError("boom")

    def take_entity(self, entity: _Entity) -> str:
        """单 dataclass 参数（memory.create_entity 就是这种形态）"""
        return entity.id

    def nothing(self) -> None:
        return None


TOOLS = {
    "echo": {"name": "echo", "description": "e", "inputSchema": {"type": "object"}},
    "fail": {"name": "fail", "description": "f", "inputSchema": {"type": "object"}},
    "take_entity": {"name": "take_entity", "description": "t", "inputSchema": {"type": "object"}},
    "nothing": {"name": "nothing", "description": "n", "inputSchema": {"type": "object"}},
}


def _drive(requests: list[dict], server: Any = None, tools: dict | None = None) -> list[dict]:
    stdin = io.StringIO("".join(json.dumps(r) + "\n" for r in requests))
    stdout = io.StringIO()
    code = serve(server or _FakeServer(), tools or TOOLS, stdin=stdin, stdout=stdout)
    assert code == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


class TestProtocol:
    def test_initialize_returns_protocol_and_server_info(self):
        out = _drive([{"jsonrpc": "2.0", "id": 1, "method": "initialize"}])
        result = out[0]["result"]
        assert result["protocolVersion"] == PROTOCOL_VERSION
        assert result["serverInfo"]["name"] == "clawd-mcp"
        assert result["capabilities"]["tools"]["listChanged"] is False

    def test_ping(self):
        out = _drive([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
        assert out[0]["result"] == {}

    def test_tools_list(self):
        out = _drive([{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        names = {t["name"] for t in out[0]["result"]["tools"]}
        assert names == set(TOOLS)

    def test_notification_gets_no_reply(self):
        out = _drive([
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        ])
        assert len(out) == 1
        assert out[0]["id"] == 3

    def test_bad_json_reports_parse_error(self):
        stdin = io.StringIO("{not json\n")
        stdout = io.StringIO()
        serve(_FakeServer(), TOOLS, stdin=stdin, stdout=stdout)
        payload = json.loads(stdout.getvalue().splitlines()[0])
        assert payload["error"]["code"] == -32700

    def test_unsupported_method(self):
        out = _drive([{"jsonrpc": "2.0", "id": 4, "method": "nothing/like/this"}])
        assert out[0]["error"]["code"] == -32601


class TestToolCalls:
    def test_call_returns_text_content(self):
        out = _drive([{
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hi"}},
        }])
        result = out[0]["result"]
        assert result["isError"] is False
        assert json.loads(result["content"][0]["text"]) == {"echo": "hi"}

    def test_unknown_tool_is_invalid_params(self):
        out = _drive([{
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        }])
        assert out[0]["error"]["code"] == -32602

    def test_tool_exception_becomes_is_error_result(self):
        out = _drive([{
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "fail", "arguments": {}},
        }])
        result = out[0]["result"]
        assert result["isError"] is True
        assert "RuntimeError" in result["content"][0]["text"]

    def test_dataclass_argument_is_coerced(self):
        out = _drive([{
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "take_entity", "arguments": {"id": "e1", "name": "n", "extra": 1}},
        }])
        assert out[0]["result"]["content"][0]["text"] == "e1"

    def test_none_result_serialized_as_null(self):
        out = _drive([{
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "nothing", "arguments": {}},
        }])
        assert out[0]["result"]["content"][0]["text"] == "null"


class TestRealServersExposeHandshake:
    def test_state_server_tools_callable(self, tmp_path):
        server = create_state_server(tmp_path)
        out = _drive(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "set_surface", "arguments": {"name": "x", "data": {"v": 1}}},
                },
                {
                    "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "get_surface", "arguments": {"name": "x"}},
                },
            ],
            server=server,
            tools=STATE_SERVER_TOOLS,
        )
        assert json.loads(out[3]["result"]["content"][0]["text"]) == {"v": 1}

    def test_trace_tool_names_have_no_typo(self):
        """曾有一个工具名写成 `sumsummarize_trace`（真实方法名是 summarize_trace）"""
        for name, spec in TRACE_SERVER_TOOLS.items():
            assert spec["name"] == name, f"{name} 的 name 字段不一致: {spec['name']}"
            assert "sumsum" not in spec["name"]

    def test_every_registered_tool_maps_to_a_real_method(self, tmp_path):
        """生成配置承诺的工具必须真的有实现方法，否则客户端调用必失败"""
        from src.core.mcp.memory_server import MEMORY_SERVER_TOOLS, create_memory_server
        from src.core.mcp.team_server import TEAM_SERVER_TOOLS, create_team_server
        from src.core.mcp.trace_server import create_trace_server

        pairs = [
            (create_state_server(tmp_path), STATE_SERVER_TOOLS, {}),
            (create_memory_server(tmp_path), MEMORY_SERVER_TOOLS, {"search_memory": "search"}),
            (create_trace_server(tmp_path), TRACE_SERVER_TOOLS, {}),
            (create_team_server(tmp_path), TEAM_SERVER_TOOLS, {}),
        ]
        missing = []
        for server, tools, alias in pairs:
            for tool_name in tools:
                method = alias.get(tool_name, tool_name)
                if not callable(getattr(server, method, None)):
                    missing.append(f"{type(server).__name__}.{method}")
        assert missing == []


class TestHandleRequestDirect:
    def test_returns_none_for_notification(self):
        assert handle_request(_FakeServer(), TOOLS, {"jsonrpc": "2.0", "method": "initialize"}) is None

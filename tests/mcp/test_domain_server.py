"""MCP 领域服务器测试（真实子进程往返，不用桩）

验证两件事：
1. 我们的 MCP server 能被标准 MCP 客户端（我们自己的 `src/mcp/client.py`）发现并调用
2. 四个领域工具的边界（路径穿越拒绝、只读、无匹配提示）
"""

from __future__ import annotations

import asyncio
import json
import sys

from pathlib import Path

import pytest


def _server_argv(root: Path) -> tuple[str, list[str]]:
    return (sys.executable, ["-m", "src.mcp.domain_server", "--root", str(root)])


class TestDomainServerDirect:
    """进程内直接驱动 JSON-RPC（快、覆盖协议细节）"""

    @pytest.fixture
    def server(self, tmp_path: Path):
        from src.mcp.domain_server import DomainServer

        (tmp_path / "demo.py").write_text("def hello():\n    return 42\n", encoding="utf-8")
        (tmp_path / "secret.txt").write_text("TOKEN=abc", encoding="utf-8")
        return DomainServer(tmp_path)

    def test_initialize_handshake(self, server):
        res = server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "1"}},
        })
        assert res["result"]["protocolVersion"] == "2024-11-05"
        assert res["result"]["serverInfo"]["name"] == "clawd-domain"
        assert "tools" in res["result"]["capabilities"]

    def test_initialized_notification_has_no_response(self, server):
        assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    def test_tools_list_exposes_four_domain_tools(self, server):
        res = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in res["result"]["tools"]}
        assert names == {"clawd_read_file", "clawd_grep", "clawd_project_map", "clawd_tool_list"}
        for tool in res["result"]["tools"]:
            assert tool["inputSchema"]["type"] == "object"

    def test_read_file_returns_content(self, server):
        res = server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "clawd_read_file", "arguments": {"path": "demo.py"}},
        })
        content = res["result"]["content"][0]["text"]
        assert "def hello" in content
        assert res["result"]["isError"] is False

    def test_read_file_blocks_path_traversal(self, server):
        res = server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "clawd_read_file", "arguments": {"path": "../../etc/passwd"}},
        })
        assert res["result"]["isError"] is True
        assert "越界" in res["result"]["content"][0]["text"]

    def test_read_file_missing(self, server):
        res = server.handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "clawd_read_file", "arguments": {"path": "nope.txt"}},
        })
        assert res["result"]["isError"] is True
        assert "不存在" in res["result"]["content"][0]["text"]

    def test_read_file_respects_max_bytes(self, server):
        res = server.handle({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "clawd_read_file",
                       "arguments": {"path": "demo.py", "max_bytes": 5}},
        })
        assert len(res["result"]["content"][0]["text"]) <= 5

    def test_grep_finds_match_and_reports_none(self, server):
        hit = server.handle({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "clawd_grep", "arguments": {"pattern": "hello", "glob": "*.py"}},
        })
        assert "def hello" in hit["result"]["content"][0]["text"]

        miss = server.handle({
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "clawd_grep", "arguments": {"pattern": "zzz-not-exist"}},
        })
        assert "无匹配" in miss["result"]["content"][0]["text"]

    def test_unknown_tool_is_protocol_error(self, server):
        res = server.handle({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        })
        assert res["error"]["code"] == -32602

    def test_unknown_method_is_protocol_error(self, server):
        res = server.handle({"jsonrpc": "2.0", "id": 10, "method": "resources/list"})
        assert res["error"]["code"] == -32601

    def test_project_map_never_crashes(self, server):
        res = server.handle({
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": "clawd_project_map", "arguments": {}},
        })
        assert res["result"]["isError"] is False
        assert res["result"]["content"][0]["text"]

    def test_tool_list_discovers_domain_tools(self, server):
        res = server.handle({
            "jsonrpc": "2.0", "id": 12, "method": "tools/call",
            "params": {"name": "clawd_tool_list", "arguments": {}},
        })
        text = res["result"]["content"][0]["text"]
        assert res["result"]["isError"] is False
        assert text.strip()


class TestMcpClientRoundtrip:
    """真实子进程 + 我们自己的 MCP 客户端（端到端互操作）"""

    def test_client_discovers_and_calls_tools(self, tmp_path: Path):
        from src.mcp.client import MCPClient, MCPClientConfig

        (tmp_path / "sample.py").write_text("VALUE = 'clawd-mcp-probe'\n", encoding="utf-8")
        command, args = _server_argv(tmp_path)

        async def scenario():
            client = MCPClient(MCPClientConfig(
                name="clawd-domain", transport="stdio", command=command, args=args,
            ))
            await client.connect()
            try:
                tools = await client.list_tools()
                names = {t.name for t in tools}
                result = await client.call_tool("clawd_read_file", {"path": "sample.py"})
                return names, result
            finally:
                await client.disconnect()

        names, result = asyncio.run(scenario())

        assert "clawd_read_file" in names
        assert "clawd_grep" in names
        payload = json.dumps(result, ensure_ascii=False, default=str)
        assert "clawd-mcp-probe" in payload

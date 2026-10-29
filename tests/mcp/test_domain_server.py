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

    def test_tools_list_exposes_domain_and_world_model_tools(self, server):
        res = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in res["result"]["tools"]}
        assert names == {
            "clawd_read_file", "clawd_grep", "clawd_project_map", "clawd_tool_list",
            "clawd_world_model_context", "clawd_world_model_predict",
            "clawd_world_model_stats",
        }
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


class TestWorldModelTools:
    """世界模型工具：把我们的代码库认知共享给任何引擎"""

    @pytest.fixture
    def wm_server(self, tmp_path: Path):
        from src.mcp.domain_server import DomainServer

        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "pkg" / "core.py").write_text(
            "def helper():\n    return 1\n\n\ndef main():\n    return helper()\n", encoding="utf-8"
        )
        (tmp_path / "pkg" / "user.py").write_text(
            "from pkg.core import helper\n\n\ndef run():\n    return helper()\n", encoding="utf-8"
        )
        return DomainServer(tmp_path)

    def _call(self, server, name, args):
        return server.handle({
            "jsonrpc": "2.0", "id": 99, "method": "tools/call",
            "params": {"name": name, "arguments": args},
        })

    def test_stats_returns_json(self, wm_server):
        res = self._call(wm_server, "clawd_world_model_stats", {})
        body = res["result"]["content"][0]["text"]
        assert res["result"]["isError"] is False
        data = json.loads(body)
        assert "node_count" in data

    def test_context_returns_upstream_downstream_patterns(self, wm_server):
        res = self._call(wm_server, "clawd_world_model_context",
                         {"file_path": "pkg/user.py"})
        assert res["result"]["isError"] is False
        data = json.loads(res["result"]["content"][0]["text"])
        assert data["file"].endswith("user.py")
        assert "upstream" in data and "downstream" in data and "patterns" in data

    def test_context_rejects_missing_file(self, wm_server):
        res = self._call(wm_server, "clawd_world_model_context",
                         {"file_path": "pkg/nope.py"})
        assert res["result"]["isError"] is True
        assert "不存在" in res["result"]["content"][0]["text"]

    def test_context_rejects_traversal(self, wm_server):
        res = self._call(wm_server, "clawd_world_model_context",
                         {"file_path": "../../etc/passwd"})
        assert res["result"]["isError"] is True

    def test_predict_returns_list(self, wm_server):
        res = self._call(wm_server, "clawd_world_model_predict",
                         {"current_file": "pkg/user.py", "depth": 1})
        assert res["result"]["isError"] is False
        data = json.loads(res["result"]["content"][0]["text"])
        assert data["current_file"] == "pkg/user.py"
        assert isinstance(data["predicted"], list)

    def test_empty_file_path_rejected(self, wm_server):
        res = self._call(wm_server, "clawd_world_model_predict", {"current_file": "  "})
        assert res["result"]["isError"] is True


class TestProjectMapUsesRealRepoMap:
    """回归：`clawd_project_map` 曾因签名写错永远走降级分支

    旧代码 `RepoMap(root=...)` + `get_map()`（缺必填 files）两处 TypeError，
    对外只返回 Python 文件清单，却带着"符号图谱不可用"的字样当结果。
    """

    def test_returns_real_symbols_not_fallback(self, tmp_path: Path):
        from src.mcp.domain_server import DomainServer

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "alpha.py").write_text(
            "def alpha_func(x):\n    return x\n\nclass AlphaClass:\n    pass\n",
            encoding="utf-8",
        )
        server = DomainServer(tmp_path)
        text = server._tool_project_map({"max_files": 10})["content"][0]["text"]

        assert "符号图谱不可用" not in text
        assert "alpha_func" in text
        assert "AlphaClass" in text

    def test_empty_project_reports_honestly(self, tmp_path: Path):
        from src.mcp.domain_server import DomainServer

        server = DomainServer(tmp_path)
        text = server._tool_project_map({"max_files": 10})["content"][0]["text"]
        assert "没有 Python 文件" in text

    def test_max_files_is_respected(self, tmp_path: Path):
        from src.mcp.domain_server import DomainServer

        for i in range(6):
            (tmp_path / f"m{i}.py").write_text(f"def f{i}():\n    pass\n", encoding="utf-8")
        server = DomainServer(tmp_path)
        text = server._tool_project_map({"max_files": 2})["content"][0]["text"]
        assert text.count("//") <= 2

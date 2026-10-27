"""MCP Client / Tool Bridge 测试"""
import asyncio

import pytest

from src.mcp.client import (
    MCPClientConfig,
    MCPClientError,
    MCPHttpClient,
    MCPServerManager,
    create_client,
)
from src.mcp.tool_bridge import MCPExternalTool, bridge_all, bridge_server_tools
from src.tools_runtime.tool_interface import ToolRegistry, execute_tool


# ============ 配置解析 ============

class TestMCPClientConfig:
    def test_stdio_config(self):
        cfg = MCPClientConfig.from_dict({
            "name": "test",
            "command": "python",
            "args": ["-m", "some_server"],
        })
        assert cfg.transport == "stdio"
        assert cfg.command == "python"

    def test_http_config(self):
        cfg = MCPClientConfig.from_dict({
            "name": "ghidra",
            "transport": "http",
            "url": "http://localhost:8080/mcp",
        })
        assert cfg.transport == "http"
        assert cfg.url == "http://localhost:8080/mcp"

    def test_stdio_requires_command(self):
        with pytest.raises(MCPClientError):
            MCPClientConfig.from_dict({"name": "bad"})

    def test_http_requires_url(self):
        with pytest.raises(MCPClientError):
            MCPClientConfig.from_dict({"name": "bad", "transport": "http"})

    def test_roundtrip(self):
        data = {
            "name": "x", "command": "npx", "args": ["-y", "foo"],
            "env": {"A": "1"}, "timeout_seconds": 5,
        }
        cfg = MCPClientConfig.from_dict(data)
        assert cfg.to_dict()["command"] == "npx"


# ============ HTTP 客户端（用 mock transport 测，不发真实网络） ============

class _MockResponse:
    def __init__(self, data, status_code=200, headers=None):
        self._data = data
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._data

    @property
    def text(self):
        import json
        return json.dumps(self._data)


class _MockAsyncClient:
    """记录请求并返回预置响应"""

    calls: list = []

    def __init__(self, **kwargs):
        self.base_url = kwargs.get("base_url", "")
        self.headers = kwargs.get("headers", {})
        self.timeout = kwargs.get("timeout")

    async def post(self, url, json=None):
        _MockAsyncClient.calls.append(json)
        method = json.get("method")
        rid = json.get("id")
        if method == "initialize":
            return _MockResponse({
                "jsonrpc": "2.0", "id": rid,
                "result": {"serverInfo": {"name": "mock", "version": "1"}},
            })
        if method == "tools/list":
            return _MockResponse({
                "jsonrpc": "2.0", "id": rid,
                "result": {"tools": [
                    {"name": "decompile", "description": "反编译函数",
                     "inputSchema": {"type": "object", "properties": {"addr": {"type": "string"}}}},
                    {"name": "list_funcs", "description": "列出函数", "inputSchema": {}},
                ]},
            })
        if method == "tools/call":
            name = json["params"]["name"]
            if name == "boom":
                return _MockResponse({
                    "jsonrpc": "2.0", "id": rid,
                    "result": {"isError": True, "content": [{"type": "text", "text": "段错误"}]},
                })
            return _MockResponse({
                "jsonrpc": "2.0", "id": rid,
                "result": {"isError": False, "content": [
                    {"type": "text", "text": f"result of {name}"}
                ]},
            })
        if method == "rpc_error":
            return _MockResponse({
                "jsonrpc": "2.0", "id": rid, "error": {"code": -1, "message": "bad method"},
            })
        return _MockResponse({"jsonrpc": "2.0", "id": rid, "result": {}}, status_code=500)

    async def aclose(self):
        pass


@pytest.fixture
def http_client(monkeypatch):
    _MockAsyncClient.calls = []
    monkeypatch.setattr("src.mcp.client.httpx.AsyncClient", _MockAsyncClient)
    cfg = MCPClientConfig(name="mockghidra", transport="http", url="http://mock:1/mcp")
    return MCPHttpClient(cfg)


class TestMCPHttpClient:
    def test_create_client_dispatch(self):
        c = create_client(MCPClientConfig(name="a", transport="http", url="http://x"))
        assert isinstance(c, MCPHttpClient)
        c2 = create_client(MCPClientConfig(name="b", command="echo"))
        assert not isinstance(c2, MCPHttpClient)

    def test_connect_and_list_tools(self, http_client):
        async def run():
            await http_client.connect()
            tools = await http_client.list_tools()
            return tools

        tools = asyncio.run(run())
        assert len(tools) == 2
        assert tools[0].qualified_name == "mcp__mockghidra__decompile"

    def test_list_tools_cached(self, http_client):
        async def run():
            await http_client.connect()
            await http_client.list_tools()
            return await http_client.list_tools()  # 第二次走缓存

        tools = asyncio.run(run())
        assert len(tools) == 2
        # 只有一次 tools/list RPC
        calls = [c for c in _MockAsyncClient.calls if c.get("method") == "tools/list"]
        assert len(calls) == 1

    def test_call_tool_success(self, http_client):
        async def run():
            await http_client.connect()
            return await http_client.call_tool("list_funcs", {})

        out = asyncio.run(run())
        assert out == "result of list_funcs"

    def test_call_tool_error(self, http_client):
        async def run():
            await http_client.connect()
            return await http_client.call_tool("boom", {})

        with pytest.raises(MCPClientError, match="段错误"):
            asyncio.run(run())

    def test_call_without_connect(self, http_client):
        async def run():
            return await http_client.call_tool("x", {})

        with pytest.raises(MCPClientError, match="未连接"):
            asyncio.run(run())

    def test_sse_response(self, http_client, monkeypatch):
        import json as _json

        class _SSEResponse(_MockResponse):
            def __init__(self, data):
                super().__init__(data)
                self.headers = {"content-type": "text/event-stream"}

            @property
            def text(self):
                payload = _json.dumps(self._data)
                return f"event: message\ndata: {payload}\n\n"

        class _SSEClient(_MockAsyncClient):
            async def post(self, url, json=None):
                method = json.get("method")
                rid = json.get("id")
                if method == "initialize":
                    return _SSEResponse({
                        "jsonrpc": "2.0", "id": rid,
                        "result": {"serverInfo": {"name": "sse"}},
                    })
                return _SSEResponse({
                    "jsonrpc": "2.0", "id": rid,
                    "result": {"tools": [{"name": "t1", "description": "", "inputSchema": {}}]},
                })

        monkeypatch.setattr("src.mcp.client.httpx.AsyncClient", _SSEClient)
        cfg = MCPClientConfig(name="sse-srv", transport="http", url="http://mock:2")
        c = MCPHttpClient(cfg)

        async def run():
            await c.connect()
            return await c.list_tools()

        tools = asyncio.run(run())
        assert tools[0].name == "t1"


# ============ Manager ============

class TestMCPServerManager:
    def test_register_and_names(self):
        m = MCPServerManager()
        m.register(MCPClientConfig(name="s1", transport="http", url="http://x"))
        assert m.server_names == ["s1"]

    def test_register_duplicate(self):
        m = MCPServerManager()
        m.register(MCPClientConfig(name="s1", transport="http", url="http://x"))
        with pytest.raises(MCPClientError, match="已注册"):
            m.register(MCPClientConfig(name="s1", transport="http", url="http://x"))

    def test_call_unregistered(self):
        m = MCPServerManager()
        with pytest.raises(MCPClientError, match="未注册"):
            asyncio.run(m.call("nope", "tool", {}))

    def test_discover_all_skips_broken(self, monkeypatch):
        m = MCPServerManager()
        m.register(MCPClientConfig(name="ok", transport="http", url="http://x"))

        class _Broken:
            is_connected = False

            async def connect(self):
                raise MCPClientError("连接失败")

        class _OkClient(_MockAsyncClient):
            pass

        m._clients["ok"] = _make_connected_mock()
        m._clients["broken"] = _Broken()
        tools = asyncio.run(m.discover_all_tools())
        assert len(tools) == 2  # 只有 ok 的两个工具


def _make_connected_mock():
    c = MCPHttpClient(MCPClientConfig(name="ok", transport="http", url="http://x"))
    c._http = _MockAsyncClient(base_url="http://x")
    c._connected = True
    return c


# ============ Tool Bridge ============

class TestToolBridge:
    def test_bridge_and_execute(self, monkeypatch):
        monkeypatch.setattr("src.mcp.client.httpx.AsyncClient", _MockAsyncClient)
        manager = MCPServerManager()
        manager.register(MCPClientConfig(name="gh", transport="http", url="http://g:1"))
        registry = ToolRegistry()

        async def setup():
            tools = await bridge_server_tools(manager, "gh", registry)
            return tools

        tools = asyncio.run(setup())
        assert len(tools) == 2
        # 注册进 registry 后可查到
        names = [t.name for t in registry.list_tools(category="mcp_external")]
        assert "mcp__gh__decompile" in names
        # 通过统一 execute_tool 不可行（全局 registry 不同），直接调 adapter
        tool = registry.get("mcp__gh__decompile")
        assert isinstance(tool, MCPExternalTool)
        result = tool.execute(addr="0x401000")
        assert result.is_success
        assert result.output == "result of decompile"
        assert result.metadata["server"] == "gh"

    def test_bridge_broken_server(self, monkeypatch):
        manager = MCPServerManager()
        manager.register(MCPClientConfig(name="bad", transport="http", url="http://x"))
        # 不 mock httpx，connect 会失败 —— bridge 应吞掉错误返回空
        registry = ToolRegistry()
        tools = asyncio.run(bridge_server_tools(manager, "bad", registry))
        assert tools == []

    def test_bridge_all(self, monkeypatch):
        monkeypatch.setattr("src.mcp.client.httpx.AsyncClient", _MockAsyncClient)
        manager = MCPServerManager()
        manager.register(MCPClientConfig(name="a", transport="http", url="http://a"))
        manager.register(MCPClientConfig(name="b", transport="http", url="http://b"))
        from src.mcp.client import MCPHttpClient

        for name in ("a", "b"):
            c = MCPHttpClient(MCPClientConfig(name=name, transport="http", url=f"http://{name}"))
            c._http = _MockAsyncClient(base_url=f"http://{name}")
            c._connected = True
            manager._clients[name] = c
        n = asyncio.run(bridge_all(manager, ToolRegistry()))
        assert n == 4

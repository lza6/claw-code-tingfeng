"""MCP Client — 外部 MCP server 桥接层（自研内核 + MCP 桥接的核心）

提供:
- MCPClientConfig: 连接配置（stdio / HTTP）
- MCPClient: 外部 server 连接、工具发现、工具调用
- MCPToolBridge: 把外部 MCP 工具适配为 clawd BaseTool 注册进 ToolRegistry
- MCPServerManager: 多 server 生命周期管理（含按需工具发现）
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """MCP 客户端错误"""


@dataclass
class MCPClientConfig:
    """外部 MCP server 连接配置"""
    name: str
    transport: str = "stdio"  # stdio | http
    # stdio 参数
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # http 参数
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    # 通用
    timeout_seconds: float = 30.0
    requires_approval: bool = False  # 检疫期未通过时强制为 True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPClientConfig":
        cfg = cls(
            name=data["name"],
            transport=data.get("transport", "stdio"),
            timeout_seconds=float(data.get("timeout_seconds", 30)),
            requires_approval=bool(data.get("requires_approval", False)),
        )
        if cfg.transport == "stdio":
            cfg.command = data.get("command")
            cfg.args = list(data.get("args", []))
            cfg.env = dict(data.get("env", {}))
            if not cfg.command:
                raise MCPClientError(f"stdio 传输需要 command: {cfg.name}")
        else:
            cfg.url = data.get("url")
            cfg.headers = dict(data.get("headers", {}))
            if not cfg.url:
                raise MCPClientError(f"http 传输需要 url: {cfg.name}")
        return cfg

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "transport": self.transport,
            "timeout_seconds": self.timeout_seconds,
            "requires_approval": self.requires_approval,
        }
        if self.transport == "stdio":
            d["command"] = self.command
            d["args"] = self.args
            d["env"] = self.env
        else:
            d["url"] = self.url
            d["headers"] = self.headers
        return d


@dataclass
class MCPToolInfo:
    """外部 MCP 工具描述"""
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        """全局唯一名: mcp__<server>__<tool>"""
        return f"mcp__{self.server}__{self.name}"


class MCPClient:
    """单个外部 MCP server 的客户端

    用法（异步）:
        client = MCPClient(config)
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("tool_name", {"arg": 1})
        await client.disconnect()
    """

    def __init__(self, config: MCPClientConfig):
        self.config = config
        self._session: ClientSession | None = None
        self._stdio_cm: Any = None  # stdio_client 的 async context manager
        self._connected = False
        self._tools: dict[str, MCPToolInfo] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """建立连接并初始化会话"""
        if self._connected:
            return
        if self.config.transport == "stdio":
            env = dict(self.config.env) or None
            params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
                env=env,
            )
            self._stdio_cm = stdio_client(params)
            try:
                read_stream, write_stream = await self._stdio_cm.__aenter__()
                self._session = ClientSession(read_stream, write_stream)
                await self._session.__aenter__()
                await asyncio.wait_for(
                    self._session.initialize(),
                    timeout=self.config.timeout_seconds,
                )
            except BaseException:
                # 半途失败：回滚已进入的 context manager，防 stdio 子进程泄漏
                logger.warning(f"MCP 连接失败，回滚会话: {self.config.name}")
                await self.disconnect()
                raise
        else:
            raise MCPClientError(
                f"HTTP 传输暂由 MCPHttpClient 处理: {self.config.name}"
            )
        self._connected = True
        logger.info(f"MCP server 已连接: {self.config.name}")

    async def disconnect(self) -> None:
        """关闭会话"""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001 — 关闭时尽最大努力
                logger.warning(f"关闭 session 异常: {e}")
            self._session = None
        if self._stdio_cm:
            try:
                await self._stdio_cm.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"关闭 stdio 传输异常: {e}")
            self._stdio_cm = None
        self._connected = False
        logger.info(f"MCP server 已断开: {self.config.name}")

    async def list_tools(self, refresh: bool = False) -> list[MCPToolInfo]:
        """发现工具（缓存，refresh=True 强制刷新）"""
        if self._tools and not refresh:
            return list(self._tools.values())
        self._ensure_session()
        try:
            resp = await asyncio.wait_for(
                self._session.list_tools(),
                timeout=self.config.timeout_seconds,
            )
        except asyncio.TimeoutError as e:
            raise MCPClientError(f"list_tools 超时: {self.config.name}") from e
        self._tools = {}
        for t in resp.tools:
            info = MCPToolInfo(
                server=self.config.name,
                name=t.name,
                description=t.description or "",
                input_schema=getattr(t, "inputSchema", None) or {},
            )
            self._tools[t.name] = info
        return list(self._tools.values())

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> Any:
        """调用外部工具，返回文本内容拼接结果"""
        self._ensure_session()
        arguments = arguments or {}
        try:
            resp = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments),
                timeout=self.config.timeout_seconds,
            )
        except asyncio.TimeoutError as e:
            raise MCPClientError(
                f"call_tool 超时: {self.config.name}.{tool_name}"
            ) from e
        if getattr(resp, "isError", False):
            parts = []
            for c in resp.content:
                if hasattr(c, "text"):
                    parts.append(c.text)
            raise MCPClientError(
                f"工具执行错误 {self.config.name}.{tool_name}: "
                + "\n".join(parts)
            )
        return self._content_to_text(resp.content)

    def _ensure_session(self) -> ClientSession:
        if not self._connected or self._session is None:
            raise MCPClientError(
                f"未连接: {self.config.name}（先调用 connect()）"
            )
        return self._session

    @staticmethod
    def _content_to_text(content: Any) -> str:
        """把 MCP content 列表转成文本（text 优先，结构化序列化为 JSON）"""
        if content is None:
            return ""
        parts: list[str] = []
        for c in content:
            if hasattr(c, "text"):
                parts.append(c.text)
            elif hasattr(c, "data"):
                # 图片等二进制内容只记录元信息
                mime = getattr(c, "mimeType", "unknown")
                parts.append(f"[binary content: {mime}]")
            else:
                parts.append(json.dumps(c, ensure_ascii=False, default=str))
        return "\n".join(parts)


class MCPHttpClient(MCPClient):
    """Streamable HTTP 传输的 MCP 客户端（GhidraMCP、x64dbg 等远程 server）"""

    def __init__(self, config: MCPClientConfig):
        super().__init__(config)
        self._http: httpx.AsyncClient | None = None
        self._next_id = 1

    async def connect(self) -> None:
        if self._connected:
            return
        assert self.config.url, "http 传输需要 url"
        self._http = httpx.AsyncClient(
            base_url=self.config.url,
            headers={**self.config.headers, "Accept": "application/json, text/event-stream"},
            timeout=self.config.timeout_seconds,
        )
        init = await self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "clawd-mcp-client", "version": "1.0.0"},
        })
        # 通知 initialized（某些 server 要求）
        try:
            await self._http.post("", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception as e:  # noqa: BLE001 — 通知失败不阻断
            logger.debug(f"initialized 通知异常: {e}")
        server_info = init.get("serverInfo", {})
        logger.info(
            f"MCP HTTP server 已连接: {self.config.name} "
            f"({server_info.get('name', 'unknown')})"
        )
        self._connected = True

    async def disconnect(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        self._connected = False

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        if self._http is None:
            raise MCPClientError(f"未连接: {self.config.name}")
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        self._next_id += 1
        try:
            resp = await self._http.post("", json=payload)
        except httpx.HTTPError as e:
            raise MCPClientError(f"HTTP 请求失败 {self.config.name}: {e}") from e
        if resp.status_code >= 400:
            raise MCPClientError(
                f"HTTP {resp.status_code}: {self.config.name} {method}"
            )
        ct = resp.headers.get("content-type", "")
        if "text/event-stream" in ct:
            # SSE 响应：取最后一个 data 行的 JSON
            result = None
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    try:
                        msg = json.loads(line[5:].strip())
                        if "error" in msg:
                            raise MCPClientError(f"{method}: {msg['error']}")
                        if "id" in msg and "result" in msg:
                            result = msg["result"]
                    except json.JSONDecodeError:
                        continue
            if result is None:
                raise MCPClientError(f"SSE 响应无结果: {method}")
            return result
        data = resp.json()
        if "error" in data:
            raise MCPClientError(f"{method}: {data['error']}")
        return data.get("result")

    async def list_tools(self, refresh: bool = False) -> list[MCPToolInfo]:
        if self._tools and not refresh:
            return list(self._tools.values())
        result = await self._rpc("tools/list", {})
        self._tools = {}
        for t in result.get("tools", []):
            info = MCPToolInfo(
                server=self.config.name,
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            self._tools[info.name] = info
        return list(self._tools.values())

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> str:
        result = await self._rpc(
            "tools/call", {"name": tool_name, "arguments": arguments or {}}
        )
        if result.get("isError"):
            texts = [
                c.get("text", "")
                for c in result.get("content", [])
                if isinstance(c, dict)
            ]
            raise MCPClientError(
                f"工具执行错误 {self.config.name}.{tool_name}: " + "\n".join(texts)
            )
        parts: list[str] = []
        for c in result.get("content", []):
            if isinstance(c, dict) and "text" in c:
                parts.append(c["text"])
            else:
                parts.append(json.dumps(c, ensure_ascii=False, default=str))
        return "\n".join(parts)


def create_client(config: MCPClientConfig) -> MCPClient:
    """按传输类型创建客户端"""
    if config.transport == "http":
        return MCPHttpClient(config)
    return MCPClient(config)


class MCPServerManager:
    """多 server 管理器：连接池 + 按需工具发现 + 统一调用入口"""

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}

    @property
    def server_names(self) -> list[str]:
        return list(self._clients.keys())

    def register(self, config: MCPClientConfig) -> None:
        """注册配置（不连接，惰性连接）"""
        if config.name in self._clients:
            raise MCPClientError(f"server 已注册: {config.name}")
        self._clients[config.name] = create_client(config)

    async def ensure_connected(self, name: str) -> MCPClient:
        client = self._clients.get(name)
        if client is None:
            raise MCPClientError(f"server 未注册: {name}")
        if not client.is_connected:
            await client.connect()
        return client

    async def disconnect_all(self) -> None:
        for name, client in self._clients.items():
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"断开 {name} 异常: {e}")

    async def discover_tools(self, server: str) -> list[MCPToolInfo]:
        client = await self.ensure_connected(server)
        return await client.list_tools()

    async def discover_all_tools(self) -> list[MCPToolInfo]:
        """发现所有已注册 server 的工具（惰性连接失败的服务器跳过并告警）"""
        all_tools: list[MCPToolInfo] = []
        for name in self._clients:
            try:
                all_tools.extend(await self.discover_tools(name))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"发现 {name} 工具失败（跳过）: {e}")
        return all_tools

    async def call(self, server: str, tool: str, arguments: dict[str, Any] | None = None) -> str:
        client = await self.ensure_connected(server)
        return await client.call_tool(tool, arguments)


# 全局单例
_manager: MCPServerManager | None = None


def get_mcp_manager() -> MCPServerManager:
    global _manager
    if _manager is None:
        _manager = MCPServerManager()
    return _manager

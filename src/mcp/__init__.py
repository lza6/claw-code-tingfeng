"""MCP Server — Model Context Protocol Server（参考 Onyx mcp_server）"""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

# 导入 MCP 服务器模块
from .memory_server import (
    MemoryEntry,
    MemoryIndex,
    MemoryServer,
    get_memory_server,
)

# 导入状态服务器
from .state_server import (
    SUPPORTED_MODES,
    Mode,
    ModeState,
    StateServer,
    build_mcp_tools,
    get_state_server,
)
from .trace_server import (
    TraceEntry,
    TraceLevel,
    TraceServer,
    TraceSession,
    get_trace_server,
)

logger = logging.getLogger(__name__)


class MCPTransport(str, Enum):
    """MCP 传输方式"""
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


class MCPMethod(str, Enum):
    """MCP 方法"""
    INITIALIZE = "initialize"
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"
    PROMPTS_LIST = "prompts/list"
    PROMPTS_GET = "prompts/get"
    COMPLETION = "complete"


@dataclass
class MCPRequest:
    """MCP 请求"""
    method: MCPMethod
    params: dict[str, Any]
    id: str | None = None


@dataclass
class MCPResponse:
    """MCP 响应"""
    result: Any
    error: str | None = None
    id: str | None = None


@dataclass
class MCPTool:
    """MCP 工具"""
    name: str
    description: str
    input_schema: dict
    handler: Any = None  # async function


class MCPServer:
    """MCP Server 实现"""

    def __init__(self, name: str = "clawd-mcp", version: str = "0.1.0"):
        self.name = name
        self.version = version
        self._tools: dict[str, MCPTool] = {}
        self._resources: dict[str, Any] = {}
        self._prompts: dict[str, Any] = {}
        self._initialized = False

    def register_tool(self, tool: MCPTool):
        """注册工具"""
        self._tools[tool.name] = tool
        logger.info(f"Registered MCP tool: {tool.name}")

    def register_resource(self, uri: str, content: Any):
        """注册资源"""
        self._resources[uri] = content
        logger.info(f"Registered MCP resource: {uri}")

    def register_prompt(self, name: str, template: str, variables: list[str]):
        """注册提示词"""
        self._prompts[name] = {
            "template": template,
            "variables": variables,
        }
        logger.info(f"Registered MCP prompt: {name}")

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """处理 MCP 请求"""
        try:
            result = None

            if request.method == MCPMethod.INITIALIZE:
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": self.name,
                        "version": self.version,
                    },
                    "capabilities": {
                        "tools": bool(self._tools),
                        "resources": bool(self._resources),
                        "prompts": bool(self._prompts),
                    },
                }
                self._initialized = True

            elif request.method == MCPMethod.TOOLS_LIST:
                result = {
                    "tools": [
                        {
                            "name": name,
                            "description": tool.description,
                            "inputSchema": tool.input_schema,
                        }
                        for name, tool in self._tools.items()
                    ]
                }

            elif request.method == MCPMethod.TOOLS_CALL:
                tool_name = request.params.get("name")
                tool_args = request.params.get("arguments", {})

                tool = self._tools.get(tool_name)
                if not tool:
                    return MCPResponse(
                        result=None,
                        error=f"Tool not found: {tool_name}",
                        id=request.id
                    )

                if tool.handler:
                    result = await tool.handler(**tool_args)
                else:
                    result = {"status": "ok"}

            elif request.method == MCPMethod.RESOURCES_LIST:
                result = {
                    "resources": [
                        {"uri": uri, "name": uri.split("/")[-1]}
                        for uri in self._resources
                    ]
                }

            elif request.method == MCPMethod.RESOURCES_READ:
                uri = request.params.get("uri")
                result = {"contents": [{"uri": uri, "text": self._resources.get(uri)}]}

            elif request.method == MCPMethod.PROMPTS_LIST:
                result = {
                    "prompts": [
                        {"name": name, "description": f"Prompt: {name}"}
                        for name in self._prompts
                    ]
                }

            else:
                return MCPResponse(
                    result=None,
                    error=f"Unknown method: {request.method}",
                    id=request.id
                )

            return MCPResponse(result=result, id=request.id)

        except Exception as e:
            logger.exception(f"MCP request failed: {request.method}")
            return MCPResponse(result=None, error=str(e), id=request.id)

    # 标准工具实现
    async def tool_echo(self, **kwargs) -> dict:
        """Echo 工具"""
        return {"echo": kwargs}

    async def tool_read_file(self, path: str) -> dict:
        """读取文件"""
        try:
            with open(path) as f:
                content = f.read()
            return {"content": content, "path": path}
        except Exception as e:
            return {"error": str(e), "path": path}

    async def tool_write_file(self, path: str, content: str) -> dict:
        """写入文件"""
        try:
            with open(path, "w") as f:
                f.write(content)
            return {"status": "ok", "path": path}
        except Exception as e:
            return {"error": str(e), "path": path}

    async def tool_run_command(self, command: str, cwd: str | None = None) -> dict:
        """运行命令"""
        import subprocess
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except Exception as e:
            return {"error": str(e)}

    def register_standard_tools(self):
        """注册标准工具"""
        self.register_tool(MCPTool(
            name="echo",
            description="Echo back the input",
            input_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
            handler=self.tool_echo,
        ))

        self.register_tool(MCPTool(
            name="read_file",
            description="Read a file",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=self.tool_read_file,
        ))

        self.register_tool(MCPTool(
            name="write_file",
            description="Write to a file",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=self.tool_write_file,
        ))

        self.register_tool(MCPTool(
            name="run_command",
            description="Run a shell command",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                },
                "required": ["command"],
            },
            handler=self.tool_run_command,
        ))

    def register_state_tools(self):
        """注册状态管理工具（来自 oh-my-codex）"""
        state_tools = build_mcp_tools()
        for tool_def in state_tools:
            self.register_tool(MCPTool(
                name=tool_def["name"],
                description=tool_def["description"],
                input_schema=tool_def["inputSchema"],
                handler=None,  # 将在运行时动态路由
            ))

    # STDIO 模式入口
    async def run_stdio_server():
        """STDIO 模式运行服务器"""
        import json
        import sys

        server = MCPServer()
        server.register_standard_tools()
        server.register_state_tools()

        logger.info("MCP Server running in STDIO mode")

        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )
                if not line:
                    break

                request_data = json.loads(line)
                request = MCPRequest(
                    method=MCPMethod(request_data.get("method", "")),
                    params=request_data.get("params", {}),
                    id=request_data.get("id"),
                )

                response = await server.handle_request(request)
                print(json.dumps({
                    "result": response.result,
                    "error": response.error,
                    "id": response.id,
                }), flush=True)

            except Exception:
                logger.exception("Error in STDIO loop")

    # SSE 模式入口
    async def run_sse_server(host: str = "0.0.0.0", port: int = 8080):
        """SSE 模式运行服务器"""
        from aiohttp import web

        server = MCPServer()
        server.register_standard_tools()
        server.register_state_tools()

        async def handle_mcp(request):
            data = await request.json()
            mcp_request = MCPRequest(
                method=MCPMethod(data.get("method")),
                params=data.get("params", {}),
                id=data.get("id"),
            )
            response = await server.handle_request(mcp_request)
            return web.json_response({
                "result": response.result,
                "error": response.error,
                "id": response.id,
            })

        app = web.Application()
        app.router.add_post("/mcp", handle_mcp)

        logger.info(f"MCP Server running on {host}:{port}")
        await web.run_app(app, host=host, port=port)


__all__ = [
    "SUPPORTED_MODES",
    "MCPMethod",
    "MCPRequest",
    "MCPResponse",
    "MCPServer",
    "MCPTool",
    "MCPTransport",
    # Memory Server
    "MemoryEntry",
    "MemoryIndex",
    "MemoryServer",
    # State Server (新增)
    "Mode",
    "ModeState",
    "StateServer",
    "TraceEntry",
    # Trace Server
    "TraceLevel",
    "TraceServer",
    "TraceSession",
    "get_memory_server",
    "get_state_server",
    "get_trace_server",
    "run_sse_server",
    "run_stdio_server",
]

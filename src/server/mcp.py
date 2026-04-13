"""
MCP 服务器模块 - 整合自 Onyx
MCP (Model Context Protocol) 服务器支持
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger


class MCPMethod(str, Enum):
    """MCP 方法"""
    INITIALIZE = "initialize"
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"
    PROMPTS_LIST = "prompts/list"
    PROMPTS_RENDER = "prompts/render"


@dataclass
class MCPTool:
    """MCP 工具定义"""
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    handler: Callable | None = None


@dataclass
class MCPResource:
    """MCP 资源定义"""
    uri: str
    name: str
    description: str = ""
    mime_type: str = "text/plain"


@dataclass
class MCPrompt:
    """MCP 提示模板"""
    name: str
    description: str
    arguments: list[dict[str, Any]] = field(default_factory=list)
    template: str = ""


@dataclass
class MCPRequest:
    """MCP 请求"""
    jsonrpc: str = "2.0"
    id: Any = None
    method: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPResponse:
    """MCP 响应"""
    jsonrpc: str = "2.0"
    id: Any = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class MCPServer:
    """
    MCP 服务器（整合自 Onyx 的 MCP 服务器模式）

    功能:
    - MCP 协议实现
    - 工具注册和调用
    - 资源管理
    - 提示模板
    """

    def __init__(self, server_name: str = "clawed-code", server_version: str = "1.0.0"):
        self.server_name = server_name
        self.server_version = server_version

        # 注册的 tools/resources/prompts
        self._tools: dict[str, MCPTool] = {}
        self._resources: dict[str, MCPResource] = {}
        self._prompts: dict[str, MCPrompt] = {}

        # 初始化完成标志
        self._initialized = False
        self._capabilities: dict[str, Any] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable,
    ):
        """注册工具"""
        tool = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )
        self._tools[name] = tool
        logger.info(f"MCP 工具已注册: {name}")

    def register_resource(
        self,
        uri: str,
        name: str,
        description: str = "",
        mime_type: str = "text/plain",
    ):
        """注册资源"""
        resource = MCPResource(
            uri=uri,
            name=name,
            description=description,
            mime_type=mime_type,
        )
        self._resources[uri] = resource
        logger.info(f"MCP 资源已注册: {uri}")

    def register_prompt(
        self,
        name: str,
        description: str,
        template: str,
        arguments: list[dict[str, Any]] | None = None,
    ):
        """注册提示模板"""
        prompt = MCPrompt(
            name=name,
            description=description,
            template=template,
            arguments=arguments or [],
        )
        self._prompts[name] = prompt
        logger.info(f"MCP 提示已注册: {name}")

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """处理 MCP 请求"""
        try:
            method = request.method
            params = request.params

            logger.info(f"MCP 请求: {method}")

            # 处理不同方法
            if method == MCPMethod.INITIALIZE:
                result = await self._handle_initialize(params)
            elif method == MCPMethod.TOOLS_LIST:
                result = await self._handle_tools_list(params)
            elif method == MCPMethod.TOOLS_CALL:
                result = await self._handle_tools_call(params)
            elif method == MCPMethod.RESOURCES_LIST:
                result = await self._handle_resources_list(params)
            elif method == MCPMethod.RESOURCES_READ:
                result = await self._handle_resources_read(params)
            elif method == MCPMethod.PROMPTS_LIST:
                result = await self._handle_prompts_list(params)
            elif method == MCPMethod.PROMPTS_RENDER:
                result = await self._handle_prompts_render(params)
            else:
                return self._error_response(
                    request.id,
                    -32601,
                    f"Method not found: {method}"
                )

            return MCPResponse(
                jsonrpc="2.0",
                id=request.id,
                result=result,
            )

        except Exception as e:
            logger.error(f"MCP 请求处理错误: {e}")
            return self._error_response(
                request.id,
                -32603,
                f"Internal error: {e!s}"
            )

    def _error_response(
        self,
        request_id: Any,
        code: int,
        message: str,
    ) -> MCPResponse:
        """创建错误响应"""
        return MCPResponse(
            jsonrpc="2.0",
            id=request_id,
            error={
                "code": code,
                "message": message,
            },
        )

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理初始化"""
        self._initialized = True
        self._capabilities = {
            "tools": {"listChanged": True},
            "resources": {"listChanged": True, "subscribe": True},
            "prompts": {"listChanged": True},
        }

        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": self.server_name,
                "version": self.server_version,
            },
            "capabilities": self._capabilities,
        }

    async def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理工具列表"""
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]
        return {"tools": tools}

    async def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理工具调用"""
        name = params.get("name")
        arguments = params.get("arguments", {})

        tool = self._tools.get(name)
        if not tool:
            return self._error_response(None, -32602, f"Tool not found: {name}")

        # 调用处理函数
        if tool.handler:
            try:
                if asyncio.iscoroutinefunction(tool.handler):
                    result = await tool.handler(**arguments)
                else:
                    result = tool.handler(**arguments)
            except Exception as e:
                return self._error_response(None, -32603, str(e))
        else:
            result = {"status": "ok"}

        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    async def _handle_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理资源列表"""
        resources = [
            {
                "uri": res.uri,
                "name": res.name,
                "description": res.description,
                "mimeType": res.mime_type,
            }
            for res in self._resources.values()
        ]
        return {"resources": resources}

    async def _handle_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理资源读取"""
        uri = params.get("uri")

        resource = self._resources.get(uri)
        if not resource:
            return self._error_response(None, -32602, f"Resource not found: {uri}")

        # TODO: 实现实际资源读取
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": resource.mime_type,
                    "text": "Resource content placeholder",
                }
            ]
        }

    async def _handle_prompts_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理提示列表"""
        prompts = [
            {
                "name": prompt.name,
                "description": prompt.description,
                "arguments": prompt.arguments,
            }
            for prompt in self._prompts.values()
        ]
        return {"prompts": prompts}

    async def _handle_prompts_render(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理提示渲染"""
        name = params.get("name")
        arguments = params.get("arguments", {})

        prompt = self._prompts.get(name)
        if not prompt:
            return self._error_response(None, -32602, f"Prompt not found: {name}")

        # 渲染模板
        template = prompt.template
        for key, value in arguments.items():
            template = template.replace(f"{{{key}}}", str(value))

        return {
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": template},
                }
            ]
        }

    async def process_message(self, message: str) -> str:
        """处理 JSON-RPC 消息"""
        try:
            data = json.loads(message)
            request = MCPRequest(
                jsonrpc=data.get("jsonrpc", "2.0"),
                id=data.get("id"),
                method=data.get("method", ""),
                params=data.get("params", {}),
            )

            response = await self.handle_request(request)

            return json.dumps(
                {
                    "jsonrpc": response.jsonrpc,
                    "id": response.id,
                    "result": response.result,
                    "error": response.error,
                }
            )

        except json.JSONDecodeError as e:
            return json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {e!s}",
                    },
                }
            )


# ==================== 便捷函数 ====================

def create_mcp_server(
    server_name: str = "clawed-code",
    server_version: str = "1.0.0",
) -> MCPServer:
    """创建 MCP 服务器"""
    return MCPServer(server_name, server_version)

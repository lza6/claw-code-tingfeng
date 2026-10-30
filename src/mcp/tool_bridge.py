"""MCP Tool Bridge — 把外部 MCP 工具适配为 clawd 原生 BaseTool

外部 MCP 工具 → MCPExternalTool(BaseTool) → ToolRegistry 注册
Agent 通过 execute_tool("mcp__server__tool") 直接调用，与自研工具无差别。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..tools_runtime.tool_interface import BaseTool, ToolCallStatus, ToolResult
from .client import MCPClientError, MCPServerManager, MCPToolInfo

logger = logging.getLogger(__name__)


class MCPExternalTool(BaseTool):
    """外部 MCP 工具的 clawd 适配器"""

    def __init__(self, info: MCPToolInfo, manager: MCPServerManager):
        self.info = info
        self._manager = manager
        super().__init__(name=info.qualified_name, description=info.description)
        self._definition.parameters = info.input_schema
        self._definition.category = "mcp_external"
        self._definition.tags = ["mcp", f"server:{info.server}"]
        self._definition.timeout = 60
        self._definition.is_local = False

    def execute(self, **kwargs) -> ToolResult:
        import time

        start = time.time()
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                # 已在事件循环内：等待结果（桥接工具通常在子代理中执行）
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(
                        asyncio.run,
                        self._manager.call(
                            self.info.server, self.info.name, kwargs
                        ),
                    )
                    output = fut.result(timeout=120)
            else:
                output = asyncio.run(
                    self._manager.call(self.info.server, self.info.name, kwargs)
                )
            return ToolResult(
                tool_name=self.name,
                status=ToolCallStatus.SUCCESS,
                output=output,
                duration_ms=(time.time() - start) * 1000,
                metadata={"server": self.info.server, "origin": "mcp"},
            )
        except MCPClientError as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolCallStatus.ERROR,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolCallStatus.ERROR,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
            )


async def bridge_server_tools(
    manager: MCPServerManager, server: str, registry: Any = None
) -> list[MCPExternalTool]:
    """连接一个 server，把它的全部工具注册进 clawd ToolRegistry

    失败的 server 返回空列表并告警（不阻断其他 server）。
    """
    from ..tools_runtime.tool_interface import get_tool_registry

    reg = registry or get_tool_registry()
    bridged: list[MCPExternalTool] = []
    try:
        tools = await manager.discover_tools(server)
    except Exception as e:
        logger.warning(f"桥接 {server} 失败（跳过）: {e}")
        return bridged
    for info in tools:
        tool = MCPExternalTool(info, manager)
        reg.register(tool, category="mcp_external")
        bridged.append(tool)
    logger.info(f"已桥接 {server}: {len(bridged)} 个工具")
    return bridged


async def bridge_all(manager: MCPServerManager, registry: Any = None) -> int:
    """桥接所有已注册 server 的工具，返回成功桥接的工具总数"""
    total = 0
    for server in manager.server_names:
        total += len(await bridge_server_tools(manager, server, registry))
    return total

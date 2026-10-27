"""
GhidraTool - 通过 HTTP 调用 GhidraMCP 插件的 REST 端点

参考: D:/参考项目/LaurieWired__GhidraMCP/src/ghidra_mcp/backend.py
端点前缀映射 (GhidraMCP server.py -> 本工具 action):
- decompile            -> /decompile?name=
- list_functions       -> /functions
- list_imports         -> /imports
- list_exports         -> /exports
- rename_symbol        -> /rename_function 或 /rename_data
- get_xrefs            -> /xrefs_to 或 /xrefs_from
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from src.tools_runtime.tool_interface import BaseTool, ToolCallStatus, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_TIMEOUT = 60.0


class GhidraTool(BaseTool):
    """Ghidra 逆向分析工具（GhidraMCP 插件 HTTP 桥接）"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT):
        super().__init__(
            name="ghidra",
            description="通过 GhidraMCP 插件对 Ghidra 中打开的程序进行反编译、"
            "符号/导入/导出枚举、交叉引用查询与重命名",
        )
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.timeout = timeout
        self._definition.category = "reverse"
        self._definition.tags = ["reverse", "ghidra", "decompile", "xref"]
        self._definition.timeout = int(timeout)

    # ------------------------------------------------------------------
    def _request(self, method: str, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        """发送 HTTP 请求（连接失败转 ToolResult 错误，不抛异常）"""
        url = self.base_url + endpoint.lstrip("/")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                if method == "GET":
                    return client.get(url, params=params)
                return client.post(url, data=params)
        except httpx.HTTPError as e:
            logger.error(f"GhidraTool 请求失败: {url}, error: {e}")
            raise ConnectionError(
                f"无法连接 GhidraMCP 后端 {self.base_url}，请确认 Ghidra 已启动并加载插件: {e}"
            ) from e

    def _get(self, endpoint: str, **params: Any) -> ToolResult:
        try:
            resp = self._request("GET", endpoint, params)
            resp.raise_for_status()
            return ToolResult(
                tool_name=self.name,
                status=ToolCallStatus.SUCCESS,
                output=resp.text,
                metadata={"endpoint": endpoint, "url": str(resp.request.url)},
            )
        except (ConnectionError, httpx.HTTPError) as e:
            return self._error_result(endpoint, e)
        except Exception as e:
            return self._error_result(endpoint, e)

    def _post(self, endpoint: str, **params: Any) -> ToolResult:
        try:
            resp = self._request("POST", endpoint, params)
            resp.raise_for_status()
            return ToolResult(
                tool_name=self.name,
                status=ToolCallStatus.SUCCESS,
                output=resp.text,
                metadata={"endpoint": endpoint, "url": str(resp.request.url)},
            )
        except (ConnectionError, httpx.HTTPError) as e:
            return self._error_result(endpoint, e)
        except Exception as e:
            return self._error_result(endpoint, e)

    def _error_result(self, endpoint: str, e: Exception) -> ToolResult:
        logger.error(f"GhidraTool action 失败: endpoint={endpoint}, error: {e}")
        return ToolResult(
            tool_name=self.name,
            status=ToolCallStatus.ERROR,
            error=str(e),
            metadata={"endpoint": endpoint},
        )

    # ------------------------------------------------------------------
    def execute(self, action: str, **params: Any) -> ToolResult:
        """按 action 分发到对应 GhidraMCP 端点"""
        dispatch = {
            "decompile": self._action_decompile,
            "list_functions": self._action_list_functions,
            "list_imports": self._action_list_imports,
            "list_exports": self._action_list_exports,
            "rename_symbol": self._action_rename_symbol,
            "get_xrefs": self._action_get_xrefs,
        }
        handler = dispatch.get(action)
        if handler is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolCallStatus.ERROR,
                error=f"未知 action: {action}，支持: {', '.join(sorted(dispatch))}",
            )
        return handler(**params)

    def _action_decompile(self, name: str | None = None, address: str | None = None, **_: Any) -> ToolResult:
        """反编译函数（按名称或地址）"""
        if not name and not address:
            return self._error_result("decompile", ValueError("需要提供 name 或 address 参数"))
        if name:
            return self._get("decompile", name=name)
        return self._get("decompile_function", address=address)

    def _action_list_functions(self, offset: int = 0, limit: int = 100, filter: str | None = None, **_: Any) -> ToolResult:
        """列出程序中的函数"""
        p: dict[str, Any] = {"offset": offset, "limit": limit}
        if filter:
            p["filter"] = filter
        return self._get("functions", **p)

    def _action_list_imports(self, offset: int = 0, limit: int = 100, **_: Any) -> ToolResult:
        """列出导入符号"""
        return self._get("imports", offset=offset, limit=limit)

    def _action_list_exports(self, offset: int = 0, limit: int = 100, **_: Any) -> ToolResult:
        """列出导出符号"""
        return self._get("exports", offset=offset, limit=limit)

    def _action_rename_symbol(self, old_name: str | None = None, address: str | None = None,
                              new_name: str = "", **_: Any) -> ToolResult:
        """重命名符号（函数按旧名，数据按地址）"""
        if not new_name:
            return self._error_result("rename_symbol", ValueError("需要提供 new_name 参数"))
        if old_name:
            return self._post("rename_function", old_name=old_name, new_name=new_name)
        if address:
            return self._post("rename_data", address=address, new_name=new_name)
        return self._error_result("rename_symbol", ValueError("需要提供 old_name 或 address 参数"))

    def _action_get_xrefs(self, address: str | None = None, direction: str = "to",
                          offset: int = 0, limit: int = 100, **_: Any) -> ToolResult:
        """查询交叉引用（direction: to/from）"""
        if not address:
            return self._error_result("get_xrefs", ValueError("需要提供 address 参数"))
        if direction == "from":
            return self._get("xrefs_from", address=address, offset=offset, limit=limit)
        return self._get("xrefs_to", address=address, offset=offset, limit=limit)

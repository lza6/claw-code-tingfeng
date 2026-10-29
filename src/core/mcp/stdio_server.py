"""通用 stdio JSON-RPC MCP 服务器骨架（供 `src/core/mcp/*_server.py` 使用）

为什么需要：`DEFAULT_MCP_SERVERS` 生成的四条配置指向
`src.core.mcp.{state,memory,trace,team}_server`，但这些模块**没有 `__main__` 入口**
——`python -m src.core.mcp.state_server` 会静默 exit 0 且零输出，MCP 客户端只看到 EOF。
生成一条必然启动失败的配置，等于给用户一个假承诺。

这里只做协议层：initialize / tools/list / tools/call / ping，其余交给各模块已有的
Server 类方法（工具名 → 方法名，必要时用 alias 覆盖）。
Windows 上必须用 UTF-8 二进制流并逐行 flush，否则中文/emoji 会被 GBK 编坏。
"""
from __future__ import annotations

import dataclasses
import inspect
import io
import json
import logging
import sys

from typing import Any, get_type_hints

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "clawd-mcp", "version": "1.0.0"}


def _jsonable(value: Any) -> Any:
    """把 Server 类返回值转成可 JSON 序列化的结构"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def _call_tool(server_obj: Any, method_name: str, arguments: dict[str, Any]) -> Any:
    """调用 Server 方法（兼容"单 dataclass 参数"的工具）"""
    fn = getattr(server_obj, method_name, None)
    if fn is None or not callable(fn):
        raise AttributeError(f"工具方法不存在: {method_name}")

    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        params = []

    if len(params) == 1:
        # 模块普遍用了 `from __future__ import annotations`，注解是字符串，
        # 必须用 get_type_hints 解析，否则 dataclass 判定永远为假
        annotation = params[0].annotation
        if isinstance(annotation, str):
            try:
                annotation = get_type_hints(fn).get(params[0].name, annotation)
            except Exception:  # noqa: BLE001 — 解析失败就退回普通 kwargs 调用
                annotation = params[0].annotation
        if dataclasses.is_dataclass(annotation) and not isinstance(annotation, type):
            annotation = type(annotation)
        if dataclasses.is_dataclass(annotation) and isinstance(annotation, type):
            payload = arguments.get(params[0].name, arguments)
            if isinstance(payload, dict):
                allowed = {f.name for f in dataclasses.fields(annotation)}
                return fn(annotation(**{k: v for k, v in payload.items() if k in allowed}))
    return fn(**arguments)


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(request_id: Any, value: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(_jsonable(value), ensure_ascii=False)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
    }


def handle_request(
    server_obj: Any,
    tools: dict[str, dict[str, Any]],
    request: dict[str, Any],
    *,
    alias: dict[str, str] | None = None,
    name: str = "clawd-mcp",
) -> dict[str, Any] | None:
    """处理单条 JSON-RPC 请求；通知（无 id）返回 None"""
    method = request.get("method")
    request_id = request.get("id")
    if request_id is None:
        return None  # 通知不回复（回复会破坏 MCP 客户端的请求配对）

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {**SERVER_INFO, "name": name},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": list(tools.values())}}
    if method == "tools/call":
        params = request.get("params") or {}
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if tool_name not in tools:
            return _error(request_id, -32602, f"未知工具: {tool_name}")
        method_name = (alias or {}).get(tool_name, tool_name)
        try:
            value = _call_tool(server_obj, method_name, dict(arguments))
        except Exception as e:  # noqa: BLE001 — 工具失败要作为 isError 结果回给客户端
            logger.debug("工具 %s 调用失败: %s", tool_name, e)
            return _tool_result(request_id, f"{type(e).__name__}: {e}", is_error=True)
        return _tool_result(request_id, value)

    return _error(request_id, -32601, f"不支持的方法: {method}")


def serve(
    server_obj: Any,
    tools: dict[str, dict[str, Any]],
    *,
    alias: dict[str, str] | None = None,
    name: str = "clawd-mcp",
    stdin: io.TextIOBase | None = None,
    stdout: io.TextIOBase | None = None,
) -> int:
    """stdio 主循环（逐行读，逐行 flush）"""
    instream = stdin or io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    outstream = stdout or io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", newline=chr(10), write_through=True
    )

    while True:
        line = instream.readline()
        if not line:
            return 0
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            outstream.write(json.dumps(_error(None, -32700, "JSON 解析失败")) + chr(10))
            outstream.flush()
            continue
        if not isinstance(request, dict):
            outstream.write(json.dumps(_error(None, -32600, "请求必须是对象")) + chr(10))
            outstream.flush()
            continue

        response = handle_request(server_obj, tools, request, alias=alias, name=name)
        if response is None:
            continue
        outstream.write(json.dumps(response, ensure_ascii=False) + chr(10))
        outstream.flush()


def main_for(
    server_obj: Any,
    tools: dict[str, dict[str, Any]],
    *,
    alias: dict[str, str] | None = None,
    name: str = "clawd-mcp",
) -> int:
    """各 server 模块 `main()` 的统一实现（解析 --root 等通用参数）"""
    import argparse
    import os

    ap = argparse.ArgumentParser(description=f"{name} MCP Server (stdio)")
    ap.add_argument("--root", default=os.getcwd(), help="项目根目录")
    args, _unknown = ap.parse_known_args()
    del args.root  # 项目根目录由调用方在构造 server_obj 时决定
    return serve(server_obj, tools, alias=alias, name=name)


__all__ = ["handle_request", "main_for", "serve", "PROTOCOL_VERSION"]

"""LSP 代码智能工具（内置原生，不用 MCP）

提供 agent 真正需要的三件事：
- 诊断：真实类型/未定义名等错误（比 AST 猜测准）
- 跳转定义：拿到跨文件的真实定义位置
- 悬停类型：拿到签名/类型信息

行号约定：**对外用 1-based（人类与模型习惯），内部转 0-based（LSP 约定）**。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import json
import threading
from pathlib import Path
from typing import Any

from ..lsp import LSPClient, LSPError, LSPUnavailable, language_for, server_command_for
from .base import BaseTool, ParameterSchema, ToolCategory, ToolResult

#: 每个 (根目录, 语言) 复用一个客户端：LSP 启动要几秒，反复起会拖死体验
_CLIENTS: dict[tuple[str, str], LSPClient] = {}
_CLIENTS_LOCK = threading.Lock()


def _client_for(root: Path, language: str) -> LSPClient:
    key = (str(root), language)
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client is not None and client.proc is not None:
            return client
        cmd_args = server_command_for(language)
        if cmd_args is None:
            raise LSPUnavailable(f"未配置该语言的 LSP 服务器: {language}")
        command, args = cmd_args
        client = LSPClient(command, list(args), root=root, request_timeout=45)
        client.start()
        _CLIENTS[key] = client
        return client


def shutdown_clients() -> None:
    """关闭所有缓存的 LSP 客户端（测试/退出时调用）"""
    with _CLIENTS_LOCK:
        for client in _CLIENTS.values():
            try:
                client.stop()
            except Exception:
                pass
        _CLIENTS.clear()


class LSPTool(BaseTool):
    """语言服务器代码智能：诊断 / 跳转定义 / 悬停类型"""

    name = 'LSPTool'
    description = (
        '用真实语言服务器做代码理解：diagnostics 查错误、definition 跳转定义、'
        'hover 看类型签名。比纯 AST 解析准确（需要本机装有对应语言服务器）'
    )
    category = ToolCategory.SEARCH
    risk_kind = 'read'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='action',
            param_type='str',
            required=True,
            description='操作: diagnostics(诊断) | definition(跳转定义) | hover(悬停类型)',
            allowed_values=('diagnostics', 'definition', 'hover'),
        ),
        ParameterSchema(
            name='file_path',
            param_type='str',
            required=True,
            description='目标文件（相对工作目录）',
            max_length=500,
        ),
        ParameterSchema(
            name='line',
            param_type='int',
            required=False,
            description='行号（1-based；definition/hover 必填）',
            min_value=1,
            max_value=100000,
        ),
        ParameterSchema(
            name='column',
            param_type='int',
            required=False,
            description='列号（1-based；默认 1）',
            min_value=1,
            max_value=10000,
            default=1,
        ),
    )

    def __init__(self, workdir: Path | str | None = None):
        super().__init__()
        self.workdir = Path(workdir or Path.cwd()).resolve()

    def _resolve_target(self, rel: str) -> Path:
        target = (self.workdir / rel).resolve()
        if not target.is_relative_to(self.workdir):
            raise ValueError(f"路径越界: {rel}")
        if not target.is_file():
            raise FileNotFoundError(f"文件不存在: {rel}")
        return target

    def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get('action') or '').strip()
        rel = str(kwargs.get('file_path') or '').strip()
        self._increment_usage()

        # 先校验 action：否则非法 action 会先撞上"需要 line"的检查，报出误导性错误
        if action not in ('diagnostics', 'definition', 'hover'):
            return ToolResult(
                success=False, output="",
                error=f"未知 action: {action or '(空)'}（支持 diagnostics/definition/hover）",
                exit_code=1,
            )

        if not rel:
            return ToolResult(success=False, output="", error="file_path 必填", exit_code=1)
        try:
            target = self._resolve_target(rel)
        except (ValueError, FileNotFoundError) as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1)

        language = language_for(target)
        if language is None:
            return ToolResult(
                success=False, output="",
                error=f"该文件类型未配置 LSP（支持: .py/.go/.ts/.tsx/.js/.jsx/.rs）",
                exit_code=1,
            )

        try:
            client = _client_for(self.workdir, language)
        except LSPUnavailable as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=2)
        except LSPError as e:
            return ToolResult(success=False, output="", error=f"LSP 启动失败: {e}", exit_code=2)

        try:
            if action == 'diagnostics':
                diags = client.diagnostics(rel, wait=20.0)
                payload = {
                    "file": rel,
                    "language": language,
                    "count": len(diags),
                    "diagnostics": [
                        {"line": d.line + 1, "column": d.character + 1,
                         "severity": d.severity_name, "message": d.message, "code": d.code}
                        for d in diags
                    ],
                }
                return ToolResult(success=True, output=json.dumps(payload, ensure_ascii=False, indent=2),
                                  metadata={"count": len(diags)})

            line = kwargs.get('line')
            if not line:
                return ToolResult(success=False, output="",
                                  error=f"action={action} 需要 line（1-based）", exit_code=1)
            zero_line = max(0, int(line) - 1)
            zero_col = max(0, int(kwargs.get('column') or 1) - 1)

            if action == 'definition':
                locs = client.definition(rel, zero_line, zero_col)
                items = []
                for loc in locs:
                    uri = str(loc.get("uri") or "")
                    rng = loc.get("range") or {}
                    start = rng.get("start") or {}
                    try:
                        path = Path(uri.replace("file:///", "").replace("%20", " ")).as_posix()
                    except Exception:
                        path = uri
                    items.append({"uri": uri, "path": path,
                                  "line": int(start.get("line", 0)) + 1,
                                  "column": int(start.get("character", 0)) + 1})
                return ToolResult(
                    success=True,
                    output=json.dumps({"file": rel, "line": int(line), "count": len(items),
                                       "definitions": items}, ensure_ascii=False, indent=2),
                    metadata={"count": len(items)},
                )

            if action == 'hover':
                text = client.hover(rel, zero_line, zero_col)
                return ToolResult(
                    success=bool(text),
                    output=json.dumps({"file": rel, "line": int(line), "hover": text},
                                      ensure_ascii=False, indent=2),
                    error="" if text else "该位置无悬停信息（可能不在符号上）",
                    exit_code=0 if text else 1,
                )

            return ToolResult(success=False, output="",
                              error=f"未知 action: {action}（支持 diagnostics/definition/hover）",
                              exit_code=1)
        except LSPError as e:
            return ToolResult(success=False, output="", error=f"LSP 请求失败: {e}", exit_code=2)


def get_lsp_tool(workdir: Path | str | None = None) -> BaseTool:
    return LSPTool(workdir)

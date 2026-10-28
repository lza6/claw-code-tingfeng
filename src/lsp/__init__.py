"""LSP 集成 —— 用真实语言服务器做代码理解（替代纯 AST 猜测）

借鉴 OpenCode 的 `internal/lsp/`（Go, MIT）：stdio + Content-Length 分帧 + 请求 id 分发。
我们只做 agent 真正需要的三件事：诊断 / 跳转定义 / 悬停类型。
"""

from .client import (
    LANGUAGE_SERVERS,
    Diagnostic,
    LSPClient,
    LSPError,
    LSPUnavailable,
    available_servers,
    language_for,
    server_command_for,
    which_server,
)

__all__ = [
    "LANGUAGE_SERVERS",
    "Diagnostic",
    "LSPClient",
    "LSPError",
    "LSPUnavailable",
    "available_servers",
    "language_for",
    "server_command_for",
    "which_server",
]

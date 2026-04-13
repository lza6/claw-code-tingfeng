"""WebSocket 服务器模块

为 Clawd Code 项目提供基于 WebSocket 的远程代理执行接口。

模块结构:
    - websocket_server: 主服务器实现（ClawdWebSocketServer）
    - handlers: JSON-RPC 消息处理器与路由
    - auth: 令牌认证管理
"""
from __future__ import annotations

from .auth import AuthManager
from .handlers import MessageRouter, build_error, build_response
from .websocket_server import ClawdWebSocketServer, create_server

__all__ = [
    'AuthManager',
    'ClawdWebSocketServer',
    'MessageRouter',
    'build_error',
    'build_response',
    'create_server',
]

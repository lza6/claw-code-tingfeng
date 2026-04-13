"""WebSocket 会话管理"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from websockets import ServerProtocol


class ConnectionSession:
    """单个客户端 WebSocket 连接的会话状态。"""

    __slots__ = ('connected_at', 'last_pong', 'message_count', 'ws')

    def __init__(self, ws: ServerProtocol) -> None:
        self.ws = ws
        self.connected_at = time.time()
        self.last_pong = time.time()
        self.message_count = 0

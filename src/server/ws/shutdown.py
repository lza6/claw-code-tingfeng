from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ...core.events import Event, EventType, get_event_bus

if TYPE_CHECKING:
    from ..websocket_server import ClawdWebSocketServer

DEFAULT_SHUTDOWN_TIMEOUT = 5.0

logger = logging.getLogger('server.ws.shutdown')

class ServerShutdown:
    """优雅关闭上下文管理器"""

    def __init__(
        self,
        server: ClawdWebSocketServer,
        timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        self.server = server
        self.timeout = timeout

    async def __aenter__(self) -> ServerShutdown:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        logger.info('开始执行优雅关闭流程...')

        # 设置关闭标志
        self.server._shutting_down = True

        # 1. 获取所有会话副本
        sessions = list(self.server._manager._sessions.values())

        # 2. 通知所有客户端正在关闭并尝试正常关闭
        close_tasks = []
        for session in sessions:
            close_tasks.append(self._safe_close(session.ws))

        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

        # 3. 等待 Websocket 服务端停止接收新请求并关闭
        if self.server._ws_server:
            self.server._ws_server.close()
            try:
                await asyncio.wait_for(self.server._ws_server.wait_closed(), timeout=self.timeout)
            except asyncio.TimeoutError:
                logger.warning("WebSocket 服务端关闭超时")

        # 4. 发布事件
        get_event_bus().publish(Event(
            type=EventType.SERVER_STOPPED,
            data={
                'total_served': len(sessions),
                'reason': str(exc_val) if exc_val else 'normal',
            },
            source='websocket_server',
        ))

        logger.info('服务器已完全关闭')

    async def _safe_close(self, ws: Any) -> None:
        try:
            await ws.close(1001, '服务器正在关闭')
        except Exception:
            pass

import asyncio

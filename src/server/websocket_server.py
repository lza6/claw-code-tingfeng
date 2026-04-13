"""Clawd WebSocket 服务器模块

基于 websockets v15 实现的异步 WebSocket 服务器。
此模块现在主要作为启动入口，核心逻辑已拆分至 ws/ 子模块。
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Any

from ..core.events import Event, EventBus, EventType, get_event_bus
from ..core.settings import AgentSettings, get_settings
from ..llm import LLMConfig
from ..utils.logger import get_logger
from .auth import AuthManager
from .handlers import MessageRouter
from .ws.engine_factory import EngineFactory
from .ws.manager import WSManager
from .ws.shutdown import ServerShutdown

if TYPE_CHECKING:
    from websockets.asyncio.server import Server as WsServer


class ClawdWebSocketServer:
    """Clawd WebSocket 服务器。"""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        token: str | None = None,
        heartbeat_interval: float = 30.0,
        settings: AgentSettings | None = None,
        event_bus: EventBus | None = None,
        llm_config: LLMConfig | None = None,
        max_iterations: int = 10,
        developer_mode: bool = False,
        enable_cost_tracking: bool = True,
    ) -> None:
        self.logger = get_logger('server.websocket')
        self._shutting_down = False
        self._start_time = time.time()

        # 加载配置
        self._settings = settings or get_settings()
        self._event_bus = event_bus or get_event_bus()

        # 主机:端口
        self.host = host or os.environ.get('AGENT_SERVER_HOST') or self._settings.agent_server_host
        self.port = port or int(os.environ.get('AGENT_SERVER_PORT', '0')) or self._settings.agent_server_port

        # 认证、路由、引擎工厂
        self._auth_manager = AuthManager(token=token)
        self._router = MessageRouter(
            auth_manager=self._auth_manager,
            event_bus=self._event_bus,
        )

        self._engine_factory = EngineFactory(
            default_llm_config=llm_config,
            workdir=self._settings.workdir,
            max_iterations=max_iterations,
            developer_mode=developer_mode,
            enable_events=True,
            event_bus=self._event_bus,
            enable_cost_tracking=enable_cost_tracking,
        )

        # 初始化连接管理器
        self._manager = WSManager(
            auth_manager=self._auth_manager,
            router=self._router,
            engine_factory=self._engine_factory,
            heartbeat_interval=heartbeat_interval,
        )

        self._ws_server: WsServer | None = None

    @property
    def is_running(self) -> bool:
        return self._ws_server is not None and not self._shutting_down

    @property
    def uptime(self) -> float:
        return time.time() - self._start_time

    async def start(self) -> tuple[str, int]:
        """启动服务器"""
        from websockets.asyncio.server import serve

        self._start_time = time.time()
        self._shutting_down = False

        self._ws_server = await serve(
            self._manager.handle_connection,
            self.host,
            self.port,
            ping_interval=self._manager.heartbeat_interval if self._manager.heartbeat_interval > 0 else None,
        )

        # 获取实际端口
        sockets = self._ws_server.sockets
        if sockets:
            addr, port = sockets[0].getsockname()[:2]
            self.host, self.port = str(addr), int(port)

        uri = f'ws://{self.host}:{self.port}'
        self.logger.info(f'WebSocket 服务器已启动: {uri}')

        self._event_bus.publish(Event(
            type=EventType.SERVER_STARTED,
            data={'host': self.host, 'port': self.port, 'uri': uri},
            source='websocket_server',
        ))

        return (self.host, self.port)

    async def stop(self) -> None:
        """停止服务器"""
        async with ServerShutdown(self):
            pass

    async def run_forever(self) -> None:
        """运行直到关闭"""
        try:
            if self._ws_server is None:
                await self.start()
            await self._ws_server.wait_closed()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def __aenter__(self) -> ClawdWebSocketServer:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    async def broadcast(self, message: dict[str, Any]) -> int:
        """广播消息"""
        return await self._manager.broadcast(message)


def create_server(
    settings: AgentSettings | None = None,
    llm_config: LLMConfig | None = None,
    **kwargs: Any,
) -> ClawdWebSocketServer:
    """创建服务器便捷函数"""
    return ClawdWebSocketServer(
        settings=settings,
        llm_config=llm_config,
        **kwargs,
    )

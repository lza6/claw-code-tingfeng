from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import websockets.exceptions

from ..auth import AuthManager
from ..handlers import MessageRouter, build_error
from .sessions import ConnectionSession

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerProtocol

    from .engine_factory import EngineFactory

logger = logging.getLogger('server.ws.manager')

class WSManager:
    """WebSocket 连接管理器 - 处理连接生命周期与消息分发"""

    def __init__(
        self,
        auth_manager: AuthManager,
        router: MessageRouter,
        engine_factory: EngineFactory,
        heartbeat_interval: float = 30.0,
        event_bus: Any | None = None,
    ) -> None:
        self.auth_manager = auth_manager
        self.router = router
        self.engine_factory = engine_factory
        self.heartbeat_interval = heartbeat_interval
        self._sessions: dict[str, ConnectionSession] = {}
        # 引擎事件 → WS 广播（工具调用/阶段进度实时推给前端）
        if event_bus is not None:
            self._subscribe_engine_events(event_bus)

    def _subscribe_engine_events(self, event_bus: Any) -> None:
        """订阅引擎事件总线，把关键事件实时广播给已认证客户端"""
        from ...core.events import EventType

        # 需要实时推送的事件类型
        watch = {
            EventType.AGENT_TASK_STARTED,
            EventType.AGENT_TASK_COMPLETED,
            EventType.AGENT_TASK_ERROR,
        }
        # 其余事件类型统一按 step 推送（工具调用/LLM 轮次等）
        try:
            other = {t for t in EventType if t not in watch and t.name.startswith('AGENT')}
        except Exception:
            other = set()

        def _make_handler(ev_type: EventType):
            def _handler(event: Any) -> None:
                # 线程模型: 引擎子线程同步调 publish，本 handler 在引擎线程执行。
                # get_running_loop 可能拿到引擎自己的 loop，其上 create_task 会
                # 从非归属线程并发调 ws.send（协议对象非线程安全，帧交错风险）。
                # 必须显式 threadsafe 调度回 WS 服务 loop。
                loop = getattr(self, "_service_loop", None)
                if loop is None or loop.is_closed():
                    return  # 服务未起/已停：静默丢弃（不阻断引擎）
                payload = {
                    'type': 'event',
                    'event': ev_type.name,
                    'data': event.data if hasattr(event, 'data') else str(event),
                }
                asyncio.run_coroutine_threadsafe(self.broadcast(payload), loop)

            return _handler

        for ev_type in (watch | other):
            try:
                event_bus.subscribe(ev_type, _make_handler(ev_type))
            except Exception as e:
                logger.debug(f"事件订阅失败 {ev_type}: {e}")

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def set_service_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """记录 WS 服务事件循环（事件广播的 threadsafe 目标）"""
        self._service_loop = loop

    async def handle_connection(self, ws: ServerProtocol) -> None:
        """处理新进入的连接"""
        remote = str(ws.remote_address)
        session = ConnectionSession(ws)
        self._sessions[remote] = session

        try:
            await self._authenticate_and_serve(ws, session)
        finally:
            self._sessions.pop(remote, None)
            self.auth_manager.unregister(ws)

    async def _authenticate_and_serve(self, ws: ServerProtocol, session: ConnectionSession) -> None:
        """等待认证并开始服务"""
        while True:
            try:
                # 10秒内必须完成一次尝试
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                message = json.loads(raw)

                if message.get('type') != 'auth':
                    await ws.send(json.dumps(build_error(
                        message.get('id'),
                        'E_AUTH_REQUIRED',
                        '请先发送认证消息'
                    ), ensure_ascii=False))
                    continue

                response = await self.router.dispatch(ws, message, self.engine_factory)
                await ws.send(json.dumps(response, ensure_ascii=False))

                if response.get('type') == 'response' and response.get('data', {}).get('status') == 'authenticated':
                    # 认证成功，进入消息循环
                    await self._message_loop(ws, session)
                    break
            except asyncio.TimeoutError:
                logger.warning(f"认证超时: {ws.remote_address}")
                await ws.close(1008, "认证超时")
                break
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception as e:
                logger.error(f"WS 认证或服务异常: {e}", exc_info=True)
                await ws.close(1011, "内部服务器错误")
                break

    async def _message_loop(self, ws: ServerProtocol, session: ConnectionSession) -> None:
        """主消息循环"""
        async for raw in ws:
            try:
                session.message_count += 1
                message = json.loads(raw)

                # 注入路由器上下文（如运行时间等）
                # 这里可以扩展更多会话相关的上下文
                response = await self.router.dispatch(ws, message, self.engine_factory)
                await ws.send(json.dumps(response, ensure_ascii=False))
            except json.JSONDecodeError:
                await ws.send(json.dumps(build_error(None, 'E_INVALID_JSON', '无效的 JSON 格式')))
            except Exception as e:
                logger.error(f"处理消息时出错: {e}", exc_info=True)
                # 不中断循环，仅返回错误
                await ws.send(json.dumps(build_error(None, 'E_INTERNAL_ERROR', str(e))))

    async def broadcast(self, message: dict[str, Any], authenticated_only: bool = True) -> int:
        """广播消息到所有（已认证的）客户端"""
        payload = json.dumps(message, ensure_ascii=False)
        sent = 0

        for session in list(self._sessions.values()):
            if authenticated_only and not self.auth_manager.is_authenticated(session.ws):
                continue

            try:
                await session.ws.send(payload)
                sent += 1
            except Exception as e:
                logger.warning(f"广播至 {session.ws.remote_address} 失败: {e}")

        return sent

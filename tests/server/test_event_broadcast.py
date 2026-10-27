"""WSManager 事件广播单测（不起真实引擎，直接发 event_bus 事件）"""
import asyncio
import json

import pytest


class TestEventBroadcast:
    def test_event_bus_broadcasts_to_authenticated_ws(self):
        from src.core.events import EventBus, EventType
        from src.server.auth import AuthManager
        from src.server.handlers import MessageRouter
        from src.server.ws.manager import WSManager

        async def scenario():
            bus = EventBus()
            auth = AuthManager(token="t")
            router = MessageRouter(auth_manager=auth)
            mgr = WSManager(
                auth_manager=auth, router=router,
                engine_factory=None, event_bus=bus,
            )

            # fake ws
            class FakeWS:
                remote_address = ("127.0.0.1", 1)
                sent = []

                async def send(self, payload):
                    FakeWS.sent.append(json.loads(payload))

            ws = FakeWS()
            from src.server.ws.sessions import ConnectionSession

            session = ConnectionSession(ws)
            mgr._sessions["127.0.0.1:1"] = session
            auth._authenticated.add(ws)

            # 发布一个事件
            from src.core.events import Event

            bus.publish(Event(
                type=EventType.AGENT_TOOL_EXEC_STARTED,
                data={"tool_name": "FileReadTool", "tool_args": {"file_path": "x"}},
                source="test",
            ))
            await asyncio.sleep(0.3)  # 等 async handler 执行
            return FakeWS.sent

        sent = asyncio.run(scenario())
        assert len(sent) == 1
        assert sent[0]["type"] == "event"
        assert sent[0]["event"] == "AGENT_TOOL_EXEC_STARTED"
        assert sent[0]["data"]["tool_name"] == "FileReadTool"

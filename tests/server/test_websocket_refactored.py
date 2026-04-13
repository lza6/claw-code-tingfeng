import pytest
import asyncio
import json
from src.server.websocket_server import ClawdWebSocketServer
from src.core.events import get_event_bus, EventType

@pytest.mark.asyncio
async def test_websocket_server_lifecycle():
    # 使用随机可用端口
    server = ClawdWebSocketServer(host='127.0.0.1', port=0, token='test-token')

    # 测试启动
    host, port = await server.start()
    assert server.is_running
    assert port > 0

    # 测试停止
    await server.stop()
    assert not server.is_running

@pytest.mark.asyncio
async def test_websocket_auth_flow():
    import websockets
    server = ClawdWebSocketServer(host='127.0.0.1', port=0, token='test-token')
    host, port = await server.start()

    uri = f"ws://{host}:{port}"
    try:
        async with websockets.connect(uri) as ws:
            # 1. 发送错误令牌
            await ws.send(json.dumps({"type": "auth", "token": "wrong"}))
            raw = await ws.recv()
            resp = json.loads(raw)
            assert resp['type'] == 'error'
            assert resp['code'] == 'E_AUTH_FAILED'

            # 2. 发送正确令牌
            await ws.send(json.dumps({"type": "auth", "token": "test-token"}))
            raw = await ws.recv()
            resp = json.loads(raw)
            assert resp['type'] == 'response'
            assert resp['data']['status'] == 'authenticated'

            # 3. 测试 ping
            await ws.send(json.dumps({"type": "ping", "id": "msg1"}))
            raw = await ws.recv()
            resp = json.loads(raw)
            assert resp['id'] == 'msg1'
            assert resp['data']['pong'] is True
    finally:
        await server.stop()

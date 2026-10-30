"""「停止生成」契约：run 不能阻塞消息循环，cancel 必须能真打断

真实缺陷：`_message_loop` 以前是 `await dispatch(...)` 串行执行 —— 模型端点一旦挂住，
连接就再也收不到任何消息（包括"停止"），前端按钮永久禁用，用户只能重启应用。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from src.server.auth import AuthManager
from src.server.handlers import MessageRouter
from src.server.ws.manager import WSManager


class _FakeWS:
    remote_address = ("127.0.0.1", 4242)

    def __init__(self, incoming: list[str]) -> None:
        self._incoming = list(incoming)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def __aiter__(self):
        async def gen():
            for item in self._incoming:
                yield item
                await asyncio.sleep(0)   # 让 run task 有机会启动
        return gen()

    async def send(self, payload: str) -> None:
        try:
            self.sent.append(json.loads(payload))
        except json.JSONDecodeError:
            self.sent.append({"raw": payload})

    async def close(self, *args, **kwargs) -> None:
        self.closed = True


class _Session:
    message_count = 0
    run_task = None


class _Factory:
    """engine_factory：create() 返回一个"卡住"的引擎（模拟端点无响应）"""

    def __init__(self) -> None:
        self.started = False
        self.cancelled = False

    def create(self, llm_config=None, workdir=None):
        factory = self

        class _SlowEngine:
            llm_provider = None

            async def run_stream(self, goal, on_chunk=None, prior_messages=None, images=None):
                factory.started = True
                try:
                    await asyncio.sleep(30)      # 假装模型 30 秒不回
                except asyncio.CancelledError:
                    factory.cancelled = True
                    raise
                return _Done()

            async def run(self, goal, prior_messages=None, images=None):
                return await self.run_stream(goal)

        return _SlowEngine()


class _Done:
    final_result = "ok"
    steps: list = []


@pytest.fixture
def manager(monkeypatch):
    auth = AuthManager(token="t")
    # 这些用例只关心 run/cancel 的并发语义，直接视为已认证（认证另有测试覆盖）
    monkeypatch.setattr(auth, "is_authenticated", lambda _ws: True)
    return WSManager(
        auth_manager=auth,
        router=MessageRouter(auth_manager=auth),
        engine_factory=_Factory(),
    )


def test_run_does_not_block_message_loop_and_cancel_stops_it(manager):
    factory = manager.engine_factory
    ws = _FakeWS([
        json.dumps({"type": "run", "id": "r1", "goal": "跑一个会挂住的任务", "stream": True}),
        json.dumps({"type": "cancel", "id": "c1"}),
    ])
    session = _Session()

    async def scenario():
        task = asyncio.create_task(manager._message_loop(ws, session))
        try:
            await asyncio.wait_for(task, timeout=10)
        except asyncio.TimeoutError:  # pragma: no cover - 说明循环被 run 卡住了
            task.cancel()
            raise AssertionError("消息循环被 run 阻塞了（cancel 收不到）")

    asyncio.run(scenario())

    assert factory.started, "run 没有被执行"
    assert factory.cancelled, "cancel 没有真正打断 run（引擎侧没收到 CancelledError）"
    statuses = [m.get("data", {}).get("status") for m in ws.sent if m.get("type") == "response"]
    assert "cancelled" in statuses, f"没有回 cancelled 响应: {ws.sent}"


def test_busy_when_second_run_arrives(manager):
    """上一轮还在跑时再发 run → E_BUSY，不能并发跑两轮"""
    ws = _FakeWS([
        json.dumps({"type": "run", "id": "r1", "goal": "第一个"}),
        json.dumps({"type": "run", "id": "r2", "goal": "第二个"}),
        json.dumps({"type": "cancel", "id": "c1"}),
    ])
    session = _Session()

    asyncio.run(asyncio.wait_for(manager._message_loop(ws, session), timeout=10))

    codes = [m.get("code") for m in ws.sent]
    assert "E_BUSY" in codes, f"第二个 run 没有被拒绝: {ws.sent}"


def test_cancel_without_running_task_is_harmless(manager):
    ws = _FakeWS([json.dumps({"type": "cancel", "id": "c1"})])
    asyncio.run(asyncio.wait_for(manager._message_loop(ws, _Session()), timeout=5))
    assert ws.sent and ws.sent[0]["data"]["stopped"] is False

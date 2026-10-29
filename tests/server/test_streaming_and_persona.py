"""WS 处理器：真流式增量 + 角色选择

真实现象（用户反馈）：桌面端发消息后"只汇报工具调用，没有正常回复"。
根因之一在 `_handle_run`：stream 分支把 chunk 收进本地 list 就扔了，
客户端全程只看到工具事件，模型说的话要等整段跑完才出现。

这里用假 engine 直接驱动 handler，断言：
- 增量文本以 `AGENT_STREAM_DELTA` 事件发出（且做了合并，不是 token 级洪水）
- STARTED / COMPLETED 成对出现
- persona 字段会真正装到 engine；未知角色返回 E_PERSONA_UNKNOWN
- `personas` 请求能列出角色库
"""

from __future__ import annotations

import asyncio

from typing import Any

import pytest

from src.core.events import EventBus
from src.server.auth import AuthManager
from src.server.handlers import MessageRouter


class _FakeSession:
    final_result = "最终答案"
    steps: list = []


class _FakeEngine:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self.persona = None
        self.streamed = False
        self.llm_provider = None  # handlers 会判断它是否为空来决定是否手动建 provider

    def apply_persona(self, persona: Any) -> None:
        self.persona = persona

    async def run_stream(self, goal: str, on_chunk=None):
        self.streamed = True
        for chunk in self._chunks:
            if on_chunk:
                on_chunk(chunk)
        return _FakeSession()

    async def run(self, goal: str):
        return _FakeSession()

    def get_perf_summary(self) -> str:
        return ""


class _FakeFactory:
    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def create(self, llm_config=None):
        return self._engine


class _FakeWS:
    remote_address = ("127.0.0.1", 12345)


@pytest.fixture
def bus() -> tuple[EventBus, list]:
    bus = EventBus()
    events: list = []
    from src.core.events import EventType

    for et in (
        EventType.AGENT_STREAM_STARTED,
        EventType.AGENT_STREAM_DELTA,
        EventType.AGENT_STREAM_COMPLETED,
        EventType.AGENT_TASK_STARTED,
        EventType.AGENT_TASK_COMPLETED,
    ):
        bus.subscribe(et, lambda e, _et=et: events.append((_et.name, e.data)))
    return bus, events


class TestStreamingDeltas:
    def test_chunks_are_emitted_as_delta_events(self, bus):
        event_bus, events = bus
        handler = MessageRouter(auth_manager=AuthManager(token='test-token'), event_bus=event_bus)
        engine = _FakeEngine(["你好", "，这是", "流式回复"])

        resp = asyncio.run(
            handler._handle_run(
                _FakeWS(),
                {"id": "r1", "type": "run", "goal": "hi", "stream": True},
                engine_factory=_FakeFactory(engine),
            )
        )

        assert resp["data"]["status"] == "completed"
        assert engine.streamed is True

        names = [n for n, _ in events]
        assert "AGENT_STREAM_STARTED" in names
        assert "AGENT_STREAM_COMPLETED" in names

        joined = "".join(d.get("text", "") for n, d in events if n == "AGENT_STREAM_DELTA")
        assert joined == "你好，这是流式回复", f"增量文本丢了: {joined!r}"

    def test_deltas_are_coalesced_not_per_token(self, bus):
        """逐字符 200 次 → 不应产生 200 个事件（会打爆 WS）"""
        event_bus, events = bus
        handler = MessageRouter(auth_manager=AuthManager(token='test-token'), event_bus=event_bus)
        engine = _FakeEngine(["字"] * 200)

        asyncio.run(
            handler._handle_run(
                _FakeWS(),
                {"id": "r2", "type": "run", "goal": "hi", "stream": True},
                engine_factory=_FakeFactory(engine),
            )
        )
        delta_events = [d for n, d in events if n == "AGENT_STREAM_DELTA"]
        assert 1 <= len(delta_events) < 50, f"合并失败，产生了 {len(delta_events)} 个事件"
        assert sum(len(d["text"]) for d in delta_events) == 200

    def test_non_stream_path_does_not_emit_deltas(self, bus):
        event_bus, events = bus
        handler = MessageRouter(auth_manager=AuthManager(token='test-token'), event_bus=event_bus)
        engine = _FakeEngine(["不该出现"])

        asyncio.run(
            handler._handle_run(
                _FakeWS(),
                {"id": "r3", "type": "run", "goal": "hi", "stream": False},
                engine_factory=_FakeFactory(engine),
            )
        )
        assert not [d for n, d in events if n == "AGENT_STREAM_DELTA"]


class TestPersonaSelection:
    def test_persona_is_applied_to_engine(self, bus):
        event_bus, _ = bus
        handler = MessageRouter(auth_manager=AuthManager(token='test-token'), event_bus=event_bus)
        engine = _FakeEngine(["ok"])

        asyncio.run(
            handler._handle_run(
                _FakeWS(),
                {"id": "r4", "type": "run", "goal": "hi", "persona": "reviewer"},
                engine_factory=_FakeFactory(engine),
            )
        )
        assert engine.persona is not None
        assert engine.persona.name == "reviewer"

    def test_unknown_persona_returns_error_code(self, bus):
        event_bus, _ = bus
        handler = MessageRouter(auth_manager=AuthManager(token='test-token'), event_bus=event_bus)
        engine = _FakeEngine(["ok"])

        resp = asyncio.run(
            handler._handle_run(
                _FakeWS(),
                {"id": "r5", "type": "run", "goal": "hi", "persona": "not-exist"},
                engine_factory=_FakeFactory(engine),
            )
        )
        assert resp.get("code") == "E_PERSONA_UNKNOWN" or "persona" in str(resp).lower()
        assert engine.persona is None

    def test_personas_message_lists_library(self, bus):
        event_bus, _ = bus
        handler = MessageRouter(auth_manager=AuthManager(token='test-token'), event_bus=event_bus)
        resp = asyncio.run(handler._handle_personas(_FakeWS(), {"id": "p1", "type": "personas"}))
        data = resp.get("data") or {}
        names = {p["name"] for p in data.get("personas", [])}
        assert "reviewer" in names
        assert data.get("count", 0) >= 4


class TestDispatchArity:
    """dispatch 统一用 `handler(ws, message, engine_factory)` 三参调用

    真实踩坑：`_handle_personas(self, ws, message)` 少一个参数 →
    TypeError 被 dispatch 吞成 E_INTERNAL_ERROR，前端角色下拉永远是空的。
    所以这里必须**走 dispatch**，而不是直接调 handler。
    """

    def test_personas_via_dispatch_returns_items(self, bus):
        event_bus, _ = bus
        router = MessageRouter(auth_manager=AuthManager(token="t"), event_bus=event_bus)
        router.auth_manager.is_authenticated = lambda ws: True  # 跳过认证，专测分发

        resp = asyncio.run(router.dispatch(_FakeWS(), {"type": "personas", "id": "p3"}))
        assert resp.get("type") == "response", f"分发失败: {resp}"
        names = {p["name"] for p in (resp.get("data") or {}).get("personas", [])}
        assert "reviewer" in names


class TestDefaultProviderApplied:
    """WS run 未显式传 llm_config 时，必须用设置里选的默认 provider"""

    def test_run_uses_active_provider(self, bus, tmp_path, monkeypatch):
        from src.core import providers_store

        monkeypatch.chdir(tmp_path)
        providers_store.save_provider(
            {"id": "p1", "name": "P1", "kind": "deepseek", "model": "deepseek-chat", "key": "sk-test-123456"},
            tmp_path,
        )

        captured = {}

        class _Factory:
            def create(self, llm_config=None):
                captured["cfg"] = llm_config
                return _FakeEngine(["ok"])

        event_bus, _ = bus
        router = MessageRouter(auth_manager=AuthManager(token="t"), event_bus=event_bus)
        asyncio.run(router._handle_run(_FakeWS(), {"id": "r9", "type": "run", "goal": "hi"}, engine_factory=_Factory()))

        cfg = captured.get("cfg")
        assert cfg is not None, "没把默认 provider 的配置传给引擎"
        assert cfg.model == "deepseek-chat"
        assert cfg.api_key == "sk-test-123456"

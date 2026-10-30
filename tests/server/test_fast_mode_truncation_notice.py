"""快速模式截断必须**告知用户**（P3 项 4 回归）

真实缺陷：`_handle_run` 里 `if fast_mode: overrides['max_tokens'] = min(base, 1024)`
—— 把输出上限硬压到 1024，却一个字都不说。用户看到回答被半路截断，
既不知道为什么，也不知道该怎么关掉（关掉"快速模式"）。

修法：**真的发生截断**（base max_tokens > 1024）时发布一条 `SYSTEM_CONFIG_CHANGED`
告警事件（既有事件体系，不新造）并 `logger.warning`；本来就不超过 1024 的不发，
避免变成噪声。该事件在 `ws/manager` 的广播白名单里，前端 trace 能收到。
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from src.core.events import EventBus, EventType
from src.llm import LLMConfig
from src.server.auth import AuthManager
from src.server.handlers import FAST_MODE_MAX_TOKENS, MessageRouter


class _RecordingBus(EventBus):
    """轻量假总线：只记录 publish 了什么，不真广播"""

    def __init__(self) -> None:
        super().__init__()
        self.published: list[Any] = []

    def publish(self, event: Any) -> None:  # type: ignore[override]
        self.published.append(event)

    def warnings(self) -> list[Any]:
        return [
            e for e in self.published
            if getattr(e, 'type', None) is EventType.SYSTEM_CONFIG_CHANGED
            and (getattr(e, 'data', {}) or {}).get('level') == 'warning'
        ]


class _Session:
    final_result = "ok"
    steps: ClassVar[list] = []


class _Engine:
    def __init__(self) -> None:
        self.llm_provider = None

    def apply_persona(self, persona: Any) -> None:
        pass

    async def run_stream(self, goal: str, on_chunk=None, prior_messages=None, images=None):
        if on_chunk:
            on_chunk("ok")
        return _Session()

    async def run(self, goal: str, prior_messages=None, images=None):
        return _Session()

    def get_perf_summary(self) -> str:
        return ""


class _Factory:
    def create(self, llm_config=None, workdir=None):
        return _Engine()


class _WS:
    remote_address = ("127.0.0.1", 1)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _dispatch(base_max_tokens: int, *, fast_mode: bool) -> _RecordingBus:
    import asyncio

    bus = _RecordingBus()
    router = MessageRouter(auth_manager=AuthManager(token="t"), event_bus=bus)
    base_cfg = LLMConfig(
        provider="openai", model="m-base", api_key="sk-test-000000", max_tokens=base_max_tokens
    )
    msg: dict[str, Any] = {
        "id": "r1",
        "type": "run",
        "goal": "hi",
        "stream": True,
        "model": "m-fast",
        "fast_mode": fast_mode,
        "llm_config": base_cfg,
    }
    asyncio.run(router._handle_run(_WS(), msg, engine_factory=_Factory()))
    return bus


class TestFastModeTruncationNotice:
    def test_truncation_publishes_warning_event_with_1024(self, isolated):
        bus = _dispatch(4096, fast_mode=True)

        warnings = bus.warnings()
        assert warnings, f"截断了却没告知用户（事件: {[e.type for e in bus.published]}）"

        data = warnings[0].data
        assert data["reason"] == "fast_mode_output_truncation", data
        assert "1024" in str(data), data
        assert str(FAST_MODE_MAX_TOKENS) in data["notice"], data["notice"]
        assert "4096" in data["notice"], "告警里要写清被压之前是多少"

    def test_no_notice_when_not_actually_truncated(self, isolated):
        """base 本来就 <= 1024 → 没截断，不许发告警（否则每轮都是噪声）"""
        bus = _dispatch(512, fast_mode=True)

        assert bus.warnings() == [], f"未截断却发了告警: {[e.data for e in bus.warnings()]}"

    def test_no_notice_without_fast_mode(self, isolated):
        bus = _dispatch(4096, fast_mode=False)

        assert bus.warnings() == [], "没开快速模式不该有任何截断告警"


class TestNoticeReachesClient:
    def test_ws_broadcast_includes_config_changed(self):
        """告警只有真的广播出去才算"告知用户"：SYSTEM_CONFIG_CHANGED 必须在转发白名单里"""
        import asyncio
        import json

        from src.core.events import Event
        from src.server.ws.manager import WSManager
        from src.server.ws.sessions import ConnectionSession

        async def scenario():
            bus = EventBus()
            auth = AuthManager(token="t")
            mgr = WSManager(
                auth_manager=auth,
                router=MessageRouter(auth_manager=auth, event_bus=bus),
                engine_factory=None,
                event_bus=bus,
            )
            mgr.set_service_loop(asyncio.get_running_loop())

            class FakeWS:
                remote_address = ("127.0.0.1", 1)
                sent: ClassVar[list] = []

                async def send(self, payload):
                    FakeWS.sent.append(json.loads(payload))

            ws = FakeWS()
            mgr._sessions["127.0.0.1:1"] = ConnectionSession(ws)
            auth._authenticated.add(ws)

            bus.publish(Event(
                type=EventType.SYSTEM_CONFIG_CHANGED,
                data={
                    "level": "warning",
                    "reason": "fast_mode_output_truncation",
                    "notice": f"快速模式已把输出上限从 4096 压到 {FAST_MODE_MAX_TOKENS}",
                },
                source="test",
            ))
            await asyncio.sleep(0.3)
            return FakeWS.sent

        sent = asyncio.run(scenario())

        assert sent, "SYSTEM_CONFIG_CHANGED 没被广播（前端就收不到截断告知）"
        assert sent[0]["event"] == "SYSTEM_CONFIG_CHANGED", sent[0]
        assert str(FAST_MODE_MAX_TOKENS) in json.dumps(sent[0], ensure_ascii=False), sent[0]

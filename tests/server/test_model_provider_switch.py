"""跨 provider 选模型必须连 provider / 密钥 / base_url 一起换（R3 回归）

真实缺陷（Critic 实跑发现，v0.88.9 修复前）：
`/api/models` 返回**所有 provider** 的模型，前端把 `model: selectedModel` 原样发回，
而 `_handle_run` 只 `replace(model=...)` —— 等于**用 A 家密钥发 B 家模型名**，
跨 provider 选型必然失败（默认选第一个时恰好是对的，所以演示看不出来）。

修法：模型 id 用复合键 `provider_id:model`，服务端据此 `build_llm_config(pid)` 取整份配置。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.core.events import EventBus
from src.server.auth import AuthManager
from src.server.handlers import MessageRouter


class _Session:
    final_result = "ok"
    steps: list = []


class _Engine:
    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured
        self.llm_provider = None

    def apply_persona(self, persona: Any) -> None:  # noqa: D401 — 测试桩
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
    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    def create(self, llm_config=None, workdir=None):
        self._captured["cfg"] = llm_config
        return _Engine(self._captured)


class _WS:
    remote_address = ("127.0.0.1", 1)


@pytest.fixture
def two_providers(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    from src.core import providers_store

    providers_store.save_provider({
        "id": "pa", "name": "A 家", "kind": "openai",
        "model": "model-a", "base_url": "https://a.example/v1", "key": "sk-aaa-111111",
    }, tmp_path)
    providers_store.save_provider({
        "id": "pb", "name": "B 家", "kind": "openai",
        "model": "model-b", "base_url": "https://b.example/v1", "key": "sk-bbb-222222",
    }, tmp_path)
    providers_store.set_default("pa", tmp_path)
    return tmp_path


def _dispatch(model: str) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    msg = {"id": "r1", "type": "run", "goal": "hi", "stream": True, "model": model}
    router = MessageRouter(auth_manager=AuthManager(token="t"), event_bus=EventBus())
    asyncio.run(router._handle_run(_WS(), msg, engine_factory=_Factory(captured)))
    return captured.get("cfg")


class TestCompositeModelKey:
    def test_switching_to_other_provider_swaps_key_and_base_url(self, two_providers):
        cfg = _dispatch("pb:model-b")

        assert cfg is not None, "没把配置传给引擎"
        assert cfg.model == "model-b", cfg.model
        assert cfg.api_key == "sk-bbb-222222", "没换上 B 家的密钥（等于用 A 的 key 发 B 的模型）"
        assert cfg.base_url == "https://b.example/v1", f"base_url 没跟着换: {cfg.base_url}"

    def test_plain_model_name_keeps_current_config(self, two_providers):
        """纯模型名（老客户端/CLI）不能被复合键逻辑弄坏"""
        cfg = _dispatch("model-a")

        assert cfg is not None
        assert cfg.model == "model-a"

    def test_unknown_provider_falls_back_without_crash(self, two_providers):
        cfg = _dispatch("ghost:model-x")

        assert cfg is not None, "未知 provider 不该让整轮崩掉"

"""`/run` 带图时的两条路径：真多模态 vs 诚实回退

- 视觉模型（gpt-4o / claude-3 / qwen-vl …）：图片转成图像内容块随消息发出，
  goal 里只留一句"已附图为内容"，**不再**塞一串本机路径；
- 非视觉模型：保持旧行为 —— 路径写进 goal + "看不到就直说，不要猜"。
判定依据 `src/llm/vision.supports_vision`（模型名白名单 / CLAWD_VISION 强制）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.core.events import EventBus
from src.server.auth import AuthManager
from src.server.handlers import MessageRouter

PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/wD/AL0AAAAASUVORK5CYII="
)


class _Session:
    final_result = "看到了"
    steps: list = []


class _Engine:
    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured
        self.llm_provider = None

    def apply_persona(self, persona: Any) -> None:  # noqa: D401 — 测试桩
        self._captured["persona"] = persona

    async def run_stream(self, goal: str, on_chunk=None, prior_messages=None, images=None):
        self._captured["goal"] = goal
        self._captured["images"] = images
        if on_chunk:
            on_chunk("看到了")
        return _Session()

    async def run(self, goal: str, prior_messages=None, images=None):
        self._captured["goal"] = goal
        self._captured["images"] = images
        return _Session()

    def get_perf_summary(self) -> str:
        return ""


class _Factory:
    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    def create(self, llm_config=None, workdir=None):
        self._captured["workdir"] = workdir
        return _Engine(self._captured)


class _WS:
    remote_address = ("127.0.0.1", 1)


def _make_llm_config(model: str):
    from src.llm.config import LLMConfig, LLMProviderType

    return LLMConfig(provider=LLMProviderType.OPENAI, api_key="sk-test", model=model)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("CLAWD_DATA_DIR", str(d))
    monkeypatch.delenv("CLAWD_VISION", raising=False)
    return d


def _dispatch(model: str, *, stream: bool = True) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    msg = {
        "id": "r1",
        "type": "run",
        "goal": "这张图是什么颜色？",
        "stream": stream,
        "llm_config": _make_llm_config(model),
        "images": [{"data_url": f"data:image/png;base64,{PNG_B64}"}],
    }
    router = MessageRouter(auth_manager=AuthManager(token="t"), event_bus=EventBus())
    asyncio.run(router._handle_run(_WS(), msg, engine_factory=_Factory(captured)))
    return captured


class TestVisionModelGetsBlocks:
    def test_vision_model_passes_images_and_skips_paths(self, data_dir: Path):
        captured = _dispatch("gpt-4o")

        assert captured["images"], "视觉模型必须收到 images（否则等于没做多模态）"
        assert len(captured["images"]) == 1
        assert Path(captured["images"][0]).is_file()
        # 真多模态时不要把本机路径塞进 goal
        assert "已保存到本机" not in captured["goal"]
        assert "请直接看图回答" in captured["goal"]

    def test_claude_sonnet_also_vision(self, data_dir: Path):
        captured = _dispatch("claude-sonnet-4-20250514")
        assert captured["images"], "claude-sonnet 属于视觉模型"

    def test_non_stream_path_also_passes_images(self, data_dir: Path):
        captured = _dispatch("gpt-4o", stream=False)
        assert captured["images"], "非流式路径也要带图"


class TestNonVisionModelFallsBack:
    def test_non_vision_model_keeps_path_note(self, data_dir: Path):
        captured = _dispatch("step-5-preview")

        assert captured["images"] is None, "不支持视觉的模型绝不能收到内容块（会 400）"
        goal = captured["goal"]
        assert "已保存到本机" in goal
        assert "不要猜内容" in goal
        assert any(str(data_dir / "uploads") in goal for _ in [0]), "路径要在 goal 里"

    def test_env_forced_vision_switches_path(self, data_dir: Path, monkeypatch):
        monkeypatch.setenv("CLAWD_VISION", "1")
        captured = _dispatch("step-5-preview")
        assert captured["images"], "CLAWD_VISION=1 应强制走多模态"

    def test_env_forced_off_switches_back(self, data_dir: Path, monkeypatch):
        monkeypatch.setenv("CLAWD_VISION", "0")
        captured = _dispatch("gpt-4o")
        assert captured["images"] is None, "CLAWD_VISION=0 应强制回退"
        assert "已保存到本机" in captured["goal"]

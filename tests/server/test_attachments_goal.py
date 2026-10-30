"""图片附件必须真的"告诉"模型（绝对路径写进 goal）

真实发现（2026-10-30 装机验证）：桌面端粘贴图片后，文件确实落到了
`<数据目录>/uploads/img-<hash>.png`，但代码用
`target.relative_to(self._workdir())` 把它转成相对工作目录的路径 ——
上传目录在数据目录（userData/data），根本不在工作目录这棵树里，
`relative_to` 抛 ValueError 被外层 except 吞掉，于是 **goal 里一条附件路径都没有**。
用户看到的现象就是"图传上去了，模型却说没看到图"。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.core.events import EventBus
from src.server.auth import AuthManager
from src.server.handlers import MessageRouter

# 1x1 透明 PNG
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/wD/AL0AAAAASUVORK5CYII="
)


class _Session:
    final_result = "好"
    steps: list = []


class _Engine:
    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured
        self.llm_provider = None

    def apply_persona(self, persona: Any) -> None:  # noqa: D401 — 测试桩
        self._captured["persona"] = persona

    async def run_stream(self, goal: str, on_chunk=None, prior_messages=None):
        self._captured["goal"] = goal
        if on_chunk:
            on_chunk("好")
        return _Session()

    async def run(self, goal: str, prior_messages=None):
        self._captured["goal"] = goal
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


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("CLAWD_DATA_DIR", str(d))
    return d


def _run_message(images: list[dict[str, str]] | None = None, goal: str = "这是什么颜色？") -> dict[str, Any]:
    msg: dict[str, Any] = {"id": "r1", "type": "run", "goal": goal, "stream": True}
    if images:
        msg["images"] = images
    return msg


def _dispatch(msg: dict[str, Any]) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    router = MessageRouter(auth_manager=AuthManager(token="t"), event_bus=EventBus())
    asyncio.run(router._handle_run(_WS(), msg, engine_factory=_Factory(captured)))
    return captured


class TestAttachmentPathInGoal:
    def test_attachment_saved_and_absolute_path_in_goal(self, data_dir: Path):
        captured = _dispatch(_run_message([{"data_url": f"data:image/png;base64,{PNG_B64}"}]))

        files = list((data_dir / "uploads").glob("img-*.png"))
        assert len(files) == 1, "附件没有落盘到数据目录的 uploads/"

        goal = captured["goal"]
        assert str(files[0]) in goal, f"goal 里没有附件绝对路径: {goal}"
        assert "随消息附图 1 张" in goal
        assert "不要猜内容" in goal, "必须明确告诉模型：不支持视觉就直说看不到"

    def test_absolute_path_survives_different_workdir(self, data_dir: Path, tmp_path):
        """工作目录与数据目录不在同一棵树（桌面端就是如此）时也必须带上路径"""
        other = tmp_path / "work" / "proj"
        other.mkdir(parents=True)
        msg = _run_message([{"data_url": f"data:image/png;base64,{PNG_B64}"}])
        msg["workdir"] = str(other)

        captured = _dispatch(msg)

        goal = captured["goal"]
        saved = list((data_dir / "uploads").glob("img-*.png"))
        assert len(saved) == 1
        assert str(saved[0]) in goal

    def test_no_images_leaves_goal_clean(self, data_dir: Path):
        captured = _dispatch(_run_message(None, goal="纯文本问题"))
        assert captured["goal"] == "纯文本问题"
        assert "随消息附图" not in captured["goal"]

    def test_bad_data_url_does_not_block_message(self, data_dir: Path):
        captured = _dispatch(_run_message([{"data_url": "data:image/png;base64,@@@not-base64@@@"}]))
        # 解析失败时不能把整条消息搞崩，goal 仍是用户原文
        assert captured["goal"].startswith("这是什么颜色？")

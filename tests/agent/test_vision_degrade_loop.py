"""loop 级降级验证：provider 首次拒绝 image_url → 第二次自动改发纯文本

真实场景（v0.88.4 实测）：端点看到 `image_url` 内容块会**直接断连**（APIConnectionError），
所以 `_run_agent_loop` 必须在失败后自动剥离图像块重试 —— 否则用户只看到
"LLM 流式调用失败: Connection error."，整轮报废。

已有的 `test_vision_fallback.py` 只测了 helper（`_has_image_blocks` / `_strip_image_blocks`），
这里补的是**真的跑一遍 loop**，证明降级在整条链路上生效。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from src.agent.engine_loop import AgentLoopConfig, _run_agent_loop
from src.llm.config import LLMResponse

PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/wD/AL0AAAAASUVORK5CYII="
)


def _has_image(messages: list[Any]) -> bool:
    for m in messages or []:
        content = getattr(m, "content", None)
        if isinstance(content, (list, tuple)) and any(
            isinstance(b, dict) and b.get("type") == "image_url" for b in content
        ):
            return True
    return False


class _FlakyProvider:
    """第一次调用模拟"端点拒绝 image_url 直接断连"，之后正常返回"""

    def __init__(self) -> None:
        self.seen: list[list[Any]] = []

    async def chat_stream(self, messages=None, **kwargs):
        self.seen.append(list(messages or []))
        if len(self.seen) == 1:
            raise RuntimeError("Connection error")  # 等价于 openai.APIConnectionError
        yield "看到的是一张图片"

    async def chat(self, messages=None, **kwargs):
        self.seen.append(list(messages or []))
        if len(self.seen) == 1:
            raise RuntimeError("Connection error")
        return LLMResponse(content="看到的是一张图片", model="fake", usage={"total_tokens": 10})


@pytest.fixture
def png(tmp_path: Path) -> Path:
    p = tmp_path / "shot.png"
    p.write_bytes(base64.b64decode(PNG_B64))
    return p


def _config(provider: _FlakyProvider, images: list[str], **kw) -> AgentLoopConfig:
    return AgentLoopConfig(
        goal="这张图是什么颜色？",
        llm_provider=provider,
        messages=[],
        max_iterations=kw.pop("max_iterations", 3),
        system_prompt="sys",
        tools={},
        images=images,
        is_stream=kw.pop("is_stream", True),
        _parse_tool_calls=lambda c: [],
        _execute_tool=lambda *a, **k: None,
        **kw,
    )


class TestLoopLevelDegrade:
    def test_second_attempt_has_no_image_blocks(self, png: Path):
        provider = _FlakyProvider()
        config = _config(provider, [str(png)])

        result = _run_with_timeout(config)

        assert len(provider.seen) == 2, f"应当降级重试一次，实际调用 {len(provider.seen)} 次"
        assert _has_image(provider.seen[0]), "第一次应该带图像内容块"
        assert not _has_image(provider.seen[1]), "降级后第二次不能再带图像块"
        assert result is not None

    def test_no_images_means_single_call(self):
        provider = _FlakyProvider()
        config = _config(provider, [])

        _run_with_timeout(config)

        assert len(provider.seen) == 1, "没有图片时不应触发降级重试"

    def test_degrade_does_not_consume_iteration_budget(self, png: Path):
        """降级重试是**轮内**的，不能吃掉迭代额度（R6）

        修前：降级走外层 `continue`，`max_iterations=1` 时循环直接结束，
        用户拿不到任何回答，只看到"达到最大迭代次数"—— 降级等于没生效。
        修后：同一轮内原地重试，仍然能得到第二次（纯文本）调用的回答。
        """
        provider = _FlakyProvider()
        config = _config(provider, [str(png)], max_iterations=1)

        result = _run_with_timeout(config)

        assert len(provider.seen) == 2, "降级重试必须在同一轮内发生"
        session = result["session"]
        assert "看到的是一张图片" in (session.final_result or ""), (
            f"同一轮内降级重试成功后必须拿到回答，实际: {session.final_result!r}"
        )
        # 模型侧只看到一条 assistant 回答：降级重试没有重复追加消息
        assistant = [m for m in result["messages"] if getattr(m, "role", "") == "assistant"]
        assert len(assistant) == 1, f"降级重试后只应有一条 assistant 消息，实际 {len(assistant)} 条"
        assert "看到的是一张图片" in str(assistant[0].content)


def _run_with_timeout(config: AgentLoopConfig):
    import asyncio

    return asyncio.run(asyncio.wait_for(_run_agent_loop(config=config), timeout=30))

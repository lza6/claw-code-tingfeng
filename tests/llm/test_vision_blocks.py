"""真多模态：图片以 `image_url` 内容块进 LLM 消息（而不是只丢个路径给模型）

背景：桌面端粘贴图片后只把"已保存到本机: <路径>"写进 goal，模型没有视觉能力就
只能说看不到。这一组测试钉住"图片真的变成消息内容块"这条链路，以及
"模型不支持视觉时不要硬塞、老实回退成路径说明"的判定。
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from src.llm.vision import MAX_VISION_IMAGE_BYTES, build_image_blocks, supports_vision

# 1x1 透明 PNG
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/wD/AL0AAAAASUVORK5CYII="
)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


class TestSupportsVision:
    def test_known_vision_models(self):
        for model in ("gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "claude-sonnet-4",
                      "gemini-2.0-flash", "qwen2.5-vl-72b", "glm-4v", "step-1v-8k"):
            assert supports_vision(model), model

    def test_non_vision_models(self):
        for model in ("step-5-preview", "deepseek-chat", "qwen3-coder-plus", ""):
            assert not supports_vision(model), model

    def test_env_force_on(self, monkeypatch):
        monkeypatch.setenv("CLAWD_VISION", "1")
        assert supports_vision("step-5-preview"), "CLAWD_VISION=1 应强制走多模态"

    def test_env_force_off(self, monkeypatch):
        monkeypatch.setenv("CLAWD_VISION", "0")
        assert not supports_vision("gpt-4o"), "CLAWD_VISION=0 应强制回退"


class TestBuildImageBlocks:
    def test_png_becomes_image_url_block(self, tmp_path):
        p = _write(tmp_path, "a.png", PNG_BYTES)
        blocks = build_image_blocks([str(p)])
        assert len(blocks) == 1
        block = blocks[0]
        assert block["type"] == "image_url"
        url = block["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        # 解回来必须和原文件一致（不能截断/串码）
        assert base64.b64decode(url.split(",", 1)[1]) == PNG_BYTES

    def test_mime_by_extension(self, tmp_path):
        jpg = _write(tmp_path, "b.jpg", b"\xff\xd8\xff\xe0fakejpeg")
        webp = _write(tmp_path, "c.webp", b"RIFF....WEBPVP8 ")
        blocks = build_image_blocks([str(jpg), str(webp)])
        assert blocks[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert blocks[1]["image_url"]["url"].startswith("data:image/webp;base64,")

    def test_oversized_image_skipped(self, tmp_path, caplog):
        big = _write(tmp_path, "big.png", b"\x89PNG" + b"\x00" * (MAX_VISION_IMAGE_BYTES + 1))
        blocks = build_image_blocks([str(big)])
        assert blocks == [], "超过上限的图片不能塞进上下文（base64 会把 token 撑爆）"

    def test_missing_file_skipped(self, tmp_path):
        blocks = build_image_blocks([str(tmp_path / "nope.png")])
        assert blocks == []

    def test_empty_and_none(self):
        assert build_image_blocks(None) == []
        assert build_image_blocks([]) == []

    def test_mixed_good_and_bad(self, tmp_path):
        good = _write(tmp_path, "good.png", PNG_BYTES)
        blocks = build_image_blocks([str(good), str(tmp_path / "missing.png")])
        assert len(blocks) == 1, "坏的那张跳过，好的那张要留下"


class TestMessageContentBlocks:
    def test_initial_messages_use_blocks_when_images_present(self, tmp_path):
        from src.agent.engine_loop import AgentLoopConfig, build_initial_messages

        p = _write(tmp_path, "shot.png", PNG_BYTES)
        cfg = AgentLoopConfig(
            llm_provider=None, messages=[], max_iterations=1, tools={},
            goal="这是什么颜色？", system_prompt="sys", images=[str(p)],
        )
        messages = build_initial_messages(cfg, "这是什么颜色？")
        user = messages[-1]
        assert user.role == "user"
        assert isinstance(user.content, list), "有图时 content 必须是内容块列表"
        assert user.content[0]["type"] == "text"
        assert any(b.get("type") == "image_url" for b in user.content)

    def test_initial_messages_stay_string_without_images(self):
        from src.agent.engine_loop import AgentLoopConfig, build_initial_messages

        cfg = AgentLoopConfig(
            llm_provider=None, messages=[], max_iterations=1, tools={},
            goal="纯文本", system_prompt="sys",
        )
        messages = build_initial_messages(cfg, "纯文本")
        assert messages[-1].content == "纯文本", "没图时必须是字符串（保持旧行为）"

    def test_unreadable_images_fall_back_to_string(self, tmp_path):
        from src.agent.engine_loop import AgentLoopConfig, build_initial_messages

        cfg = AgentLoopConfig(
            llm_provider=None, messages=[], max_iterations=1, tools={},
            goal="x", system_prompt="s", images=[str(tmp_path / "gone.png")],
        )
        messages = build_initial_messages(cfg, "x")
        assert messages[-1].content == "x", "图都读不到时应退回纯文本而不是空列表"

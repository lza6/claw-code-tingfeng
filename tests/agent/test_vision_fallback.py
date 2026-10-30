"""带图请求失败要**自动降级**成纯文本（而不是让整轮任务报 Connection error）

真实证据（2026-10-30 实测）：当前端点 `step-5-preview` 收到带 `image_url` 的请求体时
**直接断连**（openai SDK 抛 APIConnectionError），纯文本请求则正常返回 PONG。
所以"模型不支持视觉"的表现不是 400，而是连接错误 —— 不降级用户只会看到
"LLM 流式调用失败: Connection error."，整轮报废。
"""

from __future__ import annotations

from src.agent.engine_loop import (
    LLMMessage,
    _has_image_blocks,
    _strip_image_blocks,
)
from src.llm.vision import build_image_blocks


def _image_block() -> dict:
    return {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


class TestDetectImageBlocks:
    def test_detects_image_block(self):
        msgs = [LLMMessage(role="user", content=[{"type": "text", "text": "hi"}, _image_block()])]
        assert _has_image_blocks(msgs) is True

    def test_plain_string_has_no_image(self):
        msgs = [LLMMessage(role="user", content="纯文本")]
        assert _has_image_blocks(msgs) is False

    def test_text_only_blocks_have_no_image(self):
        msgs = [LLMMessage(role="user", content=[{"type": "text", "text": "hi"}])]
        assert _has_image_blocks(msgs) is False


class TestStripImageBlocks:
    def test_image_removed_text_kept_and_note_added(self):
        msgs = [
            LLMMessage(role="system", content="sys"),
            LLMMessage(role="user", content=[
                {"type": "text", "text": "这张图是什么颜色？"},
                _image_block(),
            ]),
        ]

        out = _strip_image_blocks(msgs)

        assert isinstance(out[1].content, str), "降级后必须是纯字符串"
        assert "这张图是什么颜色？" in out[1].content
        assert "无法作为图像输入发送" in out[1].content
        assert "不要猜" in out[1].content, "必须明确要求模型别编内容"
        assert out[0].content == "sys", "非图片消息不能被改动"
        assert _has_image_blocks(out) is False

    def test_keeps_role_and_tool_fields(self):
        msgs = [
            LLMMessage(role="user", content=[_image_block()], name="u1"),
        ]
        out = _strip_image_blocks(msgs)
        assert out[0].role == "user"
        assert out[0].name == "u1"

    def test_no_image_messages_untouched(self):
        msgs = [LLMMessage(role="user", content="纯文本")]
        assert _strip_image_blocks(msgs)[0] is msgs[0]


class TestBuildImageBlocksContract:
    def test_real_blocks_are_detected_by_the_same_predicate(self, tmp_path):
        """vision.build_image_blocks 产出的块必须被 _has_image_blocks 认出来（两处口径一致）"""
        png = tmp_path / "a.png"
        png.write_bytes(bytes.fromhex("89504e470d0a1a0a"))
        blocks = build_image_blocks([str(png)])
        assert blocks, "没构造出图像块"
        msgs = [LLMMessage(role="user", content=[{"type": "text", "text": "x"}, *blocks])]
        assert _has_image_blocks(msgs) is True

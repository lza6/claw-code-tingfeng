"""Token Counter 测试 - 覆盖 src/utils/token_counter.py"""

import pytest
from src.utils.token_counter import (
    count_tokens,
    count_message_tokens,
    estimate_tokens,
    get_model_context_window,
    count_image_tokens,
    count_image_tokens_advanced,
    count_audio_token_input,
    count_audio_token_output,
    count_video_token,
    count_file_token,
    count_message_tokens_advanced,
    get_encoder,
)


class TestTokenCounter:
    """Token 计数器测试"""

    def test_count_tokens_basic(self):
        """测试基本 token 计数"""
        text = "Hello world"
        tokens = count_tokens(text, "gpt-4")
        assert tokens > 0

    def test_count_tokens_chinese(self):
        """测试中文 token 计数"""
        text = "你好世界"
        tokens = count_tokens(text, "gpt-4")
        assert tokens > 0

    def test_count_tokens_empty(self):
        """测试空文本"""
        text = ""
        tokens = count_tokens(text, "gpt-4")
        assert tokens == 0

    def test_estimate_tokens(self):
        """测试 token 估算"""
        text = "Hello world"
        tokens = estimate_tokens(text)
        assert tokens >= 0

    def test_estimate_tokens_chinese(self):
        """测试中文估算"""
        text = "你好世界"
        tokens = estimate_tokens(text)
        assert tokens > 0

    def test_estimate_tokens_empty(self):
        """测试空文本估算"""
        text = ""
        tokens = estimate_tokens(text)
        assert tokens == 0

    def test_get_encoder(self):
        """测试获取编码器"""
        encoder = get_encoder("gpt-4")
        assert encoder is not None

    def test_get_encoder_default(self):
        """测试默认编码器"""
        encoder = get_encoder("unknown-model")
        assert encoder is not None


class TestMessageTokens:
    """消息 Token 测试"""

    def test_count_message_tokens_basic(self):
        """测试基本消息 token 计数"""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        tokens = count_message_tokens(messages, "gpt-4")
        assert tokens > 0

    def test_count_message_tokens_empty(self):
        """测试空消息列表"""
        messages = []
        tokens = count_message_tokens(messages, "gpt-4")
        assert tokens > 0


class TestContextWindow:
    """上下文窗口测试"""

    def test_get_model_context_window_gpt4(self):
        """测试 GPT-4 上下文窗口"""
        window = get_model_context_window("gpt-4")
        assert window == 8192

    def test_get_model_context_window_gpt432k(self):
        """测试 GPT-4-32k 上下文窗口 - 前缀匹配"""
        window = get_model_context_window("gpt-4-32k")
        assert window >= 8192  # gpt-4-32k contains gpt-4, matches to 8192

    def test_get_model_context_window_claude(self):
        """测试 Claude 上下文窗口"""
        window = get_model_context_window("claude-3-opus")
        assert window == 200000

    def test_get_model_context_window_unknown(self):
        """测试未知模型默认窗口"""
        window = get_model_context_window("unknown-model")
        assert window == 8192  # 默认值


class TestImageTokens:
    """图片 Token 测试"""

    def test_count_image_tokens_low(self):
        """测试低细节图片"""
        tokens = count_image_tokens(1024, 1024, "low")
        assert tokens == 85

    def test_count_image_tokens_auto(self):
        """测试自动细节图片"""
        tokens = count_image_tokens(1024, 1024, "auto")
        assert tokens > 85

    def test_count_image_tokens_large(self):
        """测试大图片缩放"""
        tokens = count_image_tokens(4096, 4096, "auto")
        assert tokens > 0

    def test_count_image_tokens_advanced(self):
        """测试高级图片 token 计算"""
        tokens = count_image_tokens_advanced(1024, 1024, "gpt-4o")
        assert tokens > 0

    def test_count_image_tokens_advanced_patch(self):
        """测试 patch 模式"""
        tokens = count_image_tokens_advanced(1024, 1024, "gpt-4.1-mini")
        assert tokens > 0

    def test_count_image_tokens_advanced_o1(self):
        """测试 o1 模型"""
        tokens = count_image_tokens_advanced(1024, 1024, "o1")
        assert tokens > 0


class TestAudioTokens:
    """音频 Token 测试"""

    def test_count_audio_token_input(self):
        """测试输入音频 token"""
        # 简单的 base64 测试数据
        audio_b64 = "SGVsbG8gV29ybGQ="  # "Hello World" in base64
        tokens = count_audio_token_input(audio_b64)
        assert tokens > 0

    def test_count_audio_token_input_empty(self):
        """测试空音频"""
        tokens = count_audio_token_input("")
        assert tokens == 0

    def test_count_audio_token_output(self):
        """测试输出音频 token"""
        audio_b64 = "SGVsbG8gV29ybGQ="
        tokens = count_audio_token_output(audio_b64)
        assert tokens > 0


class TestVideoTokens:
    """视频 Token 测试"""

    def test_count_video_token_with_duration(self):
        """测试带时长的视频"""
        tokens = count_video_token(60)  # 60 秒
        assert tokens > 0

    def test_count_video_token_no_duration(self):
        """测试默认视频"""
        tokens = count_video_token(0)
        assert tokens == 8192


class TestFileTokens:
    """文件 Token 测试"""

    def test_count_file_token_image(self):
        """测试图片文件"""
        tokens = count_file_token("image")
        assert tokens == 520

    def test_count_file_token_audio(self):
        """测试音频文件"""
        tokens = count_file_token("audio")
        assert tokens == 256

    def test_count_file_token_video(self):
        """测试视频文件"""
        tokens = count_file_token("video")
        assert tokens == 8192

    def test_count_file_token_unknown(self):
        """测试未知类型"""
        tokens = count_file_token("unknown")
        assert tokens == 4096


class TestAdvancedMessageTokens:
    """高级消息 Token 测试"""

    def test_count_message_tokens_advanced_basic(self):
        """测试高级消息 token 计算"""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        tokens = count_message_tokens_advanced(messages, "gpt-4")
        assert tokens > 0

    def test_count_message_tokens_advanced_multimodal(self):
        """测试多模态消息"""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {
                        "type": "image_url",
                        "image_url": {"detail": "auto"},
                    },
                ],
            }
        ]
        tokens = count_message_tokens_advanced(messages, "gpt-4")
        assert tokens > 0
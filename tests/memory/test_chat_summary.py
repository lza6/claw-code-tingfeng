"""ChatSummary 扩展测试"""

import pytest
from src.memory.chat_summary import (
    ChatSummary,
    compress_messages,
    SummaryResult,
)


class TestChatSummaryExt:
    def test_init_default(self):
        cs = ChatSummary()
        assert cs.max_tokens == 1024

    def test_init_custom(self):
        cs = ChatSummary(max_tokens=2000)
        assert cs.max_tokens == 2000

    def test_too_big(self):
        cs = ChatSummary()
        # too_big expects list of messages
        assert cs.too_big([{"content": "x" * 1000000}]) is True

    def test_get_stats(self):
        cs = ChatSummary()
        stats = cs.get_stats([{"content": "hi"}])
        assert isinstance(stats, dict)


class TestCompressMessages:
    def test_compress_empty(self):
        result = compress_messages([])
        assert result is not None

    def test_compress_single(self):
        result = compress_messages([{"role": "user", "content": "hi"}])
        assert result is not None
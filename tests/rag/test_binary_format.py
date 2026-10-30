"""Binary Format 测试"""

import pytest

from src.rag.binary_format import (
    FORMAT_VERSION,
    LOOKUP_MAGIC,
    POSTINGS_MAGIC,
)


class TestConstants:
    def test_postings_magic(self):
        assert POSTINGS_MAGIC == b'CDBT'

    def test_lookup_magic(self):
        assert LOOKUP_MAGIC == b'CDBL'

    def test_format_version(self):
        assert FORMAT_VERSION == 3

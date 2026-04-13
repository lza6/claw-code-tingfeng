"""Chunk Enrichment 测试"""

import pytest
from src.rag.chunk_enrichment import (
    ChunkEnrichmentConfig,
    RETURN_SEPARATOR,
)


class TestConstants:
    def test_separator(self):
        assert RETURN_SEPARATOR == "\n__ret__\n"


class TestConfig:
    def test_init(self):
        config = ChunkEnrichmentConfig()
        assert config is not None
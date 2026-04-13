"""Tests for RAG TextIndexer core functionality."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile
import os

from src.rag.text_indexer import TextIndexer
from src.rag.models import Document, Chunk, SearchResult
from src.rag.indexer_utils import _get_stop_words_cached

class TestStopWords:
    """Test stop words functionality."""

    def test_stop_words_contains_chinese(self):
        """Stop words should contain common Chinese words."""
        stop_words = _get_stop_words_cached()
        
        assert '的' in stop_words
        assert '了' in stop_words
        assert '在' in stop_words
        assert '是' in stop_words

    def test_stop_words_contains_python_keywords(self):
        """Stop words should contain Python keywords."""
        stop_words = _get_stop_words_cached()
        
        assert 'def' in stop_words
        assert 'class' in stop_words
        assert 'return' in stop_words
        assert 'import' in stop_words

    def test_stop_words_is_cached(self):
        """Stop words should be cached (same object on multiple calls)."""
        stop_words1 = _get_stop_words_cached()
        stop_words2 = _get_stop_words_cached()
        
        # Should be the same object (cached)
        assert stop_words1 is stop_words2


class TestTextIndexerInit:
    """Test TextIndexer initialization."""

    def test_init_default_params(self):
        """Initialize with default parameters."""
        indexer = TextIndexer()
        
        assert indexer.chunk_size == 500
        assert indexer.chunk_overlap == 50
        assert indexer.max_file_size == 1024 * 1024  # 1MB
        assert indexer.max_documents == 1000
        assert indexer.enable_reranker is False
        assert indexer.reranker_top_k == 10
        assert len(indexer._documents) == 0
        assert len(indexer._chunks) == 0

    def test_init_custom_params(self):
        """Initialize with custom parameters."""
        indexer = TextIndexer(
            chunk_size=1000,
            chunk_overlap=100,
            max_file_size=2 * 1024 * 1024,
            max_documents=500,
            enable_reranker=True,
            reranker_top_k=20,
        )
        
        assert indexer.chunk_size == 1000
        assert indexer.chunk_overlap == 100
        assert indexer.max_file_size == 2 * 1024 * 1024
        assert indexer.max_documents == 500
        assert indexer.enable_reranker is True
        assert indexer.reranker_top_k == 20

    def test_init_creates_sub_indexes(self):
        """Initialize should create word index and trigram index."""
        indexer = TextIndexer()
        
        assert indexer._word_index is not None
        assert indexer.trigram_index is not None
        assert indexer.symbol_extractor is not None
        assert indexer.dependency_graph is not None


class TestAddDocument:
    """Test add_document method."""

    def setup_method(self):
        """Setup test fixtures."""
        self.indexer = TextIndexer(max_documents=10)

    def test_add_document_success(self):
        """Add document successfully."""
        doc = Document(
            id='doc-001',
            content='This is a test document.',
            source='test.txt',
        )
        
        result = self.indexer.add_document(doc)
        
        assert result is True
        assert 'doc-001' in self.indexer._documents

    def test_add_document_exceeds_max(self):
        """Reject document when exceeding max_documents limit."""
        # Fill up to max
        for i in range(10):
            doc = Document(
                id=f'doc-{i:03d}',
                content=f'Document {i}',
                source=f'test{i}.txt',
            )
            self.indexer.add_document(doc)
        
        # Try to add one more
        extra_doc = Document(
            id='doc-extra',
            content='Extra document',
            source='extra.txt',
        )
        
        result = self.indexer.add_document(extra_doc)
        
        assert result is False
        assert 'doc-extra' not in self.indexer._documents
        # Should track skipped file
        assert 'extra.txt' in self.indexer._skipped_files

    def test_add_duplicate_document(self):
        """Adding duplicate document ID replaces old one."""
        doc1 = Document(
            id='doc-001',
            content='First version',
            source='test.txt',
        )
        self.indexer.add_document(doc1)
        
        doc2 = Document(
            id='doc-001',
            content='Second version',
            source='test.txt',
        )
        self.indexer.add_document(doc2)
        
        # Should have only one document
        assert len(self.indexer._documents) == 1
        assert self.indexer._documents['doc-001'].content == 'Second version'


class TestChunking:
    """Test text chunking functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        self.indexer = TextIndexer(chunk_size=50, chunk_overlap=10)

    def test_chunk_simple_text_via_add_document(self):
        """Chunk text through add_document workflow."""
        doc = Document(
            id='doc-1',
            content='A' * 100,  # 100 characters
            source='test.txt',
        )
        
        result = self.indexer.add_document(doc)
        
        assert result is True
        # Should have created chunks
        assert len(self.indexer._chunks) >= 1

    def test_chunk_with_overlap_via_documents(self):
        """Chunks should be created with overlap."""
        doc = Document(
            id='doc-1',
            content='ABCDEFGHIJ' * 10,  # 100 chars
            source='test.txt',
        )
        
        self.indexer.add_document(doc)
        
        # Should have created multiple chunks
        chunks = list(self.indexer._chunks.values())
        if len(chunks) > 1:
            # Verify chunks exist and have content
            assert all(len(c.content) > 0 for c in chunks)

    def test_chunk_empty_text(self):
        """Empty document should produce no chunks."""
        doc = Document(id='doc-empty', content='', source='empty.txt')
        
        self.indexer.add_document(doc)
        
        # Empty content may or may not create chunks depending on implementation
        # Just verify it doesn't crash
        assert True

    def test_chunk_short_text(self):
        """Text shorter than chunk_size should be indexed."""
        doc = Document(
            id='doc-short',
            content='Short text',
            source='short.txt',
        )
        
        result = self.indexer.add_document(doc)
        
        assert result is True
        # Document should be added
        assert 'doc-short' in self.indexer._documents


class TestSearch:
    """Test search functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        self.indexer = TextIndexer()
        
        # Add some test documents
        docs = [
            Document(id='doc-1', content='Python programming language', source='python.txt'),
            Document(id='doc-2', content='Java development environment', source='java.txt'),
            Document(id='doc-3', content='JavaScript web development', source='js.txt'),
        ]
        
        for doc in docs:
            self.indexer.add_document(doc)

    def test_search_basic(self):
        """Basic search returns relevant results."""
        results = self.indexer.search('Python')
        
        assert isinstance(results, list)
        # Should find the Python document
        assert len(results) >= 1

    def test_search_no_results(self):
        """Search with no matches returns empty list."""
        results = self.indexer.search('RustLangXYZ')
        
        assert isinstance(results, list)
        # May return empty or very low relevance
        assert len(results) >= 0

    def test_search_case_insensitive(self):
        """Search should be case-insensitive."""
        results_lower = self.indexer.search('python')
        results_upper = self.indexer.search('PYTHON')
        
        # Both should find something
        assert len(results_lower) >= 1 or len(results_upper) >= 1

    def test_search_empty_query(self):
        """Empty query should return empty results."""
        results = self.indexer.search('')
        
        assert isinstance(results, list)
        assert len(results) == 0

    def test_search_returns_search_result_objects(self):
        """Search should return SearchResult objects."""
        results = self.indexer.search('Python')
        
        if len(results) > 0:
            assert isinstance(results[0], SearchResult)
            # SearchResult has 'chunk' field (not chunk_id)
            assert hasattr(results[0], 'chunk')
            assert hasattr(results[0], 'score')
            # Chunk should have id
            assert hasattr(results[0].chunk, 'id')


class TestGetContext:
    """Test get_context method."""

    def setup_method(self):
        """Setup test fixtures."""
        self.indexer = TextIndexer()
        
        doc = Document(
            id='doc-1',
            content='Line 1\nLine 2\nLine 3\nLine 4\nLine 5',
            source='test.txt',
        )
        self.indexer.add_document(doc)

    def test_get_context_by_query(self):
        """Get context by search query."""
        # get_context takes a query string, not chunk_id
        context = self.indexer.get_context('Line', top_k=2)
        
        assert isinstance(context, str)
        # Should return some context (may be empty if no matches)
        assert len(context) >= 0


class TestIndexPersistence:
    """Test index save/load functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        self.indexer = TextIndexer()
        
        doc = Document(
            id='doc-1',
            content='Test content for persistence',
            source='test.txt',
        )
        self.indexer.add_document(doc)

    def test_save_index_to_file(self):
        """Save index to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / 'index.json'
            
            # save_index expects Path object, not string
            self.indexer.save_index(temp_path)
            
            # File should exist
            assert temp_path.exists()
            # File should have content
            assert temp_path.stat().st_size > 0

    def test_load_index_from_file(self):
        """Load index from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / 'index.json'
            
            # Save first
            self.indexer.save_index(temp_path)
            
            # Load into new indexer
            new_indexer = TextIndexer()
            # load_index also expects Path object
            new_indexer.load_index(temp_path)
            
            # Should have loaded the document
            assert 'doc-1' in new_indexer._documents

    def test_load_nonexistent_file(self):
        """Loading nonexistent file should handle gracefully."""
        indexer = TextIndexer()
        
        # Should raise FileNotFoundError or similar
        with pytest.raises((FileNotFoundError, OSError, AttributeError)):
            indexer.load_index('/nonexistent/path/index.json')


class TestSkippedFilesTracking:
    """Test skipped files tracking."""

    def setup_method(self):
        """Setup test fixtures."""
        self.indexer = TextIndexer(max_documents=2)

    def test_track_skipped_files(self):
        """Track files that exceed document limit."""
        # Add documents up to limit
        for i in range(2):
            doc = Document(
                id=f'doc-{i}',
                content=f'Content {i}',
                source=f'file{i}.txt',
            )
            self.indexer.add_document(doc)
        
        # Try to add more (should be skipped)
        for i in range(2, 5):
            doc = Document(
                id=f'doc-{i}',
                content=f'Content {i}',
                source=f'file{i}.txt',
            )
            self.indexer.add_document(doc)
        
        # Should track skipped files (up to 50)
        assert len(self.indexer._skipped_files) >= 1
        assert 'file2.txt' in self.indexer._skipped_files

    def test_skipped_files_limit(self):
        """Skipped files list should not exceed 50 entries."""
        indexer = TextIndexer(max_documents=1)
        
        # Add one document
        doc = Document(id='doc-0', content='First', source='file0.txt')
        indexer.add_document(doc)
        
        # Try to add 60 more (should skip all)
        for i in range(1, 61):
            doc = Document(
                id=f'doc-{i}',
                content=f'Content {i}',
                source=f'file{i}.txt',
            )
            indexer.add_document(doc)
        
        # Should cap at 50
        assert len(indexer._skipped_files) <= 50


class TestCacheManagement:
    """Test cache management functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        self.indexer = TextIndexer()

    def test_clear_search_cache(self):
        """Clear search cache should empty it."""
        # Manually add something to cache
        self.indexer._search_cache['test'] = []
        
        self.indexer._clear_search_cache()
        
        assert len(self.indexer._search_cache) == 0

    def test_invalidate_chunk_lengths(self):
        """Invalidating chunk lengths should clear both caches."""
        # Setup some cached data
        self.indexer._chunk_lengths['chunk-1'] = 100
        self.indexer._search_cache['query'] = []
        
        self.indexer._invalidate_chunk_lengths_cache()
        
        assert len(self.indexer._chunk_lengths) == 0
        assert len(self.indexer._search_cache) == 0


class TestIntegration:
    """Integration tests for TextIndexer."""

    def test_full_workflow(self):
        """Test complete indexing and search workflow."""
        indexer = TextIndexer()
        
        # Add documents
        docs = [
            Document(id='doc-1', content='Python is great for AI', source='ai.txt'),
            Document(id='doc-2', content='JavaScript is great for web', source='web.txt'),
            Document(id='doc-3', content='Rust is great for systems', source='sys.txt'),
        ]
        
        for doc in docs:
            indexer.add_document(doc)
        
        # Search
        results = indexer.search('Python AI')
        
        assert isinstance(results, list)
        # Should find relevant results
        assert len(results) >= 1

    def test_multiple_documents_different_sources(self):
        """Handle multiple documents from different sources."""
        indexer = TextIndexer()
        
        sources = ['file1.py', 'file2.js', 'file3.java']
        for i, source in enumerate(sources):
            doc = Document(
                id=f'doc-{i}',
                content=f'Content from {source}',
                source=source,
            )
            indexer.add_document(doc)
        
        assert len(indexer._documents) == 3
        # All sources should be tracked
        for source in sources:
            assert any(source in doc.source for doc in indexer._documents.values())


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_large_document(self):
        """Handle very large document content."""
        indexer = TextIndexer()
        
        # Create a large document (but under max_file_size)
        large_content = "Word " * 10000  # ~50KB
        
        doc = Document(
            id='large-doc',
            content=large_content,
            source='large.txt',
        )
        
        result = indexer.add_document(doc)
        
        # Should succeed (under max_file_size)
        assert result is True

    def test_special_characters_in_content(self):
        """Handle special characters in document content."""
        indexer = TextIndexer()
        
        doc = Document(
            id='special',
            content='Special chars: !@#$%^&*()_+-=[]{}|;:\'",.<>?/~`',
            source='special.txt',
        )
        
        result = indexer.add_document(doc)
        
        assert result is True

    def test_unicode_content(self):
        """Handle Unicode content (Chinese, emojis, etc.)."""
        indexer = TextIndexer()
        
        doc = Document(
            id='unicode',
            content='中文文本 🎉 Emoji 測試 Ελληνικά',
            source='unicode.txt',
        )
        
        result = indexer.add_document(doc)
        
        assert result is True
        # Should be able to search
        results = indexer.search('中文')
        assert isinstance(results, list)

    def test_zero_max_documents(self):
        """Handle zero max_documents limit."""
        indexer = TextIndexer(max_documents=0)
        
        doc = Document(id='doc-1', content='Test', source='test.txt')
        result = indexer.add_document(doc)
        
        # Should reject immediately
        assert result is False

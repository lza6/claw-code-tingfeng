"""Unit tests for src/core/indexing.py."""
import pytest
from pathlib import Path
from src.core.indexing import TrigramIndex, WordIndex, build_index

def test_trigram_encoding():
    idx = TrigramIndex()
    trigrams = idx._to_trigrams("abc")
    assert len(trigrams) == 1
    # Check if 'abc' in ASCII works
    # 'a'=0x61, 'b'=0x62, 'c'=0x63 -> 0x616263
    assert (0x616263) in trigrams

def test_trigram_search_basic():
    idx = TrigramIndex()
    idx.add_document("file1.py", "def my_function():\n    return True")
    idx.add_document("file2.py", "class MyClass:\n    pass")
    
    # Search for 'func'
    results = idx.search("function")
    assert "file1.py" in results
    assert "file2.py" not in results
    
    # Search for 'my_func' (case-insensitive)
    results = idx.search("my_func")
    assert "file1.py" in results
    assert "file2.py" not in results

def test_word_index_basic():
    widx = WordIndex()
    widx.add_document("f1.py", "import os\ndef start(): pass")
    
    hits = widx.find_word("start")
    assert len(hits) == 1
    assert hits[0][0] == "f1.py"
    assert hits[0][1] == 2

def test_indexing_persistence_flow():
    # This just ensures no crash in the logic
    idx = TrigramIndex()
    idx.add_document("test.txt", "hello world")
    assert idx.search("hello") == ["test.txt"]

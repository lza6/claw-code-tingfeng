import pytest
from pathlib import Path
from src.agent.swarm.self_fission.analyzer import SemanticCodeAnalyzer, AnalysisResult
from src.agent.swarm.self_fission.detectors.base import SemanticFeature

class TestAnalysisResult:
    def test_result_properties(self):
        f1 = SemanticFeature(tag="sql", confidence=0.8, severity="high", evidence=["SELECT *"])
        f2 = SemanticFeature(tag="crypto", confidence=0.9, severity="critical", evidence=["hashlib"])

        result = AnalysisResult(features=[f1, f2], files_analyzed=["test.py"], total_lines=10)

        assert set(result.tags) == {"sql", "crypto"}
        assert result.highest_severity == "critical"

class TestSemanticCodeAnalyzer:
    def test_parse_code_basic(self):
        analyzer = SemanticCodeAnalyzer()
        source = """
import os
from datetime import datetime
class MyClass:
    def my_method(self):
        import hashlib
        hashlib.sha256(b"test")
"""
        parsed = analyzer._parse_code(source)

        assert "os" in parsed['imports']
        assert "datetime" in parsed['imports']
        assert "MyClass" in parsed['classes']
        assert "my_method" in parsed['functions']
        assert "hashlib.sha256" in parsed['keywords']

    def test_parse_code_syntax_error_fallback(self):
        analyzer = SemanticCodeAnalyzer()
        source = "This is not valid Python code\nimport os"
        parsed = analyzer._parse_code(source)

        # Should fallback to basic string extraction for imports
        assert "os" in parsed['imports']

    def test_merge_features(self):
        analyzer = SemanticCodeAnalyzer()
        f1 = SemanticFeature(tag="sql", confidence=0.7, severity="medium", evidence=["file1.py:10"])
        f2 = SemanticFeature(tag="sql", confidence=0.9, severity="high", evidence=["file2.py:20"])
        f3 = SemanticFeature(tag="crypto", confidence=0.5, severity="low", evidence=["file1.py:5"])

        merged = analyzer._merge_features([f1, f2, f3])
        merged_dict = {f.tag: f for f in merged}

        assert len(merged) == 2
        assert merged_dict["sql"].confidence == 0.9
        assert merged_dict["sql"].severity == "high"
        assert set(merged_dict["sql"].evidence) == {"file1.py:10", "file2.py:20"}

    def test_analyze_code_string_empty(self):
        analyzer = SemanticCodeAnalyzer()
        result = analyzer.analyze_code_string("   ")
        assert len(result.features) == 0
        assert result.total_lines == 0

@pytest.mark.asyncio
async def test_analyze_file_not_exists(tmp_path):
    analyzer = SemanticCodeAnalyzer()
    result = await analyzer.analyze_file(tmp_path / "missing.py")
    assert len(result.features) == 0

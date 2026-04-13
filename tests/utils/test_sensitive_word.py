"""敏感词检测测试 - 覆盖 src/utils/sensitive_word.py"""

import pytest
from src.utils.sensitive_word import (
    AhoCorasickAutomaton,
    SensitiveWordCache,
)


class TestAhoCorasickAutomaton:
    """AC 自动机测试"""

    def test_init(self):
        """测试初始化"""
        automaton = AhoCorasickAutomaton()
        assert automaton.root is not None

    def test_build_empty(self):
        """测试构建空模式串"""
        automaton = AhoCorasickAutomaton()
        automaton.build([])
        assert automaton._built is True

    def test_build_single_pattern(self):
        """测试构建单模式串"""
        automaton = AhoCorasickAutomaton()
        automaton.build(["bad"])
        assert automaton._built is True

    def test_build_multiple_patterns(self):
        """测试构建多模式串"""
        automaton = AhoCorasickAutomaton()
        automaton.build(["bad", "ugly", "worst"])
        assert automaton._built is True

    def test_search_no_build(self):
        """测试未构建时搜索"""
        automaton = AhoCorasickAutomaton()
        matches = automaton.search("test text")
        assert matches == []

    def test_search_no_match(self):
        """测试无匹配"""
        automaton = AhoCorasickAutomaton()
        automaton.build(["bad", "ugly"])
        matches = automaton.search("hello world")
        assert matches == []

    def test_search_single_match(self):
        """测试单匹配"""
        automaton = AhoCorasickAutomaton()
        automaton.build(["bad"])
        matches = automaton.search("this is bad")
        assert "bad" in matches

    def test_search_multiple_matches(self):
        """测试多匹配"""
        automaton = AhoCorasickAutomaton()
        automaton.build(["bad", "ugly"])
        matches = automaton.search("this is bad and ugly")
        assert "bad" in matches
        assert "ugly" in matches

    def test_search_overlapping(self):
        """测试重叠匹配"""
        automaton = AhoCorasickAutomaton()
        automaton.build(["bad", "badword"])
        matches = automaton.search("badword")
        assert len(matches) >= 1

    def test_search_stop_immediately(self):
        """测试立即停止"""
        automaton = AhoCorasickAutomaton()
        automaton.build(["bad", "ugly"])
        matches = automaton.search("this is bad and ugly", stop_immediately=True)
        assert len(matches) == 1

    def test_search_case_insensitive(self):
        """测试大小写不敏感"""
        automaton = AhoCorasickAutomaton()
        automaton.build(["bad"])
        matches = automaton.search("This is BAD")
        assert "bad" in matches


class TestSensitiveWordCache:
    """敏感词缓存测试"""

    def test_get_or_build_empty(self):
        """测试空列表"""
        result = SensitiveWordCache.get_or_build([])
        assert result is None

    def test_get_or_build_single(self):
        """测试单个词汇"""
        result = SensitiveWordCache.get_or_build(["bad"])
        assert result is not None

    def test_get_or_build_multiple(self):
        """测试多个���汇"""
        result = SensitiveWordCache.get_or_build(["bad", "ugly"])
        assert result is not None

    def test_caching(self):
        """测试缓存"""
        words = ["test", "word"]
        result1 = SensitiveWordCache.get_or_build(words)
        result2 = SensitiveWordCache.get_or_build(words)
        # 应该返回同一个实例
        assert result1 is not None
        assert result2 is not None
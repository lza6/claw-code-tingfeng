"""Reasoning Tags 单元测试"""
from __future__ import annotations

import pytest

from src.llm.reasoning import (
    REASONING_TAG,
    REASONING_TAG_ALIASES,
    remove_reasoning_content,
    replace_reasoning_tags,
    format_reasoning_content,
    extract_reasoning_content,
    has_reasoning_content,
    split_reasoning_and_answer,
    normalize_reasoning_tags,
    get_reasoning_stats,
)


class TestRemoveReasoningContent:
    """remove_reasoning_content 测试"""

    def test_remove_standard_tag(self):
        text = f"prefix <{REASONING_TAG}>thinking</{REASONING_TAG}> suffix"
        result = remove_reasoning_content(text, REASONING_TAG)
        assert 'thinking' not in result
        assert 'prefix' in result
        assert 'suffix' in result

    def test_remove_multi_line(self):
        text = f"<{REASONING_TAG}>\nline1\nline2\n</{REASONING_TAG}>"
        result = remove_reasoning_content(text, REASONING_TAG)
        assert 'line1' not in result

    def test_remove_all_aliases(self):
        for tag in REASONING_TAG_ALIASES:
            text = f"<{tag}>thoughts</{tag}>"
            result = remove_reasoning_content(text)
            assert 'thoughts' not in result, f"Failed for tag: {tag}"

    def test_no_tag(self):
        text = "just normal text"
        result = remove_reasoning_content(text, REASONING_TAG)
        assert result == "just normal text"

    def test_empty_text(self):
        assert remove_reasoning_content("", REASONING_TAG) == ""

    def test_none_tag(self):
        text = f"<{REASONING_TAG}>content</{REASONING_TAG}>"
        result = remove_reasoning_content(text)
        assert 'content' not in result


class TestReplaceReasoningTags:
    """replace_reasoning_tags 测试"""

    def test_replace(self):
        text = f"before <{REASONING_TAG}>thinking</{REASONING_TAG}> after"
        result = replace_reasoning_tags(text, REASONING_TAG)
        assert 'THINKING' in result
        assert 'ANSWER' in result

    def test_empty_text(self):
        assert replace_reasoning_tags("", REASONING_TAG) == ""

    def test_no_tag(self):
        text = "no tags here"
        assert replace_reasoning_tags(text, REASONING_TAG) == "no tags here"


class TestFormatReasoningContent:
    """format_reasoning_content 测试"""

    def test_format(self):
        result = format_reasoning_content("my thoughts", REASONING_TAG)
        assert f"<{REASONING_TAG}>" in result
        assert "my thoughts" in result
        assert f"</{REASONING_TAG}>" in result

    def test_empty_content(self):
        assert format_reasoning_content("", REASONING_TAG) == ""


class TestExtractReasoningContent:
    """extract_reasoning_content 测试"""

    def test_extract(self):
        text = f"prefix <{REASONING_TAG}>my thoughts</{REASONING_TAG}> suffix"
        result = extract_reasoning_content(text, REASONING_TAG)
        assert result == "my thoughts"

    def test_extract_multi_line(self):
        text = f"<{REASONING_TAG}>\nline1\nline2\n</{REASONING_TAG}>"
        result = extract_reasoning_content(text, REASONING_TAG)
        assert result == "line1\nline2"

    def test_extract_none(self):
        text = "no tags"
        assert extract_reasoning_content(text, REASONING_TAG) == ""

    def test_extract_all_aliases(self):
        text = "<think>my thought</think>"
        result = extract_reasoning_content(text)
        assert result == "my thought"


class TestHasReasoningContent:
    """has_reasoning_content 测试"""

    def test_has_reasoning(self):
        text = f"<{REASONING_TAG}>content</{REASONING_TAG}>"
        assert has_reasoning_content(text) is True

    def test_no_reasoning(self):
        assert has_reasoning_content("plain text") is False

    def test_empty(self):
        assert has_reasoning_content("") is False

    def test_aliases(self):
        for tag in REASONING_TAG_ALIASES:
            assert has_reasoning_content(f"<{tag}>") is True


class TestSplitReasoningAndAnswer:
    """split_reasoning_and_answer 测试"""

    def test_split(self):
        text = f"<{REASONING_TAG}>thoughts</{REASONING_TAG}>answer"
        reasoning, answer = split_reasoning_and_answer(text)
        assert reasoning == "thoughts"
        assert answer == "answer"

    def test_no_reasoning(self):
        text = "just answer"
        reasoning, answer = split_reasoning_and_answer(text)
        assert reasoning == ""
        assert answer == "just answer"


class TestNormalizeReasoningTags:
    """normalize_reasoning_tags 测试"""

    def test_normalize(self):
        text = "<think>content</think>"
        result = normalize_reasoning_tags(text)
        assert f"<{REASONING_TAG}>" in result
        assert "<think>" not in result


class TestGetReasoningStats:
    """get_reasoning_stats 测试"""

    def test_stats_with_reasoning(self):
        text = f"<{REASONING_TAG}>deep thoughts here</{REASONING_TAG}>answer text"
        stats = get_reasoning_stats(text)
        assert stats['has_reasoning'] is True
        assert stats['reasoning_length'] > 0
        assert stats['answer_length'] > 0
        assert stats['total_length'] > 0

    def test_stats_without_reasoning(self):
        stats = get_reasoning_stats("plain text")
        assert stats['has_reasoning'] is False
        assert stats['reasoning_length'] == 0

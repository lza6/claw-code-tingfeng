"""search_replace 模块测试 — 灵活搜索替换引擎"""
import pytest

from src.tools_runtime.search_replace import (
    RelativeIndenter,
    SearchResult,
    flexible_search_and_replace,
    reverse_lines,
    search_and_replace,
    strip_blank_lines,
)

# 仅使用 search_and_replace 策略的策略矩阵（避免 git 依赖问题）
safe_strategies = [
    (search_and_replace, [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, False),
    ]),
]


# ==================== search_and_replace ====================

class TestSearchAndReplace:
    """测试精确搜索替换"""

    def test_simple_replacement(self):
        content = 'hello world\nfoo bar\n'
        result = search_and_replace(content, 'hello', 'goodbye')
        assert result == 'goodbye world\nfoo bar\n'

    def test_multiple_occurrences_raises(self):
        content = 'hello world\nhello again\n'
        with pytest.raises(ValueError, match='出现了 2 次'):
            search_and_replace(content, 'hello', 'goodbye')

    def test_no_match_raises(self):
        content = 'hello world\n'
        with pytest.raises(ValueError, match='未找到匹配'):
            search_and_replace(content, 'xyz', 'abc')

    def test_replacement_at_start(self):
        content = 'hello world\nfoo bar\n'
        result = search_and_replace(content, 'hello world\nfoo bar\n', 'replaced')
        assert result == 'replaced'

    def test_replacement_at_end(self):
        content = 'start\nhello world'
        result = search_and_replace(content, 'hello world', 'goodbye')
        assert result == 'start\ngoodbye'

    def test_empty_search_raises(self):
        with pytest.raises(ValueError, match='不能为空'):
            search_and_replace('hello', '', 'world')

    def test_empty_replace(self):
        content = 'hello world\nfoo bar\n'
        result = search_and_replace(content, 'hello world\n', '')
        assert result == 'foo bar\n'

    def test_multiline_replacement(self):
        content = 'line1\nline2\nline3\n'
        result = search_and_replace(content, 'line2\n', 'LINE_TWO\n')
        assert result == 'line1\nLINE_TWO\nline3\n'


# ==================== RelativeIndenter ====================

class TestRelativeIndenter:
    """测试相对缩进转换"""

    def test_make_relative_basic(self):
        """基本相对缩进转换"""
        text = '    def foo():\n        return 1\n    def bar():\n'
        indenter = RelativeIndenter()
        result = indenter.make_relative(text)
        assert 'def foo():' in result
        assert '←' in result  # 应包含减少缩进的标记

    def test_make_absolute_basic(self):
        """基本绝对缩进恢复"""
        text = '    def foo():\n        return 1\n    def bar():\n        return 2\n'
        indenter = RelativeIndenter()
        relative = indenter.make_relative(text)
        absolute = indenter.make_absolute(relative)
        # 基本结构应保留
        assert 'def foo():' in absolute
        assert 'def bar():' in absolute

    def test_empty_text(self):
        indenter = RelativeIndenter()
        assert indenter.make_relative('') == ''
        assert indenter.make_absolute('') == ''

    def test_no_indent_text(self):
        text = 'hello\nworld\n'
        indenter = RelativeIndenter()
        result = indenter.make_relative(text)
        assert 'hello' in result
        assert 'world' in result

    def test_roundtrip_preserves_structure(self):
        """往返转换应保留基本代码结构"""
        text = 'def foo():\n    if True:\n        return 1\n    return 0\n'
        indenter = RelativeIndenter()
        relative = indenter.make_relative(text)
        absolute = indenter.make_absolute(relative)
        # 关键内容应保留
        assert 'def foo():' in absolute
        assert 'if True:' in absolute
        assert 'return 1' in absolute
        assert 'return 0' in absolute

    def test_custom_marker(self):
        """自定义标记字符 — 当文本包含 ← 时自动选择其他 marker"""
        text_with_arrow = '    foo ←\n        bar ←\n    baz ←\n'
        indenter = RelativeIndenter(texts=[text_with_arrow])
        text = '    foo\n        bar\n    baz\n'
        result = indenter.make_relative(text)
        # 应使用非 ← 的 marker
        assert '←' not in result


# ==================== 预处理器 ====================

class TestPreprocessors:
    """测试预处理函数"""

    def test_strip_blank_lines_leading(self):
        assert strip_blank_lines('\n\nhello\nworld\n') == 'hello\nworld\n'

    def test_strip_blank_lines_trailing(self):
        assert strip_blank_lines('hello\nworld\n\n\n') == 'hello\nworld\n'

    def test_strip_blank_lines_both(self):
        assert strip_blank_lines('\n\nhello\nworld\n\n') == 'hello\nworld\n'

    def test_strip_blank_lines_no_blanks(self):
        assert strip_blank_lines('hello\nworld') == 'hello\nworld'

    def test_strip_blank_lines_only_blanks(self):
        assert strip_blank_lines('\n\n\n') == ''

    def test_strip_blank_lines_preserves_internal(self):
        result = strip_blank_lines('\nhello\n\nworld\n')
        assert result == 'hello\n\nworld\n'

    def test_reverse_lines(self):
        assert reverse_lines('a\nb\nc\n') == 'c\nb\na\n'

    def test_reverse_lines_empty(self):
        assert reverse_lines('') == ''

    def test_reverse_lines_single(self):
        assert reverse_lines('hello\n') == 'hello\n'


# ==================== flexible_search_and_replace ====================

class TestFlexibleSearchAndReplace:
    """测试灵活搜索替换"""

    def test_exact_match(self):
        content = 'hello world\nfoo bar\n'
        result = flexible_search_and_replace(content, 'hello', 'goodbye')
        assert result == 'goodbye world\nfoo bar\n'

    def test_match_after_stripping_blank_lines(self):
        """前后空行差异应通过 strip_blank_lines 预处理匹配"""
        content = '\n\nhello\nworld\n\n'
        search = 'hello\nworld\n'
        result = flexible_search_and_replace(content, search, 'HELLO\nWORLD\n')
        assert 'HELLO' in result
        assert 'WORLD' in result

    def test_no_match_raises(self):
        content = 'hello world\n'
        with pytest.raises(ValueError, match='所有搜索替换策略均失败'):
            flexible_search_and_replace(content, 'xyz_not_found_abc', 'replacement', strategies=safe_strategies)

    def test_preserves_rest_of_content(self):
        content = 'start\nmiddle\nend\n'
        result = flexible_search_and_replace(content, 'middle\n', 'MIDDLE\n')
        assert 'start' in result
        assert 'MIDDLE' in result
        assert 'end' in result

    def test_empty_search_raises(self):
        with pytest.raises(ValueError):
            flexible_search_and_replace('hello', '', 'world', strategies=safe_strategies)

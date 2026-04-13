"""文件操作测试 - 覆盖 src/utils/file_ops.py"""

import os
import tempfile
from pathlib import Path

import pytest
from src.utils.file_ops import (
    get_file_info,
    is_binary,
    normalize_content,
)


class TestGetFileInfo:
    """文件信息测试"""

    def test_nonexistent_file(self):
        """测试不存在的文件"""
        result = get_file_info("/nonexistent/path/file.txt")
        assert result is None

    def test_existing_file(self):
        """测试存在的文件"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            f.flush()
            path = f.name

        try:
            result = get_file_info(path)
            assert result is not None
            assert "mtime" in result
            assert "size" in result
        finally:
            os.unlink(path)

    def test_directory(self):
        """测试目录"""
        result = get_file_info(".")
        assert result is None


class TestIsBinary:
    """二进制检测测试"""

    def test_none(self):
        """测试 None"""
        result = is_binary(None)
        assert result is False

    def test_empty_bytes(self):
        """测试空字节"""
        result = is_binary(b"")
        assert result is False

    def test_text_bytes(self):
        """测试文本字节"""
        result = is_binary(b"hello world")
        assert result is False

    def test_binary_bytes(self):
        """测试二进制字节"""
        result = is_binary(b"hello\x00world")
        assert result is True

    def test_null_byte(self):
        """测试 NULL 字节"""
        result = is_binary(b"\x00")
        assert result is True


class TestNormalizeContent:
    """内容规范化测试"""

    def test_normal_text(self):
        """测试普通文本"""
        result = normalize_content("hello world")
        assert result == "hello world"

    def test_strip_bom(self):
        """测试去除 BOM"""
        result = normalize_content("\ufeffhello")
        assert result == "hello"

    def test_crlf_to_lf(self):
        """测试 CRLF 转 LF"""
        result = normalize_content("hello\r\nworld")
        assert result == "hello\nworld"

    def test_cr_to_lf(self):
        """测试 CR 转 LF"""
        result = normalize_content("hello\rworld")
        assert result == "hello\nworld"

    def test_mixed_line_endings(self):
        """测试混合行尾"""
        result = normalize_content("line1\r\nline2\rline3\nline4")
        assert "\r" not in result
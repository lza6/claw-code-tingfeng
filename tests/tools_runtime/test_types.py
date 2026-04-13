"""工具类型测试 - 覆盖 src/tools_runtime/types.py"""

import pytest
from src.tools_runtime.types import (
    BashToolArgs,
    FileReadToolArgs,
    FileEditToolArgs,
    GrepToolArgs,
    GlobToolArgs,
    ToolArgs,
)


class TestBashToolArgs:
    def test_create(self):
        args = BashToolArgs(command="ls -la")
        assert args["command"] == "ls -la"

    def test_optional_fields(self):
        args = BashToolArgs()
        assert args == {}


class TestFileReadToolArgs:
    def test_create(self):
        args = FileReadToolArgs(file_path="test.py", offset=1, limit=100)
        assert args["file_path"] == "test.py"
        assert args["offset"] == 1
        assert args["limit"] == 100


class TestFileEditToolArgs:
    def test_create(self):
        args = FileEditToolArgs(file_path="test.py", content="test", append=False)
        assert args["file_path"] == "test.py"
        assert args["content"] == "test"

    def test_default_append(self):
        args = FileEditToolArgs(file_path="test.py", content="test")
        assert args.get("append", False) is False


class TestGrepToolArgs:
    def test_create(self):
        args = GrepToolArgs(pattern="test", path=".")
        assert args["pattern"] == "test"


class TestGlobToolArgs:
    def test_create(self):
        args = GlobToolArgs(pattern="*.py")
        assert args["pattern"] == "*.py"


class TestToolArgs:
    def test_tool_args_union(self):
        # Test that ToolArgs is a union type
        args1 = BashToolArgs(command="ls")
        args2 = FileReadToolArgs(file_path="test.py")
        # Both should work as their own types
        assert "command" in args1
        assert "file_path" in args2
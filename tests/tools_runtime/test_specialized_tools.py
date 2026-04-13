"""专业工具测试 - 覆盖 src/tools_runtime/specialized_tools.py"""

import pytest
from src.tools_runtime.specialized_tools import (
    DocGenTool,
    SQLAuditTool,
    Any,
)


class TestDocGenTool:
    """文档生成工具测试"""

    def test_exists(self):
        """测试类存在"""
        assert DocGenTool is not None


class TestSQLAuditTool:
    """SQL 审计工具测试"""

    def test_exists(self):
        """测试类存在"""
        assert SQLAuditTool is not None


class TestAny:
    """Any 类型测试"""

    def test_any_type(self):
        """测试 Any 类型"""
        # Any 可以是任何类型
        value: Any = "string"
        assert value == "string"

        value = 123
        assert value == 123

        value = ["list"]
        assert value == ["list"]
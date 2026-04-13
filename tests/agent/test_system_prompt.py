"""System Prompt 测试 - 覆盖 src/agent/_system_prompt.py"""

import pytest
from src.agent._system_prompt import build_system_prompt


class TestBuildSystemPrompt:
    """系统提示词构建测试"""

    def test_build_system_prompt_empty(self):
        """测试空工具列表"""
        result = build_system_prompt({})
        assert isinstance(result, str)

    def test_build_system_prompt_with_tools(self):
        """测试带工具的提示"""
        # Mock tool class
        class MockTool:
            description = "Test tool"

        tools = {"test_tool": MockTool()}
        result = build_system_prompt(tools)
        assert "test_tool" in result

    def test_build_system_prompt_developer_mode(self):
        """测试开发者模式"""
        result = build_system_prompt({}, developer_mode=True)
        assert isinstance(result, str)
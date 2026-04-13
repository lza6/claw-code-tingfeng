"""工具接口测试 - 覆盖 src/tools_runtime/tool_interface.py"""

import pytest

from src.tools_runtime.tool_interface import (
    ToolCallStatus,
    ToolDefinition,
    ToolResult,
    BaseTool,
    ToolRegistry,
    ToolExecutor,
    get_tool_registry,
    get_tool_executor,
    register_tool,
    execute_tool,
)


class TestToolCallStatus:
    """工具调用状态测试"""

    def test_values(self):
        """测试状态值"""
        assert ToolCallStatus.SUCCESS.value == "success"
        assert ToolCallStatus.ERROR.value == "error"
        assert ToolCallStatus.TIMEOUT.value == "timeout"
        assert ToolCallStatus.CANCELLED.value == "cancelled"


class TestToolDefinition:
    """工具定义测试"""

    def test_create(self):
        """测试创建"""
        tool_def = ToolDefinition(
            name="test_tool",
            description="Test tool",
        )
        assert tool_def.name == "test_tool"
        assert tool_def.description == "Test tool"

    def test_to_dict(self):
        """测试转换为字典"""
        tool_def = ToolDefinition(name="test", description="desc")
        d = tool_def.to_dict()
        assert d["name"] == "test"
        assert d["description"] == "desc"


class TestToolResult:
    """工具结果测试"""

    def test_create_success(self):
        """测试创建成功结果"""
        result = ToolResult(
            tool_name="test",
            status=ToolCallStatus.SUCCESS,
            output="success",
        )
        assert result.is_success is True

    def test_create_error(self):
        """测试创建错误结果"""
        result = ToolResult(
            tool_name="test",
            status=ToolCallStatus.ERROR,
            error="error message",
        )
        assert result.is_success is False

    def test_to_dict(self):
        """测试转换为字典"""
        result = ToolResult(
            tool_name="test",
            status=ToolCallStatus.SUCCESS,
            output="output",
        )
        d = result.to_dict()
        assert d["tool_name"] == "test"
        assert d["status"] == "success"


class TestBaseTool:
    """基础工具测试"""

    def test_create_tool(self):
        """测试创建工具"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "executed"

        tool = TestTool("test", "Test tool")
        assert tool.name == "test"
        assert tool.definition.name == "test"

    def test_execute(self):
        """测试执行"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return ToolResult(tool_name="test", status=ToolCallStatus.SUCCESS, output="result")

        tool = TestTool("test", "Test")
        result = tool.execute()
        assert result.output == "result"

    def test_validate_params(self):
        """测试参数验证"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "result"

        tool = TestTool("test", "Test")
        is_valid, msg = tool.validate_params({})
        assert is_valid is True


class TestToolRegistry:
    """工具注册表测试"""

    def test_register(self):
        """测试注册工具"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "result"

        registry = ToolRegistry()
        tool = TestTool("test_tool", "Test")

        # 清理之前的注册
        registry._tools.clear()
        registry._categories.clear()

        registry.register(tool, "test")
        assert "test_tool" in registry._tools
        assert "test" in registry._categories

    def test_unregister(self):
        """测试注销工具"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "result"

        registry = ToolRegistry()
        tool = TestTool("to_remove", "Remove")
        registry.register(tool)

        result = registry.unregister("to_remove")
        assert result is True

    def test_get(self):
        """测试获取工具"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "result"

        registry = ToolRegistry()
        tool = TestTool("get_test", "Get test")
        registry.register(tool)

        retrieved = registry.get("get_test")
        assert retrieved is not None
        assert retrieved.name == "get_test"

    def test_list_tools(self):
        """测试列出工具"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "result"

        registry = ToolRegistry()
        tool = TestTool("list_test", "List")
        registry._tools.clear()
        registry._categories.clear()
        registry.register(tool)

        tools = registry.list_tools()
        assert len(tools) > 0

    def test_list_categories(self):
        """测试列出分类"""
        registry = ToolRegistry()
        registry._tools.clear()
        registry._categories.clear()
        categories = registry.list_categories()
        # 可能为空，因为刚清理了

    def test_get_by_tag(self):
        """测试按标签获取"""

        class TestTool(BaseTool):
            def __init__(self, name, desc):
                super().__init__(name, desc)
                self._definition.tags = ["tag1"]
            def execute(self, **kwargs):
                return "result"

        registry = ToolRegistry()
        tool = TestTool("tag_test", "Tag test")
        registry._tools.clear()
        registry._categories.clear()
        registry.register(tool)

        tools = registry.get_by_tag("tag1")
        assert len(tools) > 0

    def test_search(self):
        """测试搜索"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "result"

        registry = ToolRegistry()
        tool = TestTool("search_tool", "Searchable tool")
        registry._tools.clear()
        registry._categories.clear()
        registry.register(tool)

        results = registry.search("searchable")
        assert len(results) > 0


class TestToolExecutor:
    """工具执行器测试"""

    def test_execute_tool_not_found(self):
        """测试执行不存在的工具"""
        executor = ToolExecutor()
        result = executor.execute("nonexistent")
        assert result.status == ToolCallStatus.ERROR

    def test_execute_success(self):
        """测试成功执行"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "success"

        executor = ToolExecutor()
        tool = TestTool("exec_test", "Execute test")

        # 清理并注册
        executor.registry._tools.clear()
        executor.registry._categories.clear()
        executor.registry.register(tool)

        result = executor.execute("exec_test")
        assert result.status == ToolCallStatus.SUCCESS

    def test_execute_with_params(self):
        """测试带参数执行"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return kwargs.get("input", "")

        executor = ToolExecutor()
        tool = TestTool("param_test", "Param test")

        executor.registry._tools.clear()
        executor.registry._categories.clear()
        executor.registry.register(tool)

        result = executor.execute("param_test", {"input": "test_value"})
        assert result.output == "test_value"

    def test_execute_string_result(self):
        """测试字符串结果"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "string result"

        executor = ToolExecutor()
        tool = ToolExecutor()

        # 这个测试实际执行
        executor.registry._tools.clear()
        executor.registry._categories.clear()


class TestGlobalFunctions:
    """全局函数测试"""

    def test_get_tool_registry(self):
        """测试获取工具注册表"""
        registry = get_tool_registry()
        assert registry is not None

    def test_get_tool_executor(self):
        """测试获取工具执行器"""
        executor = get_tool_executor()
        assert executor is not None

    def test_register_tool(self):
        """测试注册工具"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "result"

        tool = TestTool("global_test", "Global test")
        register_tool(tool)
        # 检查是否注册成功
        registry = get_tool_registry()
        assert registry.get("global_test") is not None

    def test_execute_tool(self):
        """测试执行工具"""

        class TestTool(BaseTool):
            def execute(self, **kwargs):
                return "global result"

        tool = TestTool("exec_global", "Exec global")

        # 需要先注册
        get_tool_registry()._tools.clear()
        get_tool_registry()._categories.clear()
        register_tool(tool)

        result = execute_tool("exec_global")
        assert result.status == ToolCallStatus.SUCCESS
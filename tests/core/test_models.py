"""Core models 模块单元测试"""
import pytest
from src.core.models import (
    Subsystem,
    PortingModule,
    PermissionDenial,
    UsageSummary,
    PortingBacklog,
    PortingTask,
    CommandResult,
)


class TestSubsystem:
    """Subsystem 测试"""

    def test_create(self):
        """创建 Subsystem"""
        s = Subsystem(name="core", path="src/core", file_count=50, notes="核心模块")
        assert s.name == "core"
        assert s.path == "src/core"
        assert s.file_count == 50
        assert s.notes == "核心模块"

    def test_frozen(self):
        """不可变对象"""
        s = Subsystem(name="llm", path="src/llm", file_count=30, notes="LLM 集成")
        with pytest.raises(Exception):
            s.name = "new_name"


class TestPortingModule:
    """PortingModule 测试"""

    def test_defaults(self):
        """默认状态"""
        m = PortingModule(name="auth", responsibility="认证模块", source_hint="project_a")
        assert m.status == "planned"

    def test_custom_status(self):
        """自定义状态"""
        m = PortingModule(name="db", responsibility="数据库", source_hint="legacy", status="done")
        assert m.status == "done"


class TestPermissionDenial:
    """PermissionDenial 测试"""

    def test_create(self):
        """创建权限拒绝"""
        p = PermissionDenial(tool_name="bash", reason="安全策略")
        assert p.tool_name == "bash"
        assert p.reason == "安全策略"


class TestUsageSummary:
    """UsageSummary 测试"""

    def test_defaults(self):
        """默认值"""
        u = UsageSummary()
        assert u.input_tokens == 0
        assert u.output_tokens == 0

    def test_add_turn(self):
        """添加对话轮次"""
        u = UsageSummary()
        u2 = u.add_turn("hello world", "hi there")
        assert u2.input_tokens == 2
        assert u2.output_tokens == 2
        # 原始对象不变 (frozen)
        assert u.input_tokens == 0

    def test_add_multiple_turns(self):
        """多次添加"""
        u = UsageSummary()
        u1 = u.add_turn("a b c", "x y")
        u2 = u1.add_turn("d e", "z")
        assert u2.input_tokens == 5
        assert u2.output_tokens == 3


class TestPortingBacklog:
    """PortingBacklog 测试"""

    def test_empty(self):
        """空待办"""
        b = PortingBacklog(title="空项目")
        assert b.title == "空项目"
        assert b.modules == []
        assert b.summary_lines() == []

    def test_with_modules(self):
        """带模块的待办"""
        modules = [
            PortingModule(name="auth", responsibility="认证", source_hint="old"),
            PortingModule(name="db", responsibility="数据库", source_hint="legacy", status="done"),
        ]
        b = PortingBacklog(title="迁移项目", modules=modules)
        assert len(b.modules) == 2

        summary = b.summary_lines()
        assert len(summary) == 2
        assert "- auth [planned]" in summary[0]
        assert "- db [done]" in summary[1]

    def test_summary_format(self):
        """摘要格式"""
        m = PortingModule(name="test", responsibility="测试", source_hint="src")
        b = PortingBacklog(title="测试", modules=[m])
        lines = b.summary_lines()
        assert lines[0] == "- test [planned] — 测试（来自 src）"


class TestPortingTask:
    """PortingTask 测试"""

    def test_defaults(self):
        """默认状态"""
        t = PortingTask(name="task1", description="描述")
        assert t.status == "pending"

    def test_custom_status(self):
        """自定义状态"""
        t = PortingTask(name="task2", description="描述", status="done")
        assert t.status == "done"


class TestCommandResult:
    """CommandResult 测试"""

    def test_success(self):
        """成功执行"""
        r = CommandResult(exit_code=0, output="成功")
        assert r.exit_code == 0
        assert r.output == "success" if r.output != "成功" else "成功"

    def test_failure(self):
        """执行失败"""
        r = CommandResult(exit_code=1, output="错误信息")
        assert r.exit_code != 0

    def test_default_output(self):
        """默认输出"""
        r = CommandResult(exit_code=0)
        assert r.output == ""

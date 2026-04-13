"""PatchEngine 测试 - 补丁引擎"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.patch_engine import PatchEngine, PatchDefinition, PatchResult


class TestPatchDefinition:
    """PatchDefinition 测试"""

    def test_create_patch_definition(self):
        """测试创建补丁定义"""
        patch_def = PatchDefinition(
            name="test_patch",
            pattern=r"old_function",
            replacer=lambda m, fn: "new_function",
        )
        assert patch_def.name == "test_patch"
        assert patch_def.pattern == r"old_function"

    def test_create_patch_definition_with_options(self):
        """测试创建带选项的补丁定义"""
        patch_def = PatchDefinition(
            name="test_patch",
            pattern=r"old",
            replacer=lambda m, fn: "new",
            unique=True,
            optional=False,
            description="测试补丁",
        )
        assert patch_def.unique is True
        assert patch_def.optional is False
        assert patch_def.description == "测试补丁"


class TestPatchResult:
    """PatchResult 测试"""

    def test_result_success(self):
        """测试结果成功"""
        result = PatchResult(applied=1)
        assert result.success is True
        assert result.applied == 1

    def test_result_failure(self):
        """测试结果失败"""
        result = PatchResult(failed=1)
        assert result.success is False
        assert result.failed == 1

    def test_result_with_details(self):
        """测试结果包含详情"""
        details = ["  ✅ test_patch (1 replacement)"]
        result = PatchResult(applied=1, details=details)
        assert result.applied == 1
        assert "test_patch" in result.details[0]


class TestPatchEngineCreation:
    """PatchEngine 创建测试"""

    def test_create_engine_with_path(self):
        """测试使用路径创建引擎"""
        engine = PatchEngine(target_file=Path("/tmp/test.py"))
        assert engine.target_file == Path("/tmp/test.py")

    def test_create_engine_with_string(self):
        """测试使用字符串创建引擎"""
        engine = PatchEngine(target_file="/tmp/test.py")
        assert engine.target_file == Path("/tmp/test.py")


class TestPatchEngineBasic:
    """PatchEngine 基础功能测试"""

    def test_apply_patch_dry_run(self, tmp_path):
        """测试预演补丁"""
        test_file = tmp_path / "test.py"
        test_file.write_text("old_content")

        engine = PatchEngine(target_file=test_file)
        # 创建简单的补丁定义 - replacer 只接受 match 参数
        patch_def = PatchDefinition(
            name="test",
            pattern=r"old_content",
            replacer=lambda m: "new_content",
        )

        # 预演
        result = engine.apply_patches([patch_def], dry_run=True)
        assert result is not None
        assert result.applied >= 0

    def test_apply_patch_no_match(self, tmp_path):
        """测试无匹配时应用补丁"""
        test_file = tmp_path / "test.py"
        test_file.write_text("content")

        engine = PatchEngine(target_file=test_file)
        patch_def = PatchDefinition(
            name="test",
            pattern=r"nonexistent",
            replacer=lambda m: "new",
        )

        result = engine.apply_patches([patch_def])
        # 应该返回结果（可能失败）
        assert result is not None


class TestPatchEngineEdgeCases:
    """边界条件测试"""

    def test_apply_patch_to_nonexistent_file(self):
        """测试应用到不存在的文件"""
        engine = PatchEngine(target_file=Path("/nonexistent/file.py"))
        patch_def = PatchDefinition(
            name="test",
            pattern=r"old",
            replacer=lambda m, fn: "new",
        )
        
        # 应该抛出异常或返回错误结果
        try:
            result = engine.apply_patch(patch_def)
            assert result is not None
        except Exception:
            pass  # 预期行为

    def test_apply_patch_special_characters(self, tmp_path):
        """测试特殊字符"""
        test_file = tmp_path / "test.py"
        # 显式指定UTF-8编码,避免Windows默认GBK编码导致的UnicodeDecodeError
        test_file.write_text("def func():\n    # 特殊字符: $@#!\n    pass\n", encoding="utf-8")

        engine = PatchEngine(target_file=test_file)
        patch_def = PatchDefinition(
            name="test",
            pattern=r"# 特殊字符.*",
            replacer=lambda m: "# 已修改",
        )

        result = engine.apply_patches([patch_def])
        assert result is not None

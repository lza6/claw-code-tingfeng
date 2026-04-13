"""ApprovalMode 单元测试"""
import pytest
from src.core.approval_mode import ApprovalMode


class TestApprovalModeProperties:
    """ApprovalMode 属性测试"""

    def test_plan_requires_approval(self):
        """PLAN 模式需要审批"""
        assert ApprovalMode.PLAN.requires_approval is True

    def test_default_requires_approval(self):
        """DEFAULT 模式需要审批"""
        assert ApprovalMode.DEFAULT.requires_approval is True

    def test_auto_edit_no_approval(self):
        """AUTO_EDIT 模式不需要审批"""
        assert ApprovalMode.AUTO_EDIT.requires_approval is False

    def test_yolo_no_approval(self):
        """YOLO 模式不需要审批"""
        assert ApprovalMode.YOLO.requires_approval is False

    def test_plan_not_auto_edit(self):
        """PLAN 模式不是自动编辑"""
        assert ApprovalMode.PLAN.auto_edit is False

    def test_default_not_auto_edit(self):
        """DEFAULT 模式不是自动编辑"""
        assert ApprovalMode.DEFAULT.auto_edit is False

    def test_auto_edit_is_auto_edit(self):
        """AUTO_EDIT 模式是自动编辑"""
        assert ApprovalMode.AUTO_EDIT.auto_edit is True

    def test_yolo_is_auto_edit(self):
        """YOLO 模式是自动编辑"""
        assert ApprovalMode.YOLO.auto_edit is True

    def test_plan_not_auto_exec(self):
        """PLAN 模式不自动执行"""
        assert ApprovalMode.PLAN.auto_exec is False

    def test_default_not_auto_exec(self):
        """DEFAULT 模式不自动执行"""
        assert ApprovalMode.DEFAULT.auto_exec is False

    def test_auto_edit_not_auto_exec(self):
        """AUTO_EDIT 模式不自动执行 shell"""
        assert ApprovalMode.AUTO_EDIT.auto_exec is False

    def test_yolo_is_auto_exec(self):
        """YOLO 模式自动执行 shell"""
        assert ApprovalMode.YOLO.auto_exec is True


class TestApprovalModeValues:
    """ApprovalMode 值测试"""

    def test_plan_value(self):
        """PLAN 值"""
        assert ApprovalMode.PLAN.value == "plan"

    def test_default_value(self):
        """DEFAULT 值"""
        assert ApprovalMode.DEFAULT.value == "default"

    def test_auto_edit_value(self):
        """AUTO_EDIT 值"""
        assert ApprovalMode.AUTO_EDIT.value == "auto-edit"

    def test_yolo_value(self):
        """YOLO 值"""
        assert ApprovalMode.YOLO.value == "yolo"


class TestApprovalModeStringConversion:
    """ApprovalMode 字符串转换测试"""

    def test_str_conversion(self):
        """字符串转换"""
        assert ApprovalMode.PLAN.value == "plan"
        assert ApprovalMode.DEFAULT.value == "default"
        assert ApprovalMode.AUTO_EDIT.value == "auto-edit"
        assert ApprovalMode.YOLO.value == "yolo"

    def test_from_string(self):
        """从字符串创建"""
        assert ApprovalMode("plan") == ApprovalMode.PLAN
        assert ApprovalMode("default") == ApprovalMode.DEFAULT
        assert ApprovalMode("auto-edit") == ApprovalMode.AUTO_EDIT
        assert ApprovalMode("yolo") == ApprovalMode.YOLO

    def test_invalid_string_raises(self):
        """无效字符串抛出 ValueError"""
        with pytest.raises(ValueError):
            ApprovalMode("invalid")


class TestApprovalModeBehaviorMatrix:
    """ApprovalMode 行为矩阵测试"""

    @pytest.mark.parametrize("mode,requires_approval,auto_edit,auto_exec", [
        (ApprovalMode.PLAN, True, False, False),
        (ApprovalMode.DEFAULT, True, False, False),
        (ApprovalMode.AUTO_EDIT, False, True, False),
        (ApprovalMode.YOLO, False, True, True),
    ])
    def test_behavior_matrix(self, mode, requires_approval, auto_edit, auto_exec):
        """行为矩阵验证"""
        assert mode.requires_approval == requires_approval
        assert mode.auto_edit == auto_edit
        assert mode.auto_exec == auto_exec

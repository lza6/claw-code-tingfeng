"""Approval Mode — 审批模式（借鉴 Project B）

定义 AI 编程助手的审批级别:
- PLAN: 仅分析，不修改文件
- DEFAULT: 编辑文件或执行 shell 需要审批
- AUTO_EDIT: 自动批准文件编辑
- YOLO: 自动批准所有工具
"""
from __future__ import annotations

from enum import Enum


class ApprovalMode(str, Enum):
    """审批模式（借鉴 Aider）"""
    PLAN = "plan"         # 仅分析，不修改文件
    DEFAULT = "default"   # 编辑文件或执行 shell 需要审批
    AUTO_EDIT = "auto-edit" # 自动批准文件编辑
    YOLO = "yolo"         # 自动批准所有工具

    @property
    def requires_approval(self) -> bool:
        """是否需要用户审批"""
        return self in (ApprovalMode.DEFAULT, ApprovalMode.PLAN)

    @property
    def auto_edit(self) -> bool:
        """是否自动批准文件编辑"""
        return self in (ApprovalMode.AUTO_EDIT, ApprovalMode.YOLO)

    @property
    def auto_exec(self) -> bool:
        """是否自动批准 shell 执行"""
        return self == ApprovalMode.YOLO

"""Approval Mode — 审批模式（借鉴 Project B）

定义 AI 编程助手的审批级别:
- PLAN: 仅分析，不修改文件
- DEFAULT: 编辑文件或执行 shell 需要审批
- AUTO_EDIT: 自动批准文件编辑
- YOLO: 自动批准所有工具
"""
from __future__ import annotations

from enum import Enum


#: 各审批模式的中文名与解释（对外一律用中文，避免用户看不懂英文枚举）
APPROVAL_MODE_INFO: dict[str, dict[str, str]] = {
    "plan": {
        "label": "计划模式（只读）",
        "explain": "只分析、不落盘：读文件可以，写文件和执行命令一律拒绝。",
        "risk": "最安全；但无法完成需要改代码的任务。",
    },
    "default": {
        "label": "默认模式（改前确认）",
        "explain": "读操作直接放行；写文件与执行命令前先问你一次。",
        "risk": "安全；交互场景推荐。无人值守时会因无人确认而卡住。",
    },
    "auto-edit": {
        "label": "自动编辑模式（改文件不问，跑命令问）",
        "explain": "文件编辑自动通过；执行命令仍需你确认。",
        "risk": "中等；适合以改代码为主、少跑命令的任务。",
    },
    "yolo": {
        "label": "全自动模式（都不问）",
        "explain": "写文件与执行命令全部自动通过，除受保护路径（.git、密钥等）外不再询问。",
        "risk": "最高；只建议在可回滚的隔离环境里用。",
    },
}


class ApprovalMode(str, Enum):
    """审批模式（借鉴 Aider）"""
    PLAN = "plan"         # 仅分析，不修改文件
    DEFAULT = "default"   # 编辑文件或执行 shell 需要审批
    AUTO_EDIT = "auto-edit" # 自动批准文件编辑
    YOLO = "yolo"         # 自动批准所有工具

    @property
    def label(self) -> str:
        """中文名称（给用户看的名，不暴露英文枚举）"""
        return APPROVAL_MODE_INFO.get(self.value, {}).get("label", self.value)

    @property
    def explain(self) -> str:
        """一句话中文解释：这个模式到底会做什么"""
        return APPROVAL_MODE_INFO.get(self.value, {}).get("explain", "")

    @property
    def risk_note(self) -> str:
        """风险提示"""
        return APPROVAL_MODE_INFO.get(self.value, {}).get("risk", "")

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


def describe_approval_modes() -> str:
    """全部审批模式的中文说明表（供 CLI/文档展示）"""
    lines = ["审批模式一览："]
    for mode in ApprovalMode:
        info = APPROVAL_MODE_INFO.get(mode.value, {})
        lines.append(f"- {info.get('label', mode.value)}（{mode.value}）")
        lines.append(f"    行为：{info.get('explain', '')}")
        lines.append(f"    风险：{info.get('risk', '')}")
    return chr(10).join(lines)

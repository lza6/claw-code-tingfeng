"""Hook Enums — Hook 类型枚举定义（借鉴 Onyx hooks/enums + oh-my-codex HookEventName）

设计目标:
    1. 类型安全的 Hook 点定义
    2. 启动时校验确保所有 Hook 点都有注册
    3. 作为现有 hooks.py 的补充（不替换）
    4. 支持 20+ 事件类型，对齐 oh-my-codex 的 HookEventName

参考:
    - Onyx 的 HookPoint 枚举设计
    - oh-my-codex-main/src/hooks/extensibility/types.ts HookEventName (20+ events)
"""
from __future__ import annotations

from enum import Enum, auto


class HookPoint(str, Enum):
    """Hook 执行点枚举

    定义系统中所有可扩展的 Hook 位置。
    每个 HookPoint 对应一个 HookPointSpec。

    参考 Onyx HookPoint 和 oh-my-codex HookEventName 设计。
    已扩展至 20+ 事件类型。
    """
    # ========== Session 生命周期 (对标 OMX) ==========
    SESSION_START = auto()
    SESSION_END = auto()
    TURN_COMPLETE = auto()  # 对话轮次完成

    # ========== Agent 生命周期 ==========
    AGENT_START = auto()
    AGENT_END = auto()

    # ========== LLM 调用 ==========
    PRE_LLM_CALL = auto()
    POST_LLM_CALL = auto()
    LLM_ERROR = auto()  # [NEW] LLM 调用失败

    # ========== Tool 调用 (参考 OMX PreToolUse/PostToolUse) ==========
    PRE_TOOL_USE = auto()
    POST_TOOL_USE = auto()
    TOOL_ERROR = auto()  # [NEW] 工具执行异常

    # ========== 消息处理 ==========
    PRE_MESSAGE_SEND = auto()
    POST_MESSAGE_SEND = auto()

    # ========== 任务/工作流 (对标 OMX) ==========
    TASK_CREATED = auto()
    TASK_ASSIGNED = auto()
    TASK_STARTED = auto()
    TASK_COMPLETE = auto()
    TASK_FAILED = auto()
    TASK_RETRY = auto()

    # ========== Pipeline (对标 OMX) ==========
    PIPELINE_START = auto()
    PIPELINE_STAGE_START = auto()
    PIPELINE_STAGE_COMPLETE = auto()
    PIPELINE_STAGE_FAILED = auto()
    PIPELINE_COMPLETE = auto()
    PIPELINE_RESUMED = auto()

    # ========== 团队协作 (对标 OMX) ==========
    WORKER_JOINED = auto()
    WORKER_LEFT = auto()
    TEAM_DISPATCH = auto()
    TEAM_RESULT = auto()

    # ========== 审计/审查 (对标 OMX) ==========
    AUDIT_REQUEST = auto()
    AUDIT_RESULT = auto()
    REVIEW_REQUEST = auto()
    REVIEW_RESULT = auto()

    # ========== 自我修复 ==========
    ERROR_DETECTED = auto()
    ERROR_DIAGNOSED = auto()
    FIX_APPLIED = auto()
    HEAL_COMPLETE = auto()
    HEAL_FAILED = auto()

    # ========== 文件操作 ==========
    PRE_FILE_WRITE = auto()
    POST_FILE_WRITE = auto()
    PRE_FILE_READ = auto()
    POST_FILE_READ = auto()

    # ========== 通知系统 (对标 OMX) ==========
    NOTIFICATION_SENT = auto()
    NOTIFICATION_FAILED = auto()

    # ========== 阻塞/用户交互 (对标 OMX) ==========
    BLOCKED = auto()  # 需要用户介入
    USER_RESPONDED = auto()

    # ========== 性能/资源 (对标 OMX) ==========
    BUDGET_EXCEEDED = auto()
    RESOURCE_WARNING = auto()


class HookResult(str, Enum):
    """Hook 执行结果枚举"""
    CONTINUE = "continue"
    DENY = "deny"
    WARN = "warn"
    MODIFY = "modify"  # Hook 修改了输入数据


__all__ = [
    "HookPoint",
    "HookResult",
]

"""Hook Enums — Hook 类型枚举定义（借鉴 Onyx hooks/enums）

设计目标:
    1. 类型安全的 Hook 点定义
    2. 启动时校验确保所有 Hook 点都有注册
    3. 作为现有 hooks.py 的补充（不替换）

参考 Onyx 的 HookPoint 枚举设计。
"""
from __future__ import annotations

from enum import Enum, auto


class HookPoint(str, Enum):
    """Hook 执行点枚举

    定义系统中所有可扩展的 Hook 位置。
    每个 HookPoint 对应一个 HookPointSpec。

    参考 Onyx HookPoint 枚举设计。
    """
    # Agent 生命周期
    AGENT_START = auto()
    AGENT_END = auto()
    TOOL_CALL_START = auto()
    TOOL_CALL_END = auto()

    # 消息处理
    PRE_LLM_CALL = auto()
    POST_LLM_CALL = auto()
    PRE_MESSAGE_SEND = auto()

    # 自我修复
    ERROR_DETECTED = auto()
    ERROR_DIAGNOSED = auto()
    FIX_APPLIED = auto()

    # Swarm
    TASK_DISPATCH = auto()
    TASK_COMPLETE = auto()

    # Session
    SESSION_START = auto()
    SESSION_END = auto()

    # 文件操作
    PRE_FILE_WRITE = auto()
    POST_FILE_WRITE = auto()


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

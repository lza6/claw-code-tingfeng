"""Agent Modes — 单 Agent 模式切换（移植自 Aider Coder 模式系统）

Aider 通过 edit_format 参数让同一个 Coder 类切换不同行为模式:
- architect: 先分析需要修改哪些文件，确认后再编辑
- context: 自动定位涉及的文件
- ask: 只回答问题不编辑代码

Clawd Code 的实现:
- ArchitectMode: 分析模式，LLM 只输出修改计划不执行
- ContextMode: 文件定位模式，自动识别相关文件
- AskMode: 纯问答模式，禁止文件修改

新增（从 Aider 移植）:
- SwitchCoder: 异常驱动的模式切换机制
- AgentMode: 模式枚举
"""
from .architect import ArchitectMode
from .ask import AskMode
from .context import ContextMode
from .switcher import (
    AgentMode,
    SwitchCoder,
    switch_mode,
    switch_to_architect,
    switch_to_ask,
    switch_to_context,
    switch_to_default,
    switch_to_yolo,
)

__all__ = [
    "AgentMode",
    "ArchitectMode",
    "AskMode",
    "ContextMode",
    # SwitchCoder（从 Aider 移植）
    "SwitchCoder",
    "switch_mode",
    "switch_to_architect",
    "switch_to_ask",
    "switch_to_context",
    "switch_to_default",
    "switch_to_yolo",
]

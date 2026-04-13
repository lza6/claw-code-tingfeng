"""SwitchCoder — 异常驱动的 Agent 模式切换（从 Aider 移植）

Aider 使用 SwitchCoder 异常来优雅地切换不同的 Coder 模式。
这种设计允许在任何地方触发模式切换，无需传递状态。

使用:
def cmd_architect_mode(self, args):
    raise SwitchCoder(edit_format="architect")

# 主循环捕获
try:
    agent.run()
except SwitchCoder as switch:
    agent = create_agent(mode=switch.mode, **switch.kwargs)
    agent.run()

支持的切换:
- architect: 架构师模式，先分析后编辑
- ask: 问答模式，不修改文件
- context: 上下文模式，自动定位文件
- default: 默认编辑模式
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AgentMode(str, Enum):
    """Agent 工作模式"""

    DEFAULT = "default"  # 默认编辑模式
    ARCHITECT = "architect"  # 架构师模式：先分析，后编辑
    ASK = "ask"  # 问答模式：只回答问题，不修改文件
    CONTEXT = "context"  # 上下文模式：自动定位相关文件
    YOLO = "yolo"  # 自动模式：无需确认


@dataclass
class SwitchCoder(Exception):
    """Agent 模式切换异常

    通过抛出此异常来请求切换 Agent 工作模式。
    主循环捕获此异常后创建新的 Agent 实例。

    属性:
        mode: 目标模式
        kwargs: 传递给新 Agent 的额外参数

    示例:
        # 切换到架构师模式
        raise SwitchCoder(mode=AgentMode.ARCHITECT)

        # 切换到问答模式并保留历史
        raise SwitchCoder(mode=AgentMode.ASK, keep_history=True)
    """

    mode: AgentMode = AgentMode.DEFAULT
    kwargs: dict[str, Any] | None = None

    def __init__(
        self,
        mode: AgentMode | str = AgentMode.DEFAULT,
        **kwargs: Any,
    ) -> None:
        """初始化模式切换请求

        参数:
            mode: 目标模式（AgentMode 枚举或字符串）
            **kwargs: 传递给新 Agent 的参数
        """
        if isinstance(mode, str):
            mode = AgentMode(mode)
        self.mode = mode
        self.kwargs = kwargs
        super().__init__(f"Switch to {mode.value} mode")

    def get_kwargs(self) -> dict[str, Any]:
        """获取切换参数

        返回:
            包含 mode 和其他参数的字典
        """
        result = {"mode": self.mode}
        if self.kwargs:
            result.update(self.kwargs)
        return result


def switch_to_architect(**kwargs: Any) -> SwitchCoder:
    """切换到架构师模式

    架构师模式会先分析需要修改的文件，确认后再执行编辑。

    参数:
        **kwargs: 传递给新 Agent 的参数

    返回:
        SwitchCoder 异常实例
    """
    return SwitchCoder(mode=AgentMode.ARCHITECT, **kwargs)


def switch_to_ask(**kwargs: Any) -> SwitchCoder:
    """切换到问答模式

    问答模式只回答问题，不会修改任何文件。

    参数:
        **kwargs: 传递给新 Agent 的参数

    返回:
        SwitchCoder 异常实例
    """
    return SwitchCoder(mode=AgentMode.ASK, **kwargs)


def switch_to_context(**kwargs: Any) -> SwitchCoder:
    """切换到上下文模式

    上下文模式会自动定位和添加相关文件到上下文。

    参数:
        **kwargs: 传递给新 Agent 的参数

    返回:
        SwitchCoder 异常实例
    """
    return SwitchCoder(mode=AgentMode.CONTEXT, **kwargs)


def switch_to_default(**kwargs: Any) -> SwitchCoder:
    """切换到默认编辑模式

    参数:
        **kwargs: 传递给新 Agent 的参数

    返回:
        SwitchCoder 异常实例
    """
    return SwitchCoder(mode=AgentMode.DEFAULT, **kwargs)


def switch_to_yolo(**kwargs: Any) -> SwitchCoder:
    """切换到自动模式

    自动模式跳过所有确认，自动执行所有操作。

    参数:
        **kwargs: 传递给新 Agent 的参数

    返回:
        SwitchCoder 异常实例
    """
    return SwitchCoder(mode=AgentMode.YOLO, **kwargs)


# 便捷别名
switch_mode = SwitchCoder

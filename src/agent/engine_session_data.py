"""代理会话数据模型

从 engine.py 拆分出来 (v0.20.0)，
包含 AgentStep 和 AgentSession 数据类，
避免 engine.py 过于臃肿。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentStep:
    """代理执行步骤"""
    step_type: str  # plan | execute | verify | report | llm
    action: str
    result: str
    success: bool


@dataclass
class AgentSession:
    """代理会话

    属性:
        goal: 任务目标
        steps: 执行步骤历史
        context: 附加上下文字典
        total_tokens: 累计 token 消耗
        is_complete: 会话是否已完成
        final_result: 最终结果文本
    """
    goal: str
    steps: list[AgentStep] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    total_tokens: int = 0
    is_complete: bool = False
    final_result: str = ''

    def add_step(self, step: AgentStep) -> None:
        """添加执行步骤"""
        self.steps.append(step)

    def mark_complete(self, result: str, success: bool = True) -> None:
        """标记会话完成

        参数:
            result: 最终结果
            success: 是否成功
        """
        self.is_complete = True
        self.final_result = result
        if not success:
            self.context['error'] = result

    @property
    def step_count(self) -> int:
        """获取步骤数量"""
        return len(self.steps)

    @property
    def last_step(self) -> AgentStep | None:
        """获取最后一个步骤"""
        return self.steps[-1] if self.steps else None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于序列化/事件发布）"""
        return {
            'goal': self.goal,
            'is_complete': self.is_complete,
            'total_tokens': self.total_tokens,
            'step_count': self.step_count,
            'final_result': self.final_result[:500] if self.final_result else '',
        }

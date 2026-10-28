"""Eval 数据模型"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class EvalCase:
    """单条评测用例

    Attributes:
        case_id: 用例唯一 ID
        input: 交给 agent 的输入
        expect: 断言规格，支持任意组合：
            - equals: 输出必须完全等于该字符串
            - contains: 输出必须包含全部子串（list[str]）
            - not_contains: 输出不得包含任一子串（list[str]）
            - regex: 输出必须匹配该正则
            - tool_sequence: 工具调用序列必须完全一致（list[str]）
        recorded: 录制的执行结果 {"output": str, "tools": list[str]}，replay 模式使用
        tags: 分类标签
    """

    case_id: str
    input: str
    expect: dict[str, Any] = field(default_factory=dict)
    recorded: dict[str, Any] | None = None
    tags: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        """返回校验错误列表（空列表 = 合法）"""
        errors: list[str] = []
        if not self.case_id:
            errors.append("case_id 不能为空")
        if not isinstance(self.expect, dict):
            errors.append(f"{self.case_id}: expect 必须是对象")
            return errors
        if not self.expect:
            errors.append(f"{self.case_id}: expect 不能为空（否则用例无意义）")
        known = {"equals", "contains", "not_contains", "regex", "tool_sequence"}
        unknown = set(self.expect) - known
        if unknown:
            errors.append(f"{self.case_id}: 未知断言类型 {sorted(unknown)}")
        for key in ("contains", "not_contains", "tool_sequence"):
            value = self.expect.get(key)
            if value is not None and not isinstance(value, list):
                errors.append(f"{self.case_id}: {key} 必须是列表")
        return errors


@dataclass
class EvalOutcome:
    """单条用例的执行结果"""

    case_id: str
    passed: bool
    detail: str
    elapsed_ms: float = 0.0
    tags: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    """一次评测的汇总结果"""

    outcomes: list[EvalOutcome] = field(default_factory=list)
    generated_at: str = ""
    mode: str = "replay"
    dataset: str = ""

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def failures(self) -> list[EvalOutcome]:
        return [o for o in self.outcomes if not o.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at or datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
            "dataset": self.dataset,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 4),
            "outcomes": [
                {
                    "case_id": o.case_id,
                    "passed": o.passed,
                    "detail": o.detail,
                    "elapsed_ms": round(o.elapsed_ms, 2),
                    "tags": o.tags,
                }
                for o in self.outcomes
            ],
        }

    def summary_line(self) -> str:
        return (
            f"eval[{self.mode}] {self.passed}/{self.total} passed "
            f"({self.pass_rate * 100:.1f}%)"
        )

"""Intent Routing - 意图路由系统

从 GoalX 汲取的核心设计:
- 支持多种执行意图: DELIVER, EXPLORE, EVOLVE, DEBATE, IMPLEMENT
- 每种意图对应不同的 agent 行为模式
- 意图影响任务分解、验证策略和完成标准
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    """执行意图枚举"""
    DELIVER = "deliver"    # 默认: 交付结果
    EXPLORE = "explore"    # 探索: 证据优先调查
    EVOLVE = "evolve"      # 演进: 持续改进直到预算耗尽
    DEBATE = "debate"      # 辩论: 挑战和精炼已有发现
    IMPLEMENT = "implement" # 实现: 基于已有证据构建


@dataclass
class IntentConfig:
    """意图配置"""
    intent: Intent
    description: str
    guidance: str

    # 行为参数
    max_iterations: int = 10
    evidence_required: bool = True
    allow_parallel: bool = True
    budget_hours: float | None = None

    # 验证策略
    verification_style: str = "default"  # default, evidence_first, lenient, strict

    # 输出期望
    output_type: str = "result"  # result, report, exploration, improvement


# 意图配置库 (从 goalx dimensions.go 风格汲取)
INTENT_CONFIGS: dict[Intent, IntentConfig] = {
    Intent.DELIVER: IntentConfig(
        intent=Intent.DELIVER,
        description="默认的交付结果路径",
        guidance="专注于交付可验证的最终结果。确保所有 obligations 都有证据支持。",
        max_iterations=10,
        evidence_required=True,
        allow_parallel=True,
        verification_style="strict",
        output_type="result",
    ),

    Intent.EXPLORE: IntentConfig(
        intent=Intent.EXPLORE,
        description="证据优先的探索调查",
        guidance="深入调查，收集证据。不急于结论，确保每个发现都有可验证的证据支持。",
        max_iterations=5,
        evidence_required=True,
        allow_parallel=False,
        verification_style="evidence_first",
        output_type="exploration",
    ),

    Intent.EVOLVE: IntentConfig(
        intent=Intent.EVOLVE,
        description="持续迭代改进直到预算耗尽",
        guidance="不断寻找下一个最佳改进点。评估每个改进的价值/成本比，优先高价值低成本的改进。",
        max_iterations=100,  # 持续到预算耗尽
        evidence_required=False,
        allow_parallel=True,
        budget_hours=8.0,  # 默认 8 小时预算
        verification_style="lenient",
        output_type="improvement",
    ),

    Intent.DEBATE: IntentConfig(
        intent=Intent.DEBATE,
        description="挑战和精炼已有发现",
        guidance="从批判性角度审视已有结论。寻找弱点，验证假设，确保结论经得起挑战。",
        max_iterations=3,
        evidence_required=True,
        allow_parallel=False,
        verification_style="strict",
        output_type="report",
    ),

    Intent.IMPLEMENT: IntentConfig(
        intent=Intent.IMPLEMENT,
        description="基于已有证据的实现",
        guidance="根据之前探索或辩论的结论进行实现。遵循已确定的方案，不重新质疑。",
        max_iterations=15,
        evidence_required=True,
        allow_parallel=True,
        verification_style="default",
        output_type="result",
    ),
}


class IntentRouter:
    """意图路由器"""

    def __init__(self):
        self._configs = INTENT_CONFIGS.copy()

    def get_config(self, intent: Intent) -> IntentConfig:
        """获取意图配置"""
        return self._configs.get(intent, INTENT_CONFIGS[Intent.DELIVER])

    def resolve(self, intent: Intent | str) -> Intent:
        """解析意图字符串为 Intent 枚举"""
        if isinstance(intent, Intent):
            return intent

        intent_lower = intent.lower().strip()
        for i in Intent:
            if i.value == intent_lower:
                return i

        # 默认返回 DELIVER
        return Intent.DELIVER

    def get_guidance(self, intent: Intent) -> str:
        """获取意图指导"""
        return self.get_config(intent).guidance

    def register_custom(self, config: IntentConfig) -> None:
        """注册自定义意图配置"""
        self._configs[config.intent] = config

    def list_intents(self) -> list[IntentConfig]:
        """列出所有可用意图"""
        return list(self._configs.values())


# 全局路由器实例
_router: IntentRouter | None = None


def get_router() -> IntentRouter:
    """获取全局路由器实例"""
    global _router
    if _router is None:
        _router = IntentRouter()
    return _router


def resolve_intent(intent: Intent | str) -> Intent:
    """快速解析意图"""
    return get_router().resolve(intent)


def get_intent_guidance(intent: Intent | str) -> str:
    """快速获取意图指导"""
    return get_router().get_guidance(resolve_intent(intent))

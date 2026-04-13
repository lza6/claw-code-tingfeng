"""
Dimension System — 维度化引导系统 (借鉴 Project B/GoalX)

定义了不同的 session 引导维度，用于在不同场景下精确控制 LLM 的思考偏好。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResolvedDimension:
    """已解析的维度 (不可变对象)"""
    name: str
    guidance: str
    source: str = "builtin"
    weight: float = 1.0  # 维度权重，用于合并冲突


# 内置维度目录 (从 GoalX 汲取并汉化)
BUILTIN_DIMENSIONS = {
    "depth": "深度 (Depth): 挑选一个最具影响力的领域并尽可能深入。端到端地追踪代码路径。优先选择一个经过彻底验证的发现，而不是五个浅显的发现。",
    "breadth": "广度 (Breadth): 扫描所有维度以建立完整的地图。覆盖每个主要组件。寻找盲点和意想不到的连接。",
    "creative": "创意 (Creative): 跳出常规思维。提出非显而易见的解决方案。挑战关于可能性的假设。寻找优雅的简化方案。",
    "feasibility": "可行性 (Feasibility): 对于每个提议，评估实现成本、风险、依赖关系和时间表。将简单的胜利与沉重的负担区分开来。明确具体的工作量。",
    "perfectionist": "完美主义者 (Perfectionist): 对每个主张都要求铁证。引用确切的代码参考。宁要少量的高质量发现，不要大量的浅显发现。提交前重新阅读。深度优于广度。任何变更必须有对应的测试验证。",
    "adversarial": "对抗性 (Adversarial): 你的工作是寻找问题。寻找错误、设计缺陷、极端情况和错误的假设。如果某件事看起来没问题，那就再努力去打破它。特别关注竞态条件、边界溢出和逻辑漏洞。",
    "security": "安全专家 (Security): 专注于 OWASP Top 10 风险。检查输入净化、认证绕过、敏感数据泄露和权限提升。对涉及网络或文件操作的代码路径保持极度警惕。",
    "maintainability": "可维护性 (Maintainability): 优先考虑代码的可读性和长期健康。避免过度设计，但要确保足够的抽象。遵循 DRY 原则，减少圈复杂度。",
    "comparative": "比较 (Comparative): 与行业最佳实践、类似项目和成熟模式进行比较。确定偏离之处是故意的优势还是偶然的弱点。",
    "user": "用户视角 (User): 从终端用户的角度思考。体验如何？什么地方令人困惑？缺少什么？关注易用性和开发者体验。",
}


def resolve_dimension_specs(names: list[str], custom: dict[str, str] | None = None) -> list[ResolvedDimension]:
    """
    解析维度规格。支持内置名称或 'name=guidance' 格式。
    """
    catalog = BUILTIN_DIMENSIONS.copy()
    if custom:
        catalog.update(custom)

    resolved = []
    for raw in names:
        raw = raw.strip()
        if not raw:
            continue

        if "=" in raw:
            name, guidance = raw.split("=", 1)
            resolved.append(ResolvedDimension(
                name=name.strip(),
                guidance=guidance.strip(),
                source="inline"
            ))
            continue

        if raw in catalog:
            resolved.append(ResolvedDimension(
                name=raw,
                guidance=catalog[raw],
                source="builtin" if raw in BUILTIN_DIMENSIONS else "config"
            ))
        else:
            # 记录未知维度，但不报错，回退到原始名称
            resolved.append(ResolvedDimension(
                name=raw,
                guidance=f"关注维度: {raw}",
                source="unknown"
            ))

    return resolved

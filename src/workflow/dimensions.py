"""Dimension System - 维度指导系统 (从 GoalX dimensions.go 汲取)

为 Session 提供多维度的执行指导:
- Depth: 深度优先，影响关键区域
- Breadth: 广度优先，建立完整地图
- Creative: 创新思维，挑战假设
- Adversarial: 对抗思维，寻找缺陷
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import Any


class DimensionType(str, Enum):
    """维度类型枚举"""
    DEPTH = "depth"               # 深度: 针对单一区域进行深度调查
    BREADTH = "breadth"           # 广度: 扫描所有维度，建立完整地图
    CREATIVE = "creative"         # 创新: 跳出常规思维，寻找优雅简化
    FEASIBILITY = "feasibility"   # 可行性: 评估实施成本、风险和依赖
    ADVERSARIAL = "adversarial"   # 对抗: 寻找 Bug、缺陷和错误假设
    AUDIT = "audit"               # 审计: 系统性审查正确性、回归和安全性
    EVIDENCE = "evidence"         # 证据: 量化一切，不凭感觉说话
    PERFECTIONIST = "perfectionist" # 完美主义: 要求铁证，深度重读
    COMPARATIVE = "comparative"   # 对比: 与行业最佳实践和模式对比
    USER = "user"                 # 用户: 从终端用户角度思考体验


@dataclass
class Dimension:
    """维度定义"""
    name: str
    guidance: str
    source: str = "builtin"  # builtin, config, inline


# 内置维度库 (从 goalx dimensions.go 汲取)
BUILTIN_DIMENSIONS: dict[DimensionType, str] = {
    DimensionType.DEPTH: "Depth: Pick the single most impactful area and go as deep as possible. Trace code paths end-to-end. Prefer one thoroughly verified finding over five shallow ones.",
    DimensionType.BREADTH: "Breadth: Scan all dimensions to build a complete map. Cover every major component. Find blind spots and unexpected connections.",
    DimensionType.CREATIVE: "Creative: Think beyond conventional approaches. Propose non-obvious solutions. Challenge assumptions about what's possible. Look for elegant simplifications.",
    DimensionType.FEASIBILITY: "Feasibility: For every proposal, assess implementation cost, risk, dependencies, and timeline. Separate easy wins from heavy lifts. Be concrete about effort.",
    DimensionType.ADVERSARIAL: "Adversarial: Your job is to find problems. Look for bugs, design flaws, edge cases, and incorrect assumptions. If something looks fine, try harder to break it.",
    DimensionType.AUDIT: "Audit: Conduct a systematic review of correctness, regressions, safety, operational impact, and documentation consistency. Treat the whole change as a production system, not just a code diff.",
    DimensionType.EVIDENCE: "Evidence: Quantify everything. Run benchmarks, measure build times, count lines/functions/dependencies, check test coverage. No opinions without data.",
    DimensionType.PERFECTIONIST: "Perfectionist: Demand ironclad evidence for every claim. Cite exact code references. Prefer fewer high-quality findings over many shallow ones. Re-read before commit. Depth over breadth.",
    DimensionType.COMPARATIVE: "Comparative: Compare with industry best practices, similar projects, and established patterns. Identify where deviations are intentional strengths or accidental weaknesses.",
    DimensionType.USER: "User perspective: Think from the end user's point of view. What's the experience like? What's confusing? What's missing? Focus on usability and developer ergonomics.",
}


class DimensionRegistry:
    """维度注册表"""

    def __init__(self):
        self._dimensions: dict[str, Dimension] = {}
        # 初始化内置维度
        for dtype, guidance in BUILTIN_DIMENSIONS.items():
            self._dimensions[dtype.value] = Dimension(
                name=dtype.value,
                guidance=guidance,
                source="builtin"
            )

    def resolve(self, specs: list[str]) -> list[Dimension]:
        """解析维度规格

        支持格式:
        - "name": 解析内置或注册的维度
        - "name=guidance": 创建内联维度
        """
        resolved = []
        for spec in specs:
            if "=" in spec:
                name, guidance = spec.split("=", 1)
                resolved.append(Dimension(
                    name=name.strip(),
                    guidance=guidance.strip(),
                    source="inline"
                ))
            else:
                name = spec.strip()
                if name in self._dimensions:
                    resolved.append(self._dimensions[name])
                else:
                    # 容错: 如果未找到且没有 guidance，创建一个默认的
                    resolved.append(Dimension(
                        name=name,
                        guidance=f"Dimension {name}: Follow specialized guidance for this context.",
                        source="unknown"
                    ))
        return resolved

    def get_guidance_prompt(self, specs: list[str]) -> str:
        """获取维度的提示词"""
        resolved = self.resolve(specs)
        if not resolved:
            return ""

        prompt = "## Dimension Guidance\n\n"
        for d in resolved:
            prompt += f"- **{d.name.capitalize()}**: {d.guidance}\n"
        return prompt


# 全局注册表实例
_registry: DimensionRegistry | None = None


def get_dimension_registry() -> DimensionRegistry:
    """获取全局注册表实例"""
    global _registry
    if _registry is None:
        _registry = DimensionRegistry()
    return _registry


def resolve_dimensions(specs: list[str]) -> list[Dimension]:
    """快速解析维度"""
    return get_dimension_registry().resolve(specs)


def get_dimensions_prompt(specs: list[str]) -> str:
    """快速获取维度提示词"""
    return get_dimension_registry().get_guidance_prompt(specs)

"""查价优先级：自有表 → litellm 内置 → 默认价

背景（P2-2）：自有 `MODEL_PRICING` 是手写快照，`PRICING_VERSION` 写死后已过期 172 天，
每条 CLI 都警告，成本护栏还按旧价估算。修法是：自有表仍然优先（可放自有报价），
表里没有的模型去 litellm 内置的 4500+ 模型价格里找（随包升级而更新），再兜底默认价。
"""

from __future__ import annotations

import pytest

from src.core.cost_estimator.cost_estimator import (
    DEFAULT_PRICING,
    MODEL_PRICING,
    get_model_pricing,
    resolve_pricing,
)


def _model_only_in_litellm() -> str | None:
    """找一个"自有表没有、但 litellm 有价格"的模型（不写死名字，跟随 litellm 升级）"""
    try:
        from litellm import model_cost
    except Exception:  # pragma: no cover
        return None
    for name, info in model_cost.items():
        if name in MODEL_PRICING or not isinstance(info, dict):
            continue
        if info.get("input_cost_per_token") and info.get("output_cost_per_token"):
            return name
    return None


class TestOwnTableWins:
    def test_known_model_uses_own_table(self):
        pricing = resolve_pricing("gpt-4o")
        own = MODEL_PRICING["gpt-4o"]
        assert pricing.input_price == own.input_price
        assert pricing.output_price == own.output_price

    def test_get_model_pricing_uses_same_priority(self):
        a = get_model_pricing("gpt-4o")
        b = resolve_pricing("gpt-4o")
        assert (a.input_price, a.output_price) == (b.input_price, b.output_price)


class TestLitellmFallback:
    def test_model_missing_from_own_table_gets_litellm_price(self):
        name = _model_only_in_litellm()
        if not name:
            pytest.skip("当前 litellm 版本里找不到（自有表缺、litellm 有价）的模型")

        pricing = resolve_pricing(name)

        assert pricing is not DEFAULT_PRICING, f"{name} 不该退回默认价（litellm 有价）"
        assert pricing.input_price > 0 and pricing.output_price > 0, pricing

    def test_provider_prefix_is_normalized(self):
        name = _model_only_in_litellm()
        if not name:
            pytest.skip("当前 litellm 里没有仅它收录的模型")
        bare = resolve_pricing(name)
        prefixed = resolve_pricing("openai/" + name)
        assert (prefixed.input_price, prefixed.output_price) == (bare.input_price, bare.output_price)


class TestDefaultFallback:
    def test_unknown_model_falls_back_to_default(self):
        pricing = resolve_pricing("totally-made-up-model-zzz")
        assert pricing is DEFAULT_PRICING
        assert pricing.input_price == DEFAULT_PRICING.input_price

    def test_empty_name_falls_back_to_default(self):
        assert resolve_pricing("") is DEFAULT_PRICING

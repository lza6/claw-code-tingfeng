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


# ==========================================================================
# P3 项 5：兜底缓存写价恒 0
#
# 背景：`_litellm_pricing()` 里 `cache_write_price=0.0` / `reasoning_price=0.0` 是写死的，
# 等于"用了缓存写入就一定不花钱"。而 Anthropic 系的 cache write 比普通输入还贵（1.25x），
# 推理模型的 reasoning token 也单独计价 —— 长期系统性低估成本。
# 现在按 litellm `model_cost` 的真实字段映射；**缺字段就留 0.0**（不知道就不编）。
# ==========================================================================


def _patch_model_cost(monkeypatch, record: dict) -> str:
    """伪造 litellm.model_cost 里的一条价格记录（不依赖真实网络/真实型号）"""
    import litellm

    name = "fake-model-for-pricing-test"
    monkeypatch.setattr(litellm, "model_cost", {name: record}, raising=True)
    return name


class TestCacheWriteAndReasoningPricing:
    def test_cache_write_price_comes_from_cache_creation_field(self, monkeypatch):
        name = _patch_model_cost(monkeypatch, {
            "input_cost_per_token": 3e-6,
            "output_cost_per_token": 15e-6,
            "cache_read_input_token_cost": 0.3e-6,
            "cache_creation_input_token_cost": 3.75e-6,
        })

        pricing = resolve_pricing(name)

        assert pricing.cache_write_price == pytest.approx(3.75), pricing
        assert pricing.cache_read_price == pytest.approx(0.3), pricing
        assert pricing.input_price == pytest.approx(3.0), pricing

    def test_reasoning_price_comes_from_reasoning_token_field(self, monkeypatch):
        name = _patch_model_cost(monkeypatch, {
            "input_cost_per_token": 2e-6,
            "output_cost_per_token": 8e-6,
            "output_cost_per_reasoning_token": 12e-6,
        })

        pricing = resolve_pricing(name)

        assert pricing.reasoning_price == pytest.approx(12.0), pricing

    def test_missing_fields_stay_zero(self, monkeypatch):
        """litellm 记录里没有这两个字段 → 该项不单独计价，保持 0.0（不是猜一个数）"""
        name = _patch_model_cost(monkeypatch, {
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 2e-6,
        })

        pricing = resolve_pricing(name)

        assert pricing.cache_write_price == 0.0, pricing
        assert pricing.reasoning_price == 0.0, pricing

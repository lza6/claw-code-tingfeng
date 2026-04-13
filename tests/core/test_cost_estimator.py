"""成本估算模块测试"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.cost_estimator.cost_estimator import (
    CostEstimator,
    ModelPricing,
    check_pricing_freshness,
    estimate_cost,
)


class TestModelPricing:
    """ModelPricing 数据类测试"""

    def test_default_values(self):
        """测试默认值"""
        pricing = ModelPricing(input_price=1.0, output_price=2.0)
        assert pricing.currency == 'USD'
        assert pricing.cache_read_price == 0.0
        assert pricing.cache_write_price == 0.0
        assert pricing.reasoning_price == 0.0

    def test_full_pricing(self):
        """测试完整定价"""
        pricing = ModelPricing(
            input_price=2.50,
            output_price=10.00,
            cache_read_price=1.25,
            cache_write_price=2.50,
            reasoning_price=60.00,
        )
        assert pricing.input_price == 2.50
        assert pricing.output_price == 10.00
        assert pricing.cache_read_price == 1.25
        assert pricing.cache_write_price == 2.50
        assert pricing.reasoning_price == 60.00


class TestCostEstimator:
    """CostEstimator 核心测试"""

    def setup_method(self):
        """每个测试前重置"""
        self.estimator = CostEstimator()

    def test_record_call_basic(self):
        """测试基础调用记录"""
        cost = self.estimator.record_call(
            model='gpt-4o',
            input_tokens=1000,
            output_tokens=500,
        )
        assert cost > 0
        assert self.estimator.get_total_cost() == cost

    def test_record_call_with_label(self):
        """测试带标签的调用"""
        cost = self.estimator.record_call(
            model='gpt-4o',
            input_tokens=1000,
            output_tokens=500,
            label='test_call',
        )
        assert cost > 0

    def test_record_call_unknown_model(self):
        """测试未知模型使用默认定价"""
        cost = self.estimator.record_call(
            model='unknown_model',
            input_tokens=1000,
            output_tokens=500,
        )
        # 默认定价: input=1.0/1M, output=3.0/1M
        expected = (1000 / 1_000_000) * 1.0 + (500 / 1_000_000) * 3.0
        assert abs(cost - expected) < 0.0001

    def test_record_call_with_cache_tokens(self):
        """测试带缓存 tokens 的调用"""
        cost = self.estimator.record_call(
            model='gpt-4o',
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=2000,
            cache_write_tokens=1000,
        )
        assert cost > 0

    def test_record_call_with_reasoning_tokens(self):
        """测试带推理 tokens 的调用"""
        cost = self.estimator.record_call(
            model='o1',
            input_tokens=1000,
            output_tokens=500,
            reasoning_tokens=3000,
        )
        assert cost > 0

    def test_record_call_no_reasoning_price(self):
        """测试无推理定价时回退到输出价格"""
        cost = self.estimator.record_call(
            model='gpt-4o',  # 无推理定价
            input_tokens=1000,
            output_tokens=500,
            reasoning_tokens=1000,
        )
        # 推理 tokens 应按输出价格计算
        assert cost > 0

    def test_multiple_calls(self):
        """测试多次调用累计"""
        self.estimator.record_call(model='gpt-4o', input_tokens=1000, output_tokens=500)
        self.estimator.record_call(model='gpt-4o', input_tokens=2000, output_tokens=1000)
        assert self.estimator._total_input_tokens == 3000
        assert self.estimator._total_output_tokens == 1500

    def test_max_call_history(self):
        """测试调用历史限制"""
        estimator = CostEstimator(max_call_history=3)
        for i in range(5):
            estimator.record_call(model='gpt-4o', input_tokens=100, output_tokens=50)
        assert len(estimator._calls) == 3

    def test_get_total_cost(self):
        """测试获取总成本"""
        self.estimator.record_call(model='gpt-4o', input_tokens=1000, output_tokens=500)
        self.estimator.record_call(model='gpt-4o', input_tokens=2000, output_tokens=1000)
        total = self.estimator.get_total_cost()
        assert total > 0

    def test_get_summary(self):
        """测试获取摘要"""
        self.estimator.record_call(model='gpt-4o', input_tokens=1000, output_tokens=500)
        summary = self.estimator.get_summary()
        assert 'total_cost_usd' in summary
        assert 'call_count' in summary
        assert summary['call_count'] == 1

    def test_get_summary_with_cache_tokens(self):
        """测试带缓存 tokens 的摘要"""
        self.estimator.record_call(
            model='gpt-4o',
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=2000,
        )
        summary = self.estimator.get_summary()
        assert 'total_cache_read_tokens' in summary

    def test_get_summary_with_reasoning_tokens(self):
        """测试带推理 tokens 的摘要"""
        self.estimator.record_call(
            model='o1',
            input_tokens=1000,
            output_tokens=500,
            reasoning_tokens=3000,
        )
        summary = self.estimator.get_summary()
        assert 'total_reasoning_tokens' in summary

    def test_get_report_no_calls(self):
        """测试无调用时的报告"""
        report = self.estimator.get_report()
        assert '暂无调用记录' in report

    def test_get_report_with_calls(self):
        """测试有调用时的报告"""
        self.estimator.record_call(model='gpt-4o', input_tokens=1000, output_tokens=500)
        report = self.estimator.get_report()
        assert '总成本' in report
        assert 'gpt-4o' in report

    def test_get_report_model_grouping(self):
        """测试报告按模型分组"""
        self.estimator.record_call(model='gpt-4o', input_tokens=1000, output_tokens=500)
        self.estimator.record_call(model='claude-3-5-sonnet-20241022', input_tokens=1000, output_tokens=500)
        report = self.estimator.get_report()
        assert 'gpt-4o' in report
        assert 'claude-3-5-sonnet' in report

    def test_reset(self):
        """测试重置"""
        self.estimator.record_call(model='gpt-4o', input_tokens=1000, output_tokens=500)
        self.estimator.reset()
        assert self.estimator.get_total_cost() == 0.0
        assert self.estimator._total_input_tokens == 0
        assert self.estimator._total_output_tokens == 0
        assert len(self.estimator._calls) == 0


class TestEstimateCost:
    """estimate_cost 便捷函数测试"""

    def test_basic_estimate(self):
        """测试基础估算"""
        cost = estimate_cost(
            model='gpt-4o',
            input_tokens=1000,
            output_tokens=500,
        )
        assert cost > 0

    def test_unknown_model(self):
        """测试未知模型"""
        cost = estimate_cost(
            model='unknown_model',
            input_tokens=1000,
            output_tokens=500,
        )
        # 默认定价
        assert cost > 0

    def test_with_cache(self):
        """测试带缓存"""
        cost = estimate_cost(
            model='gpt-4o',
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=2000,
            cache_write_tokens=1000,
        )
        assert cost > 0

    def test_with_reasoning(self):
        """测试带推理"""
        cost = estimate_cost(
            model='o1',
            input_tokens=1000,
            output_tokens=500,
            reasoning_tokens=3000,
        )
        assert cost > 0

    def test_free_model(self):
        """测试免费模型"""
        cost = estimate_cost(
            model='qwen/qwen3.6-plus-preview:free',
            input_tokens=10000,
            output_tokens=5000,
        )
        assert cost == 0.0


class TestPricingFreshness:
    """定价数据新鲜度测试"""

    def test_fresh_pricing(self):
        """测试新鲜定价"""
        # 直接调用，验证返回结构
        result = check_pricing_freshness()
        assert isinstance(result['is_fresh'], bool)
        assert isinstance(result['days_since_update'], int)
        assert isinstance(result['days_until_expire'], int)

    def test_pricing_returns_required_fields(self):
        """测试返回必需字段"""
        result = check_pricing_freshness()
        assert 'is_fresh' in result
        assert 'days_since_update' in result
        assert 'days_until_expire' in result
        assert 'update_urls' in result

    def test_pricing_has_update_urls(self):
        """测试有更新 URL"""
        result = check_pricing_freshness()
        assert len(result['update_urls']) > 0
        assert any('openai.com' in url for url in result['update_urls'])

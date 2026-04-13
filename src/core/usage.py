"""精确成本追踪系统 — 从 Rust usage.rs 移植

支持4维 token 统计 (input/output/cache_creation/cache_read)，
内置主流模型定价表，自动计算 USD 成本。

配合 UsageTracker 进行会话级累计统计。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ==================== 默认定价（$/百万 token）====================

_DEFAULT_INPUT_COST_PER_MILLION = 15.0
_DEFAULT_OUTPUT_COST_PER_MILLION = 75.0
_DEFAULT_CACHE_CREATION_COST_PER_MILLION = 18.75
_DEFAULT_CACHE_READ_COST_PER_MILLION = 1.5


# ==================== 数据模型 ====================

@dataclass(frozen=True)
class ModelPricing:
    """模型定价"""
    input_cost_per_million: float = _DEFAULT_INPUT_COST_PER_MILLION
    output_cost_per_million: float = _DEFAULT_OUTPUT_COST_PER_MILLION
    cache_creation_cost_per_million: float = _DEFAULT_CACHE_CREATION_COST_PER_MILLION
    cache_read_cost_per_million: float = _DEFAULT_CACHE_READ_COST_PER_MILLION

    def estimate_cost(self, input_tokens: int, output_tokens: int,
                      cache_creation: int = 0, cache_read: int = 0) -> float:
        """估算 USD 成本"""
        cost = 0.0
        cost += (input_tokens / 1_000_000) * self.input_cost_per_million
        cost += (output_tokens / 1_000_000) * self.output_cost_per_million
        cost += (cache_creation / 1_000_000) * self.cache_creation_cost_per_million
        cost += (cache_read / 1_000_000) * self.cache_read_cost_per_million
        return cost


@dataclass
class TokenUsage:
    """单次调用的 token 使用量"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'cache_creation_tokens': self.cache_creation_tokens,
            'cache_read_tokens': self.cache_read_tokens,
            'total_tokens': self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenUsage:
        return cls(
            input_tokens=data.get('input_tokens', data.get('prompt_tokens', 0)),
            output_tokens=data.get('output_tokens', data.get('completion_tokens', 0)),
            cache_creation_tokens=data.get('cache_creation_tokens', 0),
            cache_read_tokens=data.get('cache_read_tokens', 0),
        )

    @classmethod
    def from_api_response(cls, response: dict[str, Any]) -> TokenUsage:
        """从 LLM API 响应中提取 token 使用量"""
        usage_data = response.get('usage', {})
        if isinstance(usage_data, dict):
            return cls.from_dict(usage_data)
        return cls()


@dataclass
class UsageRecord:
    """单次使用记录"""
    model: str
    usage: TokenUsage
    cost_usd: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            'model': self.model,
            'usage': self.usage.to_dict(),
            'cost_usd': self.cost_usd,
            'timestamp': self.timestamp,
        }


@dataclass
class UsageTracker:
    """会话级累计使用量追踪器"""
    records: list[UsageRecord] = field(default_factory=list)
    _total_input: int = 0
    _total_output: int = 0
    _total_cache_creation: int = 0
    _total_cache_read: int = 0
    _total_cost: float = 0.0

    def record(self, model: str, usage: TokenUsage, pricing: ModelPricing | None = None) -> UsageRecord:
        """记录一次使用"""
        if pricing is None:
            pricing = MODEL_PRICING.get(model, ModelPricing())

        cost = pricing.estimate_cost(
            usage.input_tokens, usage.output_tokens,
            usage.cache_creation_tokens, usage.cache_read_tokens,
        )

        record = UsageRecord(model=model, usage=usage, cost_usd=cost)
        self.records.append(record)

        self._total_input += usage.input_tokens
        self._total_output += usage.output_tokens
        self._total_cache_creation += usage.cache_creation_tokens
        self._total_cache_read += usage.cache_read_tokens
        self._total_cost += cost

        return record

    def record_from_response(self, model: str, response: dict[str, Any]) -> UsageRecord:
        """从 API 响应直接记录"""
        usage = TokenUsage.from_api_response(response)
        return self.record(model, usage)

    @property
    def total_input_tokens(self) -> int:
        return self._total_input

    @property
    def total_output_tokens(self) -> int:
        return self._total_output

    @property
    def total_tokens(self) -> int:
        return self._total_input + self._total_output

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost

    @property
    def call_count(self) -> int:
        return len(self.records)

    @property
    def average_cost_per_call(self) -> float:
        return self._total_cost / len(self.records) if self.records else 0.0

    def get_model_breakdown(self) -> dict[str, dict[str, Any]]:
        """按模型分组统计"""
        breakdown: dict[str, dict[str, Any]] = {}
        for record in self.records:
            if record.model not in breakdown:
                breakdown[record.model] = {
                    'calls': 0,
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'cost_usd': 0.0,
                }
            entry = breakdown[record.model]
            entry['calls'] += 1
            entry['input_tokens'] += record.usage.input_tokens
            entry['output_tokens'] += record.usage.output_tokens
            entry['cost_usd'] += record.cost_usd
        return breakdown

    def to_dict(self) -> dict[str, Any]:
        return {
            'total_input_tokens': self._total_input,
            'total_output_tokens': self._total_output,
            'total_tokens': self.total_tokens,
            'total_cost_usd': round(self._total_cost, 6),
            'call_count': self.call_count,
            'average_cost_per_call': round(self.average_cost_per_call, 6),
            'model_breakdown': self.get_model_breakdown(),
        }

    def reset(self) -> None:
        """重置统计"""
        self.records.clear()
        self._total_input = 0
        self._total_output = 0
        self._total_cache_creation = 0
        self._total_cache_read = 0
        self._total_cost = 0.0


# ==================== 内置模型定价表 ====================

MODEL_PRICING: dict[str, ModelPricing] = {
    # Anthropic
    'claude-3-5-sonnet-20241022': ModelPricing(3.0, 15.0, 3.75, 0.30),
    'claude-3-5-haiku-20241022': ModelPricing(0.80, 4.0, 1.0, 0.08),
    'claude-3-opus-20240229': ModelPricing(15.0, 75.0, 18.75, 1.50),
    'claude-3-sonnet-20240229': ModelPricing(3.0, 15.0, 3.75, 0.30),
    'claude-3-haiku-20240307': ModelPricing(0.25, 1.25, 0.30, 0.03),
    'claude-sonnet-4-20250514': ModelPricing(3.0, 15.0, 3.75, 0.30),
    'claude-opus-4-20250514': ModelPricing(15.0, 75.0, 18.75, 1.50),
    # OpenAI
    'gpt-4o': ModelPricing(2.50, 10.0, 1.25, 0.125),
    'gpt-4o-mini': ModelPricing(0.15, 0.60, 0.075, 0.015),
    'gpt-4-turbo': ModelPricing(10.0, 30.0),
    'gpt-4': ModelPricing(30.0, 60.0),
    'gpt-3.5-turbo': ModelPricing(0.50, 1.50),
    'o1': ModelPricing(15.0, 60.0),
    'o1-mini': ModelPricing(1.10, 4.40),
    'o1-preview': ModelPricing(15.0, 60.0),
    'o3-mini': ModelPricing(1.10, 4.40),
    # Google
    'gemini-1.5-pro': ModelPricing(1.25, 5.0),
    'gemini-1.5-flash': ModelPricing(0.075, 0.30),
    'gemini-2.0-flash': ModelPricing(0.10, 0.40),
    'gemini-2.5-pro-preview-05-06': ModelPricing(1.25, 10.0),
    # DeepSeek
    'deepseek-chat': ModelPricing(0.14, 0.28, 0.14, 0.014),
    'deepseek-reasoner': ModelPricing(0.55, 2.19, 0.55, 0.14),
    # Groq
    'llama-3.3-70b-versatile': ModelPricing(0.59, 0.79),
    'llama-3.1-8b-instant': ModelPricing(0.05, 0.08),
    'mixtral-8x7b-32768': ModelPricing(0.24, 0.24),
    # Together
    'meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo': ModelPricing(0.88, 0.88),
    'meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo': ModelPricing(0.18, 0.18),
    # Mistral
    'mistral-large-latest': ModelPricing(2.0, 6.0),
    'mistral-medium-latest': ModelPricing(2.70, 8.10),
    'open-mistral-7b': ModelPricing(0.25, 0.25),
}


def get_model_pricing(model: str) -> ModelPricing:
    """获取模型定价，支持模糊匹配"""
    # 精确匹配
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # 前缀匹配（去掉日期后缀）
    normalized = model.split('-d')[0]  # e.g., "claude-3-5-sonnet-20241022-d" -> "claude-3-5-sonnet-20241022"
    for key, pricing in MODEL_PRICING.items():
        if key in normalized or normalized in key:
            return pricing
    # 模型族匹配
    model_lower = model.lower()
    for family in ('claude', 'gpt', 'gemini', 'deepseek', 'llama', 'mixtral', 'mistral'):
        if family in model_lower:
            for key, pricing in MODEL_PRICING.items():
                if family in key.lower():
                    return pricing
    return ModelPricing()

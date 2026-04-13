"""成本估算模块 - LLM 调用成本估算报告

定价数据来源：各 LLM 提供商官方定价页面
- OpenAI: https://openai.com/api/pricing/
- Anthropic: https://www.anthropic.com/pricing
- Google: https://ai.google.dev/pricing
- Groq: https://groq.com/pricing/
- Together AI: https://www.together.ai/pricing

价格需定期更新，建议每月核对一次。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# 定价数据版本和更新日期
PRICING_VERSION = '2026-04-12-v1'
PRICING_SOURCE = '各提供商官方定价页面'
PRICING_UPDATE_INTERVAL_DAYS = 30  # 定价数据更新间隔（天）


@dataclass
class ModelPricing:
    """模型定价信息（USD / 1M tokens）

    增强功能 (v0.19.0):
    - cache_read_price: 缓存读取价格（通常为输入的 10%）
    - cache_write_price: 缓存写入价格（通常与输入相同）
    - reasoning_price: 推理/思考 tokens 价格（仅适用于 o1/o3/reasoner 等推理模型）
    """
    input_price: float  # 输入价格
    output_price: float  # 输出价格
    currency: str = 'USD'
    cache_read_price: float = 0.0  # 缓存读取价格
    cache_write_price: float = 0.0  # 缓存写入价格
    reasoning_price: float = 0.0  # 推理 tokens 价格（推理模型专用）


def _load_pricing_from_json() -> dict[str, ModelPricing] | None:
    """尝试从外部 JSON 文件加载定价数据

    优先从 model_pricing.json 加载，失败则返回 None 回退到硬编码。
    """
    import json
    json_path = Path(__file__).resolve().parent / 'model_pricing.json'
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text(encoding='utf-8'))
        models = data.get('models', {})
        result = {}
        for name, prices in models.items():
            result[name] = ModelPricing(
                input_price=prices.get('input_price', 0.0),
                output_price=prices.get('output_price', 0.0),
                cache_read_price=prices.get('cache_read_price', 0.0),
                cache_write_price=prices.get('cache_write_price', 0.0),
                reasoning_price=prices.get('reasoning_price', 0.0),
            )
        return result
    except Exception:
        return None


# 各模型定价表
# 优先从外部 model_pricing.json 加载（便于更新），失败则使用硬编码回退
_json_pricing = _load_pricing_from_json()

# 如果 JSON 加载成功，直接使用；否则使用硬编码
MODEL_PRICING: dict[str, ModelPricing] = _json_pricing if _json_pricing is not None else {
    # ============================================
    # OpenAI
    # ============================================
    # GPT-4o 系列（支持缓存）
    'gpt-4o': ModelPricing(
        input_price=2.50, output_price=10.00,
        cache_read_price=1.25, cache_write_price=2.50,
    ),
    'gpt-4o-mini': ModelPricing(
        input_price=0.15, output_price=0.60,
        cache_read_price=0.075, cache_write_price=0.15,
    ),
    'gpt-4o-2024-05-13': ModelPricing(input_price=5.00, output_price=15.00),
    'gpt-4o-2024-08-06': ModelPricing(
        input_price=2.50, output_price=10.00,
        cache_read_price=1.25, cache_write_price=2.50,
    ),

    # GPT-4 Turbo
    'gpt-4-turbo': ModelPricing(input_price=10.00, output_price=30.00),
    'gpt-4-turbo-2024-04-09': ModelPricing(input_price=10.00, output_price=30.00),

    # GPT-3.5 Turbo
    'gpt-3.5-turbo': ModelPricing(input_price=0.50, output_price=1.50),
    'gpt-3.5-turbo-0125': ModelPricing(input_price=0.50, output_price=1.50),

    # OpenAI o 系列 (推理模型 - 有推理 tokens 定价)
    # o1: 推理 tokens 价格与输出相同
    'o1': ModelPricing(
        input_price=15.00, output_price=60.00,
        cache_read_price=7.50, cache_write_price=15.00,
        reasoning_price=60.00,
    ),
    'o1-2024-12-17': ModelPricing(
        input_price=15.00, output_price=60.00,
        reasoning_price=60.00,
    ),
    'o1-mini': ModelPricing(
        input_price=3.00, output_price=12.00,
        reasoning_price=12.00,
    ),
    'o1-mini-2024-09-12': ModelPricing(
        input_price=3.00, output_price=12.00,
        reasoning_price=12.00,
    ),
    'o3': ModelPricing(
        input_price=10.00, output_price=40.00,
        reasoning_price=40.00,
    ),
    'o3-mini': ModelPricing(
        input_price=1.10, output_price=4.40,
        reasoning_price=4.40,
    ),
    'o3-mini-2025-01-31': ModelPricing(
        input_price=1.10, output_price=4.40,
        reasoning_price=4.40,
    ),
    'o4-mini': ModelPricing(
        input_price=1.10, output_price=4.40,
        reasoning_price=4.40,
    ),

    # OpenAI GPT-4.1 系列（支持缓存）
    'gpt-4.1': ModelPricing(
        input_price=2.00, output_price=8.00,
        cache_read_price=0.50, cache_write_price=2.00,
    ),
    'gpt-4.1-mini': ModelPricing(
        input_price=0.40, output_price=1.60,
        cache_read_price=0.10, cache_write_price=0.40,
    ),
    'gpt-4.1-nano': ModelPricing(
        input_price=0.10, output_price=0.40,
        cache_read_price=0.025, cache_write_price=0.10,
    ),

    # ============================================
    # Anthropic Claude
    # ============================================
    # Claude 3.5 Sonnet（支持缓存）
    'claude-3-5-sonnet-20241022': ModelPricing(
        input_price=3.00, output_price=15.00,
        cache_read_price=0.30, cache_write_price=3.75,
    ),
    'claude-3-5-sonnet-latest': ModelPricing(
        input_price=3.00, output_price=15.00,
        cache_read_price=0.30, cache_write_price=3.75,
    ),

    # Claude 3.7 Sonnet（支持缓存 + 扩展思考）
    'claude-3-7-sonnet-20250219': ModelPricing(
        input_price=3.00, output_price=15.00,
        cache_read_price=0.30, cache_write_price=3.75,
        reasoning_price=15.00,  # 扩展思考 tokens
    ),
    'claude-3-7-sonnet-latest': ModelPricing(
        input_price=3.00, output_price=15.00,
        cache_read_price=0.30, cache_write_price=3.75,
        reasoning_price=15.00,
    ),

    # Claude 3 Opus
    'claude-3-opus-20240229': ModelPricing(input_price=15.00, output_price=75.00),
    'claude-3-opus-latest': ModelPricing(input_price=15.00, output_price=75.00),

    # Claude 3 Haiku
    'claude-3-haiku-20240307': ModelPricing(input_price=0.25, output_price=1.25),

    # Claude 3.5 Haiku
    'claude-3-5-haiku-20241022': ModelPricing(input_price=0.80, output_price=4.00),
    'claude-3-5-haiku-latest': ModelPricing(input_price=0.80, output_price=4.00),

    # ============================================
    # Google Gemini
    # ============================================
    # Gemini 2.0 Flash
    'gemini-2.0-flash': ModelPricing(input_price=0.10, output_price=0.40),
    'gemini-2.0-flash-exp': ModelPricing(input_price=0.00, output_price=0.00),  # 免费预览
    'gemini-2.0-flash-lite': ModelPricing(input_price=0.075, output_price=0.30),

    # Gemini 2.5 Pro/Flash
    'gemini-2.5-pro': ModelPricing(
        input_price=1.25, output_price=10.00,
        cache_read_price=0.31, cache_write_price=1.25,
    ),
    'gemini-2.5-pro-preview-03-25': ModelPricing(
        input_price=1.25, output_price=10.00,
    ),
    'gemini-2.5-flash': ModelPricing(input_price=0.15, output_price=3.50),
    'gemini-2.5-flash-preview-04-17': ModelPricing(input_price=0.15, output_price=3.50),

    # Gemini 1.5 Pro
    'gemini-1.5-pro': ModelPricing(input_price=1.25, output_price=5.00),
    'gemini-1.5-pro-001': ModelPricing(input_price=2.50, output_price=10.00),

    # ============================================
    # Groq (超高速推理)
    # ============================================
    'llama-3.3-70b-versatile': ModelPricing(input_price=0.59, output_price=0.79),
    'llama-3.3-70b-specdec': ModelPricing(input_price=0.59, output_price=0.99),
    'mixtral-8x7b-32768': ModelPricing(input_price=0.27, output_price=0.27),
    'llama-3.1-8b-instant': ModelPricing(input_price=0.05, output_price=0.08),
    'llama-guard-4-12b': ModelPricing(input_price=0.20, output_price=0.20),

    # ============================================
    # Together AI
    # ============================================
    'meta-llama/Llama-3.3-70B-Instruct-Turbo': ModelPricing(input_price=0.88, output_price=0.88),
    'meta-llama/Llama-3.1-405B-Instruct-Turbo': ModelPricing(input_price=3.50, output_price=3.50),
    'mistralai/Mixtral-8x7B-Instruct-v0.1': ModelPricing(input_price=0.60, output_price=0.60),
    'deepseek-ai/DeepSeek-V3': ModelPricing(input_price=1.25, output_price=1.25),
    'deepseek-ai/DeepSeek-R1': ModelPricing(input_price=7.00, output_price=7.00),

    # ============================================
    # OpenRouter Free Models
    # ============================================
    'qwen/qwen3.6-plus-preview:free': ModelPricing(input_price=0.00, output_price=0.00),
    'qwen/qwen3-coder': ModelPricing(input_price=0.00, output_price=0.00),
    'qwen/qwq-32b': ModelPricing(input_price=0.00, output_price=0.00),
    'meta-llama/llama-3.1-8b-instruct:free': ModelPricing(input_price=0.00, output_price=0.00),
    'meta-llama/llama-3.2-3b-instruct:free': ModelPricing(input_price=0.00, output_price=0.00),
    'mistralai/mistral-7b-instruct:free': ModelPricing(input_price=0.00, output_price=0.00),
    'google/gemini-2.0-flash-exp:free': ModelPricing(input_price=0.00, output_price=0.00),

    # ============================================
    # DeepSeek
    # ============================================
    'deepseek-chat': ModelPricing(input_price=0.27, output_price=1.10),
    'deepseek-reasoner': ModelPricing(
        input_price=0.55, output_price=2.19,
        reasoning_price=2.19,  # 推理 tokens 价格
    ),
    'deepseek-coder': ModelPricing(input_price=0.14, output_price=0.28),

    # ============================================
    # Mistral
    # ============================================
    'mistral-large-latest': ModelPricing(input_price=2.00, output_price=6.00),
    'mistral-large-2411': ModelPricing(input_price=2.00, output_price=6.00),
    'mistral-small-latest': ModelPricing(input_price=0.20, output_price=0.60),
    'mistral-small-2503': ModelPricing(input_price=0.20, output_price=0.60),
    'pixtral-large-latest': ModelPricing(input_price=2.00, output_price=6.00),
    'codestral-latest': ModelPricing(input_price=0.30, output_price=0.90),

    # ============================================
    # xAI Grok
    # ============================================
    'grok-3': ModelPricing(input_price=3.00, output_price=15.00),
    'grok-3-mini': ModelPricing(input_price=0.30, output_price=0.50),
    'grok-4': ModelPricing(input_price=3.00, output_price=15.00),

    # ============================================
    # Qwen (阿里云)
    # ============================================
    'qwen-max': ModelPricing(input_price=1.60, output_price=6.40),
    'qwen-plus': ModelPricing(input_price=0.40, output_price=1.20),
    'qwen-turbo': ModelPricing(input_price=0.08, output_price=0.32),
    'qwen-long': ModelPricing(input_price=0.08, output_price=0.32),
    'qwen-coder-plus': ModelPricing(input_price=0.40, output_price=1.20),

    # ============================================
    # 新增模型 (v0.22.0)
    # ============================================
    # OpenAI GPT-4.1 系列更新
    'gpt-4.1-2025-04-14': ModelPricing(
        input_price=2.00, output_price=8.00,
        cache_read_price=0.50, cache_write_price=2.00,
    ),

    # Anthropic Claude 3.5 Haiku 更新
    'claude-sonnet-4-20250514': ModelPricing(
        input_price=3.00, output_price=15.00,
        cache_read_price=0.30, cache_write_price=3.75,
    ),
    'claude-opus-4-20250514': ModelPricing(
        input_price=15.00, output_price=75.00,
        cache_read_price=1.50, cache_write_price=18.75,
    ),

    # Google Gemini 3 系列
    'gemini-3-pro': ModelPricing(
        input_price=1.25, output_price=10.00,
        cache_read_price=0.31, cache_write_price=1.25,
    ),
    'gemini-3-flash': ModelPricing(input_price=0.15, output_price=0.60),

    # Qwen 3 系列
    'qwen3-235b-a22b': ModelPricing(input_price=0.40, output_price=1.20),
    'qwen3-30b-a3b': ModelPricing(input_price=0.10, output_price=0.30),
    'qwen3-14b': ModelPricing(input_price=0.08, output_price=0.24),
    'qwen3-8b': ModelPricing(input_price=0.05, output_price=0.15),
    'qwen3-coder': ModelPricing(input_price=0.40, output_price=1.20),
}

# 默认定价（未知模型使用此价格）
DEFAULT_PRICING = ModelPricing(input_price=1.00, output_price=3.00)


def check_pricing_freshness() -> dict[str, Any]:
    """检查定价数据的新鲜度

    返回:
        包含新鲜度状态的字典:
        - is_fresh: 是否在有效期内
        - days_since_update: 距离更新日期的天数
        - days_until_expire: 距离过期的天数（负数表示已过期）
        - warning: 警告信息（如果需要更新）
        - update_url: 官方定价页面 URL 列表
    """
    result: dict[str, Any] = {}
    try:
        # 从版本号中提取日期（格式: YYYY-MM-DD-vX）
        version_date_str = PRICING_VERSION.split('-v')[0]
        version_date = datetime.strptime(version_date_str, '%Y-%m-%d')
        now = datetime.now()
        days_since = (now - version_date).days
        expire_date = version_date + timedelta(days=PRICING_UPDATE_INTERVAL_DAYS)
        days_until_expire = (expire_date - now).days

        # 官方定价页面 URL（用于手动核对更新）
        update_urls = [
            'OpenAI: https://openai.com/api/pricing/',
            'Anthropic: https://www.anthropic.com/pricing',
            'Google: https://ai.google.dev/pricing',
            'Groq: https://groq.com/pricing/',
            'Together AI: https://www.together.ai/pricing',
        ]

        result = {
            'is_fresh': days_until_expire > 0,
            'days_since_update': days_since,
            'days_until_expire': days_until_expire,
            'warning': None,
            'update_urls': update_urls,
        }

        if days_until_expire <= 0:
            result['warning'] = (
                f'⚠️ 定价数据已过期 {abs(days_until_expire)} 天！'
                f'当前版本: {PRICING_VERSION}。'
                f'建议访问以下官方定价页面更新价格数据：\n'
                + '\n'.join(f'  - {url}' for url in update_urls[:3])
            )
        elif days_until_expire <= 7:
            result['warning'] = (
                f'⚠️ 定价数据将在 {days_until_expire} 天后过期。'
                f'当前版本: {PRICING_VERSION}。'
                f'建议尽快核对并更新价格数据。'
            )

        return result
    except (ValueError, IndexError):
        return {
            'is_fresh': False,
            'days_since_update': -1,
            'days_until_expire': -1,
            'warning': f'⚠️ 无法解析定价版本号: {PRICING_VERSION}，请检查格式是否正确。',
            'update_urls': [],
        }


def log_pricing_check() -> None:
    """启动时自动检查定价数据新鲜度并输出日志

    如果定价数据过期或即将过期，输出警告信息。
    此函数应在应用启动时调用一次。
    """
    freshness = check_pricing_freshness()
    if freshness.get('warning'):
        # 延迟导入避免循环依赖
        try:
            from ...utils import warn
            warn(freshness['warning'])
        except ImportError:
            # 如果在测试环境中 utils 不可用，直接打印
            print(f"[WARNING] {freshness['warning']}", flush=True)


class CostEstimator:
    """LLM 调用成本估算器

    根据模型名称和 token 使用量估算实际成本（USD）。

    增强功能 (v0.19.0):
    - 支持缓存 tokens 成本计算 (cache_read_tokens, cache_write_tokens)
    - 支持推理 tokens 成本计算 (reasoning_tokens)
    - 更详细的成本报告（按类型分组）
    """

    def __init__(self, max_call_history: int = 10_000) -> None:
        self._calls: list[dict[str, Any]] = []
        self._max_call_history = max_call_history
        self._total_cost: float = 0.0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cache_read_tokens: int = 0  # 缓存读取 tokens
        self._total_cache_write_tokens: int = 0  # 缓存写入 tokens
        self._total_reasoning_tokens: int = 0  # 推理 tokens

    def record_call(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        label: str = '',
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float:
        """记录一次 LLM 调用并计算成本

        参数:
            model: 模型名称
            input_tokens: 输入 token 数量
            output_tokens: 输出 token 数量
            label: 调用标签（用于报告）
            cache_read_tokens: 缓存读取 token 数量（v0.19.0 新增）
            cache_write_tokens: 缓存写入 token 数量（v0.19.0 新增）
            reasoning_tokens: 推理 token 数量（v0.19.0 新增，适用于 o1/o3/reasoner 等）

        返回:
            本次调用的成本（USD）
        """
        pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)

        # 计算基础成本（USD / 1M tokens）
        input_cost = (input_tokens / 1_000_000) * pricing.input_price
        output_cost = (output_tokens / 1_000_000) * pricing.output_price

        # 计算缓存成本
        cache_read_cost = (cache_read_tokens / 1_000_000) * pricing.cache_read_price
        cache_write_cost = (cache_write_tokens / 1_000_000) * pricing.cache_write_price

        # 计算推理成本（如果有专用定价）
        if pricing.reasoning_price > 0 and reasoning_tokens > 0:
            reasoning_cost = (reasoning_tokens / 1_000_000) * pricing.reasoning_price
        else:
            # 回退：如果没有推理定价，推理 tokens 按输出价格计算
            reasoning_cost = (reasoning_tokens / 1_000_000) * pricing.output_price

        total_cost = input_cost + output_cost + cache_read_cost + cache_write_cost + reasoning_cost

        # [汲取 GoalX] 全局同步预算监控 (如果存在)
        try:
            from ..events import get_event_bus, Event, EventType
            get_event_bus().publish(Event(
                type=EventType.COST_RECORDED,
                data={
                    "model": model,
                    "cost": total_cost,
                    "tokens": input_tokens + output_tokens + reasoning_tokens
                }
            ))
        except Exception:
            pass

        call_record: dict[str, Any] = {
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cache_read_tokens': cache_read_tokens,
            'cache_write_tokens': cache_write_tokens,
            'reasoning_tokens': reasoning_tokens,
            'input_cost': input_cost,
            'output_cost': output_cost,
            'cache_read_cost': cache_read_cost,
            'cache_write_cost': cache_write_cost,
            'reasoning_cost': reasoning_cost,
            'total_cost': total_cost,
            'label': label or f'call_{len(self._calls) + 1}',
        }
        self._calls.append(call_record)
        if len(self._calls) > self._max_call_history:
            self._calls = self._calls[-self._max_call_history:]
        self._total_cost += total_cost
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._total_cache_read_tokens += cache_read_tokens
        self._total_cache_write_tokens += cache_write_tokens
        self._total_reasoning_tokens += reasoning_tokens

        return total_cost

    def get_total_cost(self) -> float:
        """获取总成本（USD）"""
        return self._total_cost

    def get_report(self) -> str:
        """生成成本估算报告

        返回:
            格式化的成本报告字符串
        """
        # 检查定价数据新鲜度
        freshness = check_pricing_freshness()
        freshness_warning = f'\n{freshness["warning"]}\n' if freshness.get('warning') else ''

        if not self._calls:
            return (
                f'📊 成本估算报告 (定价版本: {PRICING_VERSION}){freshness_warning}'
                + '=' * 50 + '\n暂无调用记录'
            )

        lines = [
            f'📊 成本估算报告 (定价版本: {PRICING_VERSION}){freshness_warning}',
            '=' * 50,
            f'总成本: ${self._total_cost:.6f} USD',
            f'调用次数: {len(self._calls)}',
            '-' * 50,
            'Token 用量:',
            f'  总输入 tokens: {self._total_input_tokens:,}',
            f'  总输出 tokens: {self._total_output_tokens:,}',
        ]

        # 如果有缓存或推理 tokens，显示详细信息
        if self._total_cache_read_tokens > 0 or self._total_cache_write_tokens > 0:
            lines.extend([
                f'  缓存读取 tokens: {self._total_cache_read_tokens:,}',
                f'  缓存写入 tokens: {self._total_cache_write_tokens:,}',
            ])
        if self._total_reasoning_tokens > 0:
            lines.append(f'  推理 tokens: {self._total_reasoning_tokens:,}')

        lines.extend(['-' * 50, '', '按模型分组:', '-' * 50])

        # 按模型分组统计
        model_stats: dict[str, dict[str, Any]] = {}
        for call in self._calls:
            model = call['model']
            if model not in model_stats:
                model_stats[model] = {
                    'calls': 0,
                    'input_tokens': 0,
                    'output_tokens': 0,
                    'cache_read_tokens': 0,
                    'cache_write_tokens': 0,
                    'reasoning_tokens': 0,
                    'cost': 0.0,
                }
            model_stats[model]['calls'] += 1
            model_stats[model]['input_tokens'] += call['input_tokens']
            model_stats[model]['output_tokens'] += call['output_tokens']
            model_stats[model]['cache_read_tokens'] += call.get('cache_read_tokens', 0)
            model_stats[model]['cache_write_tokens'] += call.get('cache_write_tokens', 0)
            model_stats[model]['reasoning_tokens'] += call.get('reasoning_tokens', 0)
            model_stats[model]['cost'] += call['total_cost']

        for model, stats in model_stats.items():
            lines.append(f'  {model}:')
            lines.append(f'    调用次数: {stats["calls"]}')
            lines.append(f'    输入 tokens: {stats["input_tokens"]:,}')
            lines.append(f'    输出 tokens: {stats["output_tokens"]:,}')
            if stats['cache_read_tokens'] > 0:
                lines.append(f'    缓存读取: {stats["cache_read_tokens"]:,}')
            if stats['cache_write_tokens'] > 0:
                lines.append(f'    缓存写入: {stats["cache_write_tokens"]:,}')
            if stats['reasoning_tokens'] > 0:
                lines.append(f'    推理 tokens: {stats["reasoning_tokens"]:,}')
            lines.append(f'    成本: ${stats["cost"]:.6f} USD')
            lines.append('')

        # 详细调用记录
        lines.append('详细调用记录:')
        lines.append('-' * 50)
        for call in self._calls:
            parts = [f'输入={call["input_tokens"]:,}', f'输出={call["output_tokens"]:,}']
            if call.get('cache_read_tokens', 0) > 0:
                parts.append(f'缓存读={call["cache_read_tokens"]:,}')
            if call.get('cache_write_tokens', 0) > 0:
                parts.append(f'缓存写={call["cache_write_tokens"]:,}')
            if call.get('reasoning_tokens', 0) > 0:
                parts.append(f'推理={call["reasoning_tokens"]:,}')

            lines.append(
                f'  {call["label"]}: {call["model"]} '
                f'({", ".join(parts)}) '
                f'= ${call["total_cost"]:.6f}'
            )

        lines.append('=' * 50)
        return '\n'.join(lines)

    def get_summary(self) -> dict[str, Any]:
        """获取成本摘要"""
        summary: dict[str, Any] = {
            'total_cost': round(self._total_cost, 6),
            'total_cost_usd': round(self._total_cost, 6),
            'total_tokens': self._total_input_tokens + self._total_output_tokens,
            'total_calls': len(self._calls),
            'call_count': len(self._calls),  # 别名以兼容旧测试
            'total_input_tokens': self._total_input_tokens,
            'total_output_tokens': self._total_output_tokens,
            'avg_cost_per_call': round(self._total_cost / max(len(self._calls), 1), 6),
        }
        if self._total_cache_read_tokens > 0:
            summary['total_cache_read_tokens'] = self._total_cache_read_tokens
        if self._total_cache_write_tokens > 0:
            summary['total_cache_write_tokens'] = self._total_cache_write_tokens
        if self._total_reasoning_tokens > 0:
            summary['total_reasoning_tokens'] = self._total_reasoning_tokens
        return summary

    def reset(self) -> None:
        """重置所有记录"""
        self._calls.clear()
        self._total_cost = 0.0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cache_read_tokens = 0
        self._total_cache_write_tokens = 0
        self._total_reasoning_tokens = 0


def get_model_pricing(model_name: str) -> ModelPricing:
    """获取模型定价信息"""
    return MODEL_PRICING.get(model_name, DEFAULT_PRICING)


def estimate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> float:
    """便捷函数 - 估算单次调用成本

    参数:
        model: 模型名称
        input_tokens: 输入 token 数量
        output_tokens: 输出 token 数量
        cache_read_tokens: 缓存读取 token 数量
        cache_write_tokens: 缓存写入 token 数量
        reasoning_tokens: 推理 token 数量

    返回:
        估算成本（USD）
    """
    pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
    input_cost = (input_tokens / 1_000_000) * pricing.input_price
    output_cost = (output_tokens / 1_000_000) * pricing.output_price
    cache_read_cost = (cache_read_tokens / 1_000_000) * pricing.cache_read_price
    cache_write_cost = (cache_write_tokens / 1_000_000) * pricing.cache_write_price

    if pricing.reasoning_price > 0 and reasoning_tokens > 0:
        reasoning_cost = (reasoning_tokens / 1_000_000) * pricing.reasoning_price
    else:
        reasoning_cost = (reasoning_tokens / 1_000_000) * pricing.output_price

    return input_cost + output_cost + cache_read_cost + cache_write_cost + reasoning_cost

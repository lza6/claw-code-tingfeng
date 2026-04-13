"""显示执行类 CLI 命令处理器

集成 RTK 风格 token 节省报告 (v0.40.0)
"""
from __future__ import annotations

import argparse

from ..core.models import CommandResult


def handle_cost_report(args: argparse.Namespace) -> CommandResult:
    """处理 cost-report 命令 — 集成 LLM 成本 + RTK 风格 token 节省报告"""
    from ..core.cost_estimator.cost_estimator import CostEstimator, check_pricing_freshness

    parts: list[str] = []

    # ----- 原有 LLM 成本报告 -----
    estimator = CostEstimator()
    if hasattr(args, 'demo') and args.demo:
        # 仅在不指定 --tokens 时显示 demo 数据
        estimator.record_call('gpt-4o', input_tokens=1000, output_tokens=500, label='demo_call')
        estimator.record_call('claude-3-5-sonnet-20241022', input_tokens=2000, output_tokens=1000, label='demo_call_2')

    cost_report = estimator.get_report()
    parts.append(cost_report)

    # 附加定价新鲜度检查
    freshness = check_pricing_freshness()
    warning = freshness.get('warning')
    if warning:
        parts.append(f'\n{warning}')

    # ----- RTK 风格 token 节省报告 -----
    try:
        from .cost_analysis import run as cost_analysis_run
        days = getattr(args, 'days', 30) or 30
        token_report = cost_analysis_run(['--tokens', '--days', str(days)])
        parts.append(f'\n{token_report}')
    except (ImportError, Exception) as e:
        # 不阻断主流程
        parts.append(f'\n(token tracking 不可用: {e})')

    return CommandResult(exit_code=0, output='\n'.join(parts))

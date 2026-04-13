"""Cost Analysis CLI — 借鉴 RTK 的 gain 命令

RTK 的 `rtk gain` 展示 token 节省历史、按日/周/月聚合、ASCII 图表。
这个模块提供等价的 Clawd 增强版: `clawd cost-report` 子命令。

用法:
    clawd cost-report              # 默认成本报告
    clawd cost-report --tokens     # token 节省报告 (RTK 风格)
    clawd cost-report --chart      # ASCII 趋势图
    clawd cost-report --daily 7    # 按日聚合 (7 天)
    clawd cost-report --tools      # 按工具分组统计
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# CLI 参数定义
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='clawd cost-report',
        description='LLM 成本和 token 节省分析报告 (集成 RTK gain 功能)',
    )
    parser.add_argument(
        '--tokens',
        action='store_true',
        default=False,
        help='显示 token 节省报告 (RTK 风格)',
    )
    parser.add_argument(
        '--chart',
        action='store_true',
        default=False,
        help='显示 ASCII 趋势图',
    )
    parser.add_argument(
        '--daily',
        type=int,
        metavar='DAYS',
        default=0,
        help='按日聚合统计 (指定天数)',
    )
    parser.add_argument(
        '--tools',
        action='store_true',
        default=False,
        help='按工具分组统计',
    )
    parser.add_argument(
        '--days',
        type=int,
        default=30,
        metavar='DAYS',
        help='统计天数 (默认 30)',
    )
    return parser


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run(args: list[str] | None = None) -> str:
    """执行成本分析报告

    Args:
        args: CLI 参数列表 (默认从 sys.argv 读取)

    Returns:
        格式化的报告字符串
    """
    parser = build_parser()
    parsed = parser.parse_args(args)

    lines: list[str] = []
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines.append(f'📊 Clawd 分析报告 (生成于 {ts})')
    lines.append('=' * 55)

    if parsed.tokens or parsed.chart or parsed.daily or parsed.tools:
        # Token 相关报告 (RTK 风格)
        try:
            from src.core.telemetry.token_tracker import TokenTracker
            tracker = TokenTracker()
            tracker.init()

            if parsed.tokens:
                lines.append(tracker.get_report(days=parsed.days))

            if parsed.chart:
                lines.append('')
                lines.append(tracker.get_ascii_chart(days=min(7, parsed.days)))

            if parsed.daily > 0:
                daily = tracker.get_daily_breakdown(days=parsed.daily)
                if daily:
                    lines.append(f'\n📅 按日聚合 (最近 {parsed.daily} 天)')
                    lines.append('-' * 55)
                    lines.append(f'{"日期":<12} {"记录":>5} {"原始":>10} {"压缩后":>10} {"节省":>10} {"节省率":>8}')
                    lines.append('-' * 55)
                    for d in daily:
                        lines.append(
                            f'{d["day"]:<12} {d["records"]:>5} '
                            f'{d["raw_tokens"]:>10,} {d["compressed_tokens"]:>10,} '
                            f'{d["saved_tokens"]:>10,} {d["savings_pct"]:>7.0f}%'
                        )
                else:
                    lines.append('暂无按日数据。')

            if parsed.tools:
                tools = tracker.get_tool_breakdown(days=parsed.days)
                if tools:
                    lines.append(f'\n🔧 按工具分组 (最近 {parsed.days} 天)')
                    lines.append('-' * 55)
                    lines.append(f'{"工具":<25} {"执行":>5} {"原始":>10} {"压缩后":>10} {"节省率":>8}')
                    lines.append('-' * 55)
                    for t in tools:
                        lines.append(
                            f'{t["tool_name"]:<25} {t["records"]:>5} '
                            f'{t["raw_tokens"]:>10,} {t["compressed_tokens"]:>10,} '
                            f'{t["savings_pct"]:>7.0f}%'
                        )
                else:
                    lines.append('暂无按工具数据。')

        except (ImportError, Exception) as e:
            lines.append(f'(token tracking 不可用: {e})')

    else:
        # 默认: LLM 成本报告 (原有的 cost-report 功能)
        try:
            from src.core.cost_estimator.cost_estimator import CostEstimator
            estimator = CostEstimator()
            lines.append(estimator.get_report())
        except (ImportError, Exception) as e:
            lines.append(f'(成本报告不可用: {e})')

    return '\n'.join(lines)

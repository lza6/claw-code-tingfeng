"""HUD CLI 入口点

汲取 oh-my-codex-main/src/hud/index.ts

提供命令行接口来显示和监控 HUD。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from .render import render_hud, watch_render_loop
from .state import HudStateManager
from .types import HudRenderContext

HUD_USAGE = [
    "Usage:",
    "  clawd hud              Show current HUD state",
    "  clawd hud --watch    Poll every 1s with terminal clear",
    "  clawd hud --json     Output raw state as JSON",
    "  clawd hud --preset=X Use preset: minimal, focused, full",
    "  clawd hud --tmux     Open HUD in a tmux split pane (auto-detects orientation)",
].join("\n")


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="ClawD HUD - Heads-Up Display",
        prog="clawd hud",
        add_help=False,
    )
    parser.add_argument("--watch", action="store_true", help="Poll every 1s with terminal clear")
    parser.add_argument("--json", action="store_true", help="Output raw state as JSON")
    parser.add_argument("--preset", choices=["minimal", "focused", "full"], help="Use preset")
    parser.add_argument("--tmux", action="store_true", help="Open HUD in a tmux split pane")
    parser.add_argument("--help", "-h", action="store_true", help="Show help")
    return parser.parse_args()


async def show_hud_once() -> None:
    """显示一次 HUD 状态"""
    state_manager = HudStateManager.get_instance()
    context = state_manager.get_context()
    config = state_manager.get_config()

    # 更新时间戳
    context.session = _get_or_create_session(context)
    context.git_branch = _get_git_branch()
    context.metrics = _get_metrics(context)

    # 渲染并输出
    output = render_hud(context, config)
    if output:
        print(output)
    else:
        print("HUD: No data available")


def _get_or_create_session(context: HudRenderContext) -> dict | None:
    """获取或创建会话信息"""
    if context.session:
        return context.session

    # 创建默认会话
    return {
        "session_id": f"clawd-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "started_at": datetime.now(),
        "agent": "clawd",
    }


def _get_git_branch() -> str | None:
    """获取当前 Git 分支"""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_metrics(context: HudRenderContext) -> dict | None:
    """获取系统指标"""
    # 这里可以集成实际的指标收集
    # 暂时返回示例数据
    from .types import HudMetrics

    metrics = HudMetrics(
        total_turns=0,
        session_turns=0,
        last_activity=datetime.now(),
    )
    return metrics


def show_json() -> None:
    """输出原始状态为 JSON"""
    state_manager = HudStateManager.get_instance()
    state_dict = state_manager.to_dict()
    import json

    print(json.dumps(state_dict, indent=2, default=str))


def main() -> None:
    """主入口点"""
    args = parse_args()

    if args.help:
        print(HUD_USAGE)
        sys.exit(0)

    if args.json:
        show_json()
        return

    if args.watch:
        # 监视模式
        async def render_and_clear():
            await show_hud_once()
            # 清屏（在实际实现中可能需要更复杂的处理）
            print("\033[2J\033[H", end="")  # ANSI clear screen

        try:
            asyncio.run(
                watch_render_loop(
                    render_and_clear,
                    interval_ms=1000,
                )
            )
        except KeyboardInterrupt:
            print("\nHUD stopped.")
    else:
        # 单次显示
        asyncio.run(show_hud_once())


if __name__ == "__main__":
    main()

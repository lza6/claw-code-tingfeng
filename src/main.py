from __future__ import annotations

import argparse
import atexit
import logging
import os as _os
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .core.cost_estimator.cost_estimator import log_pricing_check

_initialized = False
logger = logging.getLogger(__name__)


def _load_slow_imports() -> None:
    """延迟加载重型模块 (借鉴 Aider)

    在后台线程中预加载耗时模块，加速后续首次使用。
    首次运行时同步加载（用户感知延迟），后续版本在后台加载。
    """
    slow_modules = [
        'networkx',
        'diskcache',
        'pathspec',
        'grep_ast',
    ]

    def _load():
        for mod_name in slow_modules:
            try:
                __import__(mod_name)
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f'延迟加载 {mod_name} 失败: {e}')

    # 后台线程预加载
    t = threading.Thread(target=_load, daemon=True, name='slow-imports')
    t.start()


def initialize() -> None:
    """初始化应用（加载 .env、文件日志、定价检查）

    此函数应仅被 main() 调用一次。
    避免 import 时产生副作用，便于测试。
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    # ClawGod v2: 尽早设置隐私保护环境变量（在 .env 加载之前）
    _os.environ.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    _os.environ.setdefault("DISABLE_INSTALLATION_CHECKS", "1")
    _os.environ.setdefault("API_TIMEOUT_MS", "3000000")

    # 加载 .env 文件
    try:
        from .utils.env_loader import load_env
        load_env()
    except Exception as e:
        print(f'[警告] .env 文件加载失败: {e}', file=sys.stderr)
        print('[警告] 请检查 .env 文件格式，或复制 .env.example 为 .env', file=sys.stderr)

    # 自动启用文件日志
    enable_logging = _os.environ.get('ENABLE_FILE_LOGGING', 'true').lower() in ('1', 'true', 'yes')
    if enable_logging:
        try:
            from .utils.logger import setup_logging
            log_dir = Path(_os.environ.get('WORK_DIR', '.')) / '.clawd' / 'logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"clawd_{int(time.time())}.jsonl"
            setup_logging(level=logging.INFO, log_file=str(log_file))
            print(f"[*] 结构化日志已启用: {log_file}")
        except Exception as e:
            print(f'[警告] 文件日志启用失败: {e}', file=sys.stderr)

    # 检查定价数据新鲜度
    try:
        log_pricing_check()
    except Exception as e:
        print(f'[警告] 定价数据检查失败: {e}', file=sys.stderr)

    # 延迟加载重型模块 (后台线程)
    _load_slow_imports()

from .cli_handlers import get_command_handler
from .core.exceptions import ClawdError

# 命令分组定义（用于帮助文本组织）
COMMAND_GROUPS: dict[str, list[str]] = {
    '交互模式': ['chat', 'doctor'],
    '显示执行': ['cost-report'],
    '工作流引擎': ['workflow'],
}

# 命令帮助文本映射
COMMAND_HELP: dict[str, str] = {
    'chat': '启动交互式 AI 编程对话（类 Claude Code）',
    'doctor': '运行环境诊断（检查 Python/依赖/API Key）',
    'evolve': '启动自主迭代优化引擎（持续改进代码库）',
    'cost-report': '显示 LLM 调用成本估算报告',
    'workflow': 'Workflow 工作流引擎（版本管理/热修复/5阶段执行管道）',
}


def _format_command_help(commands: list[str]) -> str:
    """格式化命令分组的帮助文本"""
    parts = []
    for cmd in commands:
        help_text = COMMAND_HELP.get(cmd, '')
        if help_text:
            parts.append(f'  {cmd:20s} {help_text}')
    return '\n'.join(parts)


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器（带命令分组）"""
    # 构建分组帮助文本
    group_help_parts = []
    for group_name, cmds in COMMAND_GROUPS.items():
        group_help_parts.append(f'{group_name}:')
        group_help_parts.append(_format_command_help(cmds))
        group_help_parts.append('')

    epilog = '命令分组:\n\n' + '\n'.join(group_help_parts)

    parser = argparse.ArgumentParser(
        description='Clawd Code - AI 编程代理框架',
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--version', action='version', version=f'Clawd Code v{__version__}', help='显示版本号')
    subparsers = parser.add_subparsers(dest='command', required=False, help='子命令')

    # 交互模式
    chat_parser = subparsers.add_parser('chat', help=COMMAND_HELP['chat'])
    chat_parser.add_argument('--max-iterations', type=int, default=10, help='最大迭代次数')
    chat_parser.add_argument('--tui', action='store_true', help='使用 Textual TUI 全屏仪表盘')
    subparsers.add_parser('doctor', help=COMMAND_HELP['doctor'])

    cost_parser = subparsers.add_parser('cost-report', help=COMMAND_HELP['cost-report'])
    cost_parser.add_argument('--tokens', action='store_true', help='显示 Token 节省报告 (RTK 风格)')
    cost_parser.add_argument('--chart', action='store_true', help='显示 ASCII 趋势图')
    cost_parser.add_argument('--daily', type=int, metavar='DAYS', default=0, help='按日聚合')
    cost_parser.add_argument('--tools', action='store_true', help='按工具分组统计')
    cost_parser.add_argument('--days', type=int, default=30, metavar='DAYS', help='统计天数 (默认30)')
    cost_parser.add_argument('--no-demo', action='store_true', help='跳过演示数据')

    # 自主进化
    evolve_parser = subparsers.add_parser('evolve', help=COMMAND_HELP['evolve'])
    evolve_parser.add_argument('--interval', type=int, default=300, help='检查间隔（秒）')
    evolve_parser.add_argument('--daemon', action='store_true', help='以后台守护进程模式运行')

    # 工作流引擎
    workflow_parser = subparsers.add_parser('workflow', help=COMMAND_HELP['workflow'])
    workflow_sub = workflow_parser.add_subparsers(dest='workflow_command', required=True)

    # workflow run
    run_p = workflow_sub.add_parser('run', help='执行工作流')
    run_p.add_argument('--goal', required=True, help='工作流目标/描述')
    run_p.add_argument('--intent', choices=['deliver', 'explore', 'evolve', 'debate', 'implement'], default='deliver', help='执行意图 (汲取 GoalX)')
    run_p.add_argument('--iterations', type=int, default=3, help='最大迭代次数')
    run_p.add_argument('--hotfix-id', help='热修复模式的问题 ID')
    run_p.add_argument('--isolation', action='store_true', help='启用 Git Worktree 任务隔离并行')
    run_p.add_argument('--budget', help='运行预算约束 (例如 1h, 10usd, 1000t)')
    run_p.add_argument('--evidence-level', choices=['none', 'minimal', 'full'], default='minimal', help='证据校验级别')

    # workflow hotfix
    hotfix_p = workflow_sub.add_parser('hotfix', help='切换热修复模式')
    hotfix_p.add_argument('mode', choices=['on', 'off'], help='on 或 off')
    hotfix_p.add_argument('--id', help='问题 ID (启用时必填)')

    # workflow version
    version_p = workflow_sub.add_parser('version', help='版本管理')
    version_sub = version_p.add_subparsers(dest='version_command', required=True)
    bump_p = version_sub.add_parser('bump', help='升级版本号')
    bump_p.add_argument('bump_type', choices=['major', 'minor', 'patch', 'prerelease'])
    bump_p.add_argument('--changelog-entry', action='append', help='更新日志条目')
    bump_p.add_argument('--category', default='Other', help='更新日志分类')
    bump_p.add_argument('--prerelease-id', help='预发布标识 (alpha, beta, rc)')
    version_sub.add_parser('check', help='检查版本一致性')

    # workflow status
    workflow_sub.add_parser('status', help='显示工作流状态')

    # workflow observe
    workflow_sub.add_parser('observe', help='深入观察运行状态 (汲取 GoalX)')

    # workflow recover
    workflow_sub.add_parser('recover', help='从上次中断的状态恢复工作流')

    return parser


def _register_shutdown_hooks() -> None:
    """注册清理函数"""
    from .agent import tool_executor as exec_mod
    exec_mod.shutdown_executor()


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口点 - 使用命令注册表分发（集成结构化异常处理）

    无子命令时启动交互式 REPL（类 Claude Code）。
    自动在项目目录下创建 .clawd/ 文件夹用于存储会话记录、记忆等资产。
    """
    # 注册进程退出时清理钩子
    atexit.register(_register_shutdown_hooks)

    # 安装全局异常处理器（Bug Reporter，移植自 Aider report.py）
    try:
        from .core.bug_reporter import install_exception_handler
        install_exception_handler()
    except Exception:
        pass
    initialize()
    parser = build_parser()
    args = parser.parse_args(argv)

    # 无子命令 → 启动交互式 REPL
    if args.command is None or args.command == 'chat':
        import os
        from pathlib import Path

        from .cli.repl import start_repl
        from .core.project_context import ProjectContext

        max_iter = getattr(args, 'max_iterations', 10)
        use_tui = getattr(args, 'tui', False)
        workdir_str = os.environ.get('WORK_DIR', '')
        workdir = Path(workdir_str) if workdir_str else None

        # 创建项目上下文（自动检测/创建 .clawd 目录）
        project_ctx = ProjectContext(workdir=workdir)
        project_ctx.ensure_dirs()

        return start_repl(
            workdir=workdir,
            max_iterations=max_iter,
            use_textual_tui=use_tui,
            project_ctx=project_ctx,
        )

    # doctor 命令 — 直接调用诊断
    if args.command == 'doctor':
        from .cli.repl_commands import _handle_doctor
        _handle_doctor()
        return 0

    # evolve 命令 — 启动自主迭代优化
    if args.command == 'evolve':
        import asyncio

        from .agent.evolution.optimizer import IterativeOptimizer
        optimizer = IterativeOptimizer(interval=args.interval)
        print(f"[*] 启动自主迭代优化引擎 (间隔: {args.interval}s)...")

        async def _run_forever():
            await optimizer.start()
            try:
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await optimizer.stop()

        try:
            asyncio.run(_run_forever())
        except KeyboardInterrupt:
            print("\n[*] 正在停止优化引擎...")
        return 0

    handler = get_command_handler(args.command)
    if handler is None:
        parser.error(f'未知命令: {args.command}')
        return 2

    try:
        result = handler(args)
        if result.output:
            print(result.output)
        return result.exit_code
    except ClawdError as e:
        # 结构化异常处理 - 输出错误码和建议
        print(f'[错误 {e.code.value}] {e.message}', file=sys.stderr)
        if e.details:
            print(f'详情: {e.details}', file=sys.stderr)
        if not e.recoverable:
            print('此错误需要人工干预。', file=sys.stderr)
        return 1
    except Exception as e:
        print(f'错误: 执行命令 "{args.command}" 时发生异常: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

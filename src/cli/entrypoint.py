from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from .. import __version__
from ..core.exceptions import ClawdError
from ..main import _register_shutdown_hooks, initialize

# 初始化 Typer
app = typer.Typer(
    name="clawd",
    help="Clawd Code - 企业级 AI 编程代理框架",
    add_completion=True,
    rich_markup_mode="rich",
)

console = Console()

def version_callback(value: bool):
    if value:
        console.print(f"Clawd Code [bold cyan]v{__version__}[/bold cyan]")
        raise typer.Exit()

@app.callback()
def common(
    ctx: typer.Context,
    version: bool | None = typer.Option(
        None, "--version", "-v", help="显示版本信息", callback=version_callback
    ),
):
    """
    [bold green]Clawd Code CLI[/bold green] - 您的自动进化编程助手
    """
    # 执行原有初始化逻辑
    initialize()

@app.command(name="chat")
def chat(
    max_iterations: int = typer.Option(10, "--max-iterations", "-i", help="最大迭代次数"),
    tui: bool = typer.Option(False, "--tui", help="使用全屏 TUI 仪表盘"),
):
    """
    启动交互式 AI 编程对话 (类似 Claude Code)
    """
    from ..cli.repl import start_repl
    from ..core.project_context import ProjectContext

    workdir = Path.cwd()
    project_ctx = ProjectContext(workdir=workdir)
    project_ctx.ensure_dirs()

    console.print(Panel(f"进入交互模式 (工作目录: [bold]{workdir}[/bold])", border_style="cyan"))

    try:
        exit_code = start_repl(
            workdir=workdir,
            max_iterations=max_iterations,
            use_textual_tui=tui,
            project_ctx=project_ctx,
        )
        raise typer.Exit(code=exit_code)
    except Exception as e:
        console.print(f"[bold red]错误:[/bold red] {e}")
        raise typer.Exit(code=1)

@app.command(name="workflow")
def workflow_run(
    goal: str = typer.Argument(..., help="工作流目标描述"),
    iterations: int = typer.Option(3, "--iterations", "-i", help="最大迭代次数"),
    isolation: bool = typer.Option(True, "--isolation/--no-isolation", help="是否启用工作树隔离"),
    budget: str | None = typer.Option(None, "--budget", "-b", help="运行预算 (如 1h, 10usd)"),
    recover: bool = typer.Option(False, "--recover", help="从上次中断的状态恢复"),
    intent: str = typer.Option("implement", "--intent", help="执行意图: implement (实现), debate (辩论/设计), explore (探索)"),
    dimensions: list[str] = typer.Option([], "--dimension", "-d", help="启用维度引导 (如: creative, adversarial, audit)"),
):
    """
    执行自动化工作流 (识别 -> 规划 -> 执行 -> 审查 -> 发现)
    """
    import asyncio

    from ..core.config.injector import set_config
    from ..workflow.engine import WorkflowEngine

    workdir = Path.cwd()
    engine = WorkflowEngine(workdir=workdir, max_iterations=iterations, budget_str=budget)
    engine._use_isolation = isolation

    # 注入运行时配置
    os.environ["CLAWD_WORKFLOW_INTENT"] = intent
    if dimensions:
        set_config("dimensions", dimensions)

    console.print(Panel(
        f"启动工作流: [bold green]{goal}[/bold green]\n"
        f"工作目录: {workdir}\n"
        f"执行意图: [cyan]{intent}[/cyan]\n"
        f"激活维度: [yellow]{', '.join(dimensions) if dimensions else '默认'}[/yellow]",
        title="Workflow Engine"
    ))

    try:
        result = asyncio.run(engine.run(goal, recover=recover))
        console.print("\n[bold green]工作流执行完成![/bold green]")
        console.print(result.report)
        if result.status == "failed":
            raise typer.Exit(code=1)
    except ClawdError as e:
        console.print(f"[bold red][错误 {e.code.value}][/bold red] {e.message}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[bold red]意外错误:[/bold red] {e}")
        raise typer.Exit(code=1)

@app.command(name="doctor")
def doctor():
    """
    运行环境诊断 (检查 API、依赖和配置)
    """
    from ..cli.repl_commands import _handle_doctor
    _handle_doctor()

@app.command(name="explore")
def explore(
    goal: str = typer.Argument(..., help="探索目标描述"),
    depth: int = typer.Option(2, "--depth", "-d", help="探索深度"),
    format: str = typer.Option("markdown", "--format", "-f", help="输出格式: markdown, tree, json"),
    readonly: bool = typer.Option(True, "--readonly/--no-readonly", help="只读模式"),
):
    """
    只读探索模式 - 分析代码库而不修改
    """
    from ..cli.commands.explore import explore_command

    console.print(Panel(f"探索模式: {goal}", title="Explore Mode", border_style="cyan"))
    explore_command(goal=goal, depth=depth, output_format=format)

@app.command(name="pipeline")
def pipeline(
    goal: str = typer.Argument(..., help="流水线执行目标"),
    no_team: bool = typer.Option(False, "--no-team", help="跳过团队执行阶段 (直接使用Workflow)"),
    no_ralph: bool = typer.Option(False, "--no-ralph", help="跳过Ralph验证阶段"),
    budget: str | None = typer.Option(None, "--budget", "-b", help="预算限制 (如 1h, 10usd)"),
):
    """
    执行完整流水线: RALPLAN(共识规划) → TEAM(并行执行) → RALPH(验证循环)

    完整流程:
        1. Ralplan: Planner-Architect-Critic 三角达成共识
        2. Team: TMUX 团队并行执行子任务
        3. Ralph: 持久化循环直到验证通过
    """
    import asyncio

    from ..workflow.pipeline_orchestrator import PipelineConfig, PipelineOrchestrator

    config = PipelineConfig(
        use_team=not no_team,
        use_ralph=not no_ralph,
        budget=budget,
    )
    orchestrator = PipelineOrchestrator(Path.cwd(), config)

    async def _run():
        result = await orchestrator.execute(goal)

        console.print("\n[bold green]流水线执行报告[/bold green]")
        console.print(f"目标: {result.goal}")
        console.print(f"最终状态: {result.final_status}")

        if result.consensus_plan:
            console.print(f"计划信心: {result.consensus_plan.confidence:.2f}")
            console.print(f"任务数: {len(result.consensus_plan.tasks)}")

        if result.team_result:
            console.print(f"团队执行: {result.team_result.get('status', 'unknown')}")

        if result.ralph_result:
            console.print(f"Ralph迭代: {result.ralph_result.get('iterations', 0)} 次")

        if result.artifacts:
            console.print("制品:")
            for name, path in result.artifacts.items():
                console.print(f"  - {name}: {path}")

    asyncio.run(_run())

@app.command(name="ralplan")
def ralplan_cli(
    goal: str = typer.Argument(..., help="需要共识规划的目标"),
    rounds: int = typer.Option(3, "--rounds", "-r", help="最大答辩轮次"),
    min_confidence: float = typer.Option(0.8, "--min-confidence", help="最低信心阈值"),
):
    """
    运行 RALPLAN 共识规划 (Planner-Architect-Critic 三角)

    不执行，仅生成并批准计划。输出 consensus.json 供后续流水线使用。
    """
    import asyncio

    from ..workflow.ralplan import RalplanEngine

    engine = RalplanEngine(
        Path.cwd(),
        max_rounds=rounds,
        min_confidence=min_confidence,
    )

    async def _run():
        plan = await engine.run(goal)

        console.print("\n[bold green]共识计划达成[/bold green]")
        console.print(f"目标: {plan.goal}")
        console.print(f"核心目标: {plan.objective}")
        console.print(f"信心指数: {plan.confidence:.2f}")
        console.print(f"任务数: {len(plan.tasks)}")
        console.print(f"风险数: {len(plan.risks)}")
        console.print(f"批准者: {plan.validator}")

        if plan.chosen_option:
            console.print(f"\n方案选择: {plan.chosen_option.name}")
            console.print(f"理由: 优点 {len(plan.chosen_option.pros)} 项, 缺点 {len(plan.chosen_option.cons)} 项")

        console.print("\n计划已保存至: .clawd/plan/consensus.json")

    asyncio.run(_run())

@app.command(name="quality-gate")
def quality_gate(
    level: str = typer.Option("task", "--level", "-l", help="质量门级别: commit, task, phase, release"),
    strict: bool = typer.Option(False, "--strict", help="严格模式: 警告也阻断"),
):
    """
    运行质量门检查 (lint, typecheck, tests, security)

    使用: clawd quality-gate --level=task
    """
    from ..core.quality_gate import GateLevel, QualityGate

    gate_level = GateLevel(level)
    gate = QualityGate(Path.cwd(), level=gate_level, strict=strict)

    report = gate.run()
    console.print(report.summary)

    if gate.overall.value == "fail":
        raise typer.Exit(code=1)

@app.command(name="hud")
def hud_start(
    mode: str = typer.Option("live", "--mode", "-m", help="显示模式: live, one-shot"),
    message: str | None = typer.Option(None, "--message", help="单次显示的消息"),
):
    """
    启动 HUD 状态显示器

    - live mode: 实时状态面板 (用于长时间任务)
    - one-shot mode: 单次显示重要状态
    """
    from ..cli.hud_improved import get_hud

    hud = get_hud()

    if mode == "one-shot" and message:
        hud.one_shot(message)
    else:
        console.print("[yellow]HUD live 模式暂未完全集成，使用简化输出[/yellow]")
        console.print("提示: 集成后将在后台显示持续状态")

@app.command(name="config")
def config(
    web: bool = typer.Option(False, "--web", help="启动可视化 Web 配置界面"),
    reset: bool = typer.Option(False, "--reset", help="重置所有配置为默认值"),
    report: bool = typer.Option(True, "--report", help="显示配置优先级链报告"),
    generate: bool = typer.Option(False, "--generate", "-g", help="生成Clawd Code扩展配置"),
    generate_path: Path | None = typer.Option(None, "--path", "-p", help="配置输出路径"),
):
    """
    管理配置、API Key 和系统设置

    新增子命令:
        clawd config generate   - 动态生成并合并Clawd Code配置到Codex
    """
    if web:
        from ..cli.web_config import start_web_config
        start_web_config()
    elif reset:
        from ..core.config.injector import get_config_injector
        get_config_injector().clear_runtime_overrides()
        console.print("[bold green]运行时覆盖配置已重置。[/bold green]")
    elif generate:
        from ..core.config.generator import config_generate_command
        config_generate_command(
            config_path=generate_path,
            dry_run=False,
            verbose=True,
        )
    elif report:
        from ..core.config.runtime import get_config_priority_report
        console.print(get_config_priority_report())
        console.print("\n[yellow]提示: 使用 `clawd config --web` 可启动可视化中文配置界面[/yellow]")


# ========== 注册子命令模块（oh-my-codex 风格） ==========

def _register_command_modules():
    """注册模块化命令 - 借鉴 oh-my-codex 的 CLI 组织方式"""
    # Agent 命令
    try:
        from .commands.agent_commands import register_agent_commands
        register_agent_commands(app)
    except ImportError:
        pass

    # Catalog 命令
    try:
        from .commands.catalog_commands import register_catalog_commands
        register_catalog_commands(app)
    except ImportError:
        pass

    # Workflow 命令
    try:
        from .commands.workflow_commands import register_workflow_commands
        register_workflow_commands(app)
    except ImportError:
        pass

    # Setup 命令
    try:
        from .commands.setup_commands import register_setup_commands
        register_setup_commands(app)
    except ImportError:
        pass


# 注册模块化命令
_register_command_modules()


def main():
    import atexit
    atexit.register(_register_shutdown_hooks)

    # 自动加载 Hooks 配置
    try:
        from ..core.hooks_config import load_hooks_config
        load_hooks_config(Path.cwd() / "hooks" / "config.toml")
    except Exception as e:
        import warnings
        warnings.warn(f"Hooks config load failed: {e}")

    # 启动通知分发器
    try:
        import asyncio

        from ..core.notifications.dispatcher import NotificationDispatcher
        dispatcher = NotificationDispatcher.get()
        asyncio.run(dispatcher.start())
    except Exception as e:
        import warnings
        warnings.warn(f"Notification dispatcher start failed: {e}")

    app()

if __name__ == "__main__":
    main()

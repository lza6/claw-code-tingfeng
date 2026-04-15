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

@app.command(name="config")
def config(
    web: bool = typer.Option(False, "--web", help="启动可视化 Web 配置界面"),
    reset: bool = typer.Option(False, "--reset", help="重置所有配置为默认值"),
    report: bool = typer.Option(True, "--report", help="显示配置优先级链报告"),
):
    """
    管理配置、API Key 和系统设置
    """
    if web:
        from ..cli.web_config import start_web_config
        start_web_config()
    elif reset:
        from ..core.config.injector import get_config_injector
        get_config_injector().clear_runtime_overrides()
        console.print("[bold green]运行时覆盖配置已重置。[/bold green]")
    elif report:
        from ..core.config.runtime import get_config_priority_report
        console.print(get_config_priority_report())
        console.print("\n[yellow]提示: 使用 `clawd config --web` 可启动可视化中文配置界面[/yellow]")

def main():
    import atexit
    atexit.register(_register_shutdown_hooks)
    app()

if __name__ == "__main__":
    main()

"""
工作流命令模块：ralph, ralplan, team, autopilot

参考：oh-my-codex-main/src/cli/ralph.ts, team.ts
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from ...workflow.pipeline_orchestrator import (
    can_resume_pipeline,
    create_ralph_verify_stage,
    create_ralplan_stage,
    create_team_exec_stage,
    read_pipeline_state,
)

app = typer.Typer(help="工作流编排命令")
console = Console()


# ========== RALPH 持久化完成循环 ==========

@app.command("ralph")
def ralph_run(
    goal: str = typer.Argument(..., help="要完成的目标"),
    iterations: int = typer.Option(10, "--iterations", "-i", help="最大迭代次数"),
    verify: bool = typer.Option(True, "--verify/--no-verify", help="是否启用验证"),
    recover: bool = typer.Option(False, "--recover", help="从上次中断恢复"),
    agent: str = typer.Option("executor", "--agent", "-a", help="使用的 Agent"),
):
    """
    持久化完成循环：反复执行直到任务完成。

    对应 oh-my-codex $ralph skill。
    基于 Ralph Ledger 追踪进度，循环执行 + 验证。
    """
    from ...agent.definitions import get_agent
    from ...agent.swarm.orchestrator import SwarmOrchestrator
    from ...workflow.ralph_ledger import RalphLedger

    workdir = Path.cwd()
    ledger = RalphLedger(workdir)

    console.print(Panel(
        f"[bold cyan]RALPH 完成循环[/bold cyan]\n"
        f"目标: {goal}\n"
        f"Agent: {agent}\n"
        f"最大迭代: {iterations}",
        border_style="cyan"
    ))

    # 恢复检查
    if recover or can_resume_pipeline(str(workdir)):
        state = read_pipeline_state(str(workdir))
        if state:
            console.print(f"[green]检测到可恢复状态: 阶段 {state.pipeline_stage_index}[/green]")

    async def run_ralph_loop():
        orchestrator = SwarmOrchestrator()
        current_iter = ledger.current_iteration or 0

        while current_iter < iterations:
            current_iter += 1
            ledger.start_iteration(current_iter)

            console.print(f"\n[bold]迭代 {current_iter}/{iterations}[/bold]")

            try:
                # 使用指定 agent 执行
                result = await orchestrator.execute_task(
                    task_description=goal,
                    agent_name=agent,
                    context={
                        "iteration": current_iter,
                        "ledger": ledger,
                        "recover": recover and current_iter == 1,
                    },
                )

                ledger.record_iteration_result(
                    iteration=current_iter,
                    success=result.get("success", False),
                    artifacts=result.get("artifacts", {}),
                )

                # 验证
                if verify:
                    verifier = get_agent("verifier")
                    verify_result = await verifier.verify(
                        task=goal,
                        artifacts=result.get("artifacts", {}),
                    )

                    if verify_result.get("complete", False):
                        console.print("[bold green]✓ 任务完成并通过验证[/bold green]")
                        ledger.mark_complete()
                        ledger.finalize(success=True)
                        return True
                    else:
                        reason = verify_result.get("reason", "验证未通过")
                        console.print(f"[yellow]⚠ {reason}[/yellow]")
                        ledger.record_verification_failure(reason)
                else:
                    if result.get("success", False):
                        console.print("[green]✓ 执行成功[/green]")
                        ledger.mark_complete()
                        ledger.finalize(success=True)
                        return True

            except Exception as e:
                console.print(f"[red]✗ 迭代失败: {e}[/red]")
                ledger.record_error(current_iter, str(e))

            ledger.finalize_iteration()

        console.print("[yellow]达到最大迭代上限[/yellow]")
        return False

    success = asyncio.run(run_ralph_loop())

    # 显示摘要
    summary = ledger.get_summary()
    console.print("\n" + summary)

    raise typer.Exit(0 if success else 1)


# ========== RALPLAN 共识规划 ==========

@app.command("ralplan")
def ralplan_run(
    task: str = typer.Argument(..., help="规划任务描述"),
    output: str | None = typer.Option(None, "--output", "-o", help="计划输出目录"),
    max_iterations: int = typer.Option(3, "--max-iterations", "-m", help="最大规划迭代"),
    no_critic: bool = typer.Option(False, "--no-critic", help="禁用 Critic 挑战"),
    no_architect: bool = typer.Option(False, "--no-architect", help="禁用 Architect 审查"),
):
    """
    共识规划：Planner + Architect + Critic 三方博弈生成计划。

    对应 oh-my-codex $ralplan skill。

    产出物：
    - PRD (产品需求文档)
    - 架构设计文档
    - 实施计划
    - 测试策略
    """
    from ...workflow.ralplan import RalplanWorkflow

    workdir = Path.cwd()
    output_dir = Path(output) if output else workdir / ".clawd" / "plans"
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        f"[bold cyan]RALPLAN 共识规划[/bold cyan]\n"
        f"任务: {task}\n"
        f"最大迭代: {max_iterations}\n"
        f"Architect: {'✓' if not no_architect else '✗'}\n"
        f"Critic: {'✓' if not no_critic else '✗'}",
        border_style="cyan"
    ))

    async def run_planning():
        workflow = RalplanWorkflow(
            workdir=workdir,
            output_dir=output_dir,
            max_iterations=max_iterations,
            enable_architect=not no_architect,
            enable_critic=not no_critic,
        )
        result = await workflow.execute(task)

        if result.success:
            console.print("[bold green]✓ 规划完成[/bold green]")
            for key, path in result.paths.items():
                if path:
                    console.print(f"  [cyan]{key}:[/cyan] {path}")
        else:
            console.print(f"[bold red]✗ 规划失败:[/bold red] {result.error}")

    asyncio.run(run_planning())


# ========== TEAM 团队执行 ==========

@app.command("team")
def team_run(
    goal: str = typer.Argument(..., help="团队执行目标"),
    workers: int = typer.Option(2, "--workers", "-w", min=1, max=6, help="Worker 数量 (1-6)"),
    agent_type: str = typer.Option("executor", "--agent", "-a", help="Agent 类型"),
    parallel: bool = typer.Option(True, "--parallel/--sequential", help="并行或顺序"),
    decompose: bool = typer.Option(True, "--decompose/--no-decompose", help="自动分解任务"),
    session: str | None = typer.Option(None, "--session", "-s", help="恢复指定会话"),
):
    """
    团队执行：协调多个 agent 并行完成复杂任务。

    对应 oh-my-codex $team skill。

    选项：
    - Workers: 同时执行的 worker 数量
    - Agent type: 使用的 agent 角色
    - 并行/顺序: 任务调度策略
    - 自动分解: 使用 planner 将大任务分解为子任务
    """
    from ...agent.swarm.orchestrator import SwarmOrchestrator
    from ...agent.swarm.subagent_tracker import SubagentTracker

    workdir = Path.cwd()

    console.print(Panel(
        f"[bold cyan]TEAM 执行[/bold cyan]\n"
        f"目标: {goal}\n"
        f"Workers: {workers}\n"
        f"Agent: {agent_type}\n"
        f"模式: {'并行' if parallel else '顺序'}\n"
        f"会话: {session or '新会话'}",
        border_style="cyan"
    ))

    async def run_team():
        orchestrator = SwarmOrchestrator()

        if decompose:
            console.print("[dim]分解任务...[/dim]")
            subtasks = await orchestrator.decompose_task(goal)
            console.print(f"  分解为 {len(subtasks)} 个子任务")

        if session:
            tracker = SubagentTracker(workdir)
            tracker.resume(session)
            console.print(f"[green]恢复会话: {session}[/green]")

        result = await orchestrator.coordinate_task(
            task=goal,
            worker_count=workers,
            agent_type=agent_type,
            parallel=parallel,
        )

        if result.success:
            console.print("[bold green]✓ 团队执行完成[/bold green]")
            console.print(f"  完成: {len(result.completed)}/{result.total}")
            console.print(f"  总耗时: {result.duration_ms / 1000:.1f}s")
        else:
            console.print(f"[bold red]✗ 执行失败:[/bold red] {result.error}")
            if result.failed_tasks:
                console.print(f"  失败任务: {result.failed_tasks}")

        # 保存会话
        if result.session_id:
            console.print(f"  会话 ID: {result.session_id}")

    asyncio.run(run_team())


# ========== AUTOPILOT 全自动管道 ==========

@app.command("autopilot")
def autopilot_run(
    goal: str = typer.Argument(..., help="自动执行目标"),
    workers: int = typer.Option(2, "--workers", "-w", help="Worker 数量"),
    ralph_iterations: int = typer.Option(10, "--ralph-iterations", "-i", help="ralph 迭代上限"),
    no_plan: bool = typer.Option(False, "--no-plan", help="跳过 ralplan 阶段"),
    recover: bool = typer.Option(False, "--recover", help="从中断处恢复"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
):
    """
    全自动管道: ralplan → team-exec → ralph-verify

    对应 oh-my-codex $autopilot skill。

    一站式完成从规划到实现到验证的完整流程。
    """
    from ...workflow.pipeline import PipelineOrchestrator

    workdir = Path.cwd()

    console.print(Panel(
        f"[bold cyan]AUTOPILOT 全自动管道[/bold cyan]\n"
        f"目标: {goal}\n"
        f"Workers: {workers}\n"
        f"Ralph 迭代: {ralph_iterations}\n"
        f"阶段: {'跳过规划' if no_plan else '完整'}",
        border_style="cyan"
    ))

    # 构建 pipeline 阶段
    from .workflow_commands import create_autopilot_pipeline_config

    stages = []
    if not no_plan:
        stages.append(create_ralplan_stage())
    stages.append(create_team_exec_stage(worker_count=workers))
    stages.append(create_ralph_verify_stage(max_iterations=ralph_iterations))

    config = create_autopilot_pipeline_config(
        task=goal,
        stages=stages,
        cwd=str(workdir),
        worker_count=workers,
        max_ralph_iterations=ralph_iterations,
    )

    async def run_pipeline():
        orchestrator = PipelineOrchestrator(config, cwd=str(workdir), validate=True)

        # 恢复检查
        if can_resume_pipeline(str(workdir)):
            if recover or typer.confirm("发现可恢复的 pipeline，继续？"):
                console.print("[green]从上次中断处恢复[/green]")
            else:
                console.print("[yellow]从头开始[/yellow]")
                # 清理状态
                from ...workflow.mode_state import ModeStateManager
                ModeStateManager(str(workdir)).cancel_mode("autopilot")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task_p = progress.add_task("执行 pipeline...", total=None)
            result = await orchestrator.run()
            progress.update(task_p, completed=True)

        if result.status == "completed":
            console.print("[bold green]✓ 管道执行完成[/bold green]")
            console.print(f"  总耗时: {result.duration_ms / 1000:.2f}s")
            console.print(f"  阶段数: {len(result.stage_results)}")
        elif result.status == "failed":
            console.print(f"[bold red]✗ 管道失败:[/bold red] {result.error}")
            if result.failed_stage:
                console.print(f"  失败阶段: {result.failed_stage}")
        else:
            console.print(f"[yellow]状态: {result.status}[/yellow]")

        # 输出详细报告
        if verbose and result.stage_results:
            console.print("\n[bold]阶段详情:[/bold]")
            for name, stage_result in result.stage_results.items():
                status_icon = {"completed": "✓", "failed": "✗", "skipped": "○"}.get(
                    stage_result.status, "?"
                )
                console.print(f"  {status_icon} {name}: {stage_result.status}")

    asyncio.run(run_pipeline())


def register_workflow_commands(app: typer.Typer) -> None:
    """注册所有 workflow 命令"""
    app.add_typer(app, name="workflow")

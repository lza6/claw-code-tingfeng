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
from rich.progress import Progress, SpinnerColumn, TextColumn

from ...workflow.pipeline import (
    create_ralph_verify_stage,
    create_ralplan_stage,
    create_team_exec_stage,
)
from ...workflow.pipeline_orchestrator import can_resume_pipeline, read_pipeline_state

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

    ## 实现说明（v0.57.2 重写）

    原实现引用 `SwarmOrchestrator.execute_task()` 与 `RalphLedger` ——
    两者都不存在（`git log -S` 全历史为空），命令**一运行就 ImportError**。
    现改为使用真实存在的 API：

    - 执行：`SwarmEngine(config, workdir, intent).run(goal)`
    - 进度记录：`RalphProgressLedger`（纯数据结构，序列化为 JSON）

    `--verify`：本项目的验证阶段目前是**桩**（返回 `not_implemented`），
    因此这里不会假装"已验证通过"，只以 `SwarmResult.success` 作为完成信号，
    并在启用 `--verify` 时明确说明这一点。
    """
    import json

    from ...agent.swarm.config import SwarmConfig
    from ...agent.swarm.engine import SwarmEngine
    from ...workflow.ralph_ledger import RalphProgressLedger

    workdir = Path.cwd()
    ledger_dir = workdir / ".clawd" / "ralph"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_file = ledger_dir / "ledger.json"

    if ledger_file.exists():
        try:
            ledger = RalphProgressLedger.from_dict(
                json.loads(ledger_file.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, TypeError):
            ledger = RalphProgressLedger(source=goal, strategy=f"agent:{agent}")
    else:
        ledger = RalphProgressLedger(source=goal, strategy=f"agent:{agent}")

    console.print(Panel(
        f"[bold cyan]RALPH 完成循环[/bold cyan]\n"
        f"目标: {goal}\n"
        f"Agent: {agent}\n"
        f"最大迭代: {iterations}",
        border_style="cyan"
    ))

    if recover or can_resume_pipeline(str(workdir)):
        state = read_pipeline_state(str(workdir))
        if state:
            console.print(f"[green]检测到可恢复状态: 阶段 {state.pipeline_stage_index}[/green]")

    if verify:
        console.print(
            "[yellow]注意：验证阶段当前为未实现状态（返回 not_implemented），"
            "本次以执行成功与否作为完成信号。[/yellow]"
        )

    def _persist() -> None:
        ledger_file.write_text(
            json.dumps(ledger.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    async def run_ralph_loop() -> bool:
        for current_iter in range(1, iterations + 1):
            console.print(f"\n[bold]迭代 {current_iter}/{iterations}[/bold]")
            try:
                engine = SwarmEngine(
                    config=SwarmConfig(fallback_to_single_agent=True),
                    workdir=workdir,
                    intent="implement",
                )
                result = await engine.run(goal)
                ledger.entries.append({
                    "iteration": current_iter,
                    "success": bool(result.success),
                    "elapsed_seconds": getattr(result, "elapsed_seconds", None),
                    "summary": (getattr(result, "final_result", "") or "")[:800],
                    "errors": list(getattr(result, "errors", []) or [])[:5],
                })
                _persist()

                if result.success:
                    console.print("[bold green]✓ 任务完成[/bold green]")
                    console.print((result.final_result or "")[:2000])
                    return True
                console.print("[yellow]本轮未完成，继续下一轮[/yellow]")
            except Exception as e:
                console.print(f"[red]✗ 迭代失败: {e}[/red]")
                ledger.entries.append({
                    "iteration": current_iter,
                    "success": False,
                    "error": f"{type(e).__name__}: {e}",
                })
                _persist()

        console.print("[yellow]达到最大迭代上限[/yellow]")
        return False

    success = asyncio.run(run_ralph_loop())
    console.print(f"\n进度账本: {ledger_file}")
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

    产物写入 `--output`（默认 `<cwd>/.clawd/plans/ralplan.json`）。
    """
    import json

    from ...workflow.ralplan import RalplanEngine

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

    if no_architect or no_critic:
        console.print(
            "[yellow]注意：RalplanEngine 未提供单独关闭 Architect/Critic 的开关，"
            "本轮仍执行完整三方流程；如需精简请调整 --max-iterations。[/yellow]"
        )

    async def run_planning() -> int:
        engine = RalplanEngine(workdir=workdir, max_rounds=max_iterations)
        plan = await engine.run(task)

        payload = {
            "goal": plan.goal,
            "objective": plan.objective,
            "chosen_option": plan.chosen_option,
            "confidence": plan.confidence,
            "tasks": plan.tasks,
            "prd": plan.prd,
            "architecture": plan.architecture,
            "risks": plan.risks,
            "mitigations": plan.mitigations,
            "version": plan.version,
            "created_at": plan.created_at,
        }
        out_path = output_dir / "ralplan.json"
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        console.print("[bold green]✓ 规划完成[/bold green]")
        console.print(f"  置信度: {plan.confidence}")
        console.print(f"  任务数: {len(plan.tasks) if plan.tasks else 0}")
        console.print(f"  输出: {out_path}")
        return 0

    raise typer.Exit(asyncio.run(run_planning()))


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

    async def run_team() -> int:
        # 真实入口是 SwarmEngine（多 agent 编排），不是不存在的 SwarmOrchestrator。
        from ...agent.swarm.config import SwarmConfig
        from ...agent.swarm.engine import SwarmEngine
        from ...agent.swarm.subagent_tracker import SubagentTracker

        # 会话追踪：把本次团队执行登记为一个线程，便于事后查看摘要。
        tracker = SubagentTracker(str(workdir / ".clawd" / "subagents"))
        if session:
            tracker.set_session_id(session)
            console.print(f"[green]会话: {session}[/green]")
        tracker.register_thread("swarm-main", kind="orchestrator")

        # --no-parallel 映射为单 worker；Swarm 本身总会做任务分解，
        # `--no-decompose` 无法关闭（下面如实提示，而不是静默忽略）。
        effective_workers = workers if parallel else 1
        if not decompose:
            console.print(
                "[yellow]注意：SwarmEngine 总会先分解任务，--no-decompose 无法关闭。[/yellow]"
            )

        cfg = SwarmConfig(
            max_workers=effective_workers,
            fallback_to_single_agent=True,
            enable_auditor=True,
            enable_reviewer=True,
        )
        engine = SwarmEngine(config=cfg, workdir=workdir, intent=agent_type)

        console.print("[dim]启动 Swarm 协作...[/dim]")
        try:
            result = await engine.run(goal)
        finally:
            tracker.mark_thread_completed("swarm-main")

        summary = tracker.get_summary()
        console.print(f"[dim]会话线程: {summary.total_threads} 个[/dim]")

        if result.success:
            console.print("[bold green]✓ 团队执行完成[/bold green]")
            console.print(f"  耗时: {getattr(result, 'elapsed_seconds', 0):.1f}s")
            console.print((result.final_result or "")[:2000])
            return 0

        console.print(f"[bold red]✗ 执行失败:[/bold red] {'; '.join(result.errors or [])}")
        return 1

    raise typer.Exit(asyncio.run(run_team()))


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
    from ...workflow.pipeline_orchestrator import (
        PipelineOrchestrator,
        create_autopilot_pipeline_config,
    )

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
    # 原实现 `from .workflow_commands import create_autopilot_pipeline_config`
    # 是从**自身模块**导入一个本地从未定义的名字 —— 必然 ImportError。
    # 真实定义在 workflow.pipeline_orchestrator（见文件顶部导入）。
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


def register_workflow_commands(parent_app: typer.Typer) -> None:
    """把 workflow 子命令树挂到父 app 上。

    形参不能改名回 `app`：那会造成 `app.add_typer(app, ...)` 自引用。
    详见 setup_commands.register_setup_commands 的同类说明。
    """
    parent_app.add_typer(app, name="workflow")

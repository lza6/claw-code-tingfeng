from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..core.persistence.run_state import RunStateManager

console = Console()

def show_runs_status(workdir: Path):
    """显示所有运行中的任务状态 (汲取 GoalX status)"""
    runs_dir = workdir / ".clawd" / "runs"
    if not runs_dir.exists():
        console.print("[yellow]当前没有运行中的任务。[/yellow]")
        return

    table = Table(title="Clawd Code — 活跃任务状态 (汲取 GoalX)", expand=True)
    table.add_column("Run ID", style="cyan", no_wrap=True)
    table.add_column("目标 (Goal)", style="white")
    table.add_column("状态", style="bold")
    table.add_column("进度", justify="right")
    table.add_column("更新时间", style="dim")

    for run_path in runs_dir.iterdir():
        if not run_path.is_dir():
            continue

        manager = RunStateManager(workdir, run_id=run_path.name)
        data = manager.load()
        if not data:
            continue

        goal = data.get("goal", "未知")
        tasks = data.get("tasks", [])
        total = len(tasks)
        satisfied = sum(1 for t in tasks if t.get("status") in ["claimed", "success", "waived"])

        status_text = "活跃" if satisfied < total else "完成"
        status_style = "green" if status_text == "完成" else "bold blue"

        progress = f"{satisfied}/{total}" if total > 0 else "0/0"
        updated_at = data.get("updated_at", "").split("T")[-1][:8] # 仅显示时间部分

        table.add_row(
            run_path.name,
            goal[:50] + "..." if len(goal) > 50 else goal,
            Text(status_text, style=status_style),
            progress,
            updated_at
        )

    console.print(table)

def show_run_detail(workdir: Path, run_id: str):
    """显示特定运行的详细信息 (汲取 GoalX observe)"""
    manager = RunStateManager(workdir, run_id=run_id)
    data = manager.load()
    if not data:
        console.print(f"[red]未找到运行 ID: {run_id}[/red]")
        return

    console.print(Panel(f"[bold cyan]Run Detail: {run_id}[/bold cyan]\n[white]{data.get('goal')}[/white]"))

    # 任务表格
    task_table = Table(title="任务分解 (Obligations)", box=None)
    task_table.add_column("ID", style="dim")
    task_table.add_column("任务描述", width=60)
    task_table.add_column("状态", justify="center")

    for t in data.get("tasks", []):
        status = t.get("status", "open")
        style = "green" if status in ["claimed", "success"] else "yellow"
        task_table.add_row(
            t.get("task_id", ""),
            t.get("text", ""),
            Text(status, style=style)
        )

    console.print(task_table)

#!/usr/bin/env python3
"""
Surface Viewer - Diagnostic tool for Durable Surfaces
Allows humans to inspect the persistent state of Swarm runs.
"""

import argparse
import json
from pathlib import Path
import sys

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.syntax import Syntax

# Optional import, fail gracefully if not run within the project context
try:
    from src.core.durable.surface_manager import SurfaceManager
    from src.core.durable.surfaces.status_summary import StatusSummary
    from src.core.durable.surfaces.coordination_state import CoordinationState
    from src.core.durable.surfaces.obligation_model import ObligationModel
    from src.core.durable.surfaces.assurance_plan import AssurancePlan
    from src.core.durable.surfaces.evidence_log import EvidenceLog
except ImportError:
    print("Error: Must be run from the root of the claw-code-tingfeng project.")
    sys.exit(1)

console = Console()

def get_latest_run_id(workdir: Path) -> str:
    runs_dir = workdir / ".clawd" / "runs"
    if not runs_dir.exists():
        return None
    runs = sorted([d for d in runs_dir.iterdir() if d.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
    if not runs:
        return None
    return runs[0].name

def view_status_summary(manager: SurfaceManager):
    try:
        status = manager.load_surface("status_summary", StatusSummary, create_if_missing=False)

        table = Table(title="[bold blue]Status Summary[/bold blue]", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan")
        table.add_column("Value")

        table.add_row("Run ID", status.run_id)
        table.add_row("Phase", status.phase.value if hasattr(status.phase, 'value') else str(status.phase))
        table.add_row("Progress", f"{status.progress_percentage:.1f}%")
        table.add_row("Health", status.health_status)
        table.add_row("Activity", status.current_activity)
        table.add_row("Obligations", f"{status.obligations_satisfied} / {status.obligations_total}")

        console.print(table)

        if status.summary:
            console.print(Panel(Text(status.summary), title="Summary"))

        if status.errors:
            for err in status.errors:
                console.print(f"[bold red]ERROR:[/bold red] {err}")
    except Exception as e:
        console.print(f"[yellow]Could not load Status Summary: {e}[/yellow]")

def view_coordination_state(manager: SurfaceManager):
    try:
        coord = manager.load_surface("coordination_state", CoordinationState, create_if_missing=False)

        table = Table(title="[bold green]Active Sessions[/bold green]")
        table.add_column("Session ID", style="cyan")
        table.add_column("State", style="magenta")
        table.add_column("Assigned Tasks", style="yellow")
        table.add_column("Last Activity", style="dim")

        for s_id, session in coord.sessions.items():
            tasks = ", ".join(session.assigned_obligations) if session.assigned_obligations else "None"
            state = session.state.value if hasattr(session.state, 'value') else str(session.state)
            table.add_row(s_id, state, tasks, session.last_activity)

        console.print(table)
    except Exception as e:
        console.print(f"[yellow]Could not load Coordination State: {e}[/yellow]")

def view_obligations(manager: SurfaceManager):
    try:
        model = manager.load_surface("obligation_model", ObligationModel, create_if_missing=False)

        table = Table(title="[bold yellow]Obligations (Tasks)[/bold yellow]")
        table.add_column("ID", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Evidence", style="green")
        table.add_column("Description")

        for obl in model.all_obligations():
            status = obl.status.value if hasattr(obl.status, 'value') else str(obl.status)
            evidence = f"{len(obl.evidence_paths)} items" if obl.evidence_paths else "None"
            desc = obl.text[:50] + "..." if len(obl.text) > 50 else obl.text

            # Color code status
            if status == "satisfied" or status == "completed":
                status = f"[green]{status}[/green]"
            elif status == "failed":
                status = f"[red]{status}[/red]"
            elif status == "open":
                status = f"[dim]{status}[/dim]"

            table.add_row(obl.id, status, evidence, desc)

        console.print(table)
    except Exception as e:
        console.print(f"[yellow]Could not load Obligation Model: {e}[/yellow]")

def main():
    parser = argparse.ArgumentParser(description="View Durable Surfaces for a Swarm Run")
    parser.add_argument("--run-id", type=str, help="Specific Run ID to inspect. Defaults to latest.")
    parser.add_argument("--workdir", type=str, default=".", help="Project working directory.")
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    run_id = args.run_id or get_latest_run_id(workdir)

    if not run_id:
        console.print("[bold red]No runs found in .clawd/runs/[/bold red]")
        sys.exit(1)

    run_dir = workdir / ".clawd" / "runs" / run_id
    if not run_dir.exists():
        console.print(f"[bold red]Run directory not found: {run_dir}[/bold red]")
        sys.exit(1)

    console.print(f"[bold]Inspecting Run:[/bold] [cyan]{run_id}[/cyan]\n")

    manager = SurfaceManager(run_dir)

    view_status_summary(manager)
    print()
    view_coordination_state(manager)
    print()
    view_obligations(manager)

if __name__ == "__main__":
    main()

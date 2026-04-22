"""
Catalog 命令：技能和代理清单管理

参考：oh-my-codex-main/src/cli/catalog-contract.ts
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ...catalog import get_catalog, reload_catalog

app = typer.Typer(help="技能和代理清单管理")
console = Console()


@app.command("list")
def catalog_list(
    skills_only: bool = typer.Option(False, "--skills", "-s", help="只显示技能"),
    agents_only: bool = typer.Option(False, "--agents", "-a", help="只显示 Agent"),
    active_only: bool = typer.Option(False, "--active", help="只显示活跃项"),
):
    """列出技能和 Agent 清单"""
    catalog = get_catalog()

    if not skills_only:
        table = Table(title="Agent 清单", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan")
        table.add_column("Category", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Canonical", style="dim")

        for agent in catalog.agents:
            if active_only and agent.status != "active":
                continue
            table.add_row(
                agent.name,
                agent.category,
                agent.status,
                agent.canonical or "",
            )
        console.print(table)
        console.print()

    if not agents_only:
        table = Table(title="Skill 清单", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan")
        table.add_column("Category", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Core", style="red")
        table.add_column("Canonical", style="dim")

        for skill in catalog.skills:
            if active_only and skill.status != "active":
                continue
            table.add_row(
                skill.name,
                skill.category,
                skill.status,
                "★" if skill.core else "",
                skill.canonical or "",
            )
        console.print(table)


@app.command("show")
def catalog_show(name: str = typer.Argument(..., help="技能或Agent名称")):
    """显示单个技能或Agent的详细信息"""
    catalog = get_catalog()

    # 先查找技能
    for skill in catalog.skills:
        if skill.name == name:
            console.print(f"\n[bold cyan]Skill:[/bold cyan] {skill.name}")
            console.print(f"  Category: {skill.category}")
            console.print(f"  Status: {skill.status}")
            console.print(f"  Core: {skill.core}")
            console.print(f"  Canonical: {skill.canonical or 'n/a'}")
            return

    # 再查找 Agent
    for agent in catalog.agents:
        if agent.name == name:
            console.print(f"\n[bold cyan]Agent:[/bold cyan] {agent.name}")
            console.print(f"  Category: {agent.category}")
            console.print(f"  Status: {agent.status}")
            console.print(f"  Canonical: {agent.canonical or 'n/a'}")
            return

    console.print(f"[bold red]未找到:[/bold red] {name}")


@app.command("reload")
def catalog_reload():
    """重新加载清单（从模板文件）"""
    new_catalog = reload_catalog()
    counts = catalog.get_counts()
    console.print("[bold green]清单已重新加载[/bold green]")
    console.print(f"  技能数: {counts.skill_count} (活跃: {counts.active_skill_count})")
    console.print(f"  Agent数: {counts.agent_count} (活跃: {counts.active_agent_count})")


@app.command("generate-manifest")
def generate_manifest(
    output: str = typer.Option("templates/catalog-manifest.json", "--output", "-o"),
    format: str = typer.Option("json", "--format", "-f"),
):
    """生成清单文件（供 Codex CLI 使用）"""
    # 该命令会生成类似 oh-my-codex 的 catalog-manifest.json
    # 用于 Codex CLI 的 agent catalog 功能
    console.print("[bold yellow]功能待实现[/bold yellow]")
    console.print("对应的 oh-my-codex 实现: src/catalog/reader.ts")


def register_catalog_commands(app: typer.Typer) -> None:
    """注册 catalog 命令"""
    app.add_typer(app, name="catalog")

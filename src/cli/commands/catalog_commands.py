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
    json_out: bool = typer.Option(False, "--json", help="机器可读输出"),
):
    """列出技能和 Agent 清单（`--json` 输出结构化清单，便于脚本/CI）"""
    catalog = get_catalog()

    agents_data = [
        {
            "name": a.name,
            "category": a.category,
            "status": a.status,
            "canonical": a.canonical or "",
        }
        for a in catalog.agents
        if not active_only or a.status == "active"
    ]
    skills_data = [
        {
            "name": sk.name,
            "category": sk.category,
            "status": sk.status,
            "core": bool(sk.core),
            "canonical": sk.canonical or "",
        }
        for sk in catalog.skills
        if not active_only or sk.status == "active"
    ]
    if json_out:
        from ..command_result import CommandResult, emit

        # 尊重 --skills / --agents 过滤（与终端输出保持一致）
        if skills_only:
            agents_data = []
        if agents_only:
            skills_data = []

        raise typer.Exit(emit(
            CommandResult(ok=True, data={
                "agents": agents_data,
                "skills": skills_data,
                "count": len(agents_data) + len(skills_data),
            }),
            as_json=True,
        ))

    if not skills_only:
        table = Table(title="Agent 清单", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan")
        table.add_column("Category", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Canonical", style="dim")

        for agent in agents_data:
            table.add_row(
                agent["name"],
                agent["category"],
                agent["status"],
                agent["canonical"],
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

        for skill in skills_data:
            table.add_row(
                skill["name"],
                skill["category"],
                skill["status"],
                "★" if skill["core"] else "",
                skill["canonical"],
            )
        console.print(table)


@app.command("show")
def catalog_show(
    name: str = typer.Argument(..., help="技能或Agent名称"),
    json_out: bool = typer.Option(False, "--json", help="机器可读输出"),
):
    """显示单个技能或 Agent 的详细信息（`--json` 输出结构化结构）"""
    catalog = get_catalog()

    def _emit(kind: str, item: dict) -> None:
        if not json_out:
            return
        from ..command_result import CommandResult, emit

        raise typer.Exit(emit(
            CommandResult(ok=True, data={"kind": kind, **item}),
            as_json=True,
        ))

    # 先查找技能
    for skill in catalog.skills:
        if skill.name == name:
            _emit("skill", {
                "name": skill.name, "category": skill.category, "status": skill.status,
                "core": bool(skill.core), "canonical": skill.canonical or "",
            })
            console.print(f"\n[bold cyan]Skill:[/bold cyan] {skill.name}")
            console.print(f"  Category: {skill.category}")
            console.print(f"  Status: {skill.status}")
            console.print(f"  Core: {skill.core}")
            console.print(f"  Canonical: {skill.canonical or 'n/a'}")
            return

    # 再查找 Agent
    for agent in catalog.agents:
        if agent.name == name:
            _emit("agent", {
                "name": agent.name, "category": agent.category, "status": agent.status,
                "canonical": agent.canonical or "",
            })
            console.print(f"\n[bold cyan]Agent:[/bold cyan] {agent.name}")
            console.print(f"  Category: {agent.category}")
            console.print(f"  Status: {agent.status}")
            console.print(f"  Canonical: {agent.canonical or 'n/a'}")
            return

    if json_out:
        from ..command_result import CommandResult, emit

        raise typer.Exit(emit(
            CommandResult(ok=False, data={"message": f"未找到: {name}"}, human=f"未找到: {name}"),
            as_json=True,
        ))
    console.print(f"[bold red]未找到:[/bold red] {name}")


@app.command("reload")
def catalog_reload():
    """重新加载清单（从模板文件）"""
    new_catalog = reload_catalog()
    counts = new_catalog.get_counts()
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


def register_catalog_commands(parent_app: typer.Typer) -> None:
    """把 catalog 子命令树挂到父 app 上。

    形参不能改名回 `app`：那会造成 `app.add_typer(app, ...)` 自引用。
    详见 setup_commands.register_setup_commands 的同类说明。
    """
    parent_app.add_typer(app, name="catalog")

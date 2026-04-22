"""
Agent 相关命令：agent 列表、详情、执行代理任务

参考：oh-my-codex-main/src/cli/agents.ts
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from ...agent.definitions import AGENT_DEFINITIONS, get_agent
from ...agent.keyword_registry import get_registered_keywords

app = typer.Typer(help="Agent 管理和执行命令")
console = Console()


@app.command("list")
def list_agents(
    category: str | None = typer.Option(None, "--category", "-c", help="按分类筛选"),
    format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
):
    """列出所有可用 Agent"""
    from ...agent.definitions import AgentCategory

    agents = list(AGENT_DEFINITIONS.values())

    # 分类过滤
    if category:
        try:
            cat = AgentCategory(category)
            agents = [a for a in agents if a.category == cat]
        except ValueError:
            console.print(f"[bold red]无效分类:[/bold red] {category}")
            raise typer.Exit(1)

    if format == "json":
        data = [
            {
                "name": a.name,
                "description": a.description,
                "category": a.category,
                "tools": a.tools,
                "modelClass": a.modelClass,
            }
            for a in sorted(agents, key=lambda x: x.name)
        ]
        console.print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        table = Table(title="可用 Agents", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Category", style="green")
        table.add_column("Tools", style="yellow")

        for a in sorted(agents, key=lambda x: x.name):
            table.add_row(a.name, a.description, a.category, a.tools)

        console.print(table)


@app.command("show")
def show_agent(
    name: str = typer.Argument(..., help="Agent 名称"),
):
    """显示单个 Agent 的详细信息"""
    agent = get_agent(name)
    if not agent:
        console.print(f"[bold red]未找到 Agent:[/bold red] {name}")
        raise typer.Exit(1)

    console.print(f"\n[bold cyan]Agent:[/bold cyan] {agent.name}")
    console.print(f"[bold]Description:[/bold] {agent.description}")
    console.print(f"[bold]Category:[/bold] {agent.category}")
    console.print(f"[bold]Routing Role:[/bold] {agent.routingRole}")
    console.print(f"[bold]Model Class:[/bold] {agent.modelClass}")
    console.print(f"[bold]Reasoning Effort:[/bold] {agent.reasoningEffort}")
    console.print(f"[bold]Tools Access:[/bold] {agent.tools}")
    console.print(f"[bold]Posture:[/bold] {agent.posture}")


@app.command("keywords")
def list_keywords():
    """列出所有已注册的关键词及其触发的技能"""
    from ...agent.intent_router import KEYWORD_TO_SKILL

    table = Table(title="技能关键词映射", show_header=True, header_style="bold magenta")
    table.add_column("Keyword", style="cyan")
    table.add_column("Skill", style="green")
    table.add_column("Primary", style="yellow")

    registry = get_registered_keywords()
    for kw, skill in sorted(registry.items()):
        is_primary = "✓" if KEYWORD_TO_SKILL.get(kw.lower()) == skill else ""
        table.add_row(kw, skill, is_primary)

    console.print(table)


def register_agent_commands(app: typer.Typer) -> None:
    """注册所有 agent 相关命令"""
    app.add_typer(app, name="agent")
    # 子命令已在定义时添加，这里只需确保模块被导入

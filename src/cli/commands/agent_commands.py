"""
Agent 相关命令：agent 列表、详情、执行代理任务

参考：oh-my-codex-main/src/cli/agents.ts
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ...agent.definitions import AGENT_DEFINITIONS, get_agent
from ...agent.keyword_registry import KEYWORD_TRIGGER_DEFINITIONS

app = typer.Typer(help="Agent 管理和执行命令")
console = Console()


@app.command("list")
def list_agents(
    category: str | None = typer.Option(None, "--category", "-c", help="按分类筛选"),
    format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
    json_out: bool = typer.Option(False, "--json", help="机器可读输出（契约 {ok, code, ...}）"),
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
            raise typer.Exit(1) from None

    # JSON 键名保持 camelCase（"modelClass"）以兼容既有下游脚本，
    # 而 Python 侧属性已统一为 snake_case。两者刻意不同，勿"顺手"统一。
    rows = [
        {
            "name": a.name,
            "description": a.description,
            "category": a.category,
            "tools": a.tools,
            "modelClass": a.model_class,
        }
        for a in sorted(agents, key=lambda x: x.name)
    ]

    if json_out or format == "json":
        # 统一契约 {ok, code, agents, count}：此前 `--format json` 直出裸数组，
        # 脚本只能猜结构；`--json` 与 `--format json` 共用同一份数据（同一契约，
        # 不维护两套 JSON 形态）。
        from ..command_result import CommandResult, emit

        raise typer.Exit(emit(
            CommandResult(
                ok=True,
                data={"agents": rows, "count": len(rows), "category": category},
            ),
            as_json=True,
        ))

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
    json_out: bool = typer.Option(False, "--json", help="机器可读输出（契约 {ok, code, ...}）"),
):
    """显示单个 Agent 的详细信息"""
    agent = get_agent(name)
    if not agent:
        if json_out:
            from ..command_result import CommandResult, emit

            raise typer.Exit(emit(
                CommandResult(
                    ok=False,
                    data={"error": f"未找到 Agent: {name}", "name": name},
                    human=f"未找到 Agent: {name}",
                ),
                as_json=True,
            ))
        console.print(f"[bold red]未找到 Agent:[/bold red] {name}")
        raise typer.Exit(1)

    if json_out:
        from ..command_result import CommandResult, emit

        raise typer.Exit(emit(
            CommandResult(
                ok=True,
                data={
                    "name": agent.name,
                    "description": agent.description,
                    "category": agent.category,
                    "routing_role": agent.routing_role,
                    "model_class": agent.model_class,
                    "reasoning_effort": agent.reasoning_effort,
                    "tools": agent.tools,
                    "posture": agent.posture,
                },
            ),
            as_json=True,
        ))

    console.print(f"\n[bold cyan]Agent:[/bold cyan] {agent.name}")
    console.print(f"[bold]Description:[/bold] {agent.description}")
    console.print(f"[bold]Category:[/bold] {agent.category}")
    console.print(f"[bold]Routing Role:[/bold] {agent.routing_role}")
    console.print(f"[bold]Model Class:[/bold] {agent.model_class}")
    console.print(f"[bold]Reasoning Effort:[/bold] {agent.reasoning_effort}")
    console.print(f"[bold]Tools Access:[/bold] {agent.tools}")
    console.print(f"[bold]Posture:[/bold] {agent.posture}")


@app.command("keywords")
def list_keywords(
    json_out: bool = typer.Option(False, "--json", help="机器可读输出（契约 {ok, code, ...}）"),
):
    """列出所有已注册的关键词及其触发的技能"""
    # 原实现从 intent_router 导入 `KEYWORD_TO_SKILL` —— 该符号从未存在，
    # 导致本模块导入即失败、整个 agent 命令组静默消失。
    # 真实的词→技能映射在 KEYWORD_TRIGGER_DEFINITIONS（keyword_registry）。
    triggers = sorted(
        KEYWORD_TRIGGER_DEFINITIONS,
        key=lambda t: (-t.priority, t.keyword),
    )

    if json_out:
        from ..command_result import CommandResult, emit

        rows = [
            {
                "keyword": t.keyword,
                "skill": t.skill,
                "priority": t.priority,
                "requires_intent": bool(t.requires_intent),
            }
            for t in triggers
        ]
        raise typer.Exit(emit(
            CommandResult(ok=True, data={"keywords": rows, "count": len(rows)}),
            as_json=True,
        ))

    table = Table(title="技能关键词映射", show_header=True, header_style="bold magenta")
    table.add_column("Keyword", style="cyan")
    table.add_column("Skill", style="green")
    table.add_column("Priority", justify="right")
    table.add_column("需明确意图", justify="center")

    for t in triggers:
        table.add_row(
            t.keyword,
            t.skill,
            str(t.priority),
            "是" if t.requires_intent else "",
        )

    console.print(table)
    console.print(f"[dim]共 {len(triggers)} 个关键词[/dim]")


@app.command("intent")
def classify_intent_cmd(
    text: str = typer.Argument(..., help="要分类的用户输入"),
    json_out: bool = typer.Option(False, "--json", help="机器可读输出（契约 {ok, code, ...}）"),
):
    """对一段输入做意图分类（DELIVER/EXPLORE/EVOLVE/IMPLEMENT/DEBATE）"""
    from ...agent.intent_router import classify_intent_ranked, get_primary_intent

    primary = get_primary_intent(text)
    ranked = classify_intent_ranked(text)

    if json_out:
        from ..command_result import CommandResult, emit

        raise typer.Exit(emit(
            CommandResult(
                ok=True,
                data={
                    "text": text,
                    "primary": str(getattr(primary, "value", primary)),
                    "ranked": [
                        {"intent": str(getattr(i, "value", i)), "score": score}
                        for i, score in ranked
                    ],
                },
            ),
            as_json=True,
        ))

    console.print(f"[bold cyan]主要意图:[/bold cyan] {primary}")
    if ranked:
        console.print("\n[bold]排序结果:[/bold]")
        for intent, score in ranked:
            console.print(f"  {intent:10} {score:.2f}")


def register_agent_commands(parent_app: typer.Typer) -> None:
    """把 agent 子命令树挂到父 app 上。

    注意: 形参不能叫 `app`。若写成 `app.add_typer(app, name="agent")`，
    在参数遮蔽模块级 `app` 的情况下等于把父应用注册到它自己身上，
    形成自引用。同类缺陷见 setup_commands.register_setup_commands。
    """
    parent_app.add_typer(app, name="agent")

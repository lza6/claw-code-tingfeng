from __future__ import annotations

import logging
import sys
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from .. import __version__
from ..core.exceptions import ClawdError
from ..main import _register_shutdown_hooks, initialize

logger = logging.getLogger(__name__)

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
    resume: str | None = typer.Option(
        None, "--resume", "-r", help="续聊某个已保存会话 ID（历史作为上下文，多轮累积）"
    ),
    role: str = typer.Option("", "--role", help="角色（personas/*.md 的名字），用 `clawd role list` 查看"),
):
    """
    启动交互式 AI 编程对话 (类似 Claude Code)
    """
    from ..cli.repl import start_repl
    from ..core.project_context import ProjectContext

    workdir = Path.cwd()
    project_ctx = ProjectContext(workdir=workdir)
    project_ctx.ensure_dirs()

    # 首次上手体检（onboarding 零件此前零调用点）：只在"真的什么都没配"时打扰一次
    try:
        from ..utils.onboarding import preflight_report

        preflight = preflight_report()
        if not preflight["ready"]:
            console.print(f"[yellow]提示:[/yellow] {preflight['hint']}")
            console.print("  运行 [bold]clawd onboard[/bold] 查看已有的密钥与推荐模型。")
    except Exception as e:  # noqa: BLE001 — 体检失败绝不能挡住 chat 启动
        console.print(f"[dim]上手体检跳过: {e}[/dim]")

    console.print(Panel(f"进入交互模式 (工作目录: [bold]{workdir}[/bold])", border_style="cyan"))

    try:
        exit_code = start_repl(
            workdir=workdir,
            max_iterations=max_iterations,
            use_textual_tui=tui,
            project_ctx=project_ctx,
            resume_session_id=resume,
            role=role,
        )
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[bold red]错误:[/bold red] {e}")
        raise typer.Exit(code=1)
    raise typer.Exit(code=exit_code)

@app.command(name="run")
def workflow_run(
    goal: str = typer.Argument(..., help="工作流目标描述"),
    iterations: int = typer.Option(3, "--iterations", "-i", help="最大迭代次数"),
    isolation: bool = typer.Option(True, "--isolation/--no-isolation", help="是否启用工作树隔离"),
    budget: str | None = typer.Option(None, "--budget", "-b", help="运行预算 (如 1h, 10usd)"),
    recover: bool = typer.Option(False, "--recover", help="从上次中断的状态恢复"),
    intent: str = typer.Option("implement", "--intent", help="执行意图: implement (实现), debate (辩论/设计), explore (探索)"),
    dimensions: list[str] = typer.Option([], "--dimension", "-d", help="启用维度引导 (如: creative, adversarial, audit)"),
    autonomy: str = typer.Option(
        "",
        "--autonomy",
        help="挂机级别：supervised(有人盯) / semi(只问高风险) / unattended(不打扰自决)",
    ),
):
    """
    执行自动化工作流 (识别 -> 规划 -> 执行 -> 审查 -> 发现)

    命令名是 `run` 而不是 `workflow`：`workflow` 已被
    `commands/workflow_commands.py` 注册为**命令组**（ralph/ralplan/team/autopilot）。
    Typer 中同名命令与命令组共存时，组会遮蔽命令 ——
    原先 `clawd workflow "目标"` 会把目标当成子命令去解析，永远跑不到本函数。
    """
    import asyncio

    from ..core.config.injector import set_config
    from ..workflow.engine import WorkflowEngine

    workdir = Path.cwd()

    # 挂机级别：显式 --autonomy 优先，其次沿用环境变量（CLAWD_AUTONOMY）
    if autonomy:
        from ..agent.autonomy import AutonomyLevel

        try:
            level = AutonomyLevel(autonomy.strip().lower())
        except ValueError:
            valid = " / ".join(m.value for m in AutonomyLevel)
            console.print(f"[bold red]--autonomy 取值无效:[/bold red] {autonomy}（可选: {valid}）")
            raise typer.Exit(code=2)
        os.environ["CLAWD_AUTONOMY"] = level.value
        console.print(f"[dim]挂机级别：{level.label}[/dim]")

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

@app.command(name="server")
def server(
    host: str | None = typer.Option(None, "--host", help="监听地址（默认取配置）"),
    port: int | None = typer.Option(None, "--port", "-p", help="监听端口（0=随机端口）"),
    token: str | None = typer.Option(None, "--token", help="认证令牌；缺省读取 AGENT_SERVER_TOKEN"),
    developer_mode: bool = typer.Option(False, "--developer-mode", help="开发者模式（放宽工具限制）"),
):
    """
    启动 WebSocket 服务端（远程会话）

    客户端必须携带令牌完成认证；未配置令牌时会为本进程生成一次性令牌并打印。
    """
    import asyncio
    import secrets

    from ..server import create_server

    auth_token = token or os.environ.get('AGENT_SERVER_TOKEN', '')
    generated = False
    if not auth_token:
        auth_token = secrets.token_urlsafe(24)
        generated = True

    srv = create_server(
        host=host,
        port=port,
        token=auth_token,
        developer_mode=developer_mode,
    )

    console.print(Panel(
        f"启动 WebSocket 服务端\n"
        f"监听: [bold]{srv.host}:{srv.port}[/bold]\n"
        f"令牌: [yellow]{auth_token}[/yellow]"
        + ("\n[yellow]未配置 AGENT_SERVER_TOKEN，已生成本次一次性令牌[/yellow]" if generated else ""),
        title="Clawd Server",
        border_style="cyan",
    ))

    async def _serve() -> None:
        host, port = await srv.start()
        console.print(f"[green]实际监听: {host}:{port}[/green]")
        await srv.run_forever()

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        console.print("\n[dim]服务端已停止[/dim]")


role_app = typer.Typer(help="角色库：选择内置角色（系统提示词模板），不用自己写提示词")
app.add_typer(role_app, name="role")


@role_app.command("list")
def role_list(
    as_json: bool = typer.Option(False, "--json", help="输出 JSON"),
):
    """列出可用角色（来自 <项目>/personas、当前目录/personas、~/.clawd/personas）"""
    import json as _json

    from rich.table import Table

    from ..agent.personas import search_dirs, personas_report

    items = personas_report()
    if as_json:
        typer.echo(_json.dumps(items, ensure_ascii=False))
        raise typer.Exit(code=0)
    if not items:
        console.print("[yellow]没有找到任何角色[/yellow]")
        console.print("  查找路径: " + ", ".join(str(d) for d in search_dirs()))
        raise typer.Exit(code=1)

    table = Table(title="可用角色", show_lines=False)
    table.add_column("名字", style="cyan", no_wrap=True)
    table.add_column("标题")
    table.add_column("分类", style="dim")
    table.add_column("说明", style="dim")
    for item in items:
        table.add_row(item["name"], item["title"], item["category"], item["description"][:48])
    console.print(table)
    console.print("[dim]用法：clawd chat --role <名字>；桌面端在输入框左侧切换角色[/dim]")
    raise typer.Exit(code=0)


@role_app.command("show")
def role_show(name: str = typer.Argument(..., help="角色名（见 clawd role list）")):
    """打印某个角色的完整系统提示词（可审计，不藏东西）"""
    from ..agent.personas import build_system_prefix, load_persona

    try:
        persona = load_persona(name)
    except KeyError as e:
        console.print(f"[bold red]{e}[/bold red]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{persona.title}[/bold] [dim]({persona.name} · {persona.category})[/dim]")
    if persona.description:
        console.print(f"[dim]{persona.description}[/dim]")
    if persona.source:
        console.print(f"[dim]来源: {persona.source}[/dim]")
    console.print("")
    console.print(build_system_prefix(persona))
    raise typer.Exit(code=0)


@app.command(name="usage")
def usage_cmd(
    range_key: str = typer.Option("today", "--range", help="统计范围: today | week | month | all"),
    limit: int = typer.Option(20, "--limit", "-n", help="展示最近多少条请求"),
    as_json: bool = typer.Option(False, "--json", help="输出 JSON"),
):
    """
    查看本机用量（成本 / 请求数 / token / 缓存命中率）

    数据来自 `<工作区>/.clawd/clawd.db` 的 usage 表 —— 引擎每跑完一轮就记一行。
    桌面端的「用量统计」面板读的是同一份数据。
    """
    import json as _json

    from rich.table import Table

    from ..core import usage_store

    try:
        data = usage_store.summary(range_key)
        rows = usage_store.recent(limit)
    except Exception as e:  # noqa: BLE001 — 存储坏了要如实报错
        console.print(f"[bold red]读取用量失败:[/bold red] {e}")
        raise typer.Exit(code=1)

    if as_json:
        payload = dict(data)
        payload["recent"] = rows
        typer.echo(_json.dumps(payload, ensure_ascii=False, default=str))
        raise typer.Exit(code=0)

    t = data["totals"]
    console.print(
        f"[bold]用量（{range_key}）[/bold]  成本 ${t.get('cost', 0):.4f}"
        f" · 请求 {t.get('requests', 0)} · tokens {t.get('total_tokens', 0)}"
        f" · 缓存命中率 {t.get('cache_hit_rate', 0) * 100:.1f}%"
    )

    if data.get("by_model"):
        table = Table(title="按模型", show_lines=False)
        table.add_column("模型")
        table.add_column("请求", justify="right")
        table.add_column("输入", justify="right")
        table.add_column("输出", justify="right")
        table.add_column("缓存读", justify="right")
        table.add_column("成本", justify="right")
        for row in data["by_model"]:
            table.add_row(
                str(row.get("model") or "-"), str(row.get("requests")),
                str(row.get("prompt_tokens")), str(row.get("completion_tokens")),
                str(row.get("cache_read_tokens")), f"${float(row.get('cost') or 0):.4f}",
            )
        console.print(table)

    if rows:
        recent = Table(title=f"最近 {len(rows)} 条", show_lines=False)
        for col in ("时间", "应用", "模型", "成本", "输入", "输出", "状态"):
            recent.add_column(col, justify="right" if col in ("成本", "输入", "输出") else "left")
        import datetime as _dt

        for row in rows:
            ts = _dt.datetime.fromtimestamp(float(row.get("ts") or 0)).strftime("%m-%d %H:%M:%S")
            recent.add_row(
                ts, str(row.get("client") or "-"), str(row.get("model") or "-"),
                f"${float(row.get('cost') or 0):.4f}",
                str(row.get("prompt_tokens")), str(row.get("completion_tokens")),
                str(row.get("status") or "-"),
            )
        console.print(recent)
    else:
        console.print("[dim]还没有用量记录 —— 跑一次 `clawd run` 或桌面端对话就会出现在这里。[/dim]")
    raise typer.Exit(code=0)


@app.command(name="ledger")
def ledger_cmd(
    as_json: bool = typer.Option(False, "--json", help="输出 JSON"),
):
    """
    运行账本快照（合并 mode_state 与 ralph_ledger，并做一致性诊断）

    两本账职责分开：mode_state 记"当前处于哪个模式/阶段"，ralph_ledger 记"一步步做了什么"。
    这个命令是**唯一读取入口**，会指出两本账是否对得上（只写一半 / 孤儿进度 / 时间漂移）。
    """
    import json as _json

    from ..workflow.run_ledger import ledger_snapshot

    snap = ledger_snapshot()
    if as_json:
        typer.echo(_json.dumps(snap.to_dict(), ensure_ascii=False, default=str))
        raise typer.Exit(code=0 if snap.consistent else 1)

    console.print(f"[bold]{snap.summary_line()}[/bold]")
    for mode in snap.modes:
        console.print(f"  · {mode.mode}: {mode.phase or '(无阶段)'}  — {mode.task[:60]}")
    if snap.progress:
        console.print(f"  最近进度（共 {len(snap.progress)} 条）:")
        for entry in snap.progress[-5:]:
            console.print(f"    - {entry.get('recorded_at', '')} {entry.get('text', '')[:100]}")
    if snap.issues:
        console.print("[bold red]账本不一致:[/bold red]")
        for issue in snap.issues:
            console.print(f"  - {issue}")
    raise typer.Exit(code=0 if snap.consistent else 1)


@app.command(name="onboard")
def onboard(
    as_json: bool = typer.Option(False, "--json", help="输出 JSON（便于脚本/CI 使用）"),
):
    """
    首次上手体检：检测环境里的 LLM 密钥、推断默认模型、给出下一步

    这是 `src/utils/onboarding.py` 的真实接线入口（此前该模块零调用点）。
    """
    import json as _json

    from ..utils.onboarding import preflight_report

    report = preflight_report()
    if as_json:
        # 用 typer.echo 而不是 console.print：rich 会按终端宽度折行，把 JSON 断成多行
        typer.echo(_json.dumps(report, ensure_ascii=False))
        raise typer.Exit(code=0 if report["ready"] else 1)

    if report["keys"]:
        console.print("[green]检测到的密钥:[/green] " + ", ".join(sorted(report["keys"])))
    else:
        console.print("[yellow]未检测到任何 LLM 密钥[/yellow]")
    if report["model"]:
        console.print(f"[green]推荐模型:[/green] {report['model']}")
    console.print(report["hint"])
    raise typer.Exit(code=0 if report["ready"] else 1)


@app.command(name="doctor")
def doctor():
    """
    运行环境诊断 (检查 API、依赖和配置)
    """
    from ..cli.repl_commands import _handle_doctor
    _handle_doctor()

@app.command(name="reason")
def reason(
    pattern: str = typer.Argument(..., help="推理模式: reflexion | plan-execute | lats | debate"),
    task: str = typer.Argument(..., help="任务描述"),
    conclusion: str | None = typer.Option(None, "--conclusion", help="debate 模式待审查结论"),
    branching: int = typer.Option(3, "--branching", help="lats 分支数"),
    depth: int = typer.Option(2, "--depth", help="lats 深度"),
    rounds: int = typer.Option(2, "--rounds", help="debate 轮数"),
    max_iterations: int = typer.Option(8, "--max-iterations", help="最大迭代数"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON 全量结果"),
):
    """
    推理模式 — 反推/逆向分析推理循环

    reflexion:   假设→执行→反思→修正（逆向核心循环）
    plan-execute: 计划分解→逐步执行→按结果重规划
    lats:        多分支假设树并行评估，择优展开
    debate:      多立场对抗审查结论，防误报
    """
    from ..cli_handlers.reason_handler import cmd_reason

    argv = [pattern, task]
    if conclusion:
        argv += ["--conclusion", conclusion]
    if branching != 3:
        argv += ["--branching", str(branching)]
    if depth != 2:
        argv += ["--depth", str(depth)]
    if rounds != 2:
        argv += ["--rounds", str(rounds)]
    if max_iterations != 8:
        argv += ["--max-iterations", str(max_iterations)]
    if json_output:
        argv += ["--json"]
    code = cmd_reason(argv)
    if code != 0:
        raise typer.Exit(code)

@app.command(name="serve")
def serve(
    port: int | None = typer.Option(None, "--port", help="WS 端口（默认走配置）"),
    workdir: str | None = typer.Option(None, "--workdir", help="工作目录"),
    env_file: str | None = typer.Option(None, "--env-file", help="额外加载的 .env（桌面壳传入）"),
):
    """
    启动本地 Host 服务 — 桌面端(Electron)/Web 端连接的权威运行时

    启动后写 .clawd_host_port 端口文件（含 token），壳与浏览器据此发现服务。
    """
    from ..server.host_entry import cmd_serve

    argv = []
    if port is not None:
        argv += ["--port", str(port)]
    if workdir:
        argv += ["--workdir", workdir]
    if env_file:
        argv += ["--env-file", env_file]
    code = cmd_serve(argv)
    if code != 0:
        raise typer.Exit(code)

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

    from ..workflow.pipeline import (
        create_ralph_verify_stage,
        create_ralplan_stage,
        create_team_exec_stage,
    )
    from ..workflow.pipeline_orchestrator import (
        PipelineOrchestrator,
        create_autopilot_pipeline_config,
    )

    if budget:
        # 不静默忽略：pipeline 编排器目前没有预算参数，
        # 预算只在 `clawd run`（WorkflowEngine）生效。
        console.print(
            "[yellow]注意：pipeline 编排器暂不支持 --budget，"
            "该参数本次不生效；如需预算控制请使用 `clawd run --budget`。[/yellow]"
        )

    stages = [create_ralplan_stage()]
    if not no_team:
        stages.append(create_team_exec_stage())
    if not no_ralph:
        stages.append(create_ralph_verify_stage())

    cwd = str(Path.cwd())
    config = create_autopilot_pipeline_config(task=goal, stages=stages, cwd=cwd)

    async def _run() -> int:
        result = await PipelineOrchestrator(config, cwd=cwd).run()

        console.print("\n[bold green]流水线执行报告[/bold green]")
        console.print(f"目标: {goal}")
        console.print(f"最终状态: {result.status}")
        console.print(f"耗时: {result.duration_ms / 1000:.2f}s")
        if result.failed_stage:
            console.print(f"[red]失败阶段: {result.failed_stage}[/red] {result.error or ''}")
        for name, sr in result.stage_results.items():
            console.print(f"  - {name}: {sr.status.value}")
        return 0 if result.status == "completed" else 1

    raise typer.Exit(asyncio.run(_run()))

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
    report: bool = typer.Option(True, "--report/--no-report", help="显示配置优先级链报告（--no-report 关闭）"),
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

#: 命令组清单：(组名, 模块, 注册函数)。
#:
#: 模块必须写成**模块对象**而不是字符串，且用显式 `from ... import` 获取：
#: 静态可达性工具（scripts/reachability.py）靠 AST 里的 import 语句建图，
#: 若改用 `importlib.import_module("字符串")`，这 4 个模块会在图中消失，
#: 被误判为"生产不可达" —— 实测可达数会从 429 掉到 416。
#: 运行时用字符串拼模块名虽然更"动态"，但会让项目自带的死代码分析工具失灵。
#:
#: 组名单独存一份常量：整体导入失败时**必须**能报出失败的组名，
#: 不能返回空清单——否则 `failures == []` 的断言会在全军覆没时假通过。
_COMMAND_GROUP_NAMES: tuple[str, ...] = ("agent", "catalog", "workflow", "setup")

#: 兼容旧名（历史测试引用过）。
_COMMAND_MODULES: tuple[tuple[str, object, str], ...] = ()


def _load_command_modules() -> tuple[tuple[str, object, str], ...]:
    """导入各命令组模块。导入失败不在这里处理，交给注册函数统一报告。"""
    from .commands import (
        agent_commands,
        catalog_commands,
        setup_commands,
        workflow_commands,
    )

    return (
        ("agent", agent_commands, "register_agent_commands"),
        ("catalog", catalog_commands, "register_catalog_commands"),
        ("workflow", workflow_commands, "register_workflow_commands"),
        ("setup", setup_commands, "register_setup_commands"),
    )


#: 已注册的组名。用于保证 `_register_command_modules()` **幂等** ——
#: 模块导入时会调一次，`main()` 里又调一次；不加护栏会在
#: `app.registered_groups` 里留下重复项（实测出现过 8 项 / 4 个名字）。
_REGISTERED_GROUPS: set[str] = set()


def _register_command_modules() -> list[str]:
    """注册模块化命令组，并**让失败可见**。

    这里原先是 `try: ... except ImportError: pass`，本意是"可选模块缺失时
    优雅降级"，实际把三类硬错误吞成了静默失败：

    - `agent_commands` 引用已改名的 `get_registered_keywords`
    - `workflow_commands` 从错误模块导入三个 stage 工厂
    - `hud_improved` 相对导入层数越界

    后果是 `agent` 与 `workflow` 两个命令组（7 个命令）**整体从 CLI 消失**，
    而启动时毫无提示。降级本身是合理需求，但"降级"必须可观测 ——
    因此失败时写日志，并返回失败清单供测试断言。

    注意整批导入是**一起**失败的：命令组模块间没有相互依赖，但共用
    `_load_command_modules` 这一个导入点。任一模块导入炸掉，其余组也拿不到。
    这是有意的 —— 让问题在测试里一次性暴露，而不是逐个组慢慢发现。

    Returns:
        注册失败的组名列表（空列表 = 全部成功）。
    """
    failed: list[str] = []

    try:
        groups = _load_command_modules()
    except Exception as exc:
        logger.warning(
            "命令组模块导入失败，相关命令在本进程中不可用: %s: %s",
            type(exc).__name__,
            exc,
        )
        # 必须返回**真实组名**，不能返回空列表：
        # 否则失败清单为空，`failures == []` 的回归断言会在全军覆没时假通过。
        return list(_COMMAND_GROUP_NAMES)

    for group_name, mod, func_name in groups:
        if group_name in _REGISTERED_GROUPS:
            continue
        try:
            register = getattr(mod, func_name)
            register(app)
            _REGISTERED_GROUPS.add(group_name)
        except Exception as exc:
            failed.append(group_name)
            # ImportError 之外也一并接住：`field` 未定义这类 NameError
            # 同样会让整组命令消失，只接 ImportError 会漏掉一半情况。
            logger.warning(
                "命令组 '%s' 注册失败，其命令在本进程中不可用: %s: %s",
                group_name,
                type(exc).__name__,
                exc,
            )

    return failed


# ---------------------------------------------------------------------------
# 会话管理命令组（会话持久化在 src/core/session_store.py，此前 CLI 摸不到）
# ---------------------------------------------------------------------------
session_app = typer.Typer(help="会话管理：列出/查看/分叉/改名（持久化在 .clawd/sessions/）")


@session_app.command("list")
def session_list(
    json_out: bool = typer.Option(False, "--json", help="JSON 输出"),
    sessions_dir: Path | None = typer.Option(None, "--dir", help="会话目录（默认 .clawd/sessions）"),
):
    """列出已保存的会话"""
    from ..core.session_bridge import list_all

    # 用桥接层：引擎侧与会话侧两套格式都能读（此前只读一套 → 引擎写的会话看不见）
    rows = [v.to_dict() for v in list_all(sessions_dir)]
    if json_out:
        console.print_json(data=rows)
        return
    if not rows:
        console.print("[yellow]暂无已保存会话[/yellow]")
        return
    for row in rows:
        title = row.get("title") or "(无标题)"
        parent = f" ← {row['parent_session_id']}" if row.get("parent_session_id") else ""
        console.print(
            f"[bold]{row['session_id']}[/bold]{parent}  {title}  "
            f"[dim]{row.get('turn_count', 0)} 轮 · "
            f"tokens {row.get('input_tokens', 0)}/{row.get('output_tokens', 0)} · "
            f"${row.get('total_cost', 0.0):.4f}[/dim]"
        )


@session_app.command("show")
def session_show(
    session_id: str = typer.Argument(..., help="会话 ID"),
    sessions_dir: Path | None = typer.Option(None, "--dir"),
):
    """查看单个会话详情（含分叉链）"""
    from ..core.session_bridge import chain, load

    try:
        sess = load(session_id, sessions_dir)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[bold red]读取失败:[/bold red] {e}")
        raise typer.Exit(code=1)

    payload = sess.to_dict()
    payload["chain"] = chain(session_id, sessions_dir)
    payload["roles"] = [
        {"role": m.get("role"), "chars": len(str(m.get("content") or ""))}
        for m in sess.messages
    ]
    console.print_json(data=payload)


@session_app.command("fork")
def session_fork(
    parent_id: str = typer.Argument(..., help="父会话 ID"),
    new_id: str = typer.Argument(..., help="新会话 ID"),
    title: str = typer.Option("", "--title", help="新会话标题"),
    sessions_dir: Path | None = typer.Option(None, "--dir"),
):
    """从已有会话分叉（保留历史，不改父会话）"""
    from ..core.session_bridge import fork as fork_session

    try:
        forked = fork_session(parent_id, new_id, title=title, directory=sessions_dir)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[bold red]分叉失败:[/bold red] {e}")
        raise typer.Exit(code=1)
    console.print(
        f"[green]已分叉[/green] {parent_id} → [bold]{forked.session_id}[/bold]"
        f"（继承 {len(forked.messages)} 条消息）"
    )


@session_app.command("title")
def session_title(
    session_id: str = typer.Argument(..., help="会话 ID"),
    title: str = typer.Argument(..., help="新标题"),
    sessions_dir: Path | None = typer.Option(None, "--dir"),
):
    """设置会话标题"""
    from ..core.session_bridge import set_title as update_session_meta

    try:
        updated = update_session_meta(session_id, title, sessions_dir)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[bold red]更新失败:[/bold red] {e}")
        raise typer.Exit(code=1)
    console.print(f"[green]标题已更新:[/green] {updated.session_id} → {updated.title}")


@session_app.command("resume")
def session_resume(
    session_id: str = typer.Argument(..., help="要续跑的会话 ID"),
    goal: str = typer.Argument(..., help="本次要接着做的事"),
    sessions_dir: Path | None = typer.Option(None, "--dir"),
    max_iterations: int = typer.Option(10, "--max-iterations", "-i"),
):
    """在已有会话上下文里继续执行（历史消息会注入到本轮之前）"""
    import asyncio

    from ..agent.engine import AgentEngine
    from ..core.session_bridge import load as load_view

    try:
        view = load_view(session_id, sessions_dir)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[bold red]读取失败:[/bold red] {e}")
        raise typer.Exit(code=1)

    prior = view.messages
    if not prior:
        console.print("[yellow]该会话没有历史消息，将按新任务执行[/yellow]")
    else:
        # 长历史先压成检查点（Pi 准入阈值 + Codex 检查点语义），避免续跑直接爆上下文
        from ..agent.compaction import prepare_resume_messages

        prior, checkpoint = prepare_resume_messages(list(prior))
        if checkpoint is not None:
            console.print(
                f"[yellow]历史较长（{checkpoint.dropped_entries} 条），已压缩为检查点摘要[/yellow]"
            )
        else:
            console.print(
                f"[dim]已载入 {len(prior)} 条历史消息（{view.title or '无标题'}）[/dim]"
            )

    engine = AgentEngine(workdir=Path.cwd(), max_iterations=max_iterations)
    try:
        session = asyncio.run(engine.run(goal, prior_messages=prior or None))
    except Exception as e:
        console.print(f"[bold red]执行失败:[/bold red] {type(e).__name__}: {e}")
        raise typer.Exit(code=1)

    console.print(session.final_result or "(无输出)")
    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# 挂机控制命令组（挂机前授权、挂机中叫停、事后看审计）
# ---------------------------------------------------------------------------
autonomy_app = typer.Typer(help="挂机控制：预授权命令 / 叫停 / 查看审计（.clawd/autonomy/）")


def _autonomy_dir(workdir: Path | None) -> Path:
    return (workdir or Path.cwd()).resolve() / ".clawd" / "autonomy"


@autonomy_app.command("allow")
def autonomy_allow(
    command: str = typer.Argument(..., help='要预先放行的命令（如 "npm test" 或 "pytest"）'),
    workdir: Path | None = typer.Option(None, "--dir", help="项目根（默认当前目录）"),
):
    """挂机前预先放行某个命令前缀（挂机期间就不会因无人审批而跳过它）"""
    import json

    d = _autonomy_dir(workdir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "allow.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    commands = data.get("commands") if isinstance(data, dict) else None
    if not isinstance(commands, list):
        commands = []
    if command not in commands:
        commands.append(command)
    path.write_text(json.dumps({"commands": commands}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    console.print(f"[green]已预先放行:[/green] {command}（共 {len(commands)} 条）")


@autonomy_app.command("revoke")
def autonomy_revoke(
    command: str = typer.Argument(..., help="要取消放行的命令"),
    workdir: Path | None = typer.Option(None, "--dir"),
):
    """取消某条预先放行"""
    import json

    path = _autonomy_dir(workdir) / "allow.json"
    if not path.is_file():
        console.print("[yellow]没有预先放行记录[/yellow]")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    commands = [c for c in (data.get("commands") or []) if c != command]
    path.write_text(json.dumps({"commands": commands}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    console.print(f"[green]已取消:[/green] {command}（剩 {len(commands)} 条）")


@autonomy_app.command("list")
def autonomy_list(
    workdir: Path | None = typer.Option(None, "--dir"),
):
    """查看当前预先放行的命令"""
    import json

    path = _autonomy_dir(workdir) / "allow.json"
    if not path.is_file():
        console.print("[yellow]暂无预先放行[/yellow]")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        console.print("[red]allow.json 损坏[/red]")
        raise typer.Exit(code=1)
    for cmd in data.get("commands") or []:
        console.print(f"- {cmd}")


@autonomy_app.command("stop")
def autonomy_stop(
    workdir: Path | None = typer.Option(None, "--dir"),
):
    """请求挂机在下一次检查点停止（写 STOP 文件）"""
    d = _autonomy_dir(workdir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "STOP").write_text("stop", encoding="utf-8")
    console.print("[yellow]已请求停止：挂机将在下一次检查点停下（保留进度）[/yellow]")


@autonomy_app.command("resume")
def autonomy_resume(
    workdir: Path | None = typer.Option(None, "--dir"),
):
    """撤销停止请求"""
    stop_file = _autonomy_dir(workdir) / "STOP"
    if stop_file.exists():
        stop_file.unlink()
        console.print("[green]已撤销停止请求[/green]")
    else:
        console.print("[dim]当前没有停止请求[/dim]")


@autonomy_app.command("log")
def autonomy_log(
    tail: int = typer.Option(10, "--tail", "-n", help="显示最近多少条"),
    workdir: Path | None = typer.Option(None, "--dir"),
):
    """查看挂机的自主决策审计（每条都带中文理由）"""
    import json

    path = _autonomy_dir(workdir) / "decisions.jsonl"
    if not path.is_file():
        console.print("[yellow]暂无审计记录[/yellow]")
        return
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for raw in lines[-tail:]:
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        console.print(
            f"[dim]{entry.get('时间', '')}[/dim] "
            f"[bold]{entry.get('决策', '')}[/bold] "
            f"{entry.get('工具', '')} {entry.get('目标', '') or entry.get('命令', '')} "
            f"—— {entry.get('理由', '')}"
        )


app.add_typer(autonomy_app, name="autonomy")

app.add_typer(session_app, name="session")

# 注册模块化命令
_REGISTRATION_FAILURES = _register_command_modules()


@app.command(name="collaborate")
def collaborate_run(
    goal: str = typer.Argument(..., help="要完成的任务"),
    planner: str = typer.Option("native", "--planner", help="规划引擎（native/codex/opencode）"),
    executor: str = typer.Option("native", "--executor", help="执行引擎"),
    reviewer: str = typer.Option("native", "--reviewer", help="审查引擎（建议与 executor 不同）"),
    rounds: int = typer.Option(1, "--rounds", help="审查不通过时的返工轮数（默认 1）"),
    timeout: float = typer.Option(900.0, "--timeout", help="单阶段硬超时（秒）"),
):
    """
    多引擎协同：规划 → 执行 → 独立审查 → 不合格返工 → 再审查

    用另一个引擎审你的活，能抓出"自己审自己"放过的问题。默认全用内置引擎，
    也可混搭：--planner codex --executor native --reviewer opencode
    """
    from ..workflow.collaborate import Collaborator

    console.print(f"[dim]协同：规划={planner} 执行={executor} 审查={reviewer}[/dim]")
    collab = Collaborator(
        goal,
        planner=planner,
        executor=executor,
        reviewer=reviewer,
        max_repair_rounds=rounds,
        timeout=timeout,
        workdir=Path.cwd(),
    )
    result = collab.run()

    for phase in result.phases:
        mark = "[green]OK[/green]" if phase.ok else "[red]FAIL[/red]"
        console.print(
            f"  {mark} {phase.phase}({phase.engine}) {phase.seconds}s"
            + (f" — {phase.error[:80]}" if phase.error else "")
        )

    console.print("")
    console.print("[bold]执行结果[/bold]")
    console.print(result.final or "(无输出)")
    console.print("")
    console.print(f"[bold]{result.summary()}[/bold]")
    if result.issues:
        console.print("[yellow]审查意见：[/yellow]")
        for i, issue in enumerate(result.issues, 1):
            console.print(f"  {i}. {issue}")

    raise typer.Exit(code=0 if result.ok else 1)


@app.command(name="permissions")
def permissions_explain(
    rules: bool = typer.Option(False, "--rules", help="额外列出命令策略规则明细"),
):
    """
    权限与挂机的中文说明：审批模式 / 挂机级别 / 拒绝结论 / 受保护路径

    不需要记英文枚举，这里全部用中文讲清楚"会发生什么、风险在哪"。
    """
    from ..agent.autonomy import AutonomyLevel
    from ..core.approval_mode import describe_approval_modes
    from ..core.exec_policy import Decision as ExecDecision
    from ..core.exec_policy import ExecPolicy
    from ..core.permissions import Effect, protected_reason

    console.print("[bold]一、审批模式（人盯着的时候用）[/bold]")
    for line in describe_approval_modes().splitlines()[1:]:
        console.print(line)

    console.print(chr(10) + "[bold]二、挂机级别（让 Agent 自己跑完时用）[/bold]")
    for level in AutonomyLevel:
        console.print(f"- {level.label}（{level.value}）")

    console.print(chr(10) + "[bold]三、权限结论的含义[/bold]")
    for effect in Effect:
        console.print(f"- {effect.label}（{effect.value}）")

    console.print(chr(10) + "[bold]四、命令策略结论[/bold]")
    for decision in ExecDecision:
        console.print(f"- {decision.label}（{decision.value}）")

    console.print(chr(10) + "[bold]五、无论如何都不许工具改动的路径[/bold]")
    for sample, desc in (
        (".git/config", "版本控制目录内（会破坏可回滚性）"),
        ("server.pem", "证书文件"),
        ("id_rsa", "私钥文件"),
        (".clawd_host_port", "含运行时令牌"),
    ):
        reason = protected_reason(sample)
        console.print(f"- {sample}：{reason or desc}")

    if rules:
        console.print(chr(10) + "[bold]六、内置命令规则（前缀匹配，最长匹配优先）[/bold]")
        policy = ExecPolicy()
        for rule in policy.rules:
            prefix = " ".join(rule.prefix)
            console.print(f"- [cyan]{rule.decision.label}[/cyan] `{prefix}`"
                          + (f" —— {rule.justification}" if rule.justification else ""))


@app.command(name="engines")
def engines_cmd(
    probe: bool = typer.Option(True, "--probe/--no-probe", help="是否真实探活（运行 --version）"),
    json_out: bool = typer.Option(False, "--json", help="JSON 输出"),
    run: str | None = typer.Option(None, "--run", help="用第一个可用引擎执行该任务"),
    timeout: float = typer.Option(900.0, "--timeout", help="--run 时的硬超时（秒）"),
):
    """
    多引擎总览：列出已集成的开源 agent 引擎及其真实可用性

    整合原则：不合并源码（语言/协议都不同），而是统一驱动接口 + 统一探活 +
    通过 MCP 把我们的领域工具反向供给所有引擎。
    """
    from ..backends import registry

    described = registry.describe()
    if json_out:
        console.print_json(data=described)
    else:
        console.print("[bold]已集成引擎[/bold]")
        for name, info in described.items():
            if info["kind"] != "engine":
                continue
            status = info["status"]
            color = "green" if status == "ready" else ("yellow" if status == "incompatible" else "red")
            ver = info["version"] or "-"
            console.print(f"  [{color}]{status:<13}[/{color}] {name:<10} {ver}")
        console.print("")
        console.print("[bold]非引擎项（不可当引擎驱动）[/bold]")
        for name, info in described.items():
            if info["kind"] == "engine":
                continue
            console.print(f"  [dim]{name:<10} {info['detail']}[/dim]")

    ready = registry.ready_engines()
    if not ready:
        console.print("[yellow]没有可用引擎[/yellow]")
        raise typer.Exit(code=1)

    if run:
        engine = ready[0]
        console.print(f"[dim]使用引擎: {engine}[/dim]")
        backend = registry.get_backend(engine, workdir=Path.cwd())
        result = backend.run(run, timeout=timeout)
        console.print(result.text or "(无输出)")
        if result.errors:
            for err in result.errors[:3]:
                console.print(f"[red]{err}[/red]")
        raise typer.Exit(code=0 if result.ok else 1)


@app.command(name="codex")
def codex_run(
    goal: str = typer.Argument(..., help="交给 Codex 后端执行的任务"),
    workdir: Path | None = typer.Option(None, "--cd", help="执行目录（默认当前目录）"),
    model: str | None = typer.Option(None, "--model", "-m", help="覆盖模型"),
    provider: str | None = typer.Option(None, "--provider", help="模型提供方（默认沿用 Codex 配置）"),
    base_url: str | None = typer.Option(
        None, "--base-url", help="OpenAI 兼容端点（默认读 LLM_BASE_URL）"
    ),
    sandbox: str = typer.Option(
        "workspace-write",
        "--sandbox",
        help="沙箱模式: read-only | workspace-write | danger-full-access",
    ),
    timeout: float = typer.Option(900.0, "--timeout", help="硬超时（秒）"),
    json_out: bool = typer.Option(False, "--json", help="输出归一化后的 JSON 结果"),
    bypass_approvals: bool = typer.Option(
        False, "--bypass-approvals",
        help="跳过 Codex 审批与沙箱（MCP 工具调用需要；仅隔离环境/挂机用）",
    ),
    with_clawd_tools: bool = typer.Option(
        False, "--with-clawd-tools",
        help="把我们自己的领域工具（读文件/grep/项目图谱/世界模型）通过 MCP 交给 Codex",
    ),
):
    """
    用 Codex 内核执行任务（外部成熟 agent 后端，不重复造轮子）

    说明: 需要先安装 Codex CLI —— `npm i -g @openai/codex`。
    本命令只做协议适配与进程管控，agent 循环/沙箱/工具由 Codex 自己负责。
    """
    from ..backends import CodexBackend
    from ..backends.codex import CodexBackendError

    import os as _os

    mcp_servers: dict = {}
    if with_clawd_tools:
        # 把我们的领域工具反向供给 Codex（stdlib 起 MCP server，无需额外依赖）
        mcp_servers["clawd"] = {
            "command": sys.executable,
            "args": ["-m", "src.mcp.domain_server", "--root", str(workdir or Path.cwd())],
        }
    backend = CodexBackend(
        model=model or _os.environ.get("LLM_MODEL"),
        provider=provider or _os.environ.get("LLM_PROVIDER"),
        base_url=base_url or _os.environ.get("LLM_BASE_URL"),
        sandbox=sandbox,
        workdir=workdir or Path.cwd(),
        dangerously_bypass_approvals=bypass_approvals,
        mcp_servers=mcp_servers,
    )
    if not backend.available():
        console.print(
            "[bold red]Codex 未安装[/bold red] —— 请先执行: npm i -g @openai/codex"
        )
        raise typer.Exit(code=2)

    console.print(f"[dim]codex: {backend.version() or 'unknown'} · sandbox={sandbox}[/dim]")
    try:
        result = backend.run(goal, timeout=timeout)
    except CodexBackendError as e:
        console.print(f"[bold red]执行失败:[/bold red] {e}")
        raise typer.Exit(code=2)

    if json_out:
        console.print_json(data={
            "ok": result.ok,
            "text": result.text,
            "exit_code": result.exit_code,
            "duration_s": round(result.duration_s, 2),
            "timed_out": result.timed_out,
            "usage": result.usage,
            "commands": result.commands,
            "errors": result.errors[:5],
            "thread_id": result.thread_id,
        })
    else:
        if result.text:
            console.print(result.text)
        if result.commands:
            console.print(f"[dim](执行了 {len(result.commands)} 条命令)[/dim]")
        if result.usage:
            console.print(f"[dim]tokens: {result.usage}[/dim]")
        if result.errors:
            for err in result.errors[:3]:
                console.print(f"[red]{err}[/red]")

    if result.timed_out:
        console.print(f"[bold red]超时（{timeout}s），已强杀进程树[/bold red]")
        raise typer.Exit(code=124)
    raise typer.Exit(code=0 if result.ok else 1)


@app.command(name="explain")
def explain(
    session_id: str = typer.Argument(None, help="会话 ID（缺省=最近一次会话）"),
    as_json: bool = typer.Option(False, "--json", help="输出 JSON（便于脚本核对）"),
    cross: bool = typer.Option(False, "--cross", help="跨会话归因：最近 N 轮的成功率/常见失败/成本"),
    limit: int = typer.Option(10, "--limit", "-n", help="--cross 时统计最近多少轮"),
):
    """
    用中文讲清上一轮它到底做了什么（零成本：不调用 LLM）

    输出：目标/模型/轮次/用量、每次工具调用及其成败、失败片段、最终回答。
    没有记录的地方会明确写"没有记录"，不会替你猜成功。
    """
    import json as _json

    from .explain import explain_recent, explain_session

    if cross:
        summary = explain_recent(limit, None)
        if as_json:
            typer.echo(_json.dumps(summary, ensure_ascii=False, default=str))
            raise typer.Exit(code=0)
        console.print(
            f"[bold]最近 {summary['sessions']} 轮[/bold] 完成 {summary['completed']}"
            f" · 成功率 {summary['success_rate'] * 100:.0f}%"
            f" · 成本 ${summary['cost']:.4f} · tokens {summary['tokens']}"
        )
        if summary["top_failures"]:
            console.print("[bold red]最常见失败:[/bold red]")
            for item in summary["top_failures"]:
                console.print(f"  - {item['count']}× {item['key']}")
        if summary["top_failed_tools"]:
            console.print("[bold yellow]失败最多的工具:[/bold yellow]")
            for item in summary["top_failed_tools"]:
                console.print(f"  - {item['key']}: {item['count']} 次")
        if not summary["top_failures"] and not summary["top_failed_tools"]:
            console.print("[green]没有记录到失败[/green]")
        raise typer.Exit(code=0)

    try:
        explanation = explain_session(session_id)
    except FileNotFoundError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(code=2)
    except ValueError as e:
        console.print(f"[bold red]会话损坏:[/bold red] {e}")
        raise typer.Exit(code=2)

    if as_json:
        typer.echo(_json.dumps(explanation.to_dict(), ensure_ascii=False))
    else:
        console.print(explanation.to_text())
    raise typer.Exit(code=0)


@app.command(name="review")
def review(
    paths: list[str] = typer.Argument(None, help="要评审的文件/目录（缺省=未提交改动）"),
    roles: str = typer.Option(
        "", "--roles", help="逗号分隔的评审角色（默认四个：code/security/performance/style）"
    ),
    include_diff: bool = typer.Option(True, "--diff/--no-diff", help="是否把未提交 diff 一起给评审"),
    as_json: bool = typer.Option(False, "--json", help="输出 JSON（便于 CI）"),
    timeout: float = typer.Option(180.0, "--timeout", help="单角色超时（秒）"),
):
    """
    多角色并行评审（真正的并行调度，不是单点审计）

    角色模板来自 `prompts/agents/<role>.md`。裁决由确定性解析得到：
    `VERDICT: APPROVE|NEEDS_FIX` + `CRITICAL/HIGH/MEDIUM/LOW` 分级。
    任一角色失败 → 整体 INCOMPLETE（**不会**把"没评审"算成"没问题"）。

    退出码：0=APPROVE · 1=NEEDS_FIX · 2=INCOMPLETE（含无目标/角色失败）
    注意：这会发起真实 LLM 调用（按你配置的 provider 计费）。
    """
    import asyncio as _asyncio
    import json as _json

    from ..agent.review_team import (
        DEFAULT_ROLES,
        VERDICT_APPROVE,
        VERDICT_NEEDS_FIX,
        ReviewTeam,
        available_review_roles,
        collect_review_targets,
        get_git_diff,
    )

    role_list = tuple(r.strip() for r in roles.split(",") if r.strip()) or DEFAULT_ROLES
    known_roles = available_review_roles()
    unknown = [r for r in role_list if r not in known_roles]
    if unknown:
        console.print(f"[bold red]未知角色:[/bold red] {unknown}")
        console.print(f"  可用: {sorted(known_roles)}")
        raise typer.Exit(code=2)

    targets = collect_review_targets(paths, Path.cwd())
    if not targets:
        console.print("[yellow]没有评审目标[/yellow]（既没给路径，也没有未提交改动）")
        raise typer.Exit(code=2)

    diff_text = get_git_diff(Path.cwd()) if include_diff else ""
    team = ReviewTeam(roles=role_list, timeout=timeout)
    try:
        report = _asyncio.run(team.review(targets, diff_text=diff_text))
    except Exception as e:  # noqa: BLE001 — 配置/网络问题要如实报错，不能装作评审过
        console.print(f"[bold red]评审无法进行:[/bold red] {type(e).__name__}: {e}")
        raise typer.Exit(code=2)

    if as_json:
        typer.echo(_json.dumps(report.to_dict(), ensure_ascii=False))
    else:
        console.print(f"[bold]{report.summary_line()}[/bold]")
        for role_review in report.roles:
            if role_review.error:
                console.print(f"  [red]FAILED[/red] {role_review.role}: {role_review.error}")
                continue
            console.print(f"  [cyan]{role_review.role}[/cyan]: {role_review.verdict}")
        for finding in report.blocking_findings:
            console.print(f"  [red]{finding[:200]}[/red]")

    if report.verdict == VERDICT_APPROVE:
        raise typer.Exit(code=0)
    if report.verdict == VERDICT_NEEDS_FIX:
        raise typer.Exit(code=1)
    raise typer.Exit(code=2)


@app.command(name="eval")
def eval_dataset(
    dataset: Path = typer.Argument(..., help="评测数据集 JSON 路径"),
    baseline: Path | None = typer.Option(
        None, "--baseline", "-b", help="基线 JSON 路径（比对回归）"
    ),
    save: bool = typer.Option(False, "--save", help="把本轮结果写为基线"),
    live: bool = typer.Option(
        False, "--live", help="真实调用 agent（需 CLAWD_EVAL_ALLOW_PAID=1，会产生费用）"
    ),
    tolerance: float = typer.Option(0.0, "--tolerance", help="pass_rate 允许的下降幅度"),
):
    """
    运行 agent 评测数据集（默认 replay 模式，零成本、确定性）

    默认使用数据集里录制的输出做确定性断言（exact/contains/regex/tool_sequence），
    适合放进 CI 做 agent 行为回归。真实调用需显式 --live + 环境变量双闸。
    """
    from ..eval import (
        compare_with_baseline,
        load_baseline_strict,
        load_dataset,
        run_dataset,
        save_baseline,
    )
    from ..eval.runner import EvalConfigError

    try:
        cases = load_dataset(dataset)
    except EvalConfigError as e:
        console.print(f"[bold red]数据集非法:[/bold red] {e}")
        raise typer.Exit(code=1)

    try:
        report = run_dataset(
            cases, live=live, dataset_name=str(dataset)
        )
    except EvalConfigError as e:
        console.print(f"[bold red]无法执行:[/bold red] {e}")
        raise typer.Exit(code=2)

    console.print(f"[bold]{report.summary_line()}[/bold]")
    for outcome in report.failures:
        console.print(f"  [red]FAIL[/red] {outcome.case_id}: {outcome.detail}")
    for outcome in report.unknowns:
        console.print(f"  [yellow]UNKNOWN[/yellow] {outcome.case_id}: {outcome.detail}")

    exit_code = 0

    # 基线比对：基线文件不存在 / 损坏 → 明确报错。
    # 旧实现把 `load_baseline() is None` 当成"无回归通过"，指向不存在的路径也
    # 会打印"基线比对通过"并 exit 0 —— 假成功。
    if baseline is not None:
        if not Path(baseline).is_file() and save:
            # 首次建立基线：--save 与 --baseline 同时给出时允许文件还不存在
            console.print(f"[yellow]基线尚不存在（{baseline}），本轮结果将作为初始基线写入[/yellow]")
        else:
            try:
                baseline_data = load_baseline_strict(baseline)
            except (FileNotFoundError, ValueError) as e:
                console.print(f"[bold red]基线不可用:[/bold red] {e}")
                console.print("  （不能在没有基线的情况下宣称「无回归」）")
                raise typer.Exit(code=2)
            problems = compare_with_baseline(report, baseline_data, tolerance=tolerance)
            if problems:
                console.print("[bold red]基线回归:[/bold red]")
                for problem in problems:
                    console.print(f"  - {problem}")
                exit_code = 1
            else:
                console.print("[green]基线比对通过（无回归）[/green]")

    if save:
        target = baseline or Path(".clawd/eval_baseline.json")
        try:
            written = save_baseline(report, target)
        except OSError as e:
            console.print(f"[bold red]基线写入失败:[/bold red] {e}")
            raise typer.Exit(code=2)
        console.print(f"[green]基线已写入:[/green] {written}")

    # 全都没判定 → 无法给出结论，用独立退出码（3）与"失败"(1) 区分开
    if report.determined == 0 and report.total:
        console.print(
            "[bold yellow]没有一条用例被真正判定[/bold yellow]："
            "请补 recorded 数据或改用 --live。"
        )
        raise typer.Exit(code=3)

    if report.failed:
        exit_code = exit_code or 1
    raise typer.Exit(code=exit_code)


def main():
    import atexit
    atexit.register(_register_shutdown_hooks)

    # 自动加载 Hooks 配置
    try:
        # 安全（审计 P1-4）：**默认不自动加载项目目录里的 hooks/config.toml**。
        # 该文件可随仓库分发，自动加载等于"克隆一个仓库就跑它的命令"。
        # 需要时显式开启：CLAWD_ENABLE_HOOKS_CONFIG=1
        import os as _os

        cfg_path = Path.cwd() / "hooks" / "config.toml"
        if cfg_path.is_file():
            if _os.environ.get("CLAWD_ENABLE_HOOKS_CONFIG", "").lower() in ("1", "true", "yes"):
                from ..core.hooks_config import load_hooks_config
                load_hooks_config(cfg_path)
            else:
                # 提示一次即可（24h 节流）：否则每条命令都刷一行，变成新噪音
                try:
                    import time as _time

                    marker = Path(".clawd") / "hooks_config_warned"
                    _now = _time.time()
                    _warn = True
                    if marker.is_file():
                        _last = float(marker.read_text(encoding="utf-8").strip() or "0")
                        _warn = (_now - _last) > 86400
                    if _warn:
                        marker.parent.mkdir(parents=True, exist_ok=True)
                        marker.write_text(str(_now), encoding="utf-8")
                        console.print(
                            f"[yellow]提示：检测到 {cfg_path.name} 但未自动加载（安全默认）。"
                            f"确认可信后设置 CLAWD_ENABLE_HOOKS_CONFIG=1。[/yellow]"
                        )
                except (OSError, ValueError) as _e:
                    # 拿不到节流标记时忽略（提示本身是可选增强），但要留痕
                    import logging as _logging
                    _logging.getLogger(__name__).debug("hooks 提示节流失败: %s", _e)
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

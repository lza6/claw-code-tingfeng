from __future__ import annotations

import logging
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
    except Exception as exc:  # noqa: BLE001 - 降级要宽，但必须可见
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
        except Exception as exc:  # noqa: BLE001
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


# 注册模块化命令
_REGISTRATION_FAILURES = _register_command_modules()


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
):
    """
    用 Codex 内核执行任务（外部成熟 agent 后端，不重复造轮子）

    说明: 需要先安装 Codex CLI —— `npm i -g @openai/codex`。
    本命令只做协议适配与进程管控，agent 循环/沙箱/工具由 Codex 自己负责。
    """
    from ..backends import CodexBackend
    from ..backends.codex import CodexBackendError

    import os as _os

    backend = CodexBackend(
        model=model or _os.environ.get("LLM_MODEL"),
        provider=provider or _os.environ.get("LLM_PROVIDER"),
        base_url=base_url or _os.environ.get("LLM_BASE_URL"),
        sandbox=sandbox,
        workdir=workdir or Path.cwd(),
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
        load_baseline,
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

    exit_code = 0
    if baseline is not None:
        problems = compare_with_baseline(
            report, load_baseline(baseline), tolerance=tolerance
        )
        if problems:
            console.print("[bold red]基线回归:[/bold red]")
            for problem in problems:
                console.print(f"  - {problem}")
            exit_code = 1
        else:
            console.print("[green]基线比对通过（无回归）[/green]")

    if save:
        target = baseline or Path(".clawd/eval_baseline.json")
        written = save_baseline(report, target)
        console.print(f"[green]基线已写入:[/green] {written}")

    if report.failed:
        exit_code = exit_code or 1
    raise typer.Exit(code=exit_code)


def main():
    import atexit
    atexit.register(_register_shutdown_hooks)

    # 自动加载 Hooks 配置
    try:
        from ..core.hooks_config import load_hooks_config
        load_hooks_config(Path.cwd() / "hooks" / "config.toml")
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

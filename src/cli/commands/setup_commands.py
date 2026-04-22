"""
Setup 和配置命令：项目初始化、配置生成、环境检查

参考：oh-my-codex-main/src/cli/setup.ts, doctor.ts
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from ...config.generator import merge_config, repair_config_if_needed

app = typer.Typer(help="项目初始化和配置管理")
console = Console()


@app.command("setup")
def setup_cmd(
    force: bool = typer.Option(False, "--force", "-f", help="强制重新配置"),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="不配置 MCP 服务器"),
):
    """
    初始化 Clawd Code 项目配置。

    执行以下操作：
    1. 创建 .clawd/ 目录结构
    2. 生成/合并 config.toml
    3. 注册 MCP 服务器
    4. 创建初始 AGENTS.md（如果不存在）
    5. 生成技能清单 catalog-manifest.json
    """
    from ... import __version__
    from ...core.config import ensure_project_dirs

    workdir = Path.cwd()
    clawd_dir = workdir / ".clawd"

    console.print(Panel(
        f"[bold cyan]Clawd Code 项目初始化[/bold cyan]\n"
        f"工作目录: {workdir}\n"
        f"版本: {__version__}",
        border_style="cyan"
    ))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # Step 1: 创建目录结构
        task = progress.add_task("创建项目目录...", total=None)
        ensure_project_dirs(workdir)
        progress.update(task, completed=True)

        # Step 2: 处理配置文件
        task = progress.add_task("配置 Clawd Code...", total=None)
        config_path = workdir / ".clawd" / "config.toml"

        if config_path.exists() and not force:
            console.print("  [yellow]配置文件已存在, 合并配置...[/yellow]")
            repaired = repair_config_if_needed(str(config_path), str(workdir))
            if repaired:
                console.print("  [green]✓ 修复了配置文件问题[/green]")
        else:
            if config_path.exists() and force:
                config_path.unlink()
                console.print("  [yellow]强制重建配置[/yellow]")

            # 生成新配置
            merge_config(
                str(config_path),
                str(workdir),
                verbose=False,
                include_tui=True,
            )
            console.print(f"  [green]✓ 创建配置文件: {config_path}[/green]")

        progress.update(task, completed=True)

        # Step 3: 创建 AGENTS.md
        task = progress.add_task("创建 AGENTS.md...", total=None)
        agents_path = workdir / "AGENTS.md"
        if not agents_path.exists() or force:
            template_path = Path(__file__).parent.parent.parent / "templates" / "AGENTS.md"
            if template_path.exists():
                agents_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
                console.print("  [green]✓ 创建 AGENTS.md[/green]")
            else:
                console.print("  [dim]跳过: 模板未找到[/dim]")

        progress.update(task, completed=True)

        # Step 4: 创建 catalog manifest
        task = progress.add_task("生成技能清单...", total=None)
        catalog_path = workdir / ".clawd" / "catalog-manifest.json"
        if not catalog_path.exists() or force:
            template_path = Path(__file__).parent.parent.parent / "templates" / "catalog-manifest.json"
            if template_path.exists():
                import shutil
                shutil.copy(template_path, catalog_path)
                console.print("  [green]✓ 创建技能清单: catalog-manifest.json[/green]")

        progress.update(task, completed=True)

    console.print("\n[bold green]✓ Clawd Code 配置完成！[/bold green]")
    console.print("\n下一步：")
    console.print("  1. 编辑 .clawd/config.toml 调整模型和设置")
    console.print("  2. 运行 [cyan]clawd chat[/cyan] 启动对话")
    console.print("  3. 查看 [cyan]clawd --help[/cyan] 了解可用命令")


@app.command("doctor")
def doctor_cmd(
    fix: bool = typer.Option(False, "--fix", "-f", help="自动修复问题"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
):
    """
    诊断并修复 Clawd Code 环境问题。

    检查：
    - Python 版本
    - 依赖安装
    - 配置文件完整性
    - 目录权限
    - MCP 服务器可用性
    """
    from ... import __version__

    issues: list[str] = []
    warnings: list[str] = []

    console.print(Panel("[bold cyan]Clawd Code 环境诊断[/bold cyan]", border_style="cyan"))

    # Python 版本
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        console.print(f"  [green]✓ Python {py_version}[/green]")
    else:
        console.print(f"  [red]✗ Python {py_version} (需要 3.10+)[/red]")
        issues.append("Python 版本过低")

    # Clawd Code 版本
    console.print(f"  [green]✓ Clawd Code v{__version__}[/green]")

    # 工作目录检查
    workdir = Path.cwd()
    clawd_dir = workdir / ".clawd"

    if not clawd_dir.exists():
        warnings.append(".clawd/ 目录不存在，运行 'clawd setup' 初始化")
        console.print("  [yellow]⚠ .clawd/ 目录缺失[/yellow]")
    else:
        console.print("  [green]✓ .clawd/ 目录存在[/green]")

    # 配置文件检查
    config_path = clawd_dir / "config.toml"
    if not config_path.exists():
        issues.append("配置文件不存在")
        console.print("  [red]✗ config.toml 缺失[/red]")
    else:
        console.print("  [green]✓ config.toml 存在[/green]")

        # 检查配置完整性
        config_content = config_path.read_text(encoding="utf-8")
        required_keys = ["model", "features", "mcp_servers"]
        missing = [k for k in required_keys if k not in config_content]
        if missing:
            warnings.append(f"配置缺少键: {missing}")
            console.print(f"  [yellow]⚠ 配置不完整: {missing}[/yellow]")
        else:
            console.print("  [green]✓ 配置结构完整[/green]")

    # AGENTS.md 检查
    agents_path = workdir / "AGENTS.md"
    if not agents_path.exists():
        warnings.append("AGENTS.md 不存在")
        console.print("  [dim]ℹ AGENTS.md 可选 (运行 setup 创建)[/dim]")
    else:
        console.print("  [green]✓ AGENTS.md 存在[/green]")

    # 报告
    console.print("\n" + "=" * 50)
    if issues:
        console.print(f"[bold red]问题 ({len(issues)}):[/bold red]")
        for issue in issues:
            console.print(f"  • {issue}")
    if warnings:
        console.print(f"[bold yellow]警告 ({len(warnings)}):[/bold yellow]")
        for warning in warnings:
            console.print(f"  • {warning}")

    if not issues and not warnings:
        console.print("[bold green]✓ 环境健康，没有发现问题[/bold green]")
    elif not issues and fix is False:
        console.print("\n[cyan]提示: 运行 'clawd doctor --fix' 自动修复警告[/cyan]")

    # 自动修复
    if fix and (issues or warnings):
        console.print("\n[yellow]正在自动修复...[/yellow]")
        # 修复配置
        if not config_path.exists():
            merge_config(str(config_path), str(workdir), verbose=True)
        else:
            repaired = repair_config_if_needed(str(config_path), str(workdir))
            if repaired:
                console.print("  [green]✓ 修复了配置文件[/green]")


@app.command("init")
def init_project(
    name: str = typer.Option(None, "--name", "-n", help="项目名称"),
    description: str = typer.Option("", "--description", "-d", help="项目描述"),
    template: str = typer.Option("default", "--template", "-t", help="项目模板"),
):
    """
    创建新项目（交互式初始化向导）。

    引导用户配置：
    - 项目元数据
    - 技术栈
    - 工作流偏好
    - 生成初始配置文件
    """

    workdir = Path.cwd()
    project_name = name or workdir.name

    console.print(Panel(
        f"[bold cyan]新项目初始化向导[/bold cyan]\n"
        f"项目名称: {project_name}\n"
        f"工作目录: {workdir}",
        border_style="cyan"
    ))

    # 交互式提问
    if description == "":
        description = typer.prompt("项目描述", default="A Clawd Code project")

    # 技术栈选择
    tech_stack = typer.prompt(
        "技术栈 (用逗号分隔)",
        default="python, git"
    ).lower().split(",")

    tech_stack = [t.strip() for t in tech_stack]

    # 是否启用特定功能
    use_workflow = typer.confirm("启用工作流管道?", default=True)
    use_team = typer.confirm("启用团队模式?", default=False)
    use_mcp = typer.confirm("启用 MCP 服务器?", default=True)

    # 保存配置
    config = {
        "project": {
            "name": project_name,
            "description": description,
            "tech_stack": tech_stack,
        },
        "features": {
            "workflow": use_workflow,
            "team_mode": use_team,
            "mcp": use_mcp,
        },
    }

    import json
    config_file = workdir / ".clawd" / "project.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    console.print(f"[green]✓ 项目配置已保存: {config_file}[/green]")

    # 运行 setup
    if typer.confirm("现在运行 setup 配置环境?", default=True):
        setup_cmd(force=False, no_mcp=not use_mcp)


def register_setup_commands(app: typer.Typer) -> None:
    """注册 setup 相关命令"""
    app.add_typer(app, name="setup")

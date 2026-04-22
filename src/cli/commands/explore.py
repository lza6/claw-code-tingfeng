"""探索模式 (Explore Mode) - 只读代码分析

参考: oh-my-codex-main 的 explore 模式
特征:
    - 禁用所有写工具 (Write, Edit, Patch, Delete)
    - 只允许 Read, Search, Analyze 类工具
    - 可以执行但不会修改文件系统
    - 适合代码审查、架构分析、文档生成

用法:
    $explore 分析项目的模块结构
    clawd explore --goal "生成项目架构文档"
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ...agent.engine import AgentEngine
from ...brain.world_model import RepositoryWorldModel
from ...core.config.injector import set_config
from ...utils.logger import get_logger

logger = get_logger(__name__)
console = Console()


@dataclass
class ExploreConfig:
    """探索模式配置"""
    goal: str
    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    depth: int = 2  # 探索深度
    output_format: str = "markdown"  # markdown, json, tree


class ExploreMode:
    """只读探索模式

    1. 初始化只读 WorldModel (仅索引，不编辑)
    2. 禁用写工具
    3. 执行分析任务
    4. 输出洞察报告
    """

    # 只读白名单工具 (ClassVar 因为可变)
    READ_ONLY_TOOLS: ClassVar[set[str]] = {
        "Read",
        "Glob",
        "Grep",
        "SymbolFind",
        "RepoMap",
        "WorldModel",
        "Lint",
        "Test",
        "GitLog",
        "GitDiff",
        "Tree",
        "ArchitectureGraph",
    }

    # 写工具黑名单 (ClassVar 因为可变)
    WRITE_TOOLS: ClassVar[set[str]] = {
        "Write",
        "Edit",
        "Patch",
        "Delete",
        "Mv",
        "Rm",
        "GitCommit",
        "Bash",
    }

    def __init__(
        self,
        workdir: Path,
        config: ExploreConfig | None = None,
    ):
        self.workdir = workdir
        self.config = config or ExploreConfig(goal="分析代码库")
        self.world_model: RepositoryWorldModel | None = None

    async def run(self) -> ExploreResult:
        """运行探索模式"""
        console.print(Panel(
            f"[bold cyan]探索模式[/bold cyan]\n"
            f"目标: {self.config.goal}\n"
            f"工作目录: {self.workdir}",
            title="Explore Mode"
        ))

        # 1. 初始化只读 WorldModel
        logger.info("Initializing read-only WorldModel...")
        self.world_model = RepositoryWorldModel(self.workdir)
        self.world_model.initialize(force_refresh=False)

        # 2. 构建只读 AgentEngine
        engine = self._create_readonly_engine()

        # 3. 构建系统提示
        system_prompt = self._build_system_prompt()

        # 4. 执行分析
        logger.info("Running exploration analysis...")
        result = await engine.run(
            prompt=self.config.goal,
            system_prompt=system_prompt,
            max_iterations=20,
        )

        # 5. 生成报告
        report = self._generate_report(result)

        return ExploreResult(
            goal=self.config.goal,
            findings=report,
            world_model=self.world_model,
        )

    def _create_readonly_engine(self) -> AgentEngine:
        """创建只读模式的 AgentEngine (过滤工具)"""
        from src.agent.engine import AgentEngine
        from src.tools_runtime.tool_manager import create_readonly_tool_manager

        # 使用工具管理器过滤器
        tool_manager = create_readonly_tool_manager(
            allowed_tools=self.READ_ONLY_TOOLS,
            disallowed_tools=self.WRITE_TOOLS,
        )

        engine = AgentEngine(
            workdir=self.workdir,
            tool_manager=tool_manager,
            world_model=self.world_model,
        )

        # 标记为探索模式
        set_config("mode", "explore")
        set_config("readonly", True)

        return engine

    def _build_system_prompt(self) -> str:
        """构建探索模式系统提示"""
        return (
            "You are in EXPLORE mode - a read-only analysis mode.\n"
            "GOAL: Analyze the codebase and provide insights.\n"
            "CONSTRAINTS:\n"
            "  - DO NOT modify any files\n"
            "  - DO NOT create, edit, or delete anything\n"
            "  - Use only Read/Glob/Grep/SymbolFind tools\n"
            "  - Provide factual analysis with evidence\n"
            "OUTPUT: A comprehensive analysis report\n"
        )

    def _generate_report(self, engine_result) -> str:
        """生成探索报告"""
        if self.config.output_format == "markdown":
            return self._generate_markdown_report(engine_result)
        elif self.config.output_format == "tree":
            return self._generate_tree_report()
        else:
            return str(engine_result.final_result)

    def _generate_markdown_report(self, engine_result) -> str:
        """生成 Markdown 报告"""
        lines = [
            "# 代码库探索报告\n\n",
            f"**目标**: {self.config.goal}\n\n",
            "## 分析结果\n\n",
            engine_result.final_result or "无结果",
            "\n\n---\n",
            "*由 Clawd Code Explore 模式生成*",
        ]
        return "".join(lines)

    def _generate_tree_report(self) -> str:
        """生成目录树报告"""
        if not self.world_model:
            return "WorldModel 未初始化"
        tree = self.world_model.get_directory_tree()
        return str(tree)


@dataclass
class ExploreResult:
    """探索结果"""
    goal: str
    findings: str
    world_model: RepositoryWorldModel | None = None


# ==================== CLI 命令 ====================

def explore_command(
    goal: str,
    depth: int = 2,
    output_format: str = "markdown",
) -> None:
    """CLI 命令: clawd explore <goal>"""
    import asyncio

    config = ExploreConfig(
        goal=goal,
        depth=depth,
        output_format=output_format,
    )

    mode = ExploreMode(Path.cwd(), config)

    async def _run():
        result = await mode.run()
        console.print("\n[bold green]探索完成![/bold green]")
        console.print(Panel(result.findings, title="探索结果"))

    asyncio.run(_run())


def setup_explore_command(app: typer.Typer) -> None:
    """注册 explore 命令到 Typer app"""
    import typer

    @app.command(name="explore")
    def explore(
        goal: str = typer.Argument(..., help="探索目标描述"),
        depth: int = typer.Option(2, "--depth", "-d", help="探索深度"),
        format: str = typer.Option(
            "markdown", "--format", "-f",
            help="输出格式: markdown, tree, json"
        ),
    ):
        """只读探索模式 - 分析代码库而不修改"""
        explore_command(goal=goal, depth=depth, output_format=format)


__all__ = [
    "ExploreConfig",
    "ExploreMode",
    "ExploreResult",
    "explore_command",
    "setup_explore_command",
]

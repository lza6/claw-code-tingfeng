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
from typing import ClassVar

import typer

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
        """创建只读模式的 AgentEngine。

        ## 为什么不用"过滤工具列表"

        原实现导入 `src.tools_runtime.tool_manager.create_readonly_tool_manager`
        —— 该模块与函数**都不存在**（真实的是 `src.agent.tool_manager.ToolManager`）。
        而且 `AgentEngine.__init__` 根本不接受 `tool_manager` 参数，
        它内部自己 `ToolManager(self.tools)`。所以那条路即使补上符号也走不通。

        真正的只读保证来自审批门禁：`ApprovalMode.PLAN` 会拒绝一切
        write / exec 类工具（这是 v0.54.0 实测过的硬化点）。`ToolManager`
        在构造时从 `AgentSettings` 读取 `approval_mode`，因此这里在
        **构造期间**临时把 `APPROVAL_MODE=plan` 注入环境，构造完立刻还原，
        不影响进程内其它代码。
        """
        import os

        from src.agent.engine import AgentEngine

        previous = os.environ.get("APPROVAL_MODE")
        os.environ["APPROVAL_MODE"] = "plan"
        try:
            engine = AgentEngine(
                workdir=self.workdir,
                world_model=self.world_model,
                intent="explore",
            )
        finally:
            if previous is None:
                os.environ.pop("APPROVAL_MODE", None)
            else:
                os.environ["APPROVAL_MODE"] = previous

        if getattr(engine.tool_manager, "approval_mode", None) is None or \
                getattr(engine.tool_manager.approval_mode, "value", "") != "plan":
            # 不静默：若门禁没生效，明确说明本次并非只读
            console.print(
                "[bold yellow]⚠ 未能启用只读审批模式，本次探索可能修改文件[/bold yellow]"
            )

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
    as_json: bool = False,
) -> dict:
    """CLI 命令: clawd explore <goal>

    返回探索结果字典（`{goal, format, findings}`）：`--json` 与终端渲染共用同一份数据，
    不再"边跑边打印"，脚本才能消费（X-7 契约 `{ok, code, ...}`）。
    """
    import asyncio

    from ..command_result import CommandResult, emit

    config = ExploreConfig(
        goal=goal,
        depth=depth,
        output_format=output_format,
    )

    mode = ExploreMode(Path.cwd(), config)

    async def _run() -> dict:
        result = await mode.run()
        return {"goal": goal, "format": output_format, "findings": result.findings or ""}

    payload = asyncio.run(_run())

    if as_json:
        emit(CommandResult(ok=True, data=payload), as_json=True)
        return payload

    console.print("\n[bold green]探索完成![/bold green]")
    console.print(Panel(payload["findings"], title="探索结果"))
    return payload


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
        json_out: bool = typer.Option(False, "--json", help="机器可读输出（契约 {ok, code, ...}）"),
    ):
        """只读探索模式 - 分析代码库而不修改"""
        explore_command(goal=goal, depth=depth, output_format=format, as_json=json_out)


__all__ = [
    "ExploreConfig",
    "ExploreMode",
    "ExploreResult",
    "explore_command",
    "setup_explore_command",
]

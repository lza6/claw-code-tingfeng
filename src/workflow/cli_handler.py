"""CLI 子命令处理器 -- workflow run / hotfix / version / status"""
from __future__ import annotations

import argparse

from ..core.models import CommandResult
from .models import WorkflowIntent
from .engine import WorkflowEngine
from .hotfix_manager import HotfixManager
from .tech_debt import TechDebtManager
from .version_manager import VersionManager


def handle_workflow(args: argparse.Namespace) -> CommandResult:
    """分发 workflow 子命令。"""
    subcmd = getattr(args, "workflow_command", None) or getattr(args, "action", None)

    if subcmd == "run":
        return _handle_run(args)
    elif subcmd == "recover":
        return _handle_recover(args)
    elif subcmd == "hotfix":
        return _handle_hotfix(args)
    elif subcmd == "version":
        return _handle_version(args)
    elif subcmd == "status":
        return _handle_status(args)
    elif subcmd == "observe":
        return _handle_observe(args)
    else:
        return CommandResult(
            exit_code=1,
            output="用法: workflow {run|hotfix|version|status|observe|recover}" + "\n" + _get_help(),
        )


def _handle_run(args: argparse.Namespace) -> CommandResult:
    """workflow run --goal '...' [--iterations 3] [--hotfix-id ID] [--isolation]

    实际调用 WorkflowEngine.run(goal)，同步执行（CLI 模式使用 asyncio.run）。
    """
    import asyncio

    goal = args.goal
    iterations = getattr(args, "iterations", 3)
    use_isolation = getattr(args, "isolation", False)
    intent_val = getattr(args, "intent", "deliver")
    intent = WorkflowIntent(intent_val)

    output_lines = [
        "工作流引擎启动中",
        f"  目标: {goal}",
        f"  意图: {intent.value}",
        f"  最大迭代次数: {iterations}",
        f"  隔离模式: {'开启' if use_isolation else '关闭'}",
        "",
    ]

    engine = WorkflowEngine(max_iterations=iterations, budget_str=getattr(args, "budget", None), intent=intent)
    engine._use_isolation = use_isolation
    result = asyncio.run(engine.run(goal))

    output_lines.append(result.report or "(无报告)")
    output_lines.append("")
    output_lines.append(f"状态: {result.status.value}")
    output_lines.append(f"任务: {result.completed_tasks}/{result.total_tasks} 已完成")
    return CommandResult(exit_code=0 if result.status.value == "completed" else 1,
                         output="\n".join(output_lines))


def _handle_observe(args: argparse.Namespace) -> CommandResult:
    """深入观察运行状态 (汲取 GoalX)"""
    from ..core.persistence.run_state import RunStateManager
    from pathlib import Path
    import os

    workdir = Path(os.environ.get('WORK_DIR', '.'))
    state_mgr = RunStateManager(workdir, "latest")
    data = state_mgr.load()

    if not data:
        return CommandResult(exit_code=1, output="未找到活跃运行状态。")

    lines = [
        f"# 深入观察: {data.get('run_id')}",
        f"目标: {data.get('goal')}",
        f"更新时间: {data.get('updated_at')}",
        f"当前意图: {data.get('intent', 'N/A')}",
        "",
        "## 任务状态",
    ]

    tasks = data.get("tasks", [])
    for t in tasks:
        status_icon = "✅" if t.get("status") == "completed" else "⏳"
        lines.append(f"{status_icon} [{t.get('task_id')}] {t.get('title') or t.get('description', '')[:50]}")
        evidence = t.get("evidence_paths", [])
        if evidence:
            lines.append(f"   ↳ 证据: {', '.join(evidence)}")

    # 尝试从 MemoryManager 读取认知日志
    try:
        from ..memory.manager import MemoryManager
        mem = MemoryManager(use_sqlite=True)
        journals = mem.get_journals(limit=5)
        if journals:
            lines.append("")
            lines.append("## 最近认知日志 (Cognition Journals)")
            for j in journals:
                lines.append(f"- [{j.intent}] {j.thought[:100]}...")
    except Exception:
        pass

    return CommandResult(exit_code=0, output="\n".join(lines))


def _handle_recover(args: argparse.Namespace) -> CommandResult:
    """从上次中断的状态恢复工作流"""
    import asyncio
    engine = WorkflowEngine()
    result = asyncio.run(engine.run("", recover=True))

    return CommandResult(
        exit_code=0 if result.status.value == "completed" else 1,
        output=result.report or "恢复完成"
    )


def _handle_hotfix(args: argparse.Namespace) -> CommandResult:
    """workflow hotfix on --id ID / off"""
    mode = args.mode
    hf_mgr = HotfixManager()

    if mode == "on":
        issue_id = getattr(args, "id", None)
        if not issue_id:
            return CommandResult(
                exit_code=1,
                output="错误: 启用热修复模式需要 --id 参数",
            )
        hf_mgr.enable(issue_id)
        return CommandResult(
            exit_code=0,
            output=(
                f"热修复模式已启用 (ID: {issue_id})\n"
                f"代码修改将标注 FIXME-[{issue_id}] 并记录为技术债务"
            ),
        )
    elif mode == "off":
        pending = hf_mgr.disable()
        output = "热修复模式已禁用"
        if pending:
            output += f"\n{len(pending)} 项待处理技术债务将在下次迭代中解决:"
            for debt in pending:
                output += f"\n  - [{debt.record_id}] {debt.description}"
        return CommandResult(exit_code=0, output=output)

    return CommandResult(exit_code=1, output=f"未知模式: {mode}")


def _handle_version(args: argparse.Namespace) -> CommandResult:
    """workflow version bump <type> [/ check]"""
    action = args.version_command
    vm = VersionManager()

    if action == "bump":
        bump_type = args.bump_type
        changelog_entries = getattr(args, "changelog_entry", []) or []
        category = getattr(args, "category", "Other")
        prerelease_id = getattr(args, "prerelease_id", None)

        new_version = vm.bump(bump_type, prerelease_id)
        if changelog_entries:
            vm.update_changelog(new_version, {category: changelog_entries})
        output = f"版本已升级至 {new_version}"
        if changelog_entries:
            output += f"\n更新日志已添加 {len(changelog_entries)} 条记录"
        return CommandResult(exit_code=0, output=output)
    elif action == "check":
        is_consistent, details = vm.check_consistency()
        lines = [
            "版本一致性检查:",
            f"  pyproject.toml: {details.get('pyproject_version', 'N/A')}",
            f"  CHANGELOG.md:   {details.get('changelog_version', 'N/A')}",
        ]
        if is_consistent:
            lines.append("  状态: 一致")
            return CommandResult(exit_code=0, output="\n".join(lines))
        else:
            lines.append(f"  状态: 不一致 - {details.get('issue', '')}")
            return CommandResult(exit_code=1, output="\n".join(lines))

    return CommandResult(exit_code=1, output=f"未知版本操作: {action}")


def _handle_status(args: argparse.Namespace) -> CommandResult:
    """workflow status -- 版本 + 一致性 + 热修复 + 技术债务"""
    vm = VersionManager()
    is_consistent, details = vm.check_consistency()
    hf_mgr = HotfixManager()
    td_mgr = TechDebtManager()
    td_mgr.initialize()

    lines = [
        "# 工作流状态",
        "",
        "## 版本",
        f"- pyproject.toml: {details.get('pyproject_version', 'N/A')}",
        f"- CHANGELOG.md:   {details.get('changelog_version', 'N/A')}",
        f"- 一致性: {'一致' if is_consistent else '不一致'}",
        "",
        "## 热修复",
        f"- 状态: {'启用' if hf_mgr.is_active else '禁用'}",
    ]
    if hf_mgr.issue_id:
        lines.append(f"- 当前 ID: {hf_mgr.issue_id}")

    top_debts = td_mgr.get_top_priorities(limit=5)
    lines.append("")
    lines.append("## 技术债务 (TOP 5)")
    if top_debts:
        for d in top_debts:
            lines.append(f"- {d.record_id} [{d.priority.value}] {d.description}")
    else:
        lines.append("- 暂无技术债务记录")

    return CommandResult(exit_code=0, output="\n".join(lines))


def _get_help() -> str:
    return (
        "\n子命令:\n"
        "  run --goal <文本> [--intent <deliver|explore|evolve|debate|implement>] [--iterations N]\n"
        "  recover\n"
        "  observe\n"
        "  status\n"
        "  hotfix on --id <ID> / off\n"
        "  version bump <major|minor|patch|prerelease>\n"
    )

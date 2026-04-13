"""Git 命令 - Aider 风格 Git 命令

此模块包含 Git 相关的命令:
- cmd_git: Git 快捷命令
- cmd_undo: 撤销 AI 修改
- cmd_diff: 显示变更
- cmd_commit: 提交变更
"""
from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from ..utils.colors import bold_cyan, dim

if TYPE_CHECKING:
    from .aider_commands_base import AiderCommandHandler


def cmd_git(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """Git 快捷命令

    用法:
        /git status
        /git log --oneline -5
        /git diff HEAD
    """
    if not args.strip():
        return True, """用法: /git <command>

示例:
  /git status          显示状态
  /git log --oneline -5 显示最近5次提交
  /git diff HEAD       显示未提交的变更
  /git branch          显示分支
  /git stash           暂存当前变更
"""

    try:
        result = subprocess.run(
            f"git {args}",
            shell=True,
            capture_output=True,
            text=True,
        )

        output = []
        if result.stdout:
            output.append(result.stdout)
        if result.stderr:
            output.append(dim(f"[stderr] {result.stderr}"))

        return True, '\n'.join(output) if output else "(无输出)"

    except Exception as e:
        return False, f"Git 命令失败: {e}"


def cmd_undo(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """撤销上一次 AI 修改

    用法: /undo [count]
    """
    if self.engine_ref and hasattr(self.engine_ref, 'git_manager'):
        gm = self.engine_ref.git_manager

        count = int(args.strip()) if args.strip() else 1
        if count == 1:
            success, msg = gm.undo_last_aider_commit()
        else:
            success, msg = gm.undo_multiple_commits(count)

        return success, msg

    return False, "Git 不可用"


def cmd_diff(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """显示当前未提交的变更

    用法: /diff [staged]
    """
    staged = "staged" in args.lower() or "--staged" in args

    if self.engine_ref and hasattr(self.engine_ref, 'git_manager'):
        gm = self.engine_ref.git_manager
        diff = gm.get_diff(staged_only=staged)

        if not diff:
            return True, "没有变更"

        output = [
            f"文件: {bold_cyan(', '.join(diff.files_changed))}",
            f"+{dim(str(diff.additions))} -{dim(str(diff.deletions))}",
            "",
            diff.diff_text[:5000],  # 限制输出长度
        ]

        return True, '\n'.join(output)

    return False, "Git 不可用"


def cmd_commit(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """提交当前变更

    用法: /commit [message]
    """
    message = args.strip() if args.strip() else None

    if self.engine_ref and hasattr(self.engine_ref, 'git_manager'):
        gm = self.engine_ref.git_manager
        sha = gm.commit(
            message=message,
            aider_edits=True,
            co_authored_by=True,
            auto_add=True,
        )

        if sha:
            return True, f"已提交: {sha[:8]}"
        return False, "没有变更或提交失败"

    return False, "Git 不可用"

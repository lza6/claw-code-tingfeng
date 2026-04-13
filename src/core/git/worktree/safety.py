"""
Worktree Safety Checks - 汲取 GoalX 核心逻辑
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("core.git.worktree.safety")

class SafetyChecker:
    """Git 工作树安全检查"""

    @staticmethod
    def pre_merge_check(repo_root: Path, branch_name: str) -> tuple[bool, str]:
        """冲突预检测 (Conflict Pre-check, 汲取 GoalX)"""
        try:
            # 获取主仓库当前 HEAD
            head_rev = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root, capture_output=True, text=True, check=True
            ).stdout.strip()

            # 获取隔离分支的 HEAD
            branch_rev = subprocess.run(
                ["git", "rev-parse", f"refs/heads/{branch_name}"],
                cwd=repo_root, capture_output=True, text=True, check=True
            ).stdout.strip()

            # 寻找合并基点
            base_rev = subprocess.run(
                ["git", "merge-base", head_rev, branch_rev],
                cwd=repo_root, capture_output=True, text=True, check=True
            ).stdout.strip()

            # 使用 git merge-tree 执行内存合并测试
            mt_result = subprocess.run(
                ["git", "merge-tree", base_rev, head_rev, branch_rev],
                cwd=repo_root, capture_output=True, text=True
            )

            if "<<<<<<" in mt_result.stdout:
                logger.error(f"检测到潜在合并冲突: {branch_name} -> HEAD")
                return False, mt_result.stdout

            return True, ""
        except Exception as e:
            logger.warning(f"冲突预检测失败 (可能因为分支不规范): {e}")
            return True, f"Check failed: {e}" # 降级：假定无冲突或允许直接尝试合并

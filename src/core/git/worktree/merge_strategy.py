"""
Worktree Merge Strategies - 汲取 GoalX 核心逻辑
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("core.git.worktree.merge")

class MergeStrategy:
    """Git 合并策略"""

    @staticmethod
    def merge(repo_root: Path, branch_name: str, message: str) -> tuple[bool, str]:
        """标准 Git 合并 (no-ff)"""
        try:
            cmd = ["git", "merge", "--no-ff", "-m", message, branch_name]
            res = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
            if res.returncode != 0:
                return False, res.stderr
            return True, ""
        except Exception as e:
            return False, str(e)

    @staticmethod
    def partial_adopt(repo_root: Path, worktree_path: Path) -> tuple[bool, str]:
        """部分采纳: 仅复制文件内容，不合并分支 (汲取 GoalX partial_adopt)"""
        try:
            # 1. 获取已修改但未暂存的文件
            diff_files = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=worktree_path, capture_output=True, text=True, check=True
            ).stdout.splitlines()

            # 2. 获取未跟踪的文件 (新增文件)
            untracked_files = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=worktree_path, capture_output=True, text=True, check=True
            ).stdout.splitlines()

            all_files = list(set(diff_files + untracked_files))

            if not all_files:
                return True, "没有发现任何更改"

            for rel_path in all_files:
                src = worktree_path / rel_path
                dst = repo_root / rel_path
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    logger.info(f"部分采纳文件: {rel_path}")

            return True, f"已手动同步 {len(all_files)} 个文件"
        except Exception as e:
            return False, f"部分采纳失败: {e}"

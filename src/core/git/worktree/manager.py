"""
Worktree Manager - Git 工作树管理器
"""

import logging
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

from .merge_strategy import MergeStrategy
from .safety import SafetyChecker

logger = logging.getLogger("core.git.worktree")

class WorktreeManager:
    """Git 工作树管理器 (汲取 GoalX 核心逻辑)

    用于在独立目录中创建临时的 git 工作树，实现任务执行的完全隔离，并自动同步本地忽略文件。
    """

    _SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.worktree_base = repo_root / ".clawd" / "worktrees"
        self.worktree_base.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _validate_session_id(cls, session_id: str) -> str:
        """校验 session_id，防止路径穿越与非法字符注入。"""
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id 必须是非空字符串")
        if not cls._SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError(
                f"非法 session_id: {session_id!r}。仅允许 1-64 位字母、数字、下划线和连字符，且首字符必须是字母或数字。"
            )
        return session_id

    def create(self, session_id: str, branch_name: Optional[str] = None) -> Path:
        """创建一个新的工作树，并镜像必要的忽略文件"""
        session_id = self._validate_session_id(session_id)

        # 0. 清理过期的工作树元数据
        subprocess.run(["git", "worktree", "prune"], cwd=self.repo_root)

        worktree_path = self.worktree_base / session_id
        if worktree_path.exists():
            logger.warning(f"工作树路径已存在，尝试强制清理: {worktree_path}")
            self.remove(session_id, force=True)

        # 1. 确定分支名
        target_branch = branch_name or f"clawd-{session_id}"

        # 2. 清理陈旧本地分支
        try:
            show_ref = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{target_branch}"],
                cwd=self.repo_root
            )
            if show_ref.returncode == 0:
                logger.info(f"清理陈旧分支: {target_branch}")
                subprocess.run(["git", "branch", "-D", target_branch], cwd=self.repo_root)
        except Exception as e:
            logger.debug(f"检查分支时出错: {e}")

        # 3. 创建工作树 (汲取 GoalX 重试机制)
        cmd = ["git", "worktree", "add", str(worktree_path), "-b", target_branch]
        last_err = None
        for retry in range(3):
            res = subprocess.run(cmd, cwd=self.repo_root, capture_output=True)
            if res.returncode == 0:
                logger.info(f"成功创建工作树: {worktree_path}")
                # 4. 镜像被忽略的本地配置文件
                self.copy_ignored_files(self.repo_root, worktree_path)
                return worktree_path
            last_err = res.stderr.decode()
            logger.warning(f"创建工作树尝试 {retry+1} 失败: {last_err}")
            time.sleep(1)

        raise RuntimeError(f"创建工作树失败 (已重试 3 次): {last_err}")

    def remove(self, session_id: str, force: bool = False) -> None:
        """移除工作树"""
        session_id = self._validate_session_id(session_id)
        worktree_path = self.worktree_base / session_id
        if not worktree_path.exists():
            return

        subprocess.run(["git", "worktree", "prune"], cwd=self.repo_root)

        cmd = ["git", "worktree", "remove", str(worktree_path)]
        if force:
            cmd.append("--force")

        try:
            subprocess.run(cmd, cwd=self.repo_root, check=True, capture_output=True)
            logger.info(f"成功移除工作树: {worktree_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"移除工作树失败: {e.stderr.decode()}")
            if force:
                shutil.rmtree(worktree_path, ignore_errors=True)

    def integrate(self, session_id: str, method: str = "merge") -> Tuple[bool, str]:
        """整合工作树变更"""
        session_id = self._validate_session_id(session_id)
        worktree_path = self.worktree_base / session_id
        if not worktree_path.exists():
            return False, "工作树不存在"

        logger.info(f"整合工作树 {session_id} (方法: {method})...")

        try:
            # 1. 检查是否有更改
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=worktree_path, capture_output=True, text=True, check=True
            )
            if not status.stdout.strip():
                logger.info("无更改。")
                return True, ""

            if method == "partial_adopt":
                return MergeStrategy.partial_adopt(self.repo_root, worktree_path)

            # 2. 提交更改
            subprocess.run(["git", "add", "."], cwd=worktree_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", f"Clawd integration: {session_id}"],
                cwd=worktree_path, check=True
            )

            # 3. 获取分支
            result = subprocess.run(["git", "branch", "--show-current"], cwd=worktree_path, capture_output=True, text=True, check=True)
            branch = result.stdout.strip()

            # 4. 冲突预检测
            ok, err = SafetyChecker.pre_merge_check(self.repo_root, branch)
            if not ok:
                return False, err

            # 5. 执行合并
            return MergeStrategy.merge(self.repo_root, branch, f"Merge {branch}")

        except Exception as e:
            logger.error(f"整合失败: {e}")
            return False, str(e)

    def create_snapshot(self, label: str) -> str:
        """创建轻量级快照"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"snapshot/{label}/{timestamp}"
        try:
            subprocess.run(["git", "branch", name], cwd=self.repo_root, check=True, capture_output=True)
            return name
        except Exception:
            return ""

    def restore_snapshot(self, snapshot_name: str) -> bool:
        """恢复快照"""
        try:
            subprocess.run(["git", "checkout", "-B", "main", snapshot_name], cwd=self.repo_root, check=True, capture_output=True)
            return True
        except Exception:
            return False

    def copy_ignored_files(self, source: Path, target: Path):
        """同步被 git 忽略但对 Agent 重要的文件 (如 CLAUDE.md)"""
        try:
            result = subprocess.run(
                ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
                cwd=source, capture_output=True, text=True, check=True
            )
            ignored_files = result.stdout.splitlines()
            whitelist = ["CLAUDE.md", "docs/", ".claude/", "skills/", ".env.example"]

            for f in ignored_files:
                if any(f.startswith(p) for p in whitelist):
                    src = source / f
                    dst = target / f
                    if src.is_file():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
        except Exception:
            pass

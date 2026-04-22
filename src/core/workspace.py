"""工作区管理器 - 借鉴 oh-my-codex 的工作区隔离概念

提供基于 Git Worktree 的任务隔离执行环境。
每个任务在自己的工作区中运行，避免状态污染。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Workspace:
    """工作区描述符"""
    id: str
    path: Path
    created_at: float
    parent_branch: str
    is_snapshot: bool = False

    def exists(self) -> bool:
        return self.path.exists()

    def cleanup(self) -> None:
        """清理工作区目录"""
        if self.path.exists():
            try:
                shutil.rmtree(self.path)
                logger.debug(f"工作区已清理: {self.id} @ {self.path}")
            except Exception as e:
                logger.warning(f"工作区清理失败: {e}")


class WorkspaceManager:
    """工作区管理器

    职责:
    - 创建隔离的工作区（基于 Git worktree）
    - 管理快照和分支
    - 清理工作区资源
    - 提供工作区状态查询

    对应 omx-runtime-core 的 authority 和 dispatch 概念，
    但专注于文件系统层面的隔离。
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        self.workspaces: dict[str, Workspace] = {}
        self.worktree_base = self.repo_root / ".clawd" / "worktrees"
        self.worktree_base.mkdir(parents=True, exist_ok=True)

    def create(self, task_id: str, branch: str | None = None) -> Workspace:
        """创建新的工作区

        Args:
            task_id: 任务标识符（用作工作区分支名）
            branch: 基于哪个分支创建，默认为当前分支

        Returns:
            Workspace 实例
        """
        if branch is None:
            branch = self._get_current_branch()

        worktree_path = self.worktree_base / task_id
        worktree_path.mkdir(parents=True, exist_ok=True)

        # 使用 Git worktree 创建真正的隔离工作区
        try:
            # 添加工作区
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), branch],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
            )

            workspace = Workspace(
                id=task_id,
                path=worktree_path,
                created_at=__import__("time").time(),
                parent_branch=branch,
            )
            self.workspaces[task_id] = workspace

            logger.info(f"创建工作区: {task_id} @ {worktree_path} (基于 {branch})")
            return workspace

        except subprocess.CalledProcessError as e:
            logger.error(f"创建工作区失败: {e}")
            raise RuntimeError(f"Git worktree add 失败: {e.stderr.decode()}")

    def create_snapshot(self, name: str, branch: str | None = None) -> Workspace:
        """创建快照工作区（只读，共享仓库对象）

        用于在执行前创建检查点，支持回滚。
        """
        if branch is None:
            branch = self._get_current_branch()

        snapshot_path = self.worktree_base / f"snapshot-{name}"
        snapshot_path.mkdir(parents=True, exist_ok=True)

        try:
            # 使用 --detach 创建分离 HEAD 的工作区，不会添加分支引用
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(snapshot_path), branch],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
            )

            workspace = Workspace(
                id=f"snapshot-{name}",
                path=snapshot_path,
                created_at=__import__("time").time(),
                parent_branch=branch,
                is_snapshot=True,
            )
            self.workspaces[workspace.id] = workspace

            logger.debug(f"创建快照: {name} @ {snapshot_path}")
            return workspace

        except subprocess.CalledProcessError as e:
            logger.error(f"创建快照失败: {e}")
            raise RuntimeError(f"Git worktree snapshot 失败: {e.stderr.decode()}")

    def remove(self, task_id: str) -> bool:
        """移除工作区

        Returns:
            True 如果成功移除，False 如果不存在
        """
        if task_id not in self.workspaces:
            return False

        workspace = self.workspaces[task_id]

        try:
            # 先尝试 Git 方式移除
            subprocess.run(
                ["git", "worktree", "remove", str(workspace.path)],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            # Git 失败则直接删除目录
            workspace.cleanup()

        del self.workspaces[task_id]
        logger.debug(f"移除工作区: {task_id}")
        return True

    def integrate(self, task_id: str, target_branch: str | None = None) -> tuple[bool, str]:
        """整合工作区更改回主分支

        对应 omx-runtime 的 "deliver" 操作。
        将工作区的更改合并到指定分支（默认主分支）。

        Returns:
            (成功, 详情消息)
        """
        if task_id not in self.workspaces:
            return False, f"工作区不存在: {task_id}"

        workspace = self.workspaces[task_id]
        if target_branch is None:
            target_branch = self._get_main_branch() or "main"

        try:
            # 1. 在工作区内提交所有更改（如果未提交）
            # 注意：这假设执行者已经提交了更改

            # 2. 切换回主分支并合并
            subprocess.run(
                ["git", "checkout", target_branch],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
            )

            subprocess.run(
                ["git", "merge", str(workspace.path)],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
            )

            logger.info(f"整合完成: {task_id} -> {target_branch}")
            return True, f"已合并到 {target_branch}"

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.error(f"整合失败: {task_id} - {error_msg}")
            return False, f"合并冲突: {error_msg}"

    def list_workspaces(self) -> list[Workspace]:
        """列出所有活动工作区"""
        return list(self.workspaces.values())

    def _get_current_branch(self) -> str:
        """获取当前 Git 分支"""
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() or "main"
        except Exception:
            return "main"

    def _get_main_branch(self) -> str | None:
        """猜测主分支名"""
        for branch in ["main", "master"]:
            try:
                subprocess.run(
                    ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
                    cwd=self.repo_root,
                    check=True,
                    capture_output=True,
                )
                return branch
            except subprocess.CalledProcessError:
                continue
        return None

    def cleanup_all(self) -> None:
        """清理所有工作区"""
        for task_id in list(self.workspaces.keys()):
            self.remove(task_id)
        # 清理可能残留的目录
        if self.worktree_base.exists():
            try:
                shutil.rmtree(self.worktree_base)
                self.worktree_base.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"清理工作区基目录失败: {e}")

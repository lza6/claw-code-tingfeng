"""
Worktree Manager — Git 工作区隔离管理

对齐 oh-my-codex-main 的 worktree 隔离机制：
- 为每个并行任务创建独立的 Git worktree
- 支持断点续跑（工作区状态持久化）
- 安全的合并边界（keep/integrate 语义）

参考: oh-my-codex-main/src/agent/swarm/worktree_manager.ts
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class WorktreeConfig:
    """工作区配置"""
    worktree_id: str
    base_path: Path
    git_ref: str  # branch 或 commit SHA
    isolated: bool = True  # 是否完全隔离（独立 .git 目录）
    persistent: bool = False  # 是否持久化（跨会话保留）


@dataclass
class WorktreeState:
    """工作区运行状态"""
    worktree_id: str
    path: Path
    status: str = "active"  # active, paused, completed, failed
    created_at: float = 0.0
    last_accessed: float = 0.0
    files_modified: list[str] = field(default_factory=list)
    pending_changes: dict[str, str] = field(default_factory=dict)  # filename → diff


class WorktreeManager:
    """Git worktree 管理器

    职责:
    - 创建和管理独立的 git worktree
    - 支持并行任务的隔离执行
    - 状态持久化支持断点续跑
    - 安全的变更合并策略
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd() / ".clawd" / "worktrees"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._active_worktrees: dict[str, WorktreeState] = {}
        self._state_file = self.base_dir / "worktree_state.json"
        self._load_state()

    def _load_state(self) -> None:
        """从磁盘加载工作区状态"""
        if not self._state_file.exists():
            return

        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            for wt_id, wt_data in data.get("worktrees", {}).items():
                state = WorktreeState(
                    worktree_id=wt_id,
                    path=Path(wt_data["path"]),
                    status=wt_data.get("status", "active"),
                    created_at=wt_data.get("created_at", 0.0),
                    last_accessed=wt_data.get("last_accessed", 0.0),
                    files_modified=wt_data.get("files_modified", []),
                    pending_changes=wt_data.get("pending_changes", {}),
                )
                self._active_worktrees[wt_id] = state
        except Exception as e:
            logger.warning(f"Failed to load worktree state: {e}")

    def _persist_state(self) -> None:
        """持久化工作区状态"""
        data = {
            "worktrees": {
                wt_id: {
                    "path": str(state.path),
                    "status": state.status,
                    "created_at": state.created_at,
                    "last_accessed": state.last_accessed,
                    "files_modified": state.files_modified,
                    "pending_changes": state.pending_changes,
                }
                for wt_id, state in self._active_worktrees.items()
            }
        }
        self._state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def create_worktree(
        self,
        worktree_id: str,
        base_ref: str = "HEAD",
        isolated: bool = True,
        persistent: bool = False,
    ) -> WorktreeState:
        """创建新的 git worktree

        Args:
            worktree_id: 工作区唯一标识符
            base_ref: 基础 git 引用（branch 或 commit）
            isolated: 是否完全隔离（独立 .git 目录）
            persistent: 是否持久化（跨会话保留）

        Returns:
            WorktreeState 对象
        """
        if worktree_id in self._active_worktrees:
            raise ValueError(f"Worktree {worktree_id} already exists")

        worktree_path = self.base_dir / worktree_id
        worktree_path.mkdir(parents=True, exist_ok=True)

        try:
            # 使用 git worktree add 创建工作区
            # --force: 覆盖现有路径（如果存在）
            # --checkout: 检出文件
            cmd = [
                "git", "worktree", "add",
                "--force",
                str(worktree_path),
                base_ref
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=Path.cwd()
            )

            if result.returncode != 0:
                # 如果 git worktree 失败，创建独立目录（fallback）
                logger.warning(f"git worktree add failed: {result.stderr}, using isolated directory")
                worktree_path.mkdir(parents=True, exist_ok=True)
                # 复制当前目录内容
                src = Path.cwd()
                for item in src.iterdir():
                    if item.name == ".git" and isolated:
                        continue  # 隔离模式下不复制 .git
                    if item.is_dir():
                        shutil.copytree(item, worktree_path / item.name, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, worktree_path / item.name)

            state = WorktreeState(
                worktree_id=worktree_id,
                path=worktree_path,
                status="active",
                created_at=import_time(),
                last_accessed=import_time(),
            )
            self._active_worktrees[worktree_id] = state
            self._persist_state()

            logger.info(f"Created worktree {worktree_id} at {worktree_path}")
            return state

        except Exception as e:
            logger.error(f"Failed to create worktree {worktree_id}: {e}")
            raise

    def get_worktree(self, worktree_id: str) -> WorktreeState | None:
        """获取工作区状态"""
        state = self._active_worktrees.get(worktree_id)
        if state:
            state.last_accessed = import_time()
        return state

    def list_worktrees(self) -> list[WorktreeState]:
        """列出所有工作区"""
        return list(self._active_worktrees.values())

    def remove_worktree(self, worktree_id: str, force: bool = False) -> bool:
        """删除工作区"""
        state = self._active_worktrees.get(worktree_id)
        if not state:
            return False

        try:
            # 尝试使用 git worktree remove
            cmd = ["git", "worktree", "remove", str(state.path)]
            if force:
                cmd.append("--force")

            subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            # 即使 git 命令失败，也要清理目录
            if state.path.exists():
                shutil.rmtree(state.path, ignore_errors=True)

            del self._active_worktrees[worktree_id]
            self._persist_state()

            logger.info(f"Removed worktree {worktree_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to remove worktree {worktree_id}: {e}")
            return False

    def pause_worktree(self, worktree_id: str) -> bool:
        """暂停工作区（标记为 paused）"""
        state = self._active_worktrees.get(worktree_id)
        if not state:
            return False

        state.status = "paused"
        state.last_accessed = import_time()
        self._persist_state()
        return True

    def resume_worktree(self, worktree_id: str) -> bool:
        """恢复工作区"""
        state = self._active_worktrees.get(worktree_id)
        if not state or state.status != "paused":
            return False

        state.status = "active"
        state.last_accessed = import_time()
        self._persist_state()
        return True

    def get_worktree_path(self, worktree_id: str) -> Path | None:
        """获取工作区路径"""
        state = self._active_worktrees.get(worktree_id)
        return state.path if state else None

    def commit_worktree_changes(
        self,
        worktree_id: str,
        message: str,
        files: list[str] | None = None,
    ) -> bool:
        """在工作区提交变更

        Args:
            worktree_id: 工作区 ID
            message: 提交消息
            files: 要提交的文件列表（None 表示全部）

        Returns:
            True 如果提交成功
        """
        state = self._active_worktrees.get(worktree_id)
        if not state or not state.path.exists():
            return False

        try:
            # 在 worktree 目录中执行 git 命令
            def run_git(*args: str) -> subprocess.CompletedProcess:
                return subprocess.run(
                    ["git", *args],
                    capture_output=True,
                    text=True,
                    cwd=state.path,
                    timeout=30,
                )

            # 添加文件
            if files:
                for f in files:
                    run_git("add", f)
            else:
                run_git("add", ".")

            # 提交
            result = run_git("commit", "-m", message)
            if result.returncode != 0 and "nothing to commit" not in result.stdout.lower():
                logger.error(f"Git commit failed: {result.stderr}")
                return False

            state.last_accessed = import_time()
            self._persist_state()
            return True

        except Exception as e:
            logger.error(f"Failed to commit worktree {worktree_id}: {e}")
            return False

    def merge_worktree_changes(
        self,
        source_worktree_id: str,
        target_worktree_id: str,
        strategy: str = "keep",  # "keep" | "integrator" | "prompt"
    ) -> bool:
        """合并工作区变更

        Args:
            source_worktree_id: 源工作区（提供变更）
            target_worktree_id: 目标工作区（接收变更）
            strategy: 合并策略
                - "keep": 保留各自变更（并行模式）
                - "integrator": 通过 integrator 代理智能合并
                - "prompt": 提示用户解决冲突

        Returns:
            True 如果合并成功
        """
        source = self._active_worktrees.get(source_worktree_id)
        target = self._active_worktrees.get(target_worktree_id)

        if not source or not target:
            return False

        if strategy == "keep":
            # 简单策略：不自动合并，仅记录
            logger.info(f"Skipping automatic merge (keep strategy): {source_worktree_id} → {target_worktree_id}")
            return True

        elif strategy == "prompt":
            # 提示用户手动解决
            logger.warning(f"Merge conflict requires manual resolution: {source_worktree_id} → {target_worktree_id}")
            return False

        elif strategy == "integrator":
            # TODO: 通过 IntegratorAgent 智能合并
            logger.info(f"Integrator merge requested: {source_worktree_id} → {target_worktree_id}")
            return True

        return False

    def cleanup(self, worktree_id: str) -> bool:
        """清理工作区（删除所有未跟踪文件）"""
        state = self._active_worktrees.get(worktree_id)
        if not state or not state.path.exists():
            return False

        try:
            # 清理未跟踪文件
            subprocess.run(
                ["git", "clean", "-fd", "--exclude=.clawd/"],
                capture_output=True,
                text=True,
                cwd=state.path,
                timeout=30,
            )
            state.last_accessed = import_time()
            self._persist_state()
            return True
        except Exception as e:
            logger.error(f"Failed to cleanup worktree {worktree_id}: {e}")
            return False

    def get_worktree_status(self, worktree_id: str) -> dict[str, Any]:
        """获取工作区详细状态"""
        state = self._active_worktrees.get(worktree_id)
        if not state:
            return {"error": "Worktree not found"}

        return {
            "worktree_id": state.worktree_id,
            "path": str(state.path),
            "status": state.status,
            "created_at": state.created_at,
            "last_accessed": state.last_accessed,
            "files_modified": state.files_modified,
            "pending_changes": state.pending_changes,
        }


def import_time() -> float:
    """导入 time 模块的 time 函数（避免循环导入）"""
    import time
    return time.time()


__all__ = [
    "WorktreeConfig",
    "WorktreeManager",
    "WorktreeState",
]

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
        """把源工作区的改动合并到目标工作区

        Args:
            source_worktree_id: 源工作区（提供变更）
            target_worktree_id: 目标工作区（接收变更）
            strategy: 合并策略
                - "keep": 不合并，两边各自保留（并行模式的默认边界）
                - "integrator": 真的把源码改动落到目标工作区（tracked 差异 + 未跟踪新文件）；
                  冲突时不覆盖、不猜，返回 False 并记录冲突文件
                - "prompt": 留给人工解决，直接返回 False

        Returns:
            True **仅当改动确实进入目标工作区**。keep / prompt 策略不落地任何改动，因此返回 False
            —— 旧实现这两种情况都返回 True，等于"报成功但什么都没做"（假成功）。

        说明：integrator 用 git 三方补丁做机械合并，不做"LLM 猜冲突"。
        需要语义级合并时应在目标工作区里显式跑 IntegratorAgent，而不是在这里假装成功。
        """
        source = self._active_worktrees.get(source_worktree_id)
        target = self._active_worktrees.get(target_worktree_id)

        if not source or not target:
            logger.warning(
                f"合并失败：工作区不存在（source={source_worktree_id}, target={target_worktree_id}）"
            )
            return False

        if strategy == "keep":
            logger.info(
                f"keep 策略：两侧变更各自保留，不做合并（{source_worktree_id} → {target_worktree_id}）"
            )
            return False

        if strategy == "prompt":
            logger.warning(
                f"prompt 策略：需要人工解决冲突（{source_worktree_id} → {target_worktree_id}）"
            )
            return False

        if strategy == "integrator":
            ok = self._apply_changes_via_git(source, target)
            if ok:
                target.files_modified = sorted(set(target.files_modified) | set(source.files_modified))
                target.last_accessed = import_time()
                self._persist_state()
                logger.info(f"integrator 合并完成：{source_worktree_id} → {target_worktree_id}")
            else:
                logger.warning(f"integrator 合并未落地：{source_worktree_id} → {target_worktree_id}")
            return ok

        logger.warning(f"未知合并策略 {strategy}，未做任何改动")
        return False

    def _apply_changes_via_git(self, source: WorktreeState, target: WorktreeState) -> bool:
        """把源工作区的改动落到目标工作区（**文件级**合并，不猜冲突）

        为什么不用 `git apply --3way`：Windows 上 autocrlf 会让补丁的上下文行
        与实际工作区不一致，`--3way` 回退后照样报 "patch does not apply"，
        表现为"明明只改了一行却合不了"。文件级迁移在任何换行/编码配置下都稳定。

        规则（全有或全无）：
        1. 取两侧 `git status --porcelain`；
        2. 若**同一文件**两侧都改了 → 冲突，一个字节都不动，返回 False；
        3. 否则把源侧改动逐文件复制到目标（新增/修改 → 复制；删除 → 删除）；
        4. 真正落地了至少一个文件才返回 True。
        """
        spath, tpath = source.path, target.path
        if not _is_git_worktree(spath):
            logger.warning(f"源工作区不是 git 工作树，无法机械合并：{spath}")
            return False
        if not _is_git_worktree(tpath):
            logger.warning(f"目标工作区不是 git 工作树，无法机械合并：{tpath}")
            return False

        src_changes = _git_status_paths(spath)
        dst_changes = _git_status_paths(tpath)
        if not src_changes:
            logger.info("源工作区没有改动，无需合并")
            return False

        conflicts = sorted(set(src_changes) & set(dst_changes))
        if conflicts:
            logger.warning(
                f"合并冲突（两侧都改了这些文件，未做任何改动）：{conflicts[:10]}"
            )
            return False

        applied: list[str] = []
        for rel, code in sorted(src_changes.items()):
            src_file = spath / rel
            dst_file = tpath / rel
            if "D" in code:
                if dst_file.exists():
                    dst_file.unlink()
                    applied.append(f"删除 {rel}")
                continue
            if not src_file.is_file():
                continue
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            applied.append(f"{'新增' if '?' in code or 'A' in code else '更新'} {rel}")

        if applied:
            logger.info(f"integrator 已落地 {len(applied)} 个文件改动：{applied[:10]}")
            source.files_modified = sorted(set(source.files_modified) | set(src_changes))
            return True

        logger.warning("源工作区有状态记录但没有任何文件可迁移（可能已被移动或忽略）")
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


def _is_git_worktree(path: Path) -> bool:
    """`path` 是否位于 git 工作树内（worktree 的 .git 是文件而不是目录）"""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_status_paths(path: Path) -> dict[str, str]:
    """返回 {相对路径: 状态码}（含未跟踪文件 `??`）"""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain=v1", "-z",
             "--untracked-files=all"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"读取 {path} 的 git 状态失败: {e}")
        return {}
    if result.returncode != 0:
        logger.warning(f"读取 {path} 的 git 状态失败: {(result.stderr or '').strip()[:300]}")
        return {}

    changes: dict[str, str] = {}
    entries = (result.stdout or "").split(chr(0))
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry or len(entry) < 4:
            continue
        code, rel = entry[:2], entry[3:]
        changes[rel] = code
        # 重命名/复制条目后面还跟着"原路径"，跳过它
        if "R" in code or "C" in code:
            index += 1
    return changes

"""Integration Engine (汲取 GoalX keep/integrate 语义)

管理 Worktree 的生命周期、隔离运行，以及将子会话的修改显式合并回主干。
"""

import json
import logging
from pathlib import Path
from typing import Any

from src.core.git_integration import get_git_manager

logger = logging.getLogger("workflow.integration")


class IntegrationEngine:
    def __init__(self, project_root: Path | str, run_dir: str = "latest"):
        self.project_root = Path(project_root)
        self.run_dir = self.project_root / ".clawd" / "runs" / run_dir
        self.git = get_git_manager(self.project_root)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def _get_integration_state_path(self) -> Path:
        return self.run_dir / "integration-state.json"

    def load_integration_state(self) -> dict[str, Any]:
        """加载 integration-state.json"""
        state_path = self._get_integration_state_path()
        if not state_path.exists():
            return {"version": 1, "records": []}
        try:
            with open(state_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"无法读取 integration state: {e}")
            return {"version": 1, "records": []}

    def save_integration_record(
        self,
        session_id: str,
        method: str,
        source_branch: str,
        target_branch: str,
        commit_sha: str,
    ) -> None:
        """记录合并事实到 integration-state.json"""
        state = self.load_integration_state()

        import datetime
        record = {
            "session_id": session_id,
            "method": method,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "commit_sha": commit_sha,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }

        state["records"].append(record)
        state["updated_at"] = record["timestamp"]

        state_path = self._get_integration_state_path()
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        logger.info(f"已记录 integration: {session_id} via {method}")

    def keep_session(self, session_id: str, method: str = "merge") -> tuple[bool, str]:
        """[汲取 GoalX keep] 将隔离会话的更改合并到当前分支

        Args:
            session_id: 隔离会话的 ID
            method: 合并方法 ("merge" 或 "partial_adopt")

        Returns:
            (成功?, 详细信息)
        """
        logger.info(f"执行 Keep: 将会话 {session_id} 整合回主分支...")

        # 检查 Git 状态是否干净
        if self.git.has_uncommitted_changes() and method != "partial_adopt":
            return False, "主工作区有未提交的更改，请先提交或 stash 以保证安全合并边界"

        # 执行集成
        success, details = self.git.integrate_isolation(session_id, method=method)
        if not success:
            return False, f"Keep 失败: {details}"

        # 记录集成历史
        current_sha = self.git.get_current_sha() or "unknown"
        self.save_integration_record(
            session_id=session_id,
            method=method,
            source_branch=f"clawd-{session_id}",
            target_branch="HEAD",
            commit_sha=current_sha,
        )

        return True, "合并成功并已记录"

    def manually_integrate(self, session_id: str, method: str, notes: str = "") -> None:
        """[汲取 GoalX integrate] 记录手动发生的整合操作

        当冲突发生或使用 --method partial_adopt 手动应用文件时，
        调用此方法显式记录整合事实，使系统知道该分支已被吸收。
        """
        current_sha = self.git.get_current_sha() or "unknown"
        self.save_integration_record(
            session_id=session_id,
            method=f"manual_{method}",
            source_branch=f"clawd-{session_id}",
            target_branch="HEAD",
            commit_sha=current_sha,
        )
        logger.info(f"手动整合已记录: {session_id} ({notes})")

    def keep_to_source(self, session_id: str) -> tuple[bool, str]:
        """[汲取 GoalX keep-to-source] 绕过 git merge，直接同步文件更改。
        适用于希望在不产生 merge commit 的情况下应用更改的场景。
        """
        logger.info(f"执行 Keep-to-Source: 直接同步会话 {session_id} 的文件...")
        return self.keep_session(session_id, method="partial_adopt")

    def cherry_pick_session(self, session_id: str, commit_shas: list[str]) -> tuple[bool, str]:
        """[汲取 GoalX cherry-pick] 从会话分支中选择特定 commit 进行合并。
        """
        logger.info(f"执行 Cherry-pick: 从会话 {session_id} 选取 {len(commit_shas)} 个提交...")

        for sha in commit_shas:
            # 这里需要 git_integration 支持 cherry_pick 接口，暂假定 git.repo.git.cherry_pick
            try:
                self.git.repo.git.cherry_pick(sha)
            except Exception as e:
                logger.error(f"Cherry-pick {sha} 失败: {e}")
                return False, f"Cherry-pick {sha} 失败: {e}"

        self.save_integration_record(
            session_id=session_id,
            method="cherry_pick",
            source_branch=f"clawd-{session_id}",
            target_branch="HEAD",
            commit_sha=commit_shas[-1],
        )
        return True, "Cherry-pick 成功"

    def consolidate_session(self, session_id: str, message: str = "") -> tuple[bool, str]:
        """[汲取 GoalX consolidate] 将会话中的所有更改合并为一个 commit 应用。
        """
        logger.info(f"执行 Consolidate: 压缩并整合会话 {session_id} 的所有更改...")

        # 使用 squash merge 类似的逻辑
        if self.git.has_uncommitted_changes():
            return False, "主工作区有未提交的更改"

        source_branch = f"clawd-{session_id}"
        try:
            # 1. Merge without commit
            self.git.repo.git.merge(source_branch, "--squash")
            # 2. Commit the result
            commit_msg = message or f"consolidate: integrated session {session_id}"
            sha = self.git.commit(message=commit_msg, aider_edits=True)

            if sha:
                self.save_integration_record(
                    session_id=session_id,
                    method="consolidate",
                    source_branch=source_branch,
                    target_branch="HEAD",
                    commit_sha=sha,
                )
                return True, "Consolidate 成功"
            return False, "Commit 失败"
        except Exception as e:
            return False, f"Consolidate 失败: {e}"

    def discard_session(self, session_id: str) -> None:
        """放弃会话更改 (等同于删除 Worktree)"""
        logger.info(f"放弃会话: {session_id}")
        self.git.remove_isolation(session_id, force=True)

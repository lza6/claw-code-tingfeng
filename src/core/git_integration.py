"""Git 集成模块

核心功能 (借鉴 Aider):
1. /undo — 回滚上一次 AI 修改 (仅限本会话的 aider commits)
2. /diff — 查看当前未提交的变更
3. Commit 归因 — Co-authored-by trailer 标注 AI 协作
4. .clawdignore 支持 — 排除指定文件
5. subtree_only — 仅追踪子目录中的文件

使用:
    from src.core.git_integration import GitManager
    git = GitManager(workdir)
    git.commit("feat: add feature", aider_edits=True)
    git.undo_last_aider_commit()
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .git.commit import (
    create_commit,
    generate_commit_message,
    undo_commit,
)
from .git.commit import (
    is_commit_pushed as check_pushed,
)
from .git.diff import get_diff, get_diff_since_commit
from .git.ignore import is_file_ignored, is_path_within_subtree, load_ignore_spec
from .git.types import CommitInfo, DiffResult
from .git.worktree import WorktreeManager

logger = logging.getLogger(__name__)


class GitManager:
    """Git 操作管理器

    功能:
        - 自动创建 repo (如果不存在)
        - 追踪 AI commits 用于 /undo
        - Co-authored-by 归因
        - 安全 undo (检查是否已推送)
    """

    def __init__(
        self,
        workdir: Path | str,
        aider_name: str = "Clawd Code",
        aider_email: str = "clawd@clawd.ai",
        subtree_only: bool = False,
        clawdignore_file: str = ".clawdignore",
        weak_model_callback: Any | None = None,
    ) -> None:
        """初始化 Git 管理器

        Args:
            workdir: 工作目录
            aider_name: AI 作者名
            aider_email: AI 邮箱
            subtree_only: 是否仅追踪子目录中的文件（从 Aider 移植）
            clawdignore_file: ignore 文件名（从 Aider .aiderignore 移植）
            weak_model_callback: 弱模型回调 async fn(diff_text) -> str（借鉴 Aider）
        """
        self.workdir = Path(workdir)
        self.aider_name = aider_name
        self.aider_email = aider_email
        self.subtree_only = subtree_only
        self.clawdignore_file = clawdignore_file
        self._weak_model_callback = weak_model_callback

        # 隔离工作树管理器 (汲取 GoalX)
        self.worktree_manager = WorktreeManager(self.workdir)

        # 追踪本会话的 commit hashes (用于 /undo)
        self.aider_commit_hashes: list[str] = []

        # 每条消息前的 commit SHA (用于 /diff)
        self.commit_before_message: list[str] = []

        # .clawdignore 规范（从 Aider 移植）
        self._ignore_spec: Any = None
        self._ignore_ts: float = 0.0
        self._ignore_last_check: float = 0.0

        # 延迟初始化 repo
        self._repo: Any = None
        self._init_attempted: bool = False

    @property
    def repo(self) -> Any:
        """延迟加载 GitPython Repo"""
        if self._repo is None and not self._init_attempted:
            self._ensure_repo()
        return self._repo

    def _ensure_repo(self) -> None:
        """确保 repo 存在，必要时创建"""
        self._init_attempted = True
        try:
            import git
            from git.exc import InvalidGitRepositoryError

            try:
                self._repo = git.Repo(self.workdir, search_parent_directories=True)
            except InvalidGitRepositoryError:
                # 创建新 repo
                self._repo = git.Repo.init(self.workdir)
                logger.info(f"[Git] 初始化新仓库: {self.workdir}")

                # 配置默认 user
                config = self._repo.config_writer()
                if not config.get_value("user", "name", None):
                    config.set_value("user", "name", "Clawd User")
                if not config.get_value("user", "email", None):
                    config.set_value("user", "email", "user@clawd.ai")
                config.release()

                # 创建初始 commit
                self._repo.index.commit("Initial commit (by Clawd Code)")

        except ImportError:
            logger.warning("[Git] gitpython 未安装，Git 功能不可用")
            self._repo = None

    def is_available(self) -> bool:
        """检查 Git 是否可用"""
        if self._repo is not None:
            return True
        if not self._init_attempted:
            self._ensure_repo()
        return self._repo is not None

    # ---------- .clawdignore 支持（从 Aider .aiderignore 移植） ----------

    def _load_ignore_spec(self) -> Any:
        """加载 .clawdignore 文件（带缓存和热重载）

        从 Aider 的 aiderignore 机制移植，支持:
        - 路径规范解析（类似 .gitignore 语法）
        - 基于 mtime 的自动刷新（1 秒内不重复加载）
        """
        now = time.time()
        if now - self._ignore_last_check < 1.0:
            return self._ignore_spec

        self._ignore_last_check = now

        spec, mtime = load_ignore_spec(self.workdir, self.clawdignore_file)
        self._ignore_spec = spec
        self._ignore_ts = mtime
        return self._ignore_spec

    def is_file_ignored(self, rel_path: str) -> bool:
        """检查文件是否被 .clawdignore 排除

        Args:
            rel_path: 相对于 workdir 的文件路径

        Returns:
            True 如果文件被忽略
        """
        spec = self._load_ignore_spec()
        return is_file_ignored(rel_path, spec)

    # ---------- subtree_only 支持（从 Aider 移植） ----------

    def is_path_within_subtree(self, rel_path: str) -> bool:
        """检查文件是否在子树范围内（subtree_only 模式）

        当 subtree_only=True 时，只允许操作 workdir 子目录下的文件，
        排除 workdir 父目录的文件。

        Args:
            rel_path: 相对于 git root 的文件路径

        Returns:
            True 如果文件在允许范围内
        """
        return is_path_within_subtree(rel_path, self.workdir, self.repo, self.subtree_only)

    def get_current_sha(self) -> str | None:
        """获取当前 HEAD commit SHA"""
        if not self.is_available():
            return None
        try:
            return self.repo.head.commit.hexsha
        except Exception:
            return None

    def push_message_commit(self) -> None:
        """在用户消息处理前记录当前 commit (用于 /diff)"""
        sha = self.get_current_sha()
        if sha:
            self.commit_before_message.append(sha)

    def has_uncommitted_changes(self) -> bool:
        """检查是否有未提交的变更"""
        if not self.is_available():
            return False
        try:
            return self.repo.is_dirty(untracked_files=True)
        except Exception:
            return False

    def get_tracked_files(self) -> list[str]:
        """获取所有已追踪的文件（应用 .clawdignore 和 subtree_only 过滤）"""
        if not self.is_available():
            return []
        try:
            all_files = [item.path for item in self.repo.tree().traverse() if item.type == 'blob']

            # 应用 .clawdignore 过滤
            filtered = [f for f in all_files if not self.is_file_ignored(f)]

            # 应用 subtree_only 过滤
            if self.subtree_only:
                filtered = [f for f in filtered if self.is_path_within_subtree(f)]

            return filtered
        except Exception:
            return []

    def get_diff(self, staged_only: bool = False) -> DiffResult | None:
        """获取当前 diff

        Args:
            staged_only: 仅获取已暂存的变更

        Returns:
            DiffResult 或 None
        """
        if not self.is_available():
            return None
        return get_diff(self.repo, staged_only)

    def get_diff_since_last_message(self) -> DiffResult | None:
        """获取自上次用户消息以来的 diff"""
        if not self.is_available():
            return None

        if not self.commit_before_message:
            return self.get_diff()

        base_sha = self.commit_before_message[-1]
        return get_diff_since_commit(self.repo, base_sha)

    def commit(
        self,
        message: str | None = None,
        aider_edits: bool = True,
        co_authored_by: bool = True,
        attribute_author: bool = False,
        attribute_committer: bool = False,
        auto_add: bool = True,
        generate_message: bool = False,
    ) -> str | None:
        """创建 commit

        Args:
            message: Commit 消息（为 None 时如果 generate_message=True 则自动生成）
            aider_edits: 是否为 AI 编辑 (用于 /undo 追踪)
            co_authored_by: 添加 Co-authored-by trailer
            attribute_author: 修改 author 名称为 "(aider)"
            attribute_committer: 修改 committer 名称为 "(aider)"
            auto_add: 自动 add 所有变更
            generate_message: 是否使用弱模型自动生成 commit message（借鉴 Aider）

        Returns:
            Commit SHA 或 None
        """
        if not self.is_available():
            return None

        try:
            # 自动 add
            if auto_add:
                self.repo.git.add('-A')

            # 检查是否有变更
            if not self.repo.is_dirty(untracked_files=False):
                logger.debug("[Git] 没有变更需要提交")
                return None

            # 自动生成 commit message（借鉴 Aider）
            if generate_message and message is None and self._weak_model_callback:
                try:
                    diff_text = self.repo.git.diff('--cached') or self.repo.git.diff('HEAD')
                    if diff_text.strip():
                        message = generate_commit_message(diff_text, self._weak_model_callback)
                        if message:
                            logger.info(f"[Git] Weak model 生成 commit message: {message[:60]}")
                except Exception as e:
                    logger.debug(f"[Git] 自动生成 commit message 失败: {e}")

            if not message:
                message = "update: auto commit"

            # 创建 commit
            sha = create_commit(
                repo=self.repo,
                workdir=self.workdir,
                message=message,
                aider_name=self.aider_name,
                aider_email=self.aider_email,
                co_authored_by=co_authored_by and aider_edits,
                attribute_author=attribute_author and aider_edits,
                attribute_committer=attribute_committer and aider_edits,
                auto_add=False,  # 已在上面 add
            )

            # 追踪 aider commit
            if sha and aider_edits:
                self.aider_commit_hashes.append(sha)

            return sha

        except Exception as e:
            logger.error(f"[Git] Commit 异常: {e}")
            return None

    def undo_last_aider_commit(self) -> tuple[bool, str]:
        """撤销上一次 AI commit

        借鉴 Aider 的安全策略:
        - 仅撤销本会话的 aider commits
        - 检查是否为 merge commit
        - 检查是否已推送到远程

        Returns:
            (成功?, 消息)
        """
        if not self.is_available():
            return False, "Git 不可用"

        if not self.aider_commit_hashes:
            return False, "没有可撤销的 AI commit (本会话)"

        last_sha = self.aider_commit_hashes[-1]

        # 检查 merge commit
        try:
            commit = self.repo.commit(last_sha)
            if len(commit.parents) > 1:
                return False, "不能撤销 merge commit"
        except Exception:
            pass

        # 检查是否已推送
        if check_pushed(self.repo, last_sha):
            return False, "Commit 已推送到远程，无法撤销"

        # 执行 undo
        success, msg = undo_commit(
            self.repo,
            last_sha,
            self.has_uncommitted_changes(),
        )

        if success:
            self.aider_commit_hashes.pop()

        return success, msg

    def _is_commit_pushed(self, sha: str) -> bool:
        """检查 commit 是否已推送到远程"""
        return check_pushed(self.repo, sha)

    def get_commit_info(self, sha: str | None = None) -> CommitInfo | None:
        """获取 commit 信息"""
        if not self.is_available():
            return None

        try:
            commit = self.repo.commit(sha) if sha else self.repo.head.commit
            return CommitInfo(
                sha=commit.hexsha,
                message=commit.message.strip(),
                author=str(commit.author),
                is_merge=len(commit.parents) > 1,
                is_pushed=check_pushed(self.repo, commit.hexsha),
            )
        except Exception:
            return None

    def get_log(self, max_count: int = 10) -> list[CommitInfo]:
        """获取 commit 历史"""
        if not self.is_available():
            return []

        try:
            commits = []
            for commit in self.repo.iter_commits(max_count=max_count):
                commits.append(CommitInfo(
                    sha=commit.hexsha,
                    message=commit.message.strip().split('\n')[0],  # 第一行
                    author=str(commit.author),
                    is_merge=len(commit.parents) > 1,
                ))
            return commits
        except Exception:
            return []

    # ---------- 增强: Aider 风格的 commit 归属控制 ----------

    def commit_with_attribution(
        self,
        message: str | None = None,
        aider_edits: bool = True,
        attribute_author: bool = False,
        attribute_committer: bool = False,
        attribute_co_authored_by: bool = True,
        attribute_commit_message_author: bool = False,
        attribute_commit_message_committer: bool = False,
    ) -> str | None:
        """带归属控制的 commit (借鉴 Aider)

        借鉴 Aider 的多层归属控制:
        - attribute_author: 修改 GIT_AUTHOR_NAME 为 "(aider)" 后缀
        - attribute_committer: 修改 GIT_COMMITTER_NAME
        - attribute_co_authored_by: 添加 Co-authored-by trailer
        - attribute_commit_message_author: 在消息中标注作者
        - attribute_commit_message_committer: 在消息中标注提交者

        Returns:
            Commit SHA 或 None
        """
        if not self.is_available():
            return None

        try:
            # 添加所有变更
            self.repo.git.add('-A')

            if not self.repo.is_dirty(untracked_files=False):
                logger.debug("[Git] 没有变更需要提交")
                return None

            # 生成消息
            if not message:
                message = "update: auto commit"

            # 构建 commit 消息
            final_message = message

            # 添加 Co-authored-by trailer (最常用的归属方式)
            if aider_edits and attribute_co_authored_by:
                final_message += f"\n\nCo-authored-by: {self.aider_name} <{self.aider_email}>"

            # 消息中标注 (较少使用)
            if attribute_commit_message_author:
                author_name = self.repo.config_reader().get_value("user", "name", "User")
                final_message += f"\n\nAuthored-by: {author_name}"

            if attribute_commit_message_committer and aider_edits:
                final_message += f"\n\nCommitted-by: {self.aider_name}"

            # 执行 commit
            sha = create_commit(
                repo=self.repo,
                workdir=self.workdir,
                message=final_message,
                aider_name=self.aider_name,
                aider_email=self.aider_email,
                co_authored_by=False,  # 已在消息中处理
                attribute_author=attribute_author and aider_edits,
                attribute_committer=attribute_committer and aider_edits,
                auto_add=False,
            )

            # 追踪 aider commit
            if sha and aider_edits:
                self.aider_commit_hashes.append(sha)

            return sha

        except Exception as e:
            logger.error(f"[Git] Commit 异常: {e}")
            return None

    # ---------- 增强: Aider 风格的 undo 多级回退 ----------

    def undo_multiple_commits(self, count: int = 1) -> tuple[bool, str]:
        """撤销多个 AI commits (借鉴 Aider)

        Aider 支持 undo 后继续撤销更早的 commits。
        这在 AI 连续出错的场景下很有用。

        Args:
            count: 要撤销的 commit 数量

        Returns:
            (成功?, 消息)
        """
        if not self.is_available():
            return False, "Git 不可用"

        if count < 1:
            return False, "count 必须大于 0"

        if len(self.aider_commit_hashes) < count:
            return False, f"只有 {len(self.aider_commit_hashes)} 个可撤销的 AI commit"

        # 检查是否有未提交变更
        if self.has_uncommitted_changes():
            return False, "有未提交的变更，请先 stash 或 commit"

        undone_count = 0

        for _ in range(count):
            result, msg = self.undo_last_aider_commit()
            if not result:
                break
            undone_count += 1

        if undone_count == 0:
            return False, msg

        return True, f"已撤销 {undone_count} 个 commit"

    def get_aider_commits(self) -> list[CommitInfo]:
        """获取本会话的所有 AI commits"""
        if not self.is_available():
            return []

        commits = []
        for sha in self.aider_commit_hashes:
            info = self.get_commit_info(sha)
            if info:
                commits.append(info)

        return commits

    def can_undo(self) -> tuple[bool, str]:
        """检查是否可以执行 undo

        Returns:
            (可撤销?, 原因)
        """
        if not self.is_available():
            return False, "Git 不可用"

        if not self.aider_commit_hashes:
            return False, "没有可撤销的 AI commit (本会话)"

        if self.has_uncommitted_changes():
            return False, "有未提交的变更"

        last_sha = self.aider_commit_hashes[-1]
        commit = self.repo.commit(last_sha)

        if len(commit.parents) > 1:
            return False, "最后一个 commit 是 merge commit"

        if check_pushed(self.repo, last_sha):
            return False, "Commit 已推送到远程"

        return True, f"可以撤销 commit {last_sha[:8]}"

    # ---------- 工作树 (Isolation) 支持 (汲取 GoalX) ----------

    def create_isolation(self, session_id: str, branch_name: str | None = None) -> Path:
        """创建一个隔离的执行环境"""
        return self.worktree_manager.create(session_id, branch_name)

    def remove_isolation(self, session_id: str, force: bool = False) -> None:
        """移除隔离的执行环境"""
        self.worktree_manager.remove(session_id, force)

    def integrate_isolation(self, session_id: str) -> bool:
        """将隔离环境中的更改整合回主分支"""
        return self.worktree_manager.integrate(session_id)


# 全局实例
_git_manager: GitManager | None = None


def get_git_manager(workdir: Path | str | None = None) -> GitManager:
    """获取全局 GitManager 实例"""
    global _git_manager
    if _git_manager is None or (workdir and Path(workdir) != _git_manager.workdir):
        _git_manager = GitManager(workdir or Path.cwd())
    return _git_manager

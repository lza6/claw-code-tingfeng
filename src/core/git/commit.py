"""Git Commit 操作"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def create_commit(
    repo: Any,
    workdir: Path,
    message: str,
    aider_name: str,
    aider_email: str,
    co_authored_by: bool = True,
    attribute_author: bool = False,
    attribute_committer: bool = False,
    auto_add: bool = True,
) -> str | None:
    """创建 Git commit

    Args:
        repo: GitPython Repo 实例
        workdir: 工作目录
        message: Commit 消息
        aider_name: AI 作者名
        aider_email: AI 邮箱
        co_authored_by: 添加 Co-authored-by trailer
        attribute_author: 修改 author 名称
        attribute_committer: 修改 committer 名称
        auto_add: 自动 add 所有变更

    Returns:
        Commit SHA 或 None
    """
    try:
        # 自动 add
        if auto_add:
            repo.git.add('-A')

        # 检查是否有变更
        if not repo.is_dirty(untracked_files=False):
            logger.debug("[Git] 没有变更需要提交")
            return None

        # 构建 commit 消息
        final_message = message
        if co_authored_by:
            final_message += f"\n\nCo-authored-by: {aider_name} <{aider_email}>"

        # 使用环境变量控制 author/committer
        env = os.environ.copy()

        if attribute_author:
            original_name = repo.config_reader().get_value("user", "name", "User")
            env['GIT_AUTHOR_NAME'] = f"{original_name} ({aider_name})"

        if attribute_committer:
            original_name = repo.config_reader().get_value("user", "name", "User")
            env['GIT_COMMITTER_NAME'] = f"{original_name} ({aider_name})"

        # 执行 commit
        result = subprocess.run(
            ['git', 'commit', '-m', final_message],
            cwd=workdir,
            capture_output=True,
            text=True,
            env=env,
        )

        if result.returncode != 0:
            logger.error(f"[Git] Commit 失败: {result.stderr}")
            return None

        # 获取新 commit SHA
        sha = repo.head.commit.hexsha
        logger.info(f"[Git] Commit: {sha[:8]} - {message[:50]}")
        return sha

    except Exception as e:
        logger.error(f"[Git] Commit 异常: {e}")
        return None


def undo_commit(
    repo: Any,
    sha: str,
    has_uncommitted_changes: bool,
) -> tuple[bool, str]:
    """撤销指定 commit

    Args:
        repo: GitPython Repo 实例
        sha: 要撤销的 commit SHA
        has_uncommitted_changes: 是否有未提交的变更

    Returns:
        (成功?, 消息)
    """
    try:
        commit = repo.commit(sha)

        # 检查 merge commit
        if len(commit.parents) > 1:
            return False, "不能撤销 merge commit"

        # 检查是否有未提交变更
        if has_uncommitted_changes:
            return False, "有未提交的变更，请先 stash 或 commit"

        # 获取受影响的文件
        files = [item.a_path for item in commit.diff(commit.parents[0])]

        if not files:
            # 使用 git reset --soft
            repo.git.reset('--soft', 'HEAD~1')
        else:
            # 使用 git checkout 恢复文件，然后 reset
            import contextlib
            for f in files:
                with contextlib.suppress(Exception):
                    repo.git.checkout('HEAD~1', '--', f)

            repo.git.reset('--soft', 'HEAD~1')

        logger.info(f"[Git] Undo commit: {sha[:8]}")
        return True, f"已撤销 commit {sha[:8]}，文件已恢复到上一个版本"

    except Exception as e:
        logger.error(f"[Git] Undo 失败: {e}")
        return False, f"撤销失败: {e}"


def is_commit_pushed(repo: Any, sha: str) -> bool:
    """检查 commit 是否已推送到远程

    Args:
        repo: GitPython Repo 实例
        sha: Commit SHA

    Returns:
        True 如果已推送
    """
    try:
        # 获取远程 tracking branch
        if not repo.remotes:
            return False

        remote = repo.remotes.origin
        remote.fetch()

        # 检查 commit 是否在远程分支中
        for branch in repo.branches:
            if branch.tracking_branch():
                remote_branch = branch.tracking_branch()
                if remote_branch:
                    commits_ahead = list(repo.iter_commits(
                        f'{remote_branch}..{branch}'
                    ))
                    if sha in [c.hexsha for c in commits_ahead]:
                        return False  # 本地领先，未推送
        return True  # 已推送或无法确定

    except Exception:
        # 无法检查时保守处理
        return False


def generate_commit_message(diff_text: str, weak_model_callback: Any) -> str | None:
    """使用弱模型自动生成 commit message

    Args:
        diff_text: Diff 文本
        weak_model_callback: 异步回调函数

    Returns:
        生成的 commit message 或 None
    """
    if not weak_model_callback:
        return None
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, weak_model_callback(diff_text))
                return future.result(timeout=10)
        else:
            return loop.run_until_complete(weak_model_callback(diff_text))
    except Exception:
        return None

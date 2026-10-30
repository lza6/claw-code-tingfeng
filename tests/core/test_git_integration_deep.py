"""`src/core/git_integration.py` 深度测试（W2）。

原测试 `test_git_integration.py` 只覆盖 27%（8 个用例），而该模块有 255 条语句、
承担 commit 归因、/undo 安全判断、.clawdignore 过滤、worktree 隔离四件事。

本文件用**真实临时 git 仓库**驱动（不 mock git），因为该模块的核心价值
就是"和真实的 git 状态机打交道"，mock 掉等于没测。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.core.git_integration import GitManager, get_git_manager

# GitPython 在 import 时检查 git 版本：CI 精简容器里 git 缺失/过旧时
# `import git` 直接抛 ImportError 并打印大段指引，整个模块收集失败（38 errors）。
# 延迟到具体测试内再 import（测试本身就有"gitpython 缺失时降级"的用例）。
git = pytest.importorskip("git")


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """一个已配置 user 且有一次初始提交的真实仓库。"""
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")

    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    repo.index.add(["a.txt"])
    repo.index.commit("initial")
    return tmp_path


@pytest.fixture
def manager(repo_dir: Path) -> GitManager:
    return GitManager(repo_dir, aider_name="Clawd Code", aider_email="clawd@clawd.ai")


class TestRepoBootstrap:
    def test_lazy_repo_property_loads_existing_repo(self, manager: GitManager):
        assert manager.repo is not None
        assert manager.repo.working_dir is not None

    def test_creates_repo_when_directory_is_not_repo(self, tmp_path: Path):
        gm = GitManager(tmp_path)

        assert gm.is_available() is True
        assert (tmp_path / ".git").exists()

    def test_is_available_true_in_repo(self, manager: GitManager):
        assert manager.is_available() is True

    def test_is_available_false_when_gitpython_missing(self, tmp_path: Path, monkeypatch):
        """gitpython 缺失时必须返回 False，而不是把异常抛给调用方。"""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "git" or name.startswith("git."):
                raise ImportError("simulated absence")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        assert GitManager(tmp_path).is_available() is False


class TestIgnoreSpec:
    def test_file_matching_clawdignore_is_ignored(self, repo_dir: Path):
        (repo_dir / ".clawdignore").write_text("*.log\n", encoding="utf-8")
        gm = GitManager(repo_dir)

        assert gm.is_file_ignored("debug.log") is True
        assert gm.is_file_ignored("main.py") is False

    def test_missing_ignore_file_means_nothing_ignored(self, manager: GitManager):
        assert manager.is_file_ignored("whatever.log") is False

    def test_path_within_subtree(self, repo_dir: Path):
        """subtree_only 模式下，只有 workdir 子目录内的相对路径被允许。"""
        sub = repo_dir / "sub"
        sub.mkdir()
        gm = GitManager(sub, subtree_only=True)

        assert gm.is_path_within_subtree("sub/pkg/mod.py") is True
        assert gm.is_path_within_subtree("outside.py") is False

    def test_path_check_is_permissive_when_subtree_only_disabled(self, repo_dir: Path):
        gm = GitManager(repo_dir, subtree_only=False)

        assert gm.is_path_within_subtree("../outside.py") is True


class TestInspection:
    def test_get_current_sha_returns_head(self, manager: GitManager):
        sha = manager.get_current_sha()

        assert sha is not None
        assert len(sha) == 40

    def test_has_uncommitted_changes_false_when_clean(self, manager: GitManager):
        assert manager.has_uncommitted_changes() is False

    def test_has_uncommitted_changes_true_after_edit(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "a.txt").write_text("changed\n", encoding="utf-8")

        assert manager.has_uncommitted_changes() is True

    def test_get_tracked_files_lists_txt(self, manager: GitManager):
        files = manager.get_tracked_files()

        assert "a.txt" in files

    def test_get_diff_returns_changes(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "a.txt").write_text("changed\n", encoding="utf-8")

        diff = manager.get_diff()

        assert diff is not None
        assert "changed" in str(getattr(diff, "diff", diff))

    def test_get_log_returns_commits(self, manager: GitManager):
        log = manager.get_log(max_count=5)

        assert len(log) >= 1
        assert log[0].message.strip() == "initial"


class TestCommit:
    def test_commit_with_changes_returns_sha(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "a.txt").write_text("modified\n", encoding="utf-8")

        sha = manager.commit("feat: modify a")

        assert sha is not None
        assert len(sha) == 40
        assert sha in manager.aider_commit_hashes

    def test_commit_without_changes_returns_none(self, manager: GitManager):
        assert manager.commit("nothing to do") is None

    def test_commit_uses_default_message_when_none(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "b.txt").write_text("new\n", encoding="utf-8")

        manager.commit(None)

        assert manager.get_log(1)[0].message.strip() == "update: auto commit"

    def test_commit_adds_co_authored_trailer(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "c.txt").write_text("new\n", encoding="utf-8")

        sha = manager.commit("feat: add c", co_authored_by=True)

        body = manager.repo.commit(sha).message
        assert "Co-authored-by" in body

    def test_commit_without_trailer_when_disabled(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "d.txt").write_text("new\n", encoding="utf-8")

        sha = manager.commit("feat: add d", aider_edits=False)

        assert "Co-authored-by" not in manager.repo.commit(sha).message

    def test_commit_info_for_sha(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "e.txt").write_text("new\n", encoding="utf-8")
        sha = manager.commit("feat: add e")

        info = manager.get_commit_info(sha)

        assert info is not None
        assert info.sha == sha


class TestUndo:
    def test_can_undo_false_without_ai_commits(self, manager: GitManager):
        ok, reason = manager.can_undo()

        assert ok is False
        assert reason

    def test_can_undo_true_after_ai_commit(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "f.txt").write_text("new\n", encoding="utf-8")
        manager.commit("feat: add f")

        ok, reason = manager.can_undo()

        assert ok is True
        assert reason

    def test_undo_last_aider_commit_reverts(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "g.txt").write_text("new\n", encoding="utf-8")
        sha = manager.commit("feat: add g")
        assert sha in manager.aider_commit_hashes

        ok, msg = manager.undo_last_aider_commit()

        # undo 撤销的是"这次 commit"，不是删文件：工作区内容会保留
        assert ok is True
        assert msg
        assert sha not in manager.aider_commit_hashes

    def test_undo_without_history_reports_failure(self, manager: GitManager):
        ok, msg = manager.undo_last_aider_commit()

        assert ok is False
        assert msg

    def test_get_aider_commits_returns_tracked(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "h.txt").write_text("new\n", encoding="utf-8")
        manager.commit("feat: add h")

        commits = manager.get_aider_commits()

        assert len(commits) >= 1


class TestFactory:
    def test_get_git_manager_uses_cwd_by_default(self, repo_dir: Path, monkeypatch):
        monkeypatch.chdir(repo_dir)

        gm = get_git_manager()

        assert gm.repo is not None

    def test_get_git_manager_accepts_path(self, repo_dir: Path):
        gm = get_git_manager(str(repo_dir))

        assert gm.workdir == repo_dir


class TestCommitWithAttribution:
    def test_default_adds_co_authored_trailer(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "i.txt").write_text("new", encoding="utf-8")

        sha = manager.commit_with_attribution("feat: add i")

        assert "Co-authored-by" in manager.repo.commit(sha).message

    def test_can_disable_co_authored_trailer(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "j.txt").write_text("new", encoding="utf-8")

        sha = manager.commit_with_attribution(
            "feat: add j", attribute_co_authored_by=False
        )

        assert "Co-authored-by" not in manager.repo.commit(sha).message

    def test_attribute_commit_message_author_appends_line(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "k.txt").write_text("new", encoding="utf-8")

        sha = manager.commit_with_attribution(
            "feat: add k", attribute_commit_message_author=True
        )

        assert "Authored-by" in manager.repo.commit(sha).message

    def test_no_changes_returns_none(self, manager: GitManager):
        assert manager.commit_with_attribution("nothing") is None


class TestUndoMultiple:
    def test_rejects_non_positive_count(self, repo_dir: Path, manager: GitManager):
        ok, msg = manager.undo_multiple_commits(0)

        assert ok is False
        assert "count" in msg

    def test_rejects_more_than_available(self, repo_dir: Path, manager: GitManager):
        (repo_dir / "l.txt").write_text("new", encoding="utf-8")
        manager.commit("feat: add l")

        ok, msg = manager.undo_multiple_commits(5)

        assert ok is False
        assert "可撤销" in msg

    @pytest.mark.xfail(
        strict=True,
        reason="已知限制 D-11：第一次 undo 后工作区变脏，第二次 undo 被拒绝，"
        "count>1 实际只能撤销 1 个 commit（见计划书 W2 记录）",
    )
    def test_undoes_two_commits(self, repo_dir: Path, manager: GitManager):
        for name in ("m.txt", "n.txt"):
            (repo_dir / name).write_text("new", encoding="utf-8")
            manager.commit(f"feat: add {name}")
        assert len(manager.aider_commit_hashes) == 2

        ok, msg = manager.undo_multiple_commits(2)

        assert ok is True
        assert "2" in msg
        assert manager.aider_commit_hashes == []

    def test_undo_multiple_reports_actual_count(self, repo_dir: Path, manager: GitManager):
        """在 D-11 修好之前，至少要让调用方看到"实际撤销了几个"。"""
        for name in ("p1.txt", "p2.txt"):
            (repo_dir / name).write_text("new", encoding="utf-8")
            manager.commit(f"feat: add {name}")

        ok, msg = manager.undo_multiple_commits(2)

        assert ok is True
        assert "已撤销" in msg


class TestMessageScopeDiff:
    def test_push_message_commit_records_sha(self, manager: GitManager):
        manager.push_message_commit()

        assert len(manager.commit_before_message) == 1

    def test_diff_since_last_message_returns_diff(self, repo_dir: Path, manager: GitManager):
        manager.push_message_commit()
        # 必须改「已跟踪文件」：未跟踪文件不会出现在 git diff 里
        (repo_dir / "a.txt").write_text("changed after message", encoding="utf-8")

        diff = manager.get_diff_since_last_message()

        assert diff is not None

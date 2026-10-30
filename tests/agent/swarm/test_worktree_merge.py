"""Worktree 合并真实行为测试（回归：integrator 曾是 TODO + `return True`）

旧实现：`strategy="integrator"` 打一行日志就 `return True`，`strategy="keep"` 也返回 True
—— 调用方以为变更已合并，其实一个字节都没动过（典型假成功）。

现在：integrator 用 git 三方补丁真的落地改动；keep/prompt 不落地 → 返回 False；
冲突时**不覆盖目标**并返回 False。这些用真实临时 git 仓库验证，不 mock git。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.agent.swarm.worktree_manager import WorktreeManager


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "tester")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "app.txt").write_text("line1\n", encoding="utf-8")
    _git(root, "add", "app.txt")
    _git(root, "commit", "-q", "-m", "init")
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def manager(repo: Path, tmp_path: Path) -> WorktreeManager:
    mgr = WorktreeManager(base_dir=tmp_path / "worktrees")
    mgr.create_worktree("wt-src", base_ref="HEAD")
    mgr.create_worktree("wt-dst", base_ref="HEAD")
    return mgr


class TestIntegratorMerge:
    def test_tracked_change_lands_in_target(self, manager: WorktreeManager):
        src = manager.get_worktree("wt-src")
        dst = manager.get_worktree("wt-dst")
        (src.path / "app.txt").write_text("line1\nline2\n", encoding="utf-8")

        assert manager.merge_worktree_changes("wt-src", "wt-dst", "integrator") is True
        assert (dst.path / "app.txt").read_text(encoding="utf-8") == "line1\nline2\n"

    def test_untracked_new_file_is_copied(self, manager: WorktreeManager):
        src = manager.get_worktree("wt-src")
        dst = manager.get_worktree("wt-dst")
        (src.path / "extra.txt").write_text("new\n", encoding="utf-8")

        assert manager.merge_worktree_changes("wt-src", "wt-dst", "integrator") is True
        assert (dst.path / "extra.txt").read_text(encoding="utf-8") == "new\n"

    def test_conflict_returns_false_and_target_untouched(self, manager: WorktreeManager):
        src = manager.get_worktree("wt-src")
        dst = manager.get_worktree("wt-dst")
        (src.path / "app.txt").write_text("from-src\n", encoding="utf-8")
        (dst.path / "app.txt").write_text("from-dst\n", encoding="utf-8")

        assert manager.merge_worktree_changes("wt-src", "wt-dst", "integrator") is False
        # 冲突时绝不能覆盖目标内容
        assert (dst.path / "app.txt").read_text(encoding="utf-8") == "from-dst\n"

    def test_no_changes_returns_false(self, manager: WorktreeManager):
        """没有改动就没有"合并成功"这回事，不能假报成功"""
        assert manager.merge_worktree_changes("wt-src", "wt-dst", "integrator") is False

    def test_unknown_worktree_returns_false(self, manager: WorktreeManager):
        assert manager.merge_worktree_changes("nope", "wt-dst", "integrator") is False


class TestNonMergingStrategies:
    def test_keep_does_not_claim_success(self, manager: WorktreeManager):
        src = manager.get_worktree("wt-src")
        dst = manager.get_worktree("wt-dst")
        (src.path / "app.txt").write_text("changed\n", encoding="utf-8")

        assert manager.merge_worktree_changes("wt-src", "wt-dst", "keep") is False
        assert (dst.path / "app.txt").read_text(encoding="utf-8") == "line1\n"

    def test_prompt_returns_false(self, manager: WorktreeManager):
        assert manager.merge_worktree_changes("wt-src", "wt-dst", "prompt") is False

    def test_unknown_strategy_returns_false(self, manager: WorktreeManager):
        assert manager.merge_worktree_changes("wt-src", "wt-dst", "whatever") is False

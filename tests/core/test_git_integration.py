"""Tests for src.core.git_integration — GitManager"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch


class TestGitManagerInit:
    """GitManager initialization tests."""

    def test_init_defaults(self):
        from src.core.git_integration import GitManager
        with tempfile.TemporaryDirectory() as tmpdir:
            gm = GitManager(tmpdir)
            assert gm.workdir == Path(tmpdir)
            assert gm.aider_commit_hashes == []
            assert gm.commit_before_message == []

    def test_init_custom_name(self):
        from src.core.git_integration import GitManager
        gm = GitManager("/tmp", aider_name="Custom", aider_email="x@y.z")
        assert gm.aider_name == "Custom"
        assert gm.aider_email == "x@y.z"


class TestGitManagerAvailable:
    """GitManager availability tests."""

    def test_not_available_without_gitpython(self):
        from src.core.git_integration import GitManager
        gm = GitManager("/nonexistent")
        with patch.dict('sys.modules', {'git': None}):
            assert gm.is_available() is False

    def test_init_attempted_flag(self):
        from src.core.git_integration import GitManager
        gm = GitManager("/nonexistent")
        assert gm._init_attempted is False


class TestDiffResult:
    """DiffResult dataclass tests."""

    def test_diff_result_creation(self):
        from src.core.git_integration import DiffResult
        dr = DiffResult(
            files_changed=["a.py", "b.py"],
            additions=10,
            deletions=3,
            diff_text="diff --git a/a.py",
        )
        assert len(dr.files_changed) == 2
        assert dr.additions == 10


class TestCommitInfo:
    """CommitInfo dataclass tests."""

    def test_commit_info_creation(self):
        from src.core.git_integration import CommitInfo
        ci = CommitInfo(
            sha="abc123",
            message="feat: test",
            author="User",
            is_merge=False,
            is_pushed=False,
        )
        assert ci.sha == "abc123"
        assert ci.is_merge is False


class TestGetGitManager:
    """Global singleton tests."""

    def test_singleton_returns_same_instance(self):
        import src.core.git_integration as mod
        from src.core.git_integration import get_git_manager
        old = mod._git_manager
        try:
            mod._git_manager = None
            gm1 = get_git_manager("/tmp/a")
            gm2 = get_git_manager("/tmp/a")
            assert gm1 is gm2
        finally:
            mod._git_manager = old

    def test_singleton_resets_on_different_workdir(self):
        import src.core.git_integration as mod
        from src.core.git_integration import get_git_manager
        old = mod._git_manager
        try:
            mod._git_manager = None
            gm1 = get_git_manager("/tmp/a")
            gm2 = get_git_manager("/tmp/b")
            assert gm1 is not gm2
        finally:
            mod._git_manager = old

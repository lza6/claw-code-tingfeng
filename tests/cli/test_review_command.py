"""`clawd review` 命令测试（离线：替换 ReviewTeam，不发起真实 LLM 调用）

退出码契约：0=APPROVE · 1=NEEDS_FIX · 2=INCOMPLETE（含无目标/角色失败/未知角色）
"""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from typer.testing import CliRunner

from src.agent import review_team as rt
from src.cli import entrypoint


class _FakeReport:
    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.roles = []
        self.blocking_findings = [] if verdict != rt.VERDICT_NEEDS_FIX else ["[security] HIGH: x"]
        self.files = ["a.py"]
        self.diff_included = False

    def summary_line(self) -> str:
        return f"review[{self.verdict}] fake"

    def to_dict(self):
        return {"verdict": self.verdict, "roles": [], "blocking_findings": self.blocking_findings}


def _patch_team(monkeypatch, verdict: str) -> None:
    class _Team:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def review(self, files, diff_text=""):
            return _FakeReport(verdict)

    monkeypatch.setattr(rt, "ReviewTeam", _Team)


@pytest.fixture
def target(tmp_path: Path) -> Path:
    path = tmp_path / "a.py"
    path.write_text("x = 1\n", encoding="utf-8")
    return path


class TestReviewCommand:
    def test_unknown_role_exits_2(self):
        result = CliRunner().invoke(entrypoint.app, ["review", "--roles", "not-a-role"])
        assert result.exit_code == 2
        assert "未知角色" in result.output

    def test_no_targets_exits_2(self, monkeypatch):
        monkeypatch.setattr(rt, "collect_review_targets", lambda paths, workdir=None: [])
        result = CliRunner().invoke(entrypoint.app, ["review"])
        assert result.exit_code == 2
        assert "没有评审目标" in result.output

    def test_approve_exits_0(self, temp_repo, target, monkeypatch):
        _patch_team(monkeypatch, rt.VERDICT_APPROVE)
        monkeypatch.chdir(temp_repo)
        result = CliRunner().invoke(entrypoint.app, ["review", str(target)])
        assert result.exit_code == 0
        assert "APPROVE" in result.output

    def test_needs_fix_exits_1(self, temp_repo, target, monkeypatch):
        _patch_team(monkeypatch, rt.VERDICT_NEEDS_FIX)
        monkeypatch.chdir(temp_repo)
        result = CliRunner().invoke(entrypoint.app, ["review", str(target)])
        assert result.exit_code == 1
        assert "NEEDS_FIX" in result.output

    def test_incomplete_exits_2(self, temp_repo, target, monkeypatch):
        _patch_team(monkeypatch, rt.VERDICT_INCOMPLETE)
        monkeypatch.chdir(temp_repo)
        result = CliRunner().invoke(entrypoint.app, ["review", str(target)])
        assert result.exit_code == 2

    def test_json_output_parsable(self, temp_repo, target, monkeypatch):
        _patch_team(monkeypatch, rt.VERDICT_APPROVE)
        monkeypatch.chdir(temp_repo)
        result = CliRunner().invoke(entrypoint.app, ["review", str(target), "--json"])
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["verdict"] == rt.VERDICT_APPROVE


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """一个干净的临时 git 仓库，避免 review 读到本仓库的真实改动"""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "t"),
    ):
        subprocess.run(["git", *args], cwd=str(repo), capture_output=True, check=False)
    (repo / "seed.py").write_text("seed = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True, check=False)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=str(repo), capture_output=True, check=False
    )
    return repo

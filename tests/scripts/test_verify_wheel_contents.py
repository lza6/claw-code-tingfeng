"""`scripts/verify_wheel_contents.py` 的行为锁（发布打包契约）。

用**真实 zip** 构造合格的/缺件的手工 wheel，断言这三种情况分别得到
0 / 1 / 2 —— 发布流水线里这三个码对应"发出去"、"停下"、"别发"，
一旦退化成同一个码，坏包就会照发（本项目确实发生过 prompts 没进包的事故）。
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.verify_wheel_contents import REQUIRED_MEMBERS, main, verify  # noqa: E402


def _make_wheel(
    dist: Path,
    *,
    name: str = "clawd_code-0.90.0-py3-none-any.whl",
    version: str = "0.90.0",
    prompts: int = 34,
    members: tuple[str, ...] = REQUIRED_MEMBERS,
    with_metadata: bool = True,
) -> Path:
    dist.mkdir(parents=True, exist_ok=True)
    path = dist / name
    with zipfile.ZipFile(path, "w") as zf:
        for m in members:
            zf.writestr(m, "# stub\n")
        for i in range(prompts):
            zf.writestr(f"prompts/agents/agent-{i}.md", f"# agent {i}\n")
        if with_metadata:
            zf.writestr(
                "clawd_code-0.90.0.dist-info/METADATA",
                f"Metadata-Version: 2.1\nName: clawd-code\nVersion: {version}\n",
            )
    return path


class TestPass:
    def test_healthy_wheel_passes(self, tmp_path):
        _make_wheel(tmp_path / "dist")
        result = verify(tmp_path / "dist", "0.90.0")
        assert result["ok"] is True
        assert result["exit_code"] == 0
        assert result["prompts"] == 34
        assert result["problems"] == []


class TestBrokenPackaging:
    def test_missing_prompts_fails(self, tmp_path):
        """真实事故：prompts 没随包出去 → 装完 review 崩"""
        _make_wheel(tmp_path / "dist", prompts=0)
        result = verify(tmp_path / "dist")
        assert result["exit_code"] == 1
        assert any("prompts" in p for p in result["problems"])

    def test_missing_module_fails(self, tmp_path):
        _make_wheel(tmp_path / "dist", members=("src/__init__.py",))
        result = verify(tmp_path / "dist")
        assert result["exit_code"] == 1
        assert result["missing_members"]

    def test_version_mismatch_fails(self, tmp_path):
        _make_wheel(tmp_path / "dist", version="0.89.1")
        result = verify(tmp_path / "dist", "0.90.0")
        assert result["exit_code"] == 1
        assert any("版本" in p for p in result["problems"])

    def test_missing_metadata_fails(self, tmp_path):
        _make_wheel(tmp_path / "dist", with_metadata=False)
        assert verify(tmp_path / "dist", "0.90.0")["exit_code"] == 1


class TestUnusable:
    def test_empty_dist_is_exit_2(self, tmp_path):
        (tmp_path / "dist").mkdir()
        result = verify(tmp_path / "dist")
        assert result["exit_code"] == 2
        assert any("没有 wheel" in p for p in result["problems"])

    def test_missing_dist_is_exit_2(self, tmp_path):
        result = verify(tmp_path / "nope")
        assert result["exit_code"] == 2

    def test_corrupt_wheel_is_exit_2(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "broken-0.90.0-py3-none-any.whl").write_bytes(b"not a zip")
        result = verify(dist)
        assert result["exit_code"] == 2
        assert any("不可读" in p for p in result["problems"])


class TestCli:
    def test_main_json_contract(self, tmp_path, capsys):
        _make_wheel(tmp_path / "dist")
        code = main(["--dist", str(tmp_path / "dist"), "--expect-version", "0.90.0", "--json"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert {"ok", "exit_code", "wheel", "prompts", "problems"} <= set(payload)

    def test_main_failure_exit_code(self, tmp_path, capsys):
        _make_wheel(tmp_path / "dist", prompts=1)
        assert main(["--dist", str(tmp_path / "dist")]) == 1
        captured = capsys.readouterr()
        assert "prompts" in captured.err

"""`scripts/changelog_notes.py` 的行为锁。

发布流水线依赖它区分「取到说明」「版本不存在」「章节为空」三种情况；
这三种情况一旦退化成同一种（例如永远 exit 0 + 空输出），
发出去的 release 会是空壳而流水线全绿 —— 这正是本项目历史上出现过的
「假成功」类型，所以必须有测试钉住。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.changelog_notes import extract_notes, main, normalize_version  # noqa: E402

SAMPLE = """# 变更日志

## [Unreleased]

- 未来某条

## [v0.90.0] (2026-11-01) — 示例标题

### 新增

- 条目 A
- 条目 B

---

## [v0.89.1] (2026-10-31) — 旧版本

- 旧条目

## [0.88.0]

"""
# 上面最后一个章节刻意是空的 → 用于验证 exit 3


@pytest.fixture()
def changelog(tmp_path: Path) -> Path:
    p = tmp_path / "CHANGELOG.md"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def test_normalize_version_accepts_tag_and_plain():
    assert normalize_version("v0.90.0") == "0.90.0"
    assert normalize_version("0.90.0") == "0.90.0"
    assert normalize_version("refs/tags/v0.90.0") == "0.90.0"
    assert normalize_version("  V1.2.3  ") == "1.2.3"


def test_extract_ok(changelog: Path):
    info = extract_notes("v0.90.0", changelog)
    assert info["ok"] is True
    assert info["title"] == "示例标题"
    assert "条目 A" in info["notes"] and "条目 B" in info["notes"]
    # 不应把下一个版本的内容捞进来
    assert "旧条目" not in info["notes"]
    # 结尾的水平分隔线应被剥掉
    assert not info["notes"].rstrip().endswith("---")


def test_extract_missing_version_is_not_silent(changelog: Path):
    info = extract_notes("9.9.9", changelog)
    assert info["ok"] is False
    assert info["notes"] == ""
    assert "没有 v9.9.9" in info["reason"]


def test_extract_empty_section_is_not_success(changelog: Path):
    info = extract_notes("0.88.0", changelog)
    assert info["ok"] is False
    assert "为空" in info["reason"]


def test_extract_missing_file(tmp_path: Path):
    info = extract_notes("0.90.0", tmp_path / "nope.md")
    assert info["ok"] is False
    assert "不存在" in info["reason"]


def test_main_exit_codes(changelog: Path, capsys):
    assert main(["--version", "0.90.0", "--file", str(changelog)]) == 0
    out = capsys.readouterr().out
    assert "示例标题" in out and "条目 A" in out

    assert main(["--version", "9.9.9", "--file", str(changelog)]) == 2
    assert main(["--version", "0.88.0", "--file", str(changelog)]) == 3


def test_main_json_contract(changelog: Path, capsys):
    code = main(["--version", "0.90.0", "--file", str(changelog), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) >= {"ok", "version", "title", "notes", "reason"}
    assert payload["ok"] is True and payload["version"] == "0.90.0"

    assert main(["--version", "9.9.9", "--file", str(changelog), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False


def test_main_out_file_written_only_on_success(changelog: Path, tmp_path: Path):
    target = tmp_path / "notes.md"
    assert main(["--version", "0.90.0", "--file", str(changelog), "-o", str(target)]) == 0
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# v0.90.0 — 示例标题") and "条目 A" in text

    missing = tmp_path / "missing.md"
    assert main(["--version", "9.9.9", "--file", str(changelog), "-o", str(missing)]) == 2
    assert not missing.exists(), "取不到说明时不得留下空文件"


def test_real_changelog_has_current_version():
    """真实 CHANGELOG 必须能抽出当前 pyproject 版本 —— 否则发版时才会发现"""
    import re

    root = Path(__file__).resolve().parents[2]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M).group(1)
    info = extract_notes(version, root / "CHANGELOG.md")
    assert info["ok"] is True, f"CHANGELOG 缺少 v{version} 章节: {info['reason']}"


def test_subprocess_runs_as_script():
    """脚本要能作为子进程跑（流水线里就是这么调的），不能只作为模块可导入"""
    root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "changelog_notes.py"), "--version", "0.89.1"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    assert "v0.89.1" in proc.stdout

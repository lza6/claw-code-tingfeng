"""工作流文件的结构锁。

GitHub Actions 的 YAML 写错时，本地一切正常、**只在推送后才红**（甚至静默不触发）。
本项目已踩过一次：`.pre-commit-config.yaml` 里内联 `python -c` 不是合法 YAML，
三条工作流常红而没人当信号。

这里只做**能确定性检查的部分**（语法 + 关键字段 + 脚本引用存在），
不假装验证了 GitHub 侧的语义。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOW_DIR.glob("*.y*ml"))


def test_workflow_dir_exists():
    assert WORKFLOW_DIR.is_dir(), f"缺少工作流目录: {WORKFLOW_DIR}"
    assert _workflow_files(), "工作流目录里没有任何 yml"


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_is_valid_yaml_with_jobs(path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} 顶层不是 mapping"
    # `on:` 在 YAML 1.1 里会被解析成布尔 True —— PyYAML 就是 1.1，
    # 所以 true/in 两种键名都要接受，不能因此误判为「缺 on」。
    assert "on" in data or True in data, f"{path.name} 缺少 on 触发条件"
    assert "jobs" in data, f"{path.name} 缺少 jobs"
    assert isinstance(data["jobs"], dict) and data["jobs"], f"{path.name} 的 jobs 为空"


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_every_job_has_steps_or_uses(path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job_name, job in data["jobs"].items():
        assert isinstance(job, dict), f"{path.name}:{job_name} 不是 mapping"
        assert "runs-on" in job, f"{path.name}:{job_name} 缺 runs-on"
        assert job.get("steps") or job.get("uses"), f"{path.name}:{job_name} 既无 steps 也无 uses"


def test_release_workflow_contract():
    """发布流水线必须包含：版本三处一致性 + 说明抽取 + 产物断言 + 幂等发布"""
    path = WORKFLOW_DIR / "release.yml"
    assert path.exists(), "缺少 release.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert "tags" in text and "v*" in text, "release.yml 未在 tag v* 上触发"
    assert "changelog_notes.py" in text, "release.yml 未从 CHANGELOG 抽说明（会发空壳）"
    assert "src.__version__" in text, "release.yml 未校验 src.__version__ 与 tag 一致"
    assert "prompts" in text, "release.yml 未断言产物含 prompts/（装完 review 会崩）"
    assert "--clobber" in text or "release edit" in text, "release.yml 的发布不幂等（重跑会 422）"

    jobs = data["jobs"]
    assert {"verify", "build", "publish"} <= set(jobs), f"release.yml 缺 job: {sorted(jobs)}"
    assert "write" in str(jobs["publish"].get("permissions", "")) or "contents" in text, (
        "publish job 需要 contents: write 权限"
    )


def test_ci_gates_present():
    """ci.yml 必须仍包含四条硬指标门禁（防止有人「临时」删掉让 CI 变绿）"""
    text = (WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")
    for needle in [
        "ruff check src/ tests/ --select F821,F811,E9",
        "--collect-only",
        "import_sweep.py",
        "reachability.py",
        "check_silent_except.py",
    ]:
        assert needle in text, f"ci.yml 缺少门禁: {needle}"


def test_referenced_scripts_exist():
    """工作流里引用的本地脚本必须真实存在（写错文件名 → 只在 CI 红）"""
    import re

    missing: list[str] = []
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"python\s+(scripts/[\w\-/]+\.py)", text):
            if not (ROOT / m.group(1)).exists():
                missing.append(f"{path.name} -> {m.group(1)}")
    assert not missing, f"工作流引用了不存在的脚本: {missing}"

"""RalplanStage._read_approved_execution_launch_hint 行为测试

审查修复（2026-10-28）：死码删除批次误将 skip 语义改为读不存在的 .clawd/approved_launch_hint 文件，
导致 can_skip 恒 False。本测试锁定恢复后的 PRD 解析语义（与原 artifacts.py 行为一致）。
"""

from pathlib import Path

from src.workflow.stages.ralplan import _read_approved_execution_launch_hint


def _make_plan(tmp_path: Path, prd_content: str, with_spec: bool = True, slug: str = "auth"):
    plans = tmp_path / ".omx" / "plans"
    specs = tmp_path / ".omx" / "specs"
    plans.mkdir(parents=True)
    specs.mkdir(parents=True)
    (plans / f"prd-{slug}.md").write_text(prd_content, encoding="utf-8")
    if with_spec:
        # 原实现语义：test spec 与 PRD 同在 .omx/plans/ 目录
        (plans / f"test-spec-{slug}.md").write_text("# spec", encoding="utf-8")
    return plans, specs


def test_parses_team_command_from_prd(tmp_path):
    _make_plan(tmp_path, '## Plan\n$team 3:worker "实现登录功能"\n')
    hint = _read_approved_execution_launch_hint(tmp_path, mode="team")
    assert hint is not None
    assert hint.task == "实现登录功能"
    assert hint.worker_count == 3
    assert hint.agent_type == "worker"
    assert hint.linked_ralph is False
    assert hint.command.startswith("$team")
    assert hint.source_path.endswith("prd-auth.md")


def test_parses_team_with_ralph_link(tmp_path):
    _make_plan(tmp_path, '$team ralph 2 "批量重构"\n')
    hint = _read_approved_execution_launch_hint(tmp_path, mode="team")
    assert hint is not None
    assert hint.linked_ralph is True
    assert hint.task == "批量重构"


def test_parses_ralph_command(tmp_path):
    _make_plan(tmp_path, '$ralph "修复所有测试"\n')
    hint = _read_approved_execution_launch_hint(tmp_path, mode="ralph")
    assert hint is not None
    assert hint.task == "修复所有测试"


def test_returns_none_without_test_spec(tmp_path):
    """规划不完整（缺 test spec）→ None，与原 is_planning_complete 一致"""
    _make_plan(tmp_path, '$team 3 "任务"\n', with_spec=False)
    assert _read_approved_execution_launch_hint(tmp_path, mode="team") is None


def test_returns_none_without_command(tmp_path):
    _make_plan(tmp_path, "普通 PRD 内容，没有命令\n")
    assert _read_approved_execution_launch_hint(tmp_path, mode="team") is None


def test_returns_none_on_empty_dir(tmp_path):
    assert _read_approved_execution_launch_hint(tmp_path, mode="team") is None


def test_takes_last_match_and_filters_specs_by_slug(tmp_path):
    plans, specs = _make_plan(tmp_path, '$team 1 "旧任务"\n$team 5 "新任务"\n', slug="auth")
    (plans / "test-spec-other.md").write_text("# other", encoding="utf-8")
    hint = _read_approved_execution_launch_hint(tmp_path, mode="team")
    assert hint is not None
    assert hint.task == "新任务"
    assert hint.test_spec_paths == [str(plans / "test-spec-auth.md")]

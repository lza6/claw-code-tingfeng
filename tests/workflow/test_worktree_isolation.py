"""Git worktree 隔离执行行为测试。

覆盖 ``src/workflow/worktree_isolation.py`` 的真实行为：
路径解析、worktree 创建/复用/回滚、脏工作区与分支占用等并发安全断言。

所有 git 操作都在 ``tmp_path`` 下的临时仓库中进行，绝不触碰主仓库。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.workflow.worktree_isolation import (
    WorkerShutdownMergeReport,
    WorktreeMode,
    _run_git,
    assert_clean_leader_workspace_for_worker_worktrees,
    branch_exists,
    create_merge_report,
    create_team_worker_worktree,
    ensure_worktree,
    find_worktree_by_path,
    has_branch_in_use,
    is_git_repository,
    is_worktree_dirty,
    list_worktrees,
    plan_worktree_target,
    read_workspace_status_lines,
    resolve_worktree_path,
    rollback_provisioned_worktrees,
    sanitize_path_token,
    validate_branch_name,
)

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git 未安装",
)


def _git(cwd, *args: str) -> str:
    """执行 git 命令并断言成功，返回 stdout。"""
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, f"git {' '.join(args)} 失败: {result.stderr}"
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """临时 git 仓库（含一次提交），测试结束随 tmp_path 一起销毁。"""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    return root


# --------------------------------------------------------------------------
# 纯函数：路径 token / 仓库探测 / 分支名校验
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hello World!", "hello-world"),
        ("a---b", "a-b"),
        ("--x--", "x"),
        ("MODE_1", "mode-1"),
        ("team/a b", "team-a-b"),
    ],
)
def test_sanitize_path_token_normalizes_to_path_safe(raw, expected):
    assert sanitize_path_token(raw) == expected


@pytest.mark.parametrize("raw", ["", "!!!", "中文", "---"])
def test_sanitize_path_token_falls_back_to_default(raw):
    assert sanitize_path_token(raw) == "default"


def test_is_git_repository_detects_repo_and_plain_dir(repo, tmp_path):
    assert is_git_repository(str(repo)) is True

    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_git_repository(str(plain)) is False


def test_validate_branch_name_accepts_valid_and_rejects_invalid(repo):
    # 合法分支名不抛异常
    validate_branch_name(str(repo), "feature/ok-name")

    with pytest.raises(ValueError) as excinfo:
        validate_branch_name(str(repo), "bad name~")
    assert "Invalid branch name" in str(excinfo.value)
    assert "bad name~" in str(excinfo.value)


def test_branch_exists_tracks_created_branch(repo):
    assert branch_exists(str(repo), "no-such-branch") is False

    _git(repo, "branch", "created-branch")
    assert branch_exists(str(repo), "created-branch") is True


# --------------------------------------------------------------------------
# 工作区状态与清洁断言
# --------------------------------------------------------------------------


def test_read_workspace_status_lines_empty_for_clean_repo(repo):
    assert read_workspace_status_lines(str(repo)) == []
    assert is_worktree_dirty(str(repo)) is False


def test_read_workspace_status_lines_reports_untracked_file(repo):
    (repo / "untracked.txt").write_text("x", encoding="utf-8")

    lines = read_workspace_status_lines(str(repo))
    assert lines == ["?? untracked.txt"]
    assert is_worktree_dirty(str(repo)) is True


def test_assert_clean_leader_workspace_passes_when_clean(repo):
    # 无异常即通过
    assert_clean_leader_workspace_for_worker_worktrees(str(repo))


def test_assert_clean_leader_workspace_raises_with_preview_when_dirty(repo):
    (repo / "dirty.txt").write_text("x", encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        assert_clean_leader_workspace_for_worker_worktrees(str(repo))

    message = str(excinfo.value)
    assert "Leader workspace is dirty" in message
    assert "?? dirty.txt" in message


def test_is_worktree_dirty_detects_modification_in_worktree(repo):
    plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=True, name="dirty-check")
    )
    result = ensure_worktree(plan)
    assert result is not None

    assert is_worktree_dirty(result.worktree_path) is False
    (Path(result.worktree_path) / "a.txt").write_text("changed\n", encoding="utf-8")
    assert is_worktree_dirty(result.worktree_path) is True


# --------------------------------------------------------------------------
# worktree 列表 / 查找 / 分支占用
# --------------------------------------------------------------------------


def test_list_worktrees_contains_main_worktree(repo):
    entries = list_worktrees(str(repo))

    assert len(entries) == 1
    entry = entries[0]
    assert entry["path"] == str(repo.resolve())
    assert entry["head"] == _git(repo, "rev-parse", "HEAD")
    assert entry["branch_ref"].startswith("refs/heads/")
    assert entry["detached"] is False


def test_find_worktree_by_path_matches_and_returns_none(repo):
    entries = list_worktrees(str(repo))

    assert find_worktree_by_path(entries, str(repo)) is not None
    assert find_worktree_by_path(entries, str(repo / "nowhere")) is None


def test_has_branch_in_use_ignores_the_same_path(repo):
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    entries = list_worktrees(str(repo))

    # 同一路径不算"被其他 worktree 占用"
    assert has_branch_in_use(entries, branch, str(repo)) is False
    # 换一个路径就算占用
    assert has_branch_in_use(entries, branch, str(repo / "other")) is True


# --------------------------------------------------------------------------
# 路径解析
# --------------------------------------------------------------------------


def test_resolve_worktree_path_launch_without_mode_uses_detached_suffix(repo):
    path = resolve_worktree_path(str(repo), "launch")

    assert Path(path).name == "launch-detached"
    assert Path(path).parent.name == "repo.clawd-worktrees"


def test_resolve_worktree_path_launch_sanitizes_mode_name(repo):
    path = resolve_worktree_path(str(repo), "launch", mode_name="My Mode")

    assert Path(path).name == "launch-my-mode"


def test_resolve_worktree_path_autoresearch_uses_mode_and_tag(repo):
    path = resolve_worktree_path(str(repo), "autoresearch", mode_name="M", worktree_tag="T1")

    parts = Path(path).parts
    assert parts[-1] == "autoresearch-m-t1"
    assert parts[-3:-1] == (".clawd", "worktrees")


def test_resolve_worktree_path_team_builds_nested_layout(repo):
    path = resolve_worktree_path(str(repo), "team", team_name="Team A", worker_name="W 1")

    assert Path(path).parts[-5:] == (".clawd", "team", "team-a", "worktrees", "w-1")


# --------------------------------------------------------------------------
# plan_worktree_target
# --------------------------------------------------------------------------


def test_plan_returns_none_when_mode_disabled_or_missing(repo):
    assert plan_worktree_target(str(repo), scope="launch") is None
    assert plan_worktree_target(str(repo), scope="launch", mode=WorktreeMode()) is None


def test_plan_detached_uses_head_as_base_ref(repo):
    plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=True, name="det")
    )

    assert plan is not None
    assert plan.detached is True
    assert plan.branch_name is None
    assert plan.base_ref == _git(repo, "rev-parse", "HEAD")
    assert Path(plan.worktree_path).name == "launch-det"


def test_plan_team_attached_builds_mode_and_worker_branch(repo):
    plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="mode1"),
        team_name="teamA",
        worker_name="worker1",
    )

    assert plan is not None
    assert plan.branch_name == "mode1/worker1"
    assert plan.detached is False


def test_plan_team_attached_without_worker_name_raises(repo):
    with pytest.raises(ValueError, match="Worker name is required"):
        plan_worktree_target(
            str(repo),
            scope="team",
            mode=WorktreeMode(enabled=True, detached=False, name="mode1"),
        )


def test_plan_launch_attached_uses_mode_name_as_branch(repo):
    plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=False, name="feat-x")
    )

    assert plan is not None
    assert plan.branch_name == "feat-x"


def test_plan_autoresearch_attached_encodes_run_tag(repo):
    plan = plan_worktree_target(
        str(repo),
        scope="autoresearch",
        mode=WorktreeMode(enabled=True, detached=False, name="Exp"),
        worktree_tag="run 7",
    )

    assert plan is not None
    assert plan.branch_name == "autoresearch/exp/run-7"


def test_plan_raises_when_not_a_git_repository(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(RuntimeError, match="Not a git repository"):
        plan_worktree_target(str(plain), scope="launch", mode=WorktreeMode(enabled=True))


# --------------------------------------------------------------------------
# ensure_worktree
# --------------------------------------------------------------------------


def test_ensure_worktree_returns_none_for_empty_plan():
    assert ensure_worktree(None) is None


def test_ensure_worktree_creates_detached_worktree_at_base_ref(repo):
    plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=True, name="create")
    )
    result = ensure_worktree(plan)

    assert result is not None
    assert (result.created, result.reused, result.created_branch) == (True, False, False)
    assert result.detached is True
    assert Path(result.worktree_path).is_dir()
    # 新 worktree 的 HEAD 必须落在计划基线，且处于 detached 状态
    assert _git(result.worktree_path, "rev-parse", "HEAD") == plan.base_ref
    assert subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=result.worktree_path,
        capture_output=True,
        text=True,
    ).stdout.strip() == "HEAD"


def test_ensure_worktree_reuses_clean_matching_worktree(repo):
    plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=True, name="reuse")
    )
    first = ensure_worktree(plan)
    second = ensure_worktree(plan)

    assert first is not None and second is not None
    assert first.created is True
    assert (second.created, second.reused) == (False, True)
    assert second.worktree_path == first.worktree_path
    # 复用不得产生新的 worktree 条目
    assert len(list_worktrees(str(repo))) == 2


def test_ensure_worktree_rejects_head_mismatch_on_reuse(repo):
    plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=True, name="stale")
    )
    assert ensure_worktree(plan) is not None

    # 领导者仓库前进一次提交 → 已存在 worktree 的 HEAD 不再匹配基线
    (repo / "b.txt").write_text("second\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "second")
    new_plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=True, name="stale")
    )
    assert new_plan.base_ref != plan.base_ref

    with pytest.raises(RuntimeError, match="Worktree target mismatch"):
        ensure_worktree(new_plan)


def test_ensure_worktree_rejects_dirty_existing_worktree(repo):
    plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=True, name="dirty")
    )
    result = ensure_worktree(plan)
    assert result is not None
    (Path(result.worktree_path) / "scratch.txt").write_text("x", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Worktree is dirty"):
        ensure_worktree(plan)


def test_ensure_worktree_creates_new_branch_when_absent(repo):
    plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="rb"),
        team_name="teamA",
        worker_name="wa",
    )
    result = ensure_worktree(plan)

    assert result is not None
    assert result.branch_name == "rb/wa"
    assert result.created_branch is True
    assert branch_exists(str(repo), "rb/wa") is True
    assert _git(result.worktree_path, "rev-parse", "--abbrev-ref", "HEAD") == "rb/wa"


def test_ensure_worktree_checks_out_preexisting_branch(repo):
    _git(repo, "branch", "rb/wb")
    plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="rb"),
        team_name="teamA",
        worker_name="wb",
    )
    result = ensure_worktree(plan)

    assert result is not None
    assert (result.created, result.created_branch) == (True, False)
    assert _git(result.worktree_path, "rev-parse", "--abbrev-ref", "HEAD") == "rb/wb"


def test_ensure_worktree_rejects_path_occupied_by_plain_directory(repo):
    plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=True, name="occupied")
    )
    assert plan is not None
    Path(plan.worktree_path).mkdir(parents=True)

    with pytest.raises(RuntimeError, match="Path exists but is not a worktree"):
        ensure_worktree(plan)


def test_ensure_worktree_rejects_branch_checked_out_elsewhere(repo):
    # 团队 worktree 先占用 rb/wa
    team_plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="rb"),
        team_name="teamA",
        worker_name="wa",
    )
    assert ensure_worktree(team_plan) is not None

    # 另一个 scope 复用同一分支名 → 必须被预检拒绝，而不是让 git 报错
    launch_plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=False, name="rb/wa")
    )
    assert launch_plan.branch_name == "rb/wa"

    with pytest.raises(RuntimeError, match="already checked out in another worktree"):
        ensure_worktree(launch_plan)


def test_ensure_worktree_attached_without_branch_name_fails_loudly(repo):
    """已知缺陷（worktree_isolation.py:390）：attached 模式缺 branch_name 时透出原始 TypeError。

    正常调用方由 plan_worktree_target 的 name 校验挡住；这里锁定当前失败形态，
    确保它至少不会静默创建出错误 worktree。
    """
    plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name=None),
        team_name="teamA",
        worker_name="w1",
    )
    assert plan.branch_name is None and plan.detached is False

    with pytest.raises(TypeError):
        ensure_worktree(plan)

    assert len(list_worktrees(str(repo))) == 1


# --------------------------------------------------------------------------
# rollback_provisioned_worktrees
# --------------------------------------------------------------------------


async def test_rollback_removes_worktrees_and_created_branches(repo):
    mode = WorktreeMode(enabled=True, detached=False, name="rb")
    plans = [
        plan_worktree_target(str(repo), scope="team", mode=mode, team_name="t", worker_name=w)
        for w in ("wa", "wb")
    ]
    results = [ensure_worktree(p) for p in plans]
    assert all(r is not None and r.created for r in results)
    assert branch_exists(str(repo), "rb/wa") and branch_exists(str(repo), "rb/wb")

    await rollback_provisioned_worktrees(results)

    assert not Path(results[0].worktree_path).exists()
    assert not Path(results[1].worktree_path).exists()
    assert branch_exists(str(repo), "rb/wa") is False
    assert branch_exists(str(repo), "rb/wb") is False
    assert len(list_worktrees(str(repo))) == 1


async def test_rollback_keeps_branch_when_skip_branch_deletion(repo):
    plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="rb"),
        team_name="t",
        worker_name="wa",
    )
    result = ensure_worktree(plan)
    assert result is not None

    await rollback_provisioned_worktrees([result], skip_branch_deletion=True)

    assert not Path(result.worktree_path).exists()
    assert branch_exists(str(repo), "rb/wa") is True


async def test_rollback_ignores_none_and_reused_results(repo):
    plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="rb"),
        team_name="t",
        worker_name="wa",
    )
    created = ensure_worktree(plan)
    reused = ensure_worktree(plan)
    assert created is not None and reused is not None
    assert reused.reused is True

    # 只回滚 created 的项；reused 与 None 不参与，也不得报错
    await rollback_provisioned_worktrees([None, reused])

    assert Path(created.worktree_path).exists()
    assert branch_exists(str(repo), "rb/wa") is True


async def test_rollback_aggregates_removal_failures(repo, monkeypatch):
    plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="rb"),
        team_name="t",
        worker_name="wa",
    )
    result = ensure_worktree(plan)
    assert result is not None

    def boom(args, cwd, check=True):
        raise OSError("git exploded")

    monkeypatch.setattr("src.workflow.worktree_isolation._run_git", boom)

    with pytest.raises(RuntimeError, match="Worktree rollback failed"):
        await rollback_provisioned_worktrees([result])


# --------------------------------------------------------------------------
# 便捷函数与合并报告
# --------------------------------------------------------------------------


def test_create_team_worker_worktree_builds_attached_branch(repo):
    result = create_team_worker_worktree(str(repo), team_name="teamA", worker_name="worker1")

    assert result is not None
    assert result.detached is False
    assert result.branch_name == "worker1/worker1"
    assert result.created is True
    assert branch_exists(str(repo), "worker1/worker1") is True


def test_create_team_worker_worktree_honours_explicit_mode_name(repo):
    result = create_team_worker_worktree(
        str(repo), team_name="teamA", worker_name="w9", mode_name="planner"
    )

    assert result is not None
    assert result.branch_name == "planner/w9"


@pytest.mark.parametrize(
    ("merge_result", "expected_success"),
    [("merged", True), ("noop", True), ("conflict", False), ("skipped", False)],
)
def test_merge_report_is_success_matrix(merge_result, expected_success):
    report = create_merge_report("worker-1", merge_result)

    assert isinstance(report, WorkerShutdownMergeReport)
    assert report.is_success is expected_success
    assert report.conflict_files == []


def test_merge_report_carries_commit_sha_and_conflicts():
    report = create_merge_report(
        "worker-2",
        "conflict",
        commit_sha="deadbeef",
        conflict_files=["a.py", "b.py"],
        message="needs manual resolve",
    )

    assert report.commit_sha == "deadbeef"
    assert report.conflict_files == ["a.py", "b.py"]
    assert report.message == "needs manual resolve"
    assert report.is_success is False


# --------------------------------------------------------------------------
# _run_git 超时处理
# --------------------------------------------------------------------------


def test_run_git_raises_runtime_error_on_timeout(repo, monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["git", "status"], timeout=30)

    monkeypatch.setattr("src.workflow.worktree_isolation.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="Git command timed out"):
        _run_git(["status"], str(repo))


def test_run_git_returns_rc_stdout_stderr(repo):
    rc, stdout, _ = _run_git(["rev-parse", "--show-toplevel"], str(repo))

    assert rc == 0
    assert stdout.endswith("repo")


# --------------------------------------------------------------------------
# 错误路径与 git 错误翻译
# --------------------------------------------------------------------------


def test_status_helpers_raise_outside_git_repository(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(RuntimeError, match="Failed to check worktree status"):
        is_worktree_dirty(str(plain))
    with pytest.raises(RuntimeError, match="Failed to read workspace status"):
        read_workspace_status_lines(str(plain))
    with pytest.raises(RuntimeError, match="Failed to list worktrees"):
        list_worktrees(str(plain))


def test_list_worktrees_returns_empty_list_for_blank_output(repo, monkeypatch):
    def fake(args, cwd, check=True):
        if args[:2] == ["worktree", "list"]:
            return 0, "", ""
        return _run_git(args, cwd, check)

    monkeypatch.setattr("src.workflow.worktree_isolation._run_git", fake)

    assert list_worktrees(str(repo)) == []


def test_plan_raises_when_repository_has_no_commit(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    _git(root, "init")

    with pytest.raises(RuntimeError, match="Failed to get HEAD ref"):
        plan_worktree_target(str(root), scope="launch", mode=WorktreeMode(enabled=True))


def test_ensure_worktree_rejects_branch_mismatch_on_reuse(repo):
    # 同一路径先被分支 rb/wa 占用
    first = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="rb"),
        team_name="teamA",
        worker_name="wa",
    )
    assert ensure_worktree(first) is not None

    # 同一路径改用别的分支名 → 必须拒绝复用
    second = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="other"),
        team_name="teamA",
        worker_name="wa",
    )
    assert second.worktree_path == first.worktree_path
    assert second.branch_name == "other/wa"

    with pytest.raises(RuntimeError, match="expected branch refs/heads/other/wa"):
        ensure_worktree(second)


def test_ensure_worktree_translates_git_already_checked_out_error(repo, monkeypatch):
    real_run = _run_git

    def fake(args, cwd, check=True):
        if args[:2] == ["worktree", "add"]:
            return 1, "", "fatal: 'rb/wa' is already checked out at 'C:/other/wt'"
        return real_run(args, cwd, check)

    monkeypatch.setattr("src.workflow.worktree_isolation._run_git", fake)
    plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="rb"),
        team_name="teamA",
        worker_name="wa",
    )

    with pytest.raises(RuntimeError, match="already in use by another worktree"):
        ensure_worktree(plan)


def test_ensure_worktree_propagates_generic_git_failure(repo, monkeypatch):
    real_run = _run_git

    def fake(args, cwd, check=True):
        if args[:2] == ["worktree", "add"]:
            return 128, "", "fatal: some unrelated git problem"
        return real_run(args, cwd, check)

    monkeypatch.setattr("src.workflow.worktree_isolation._run_git", fake)
    plan = plan_worktree_target(
        str(repo), scope="launch", mode=WorktreeMode(enabled=True, detached=True, name="gen-fail")
    )

    with pytest.raises(RuntimeError, match="Failed to create worktree: fatal: some unrelated git problem"):
        ensure_worktree(plan)


async def test_rollback_keeps_branch_it_did_not_create(repo):
    _git(repo, "branch", "rb/wb")
    plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="rb"),
        team_name="teamA",
        worker_name="wb",
    )
    result = ensure_worktree(plan)
    assert result is not None
    assert result.created_branch is False

    await rollback_provisioned_worktrees([result])

    assert Path(result.worktree_path).exists() is False
    # 分支不是本流程创建的，回滚不得删除
    assert branch_exists(str(repo), "rb/wb") is True


async def test_rollback_reports_branch_deletion_failure(repo, monkeypatch):
    plan = plan_worktree_target(
        str(repo),
        scope="team",
        mode=WorktreeMode(enabled=True, detached=False, name="rb"),
        team_name="teamA",
        worker_name="wa",
    )
    result = ensure_worktree(plan)
    assert result is not None
    assert result.created_branch is True

    real_run = _run_git

    def fake(args, cwd, check=True):
        if args[:2] == ["branch", "-D"]:
            raise OSError("cannot delete branch")
        return real_run(args, cwd, check)

    monkeypatch.setattr("src.workflow.worktree_isolation._run_git", fake)

    with pytest.raises(RuntimeError, match="Worktree rollback failed"):
        await rollback_provisioned_worktrees([result])

    # worktree 已被移除，但分支仍在
    assert Path(result.worktree_path).exists() is False
    assert branch_exists(str(repo), "rb/wa") is True

""" team-exec 阶段必须真的把团队状态落盘（此前 team_persistence 270 行零调用）

真实背景：`src/workflow/team_persistence.py` 整套 API（成员/消息/状态）造好了，
但只在 `workflow/__init__.py` 里 re-export，**没有任何调用方** —— 也就是
"团队状态持久化"这个能力一直没跑过。本测试钉住接线后的行为。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """把团队状态目录指到临时目录，避免污染真实数据目录"""
    monkeypatch.setenv("CLAWD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


class _FakeResult:
    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.final_result = "worker 完成"
        self.errors: list[str] = [] if success else ["boom"]
        self.elapsed_seconds = 0.1


def _run_stage(ctx, *, success: bool = True, monkeypatch=None):
    from src.workflow.pipeline import create_team_exec_stage

    class _FakeEngine:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def run(self, task):
            return _FakeResult(success)

    monkeypatch.setattr("src.agent.swarm.engine.SwarmEngine", _FakeEngine)
    stage = create_team_exec_stage(worker_count=2, agent_type="executor")
    return asyncio.run(stage.run(ctx))


def _ctx(tmp_path: Path, session_id: str | None = None):
    from src.workflow.pipeline_stage import StageContext

    return StageContext(task="实现一个登录接口", cwd=str(tmp_path), session_id=session_id)


def _state_file(tmp_path: Path, session_id: str | None = None) -> Path:
    base = tmp_path / "data" / "state"
    return (base / session_id / "team-state.json") if session_id else (base / "team-state.json")


class TestTeamStatePersisted:
    def test_members_and_phase_written_on_success(self, isolated_state, monkeypatch):
        tmp_path = isolated_state
        result = _run_stage(_ctx(tmp_path), success=True, monkeypatch=monkeypatch)
        assert result.status.name == "SUCCESS"

        path = _state_file(tmp_path)
        assert path.is_file(), f"团队状态没落盘: {path}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["phase"] == "completed", data
        assert data["task"].startswith("实现一个登录接口")
        member_ids = {m["id"] for m in data["members"]}
        assert {"worker-1", "worker-2"} <= member_ids, data["members"]
        assert all(m["status"] == "idle" for m in data["members"]), data["members"]
        assert data["completed_at"], "收尾时间没写"
        texts = [m.get("content", "") for m in data.get("messages", [])]
        assert any("team-exec 开始" in t for t in texts), f"没有开始消息: {texts}"
        assert any("team-exec 结束" in t for t in texts), f"没有收尾消息: {texts}"

    def test_failure_marks_phase_failed(self, isolated_state, monkeypatch):
        tmp_path = isolated_state
        result = _run_stage(_ctx(tmp_path), success=False, monkeypatch=monkeypatch)
        assert result.status.name == "FAILED"

        data = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
        assert data["phase"] == "failed", data
        assert all(m["status"] == "offline" for m in data["members"]), data["members"]

    def test_session_id_scopes_state_file(self, isolated_state, monkeypatch):
        tmp_path = isolated_state
        _run_stage(_ctx(tmp_path, session_id="sess-x"), success=True, monkeypatch=monkeypatch)
        assert _state_file(tmp_path, "sess-x").is_file(), "带 session_id 时应写到子目录"
        assert not _state_file(tmp_path).is_file(), "不应同时写全局文件"

    def test_state_dir_follows_data_dir_not_cwd(self, isolated_state, monkeypatch):
        """状态目录跟随 CLAWD_DATA_DIR（不是 cwd 下的 .clawd）"""
        tmp_path = isolated_state
        work = tmp_path / "proj"
        work.mkdir()
        from src.workflow.pipeline_stage import StageContext

        ctx = StageContext(task="x", cwd=str(work))
        _run_stage(ctx, success=True, monkeypatch=monkeypatch)

        assert (tmp_path / "data" / "state" / "team-state.json").is_file()
        assert not (work / ".clawd" / "state").exists(), "不应再往 cwd 的 .clawd 里写"


class TestCwdIsNotAPathInput:
    """P3 项 3：`cwd` 曾是死参数（函数体从不使用，传什么都不影响落盘位置）

    以前 `_get_team_state_path(cwd=".", session_id=None)` 收下 cwd 就扔了 ——
    读代码的人会以为"传 cwd 能改落盘目录"，实际不能（本项目已知陷阱表里
    「参数被接受但被忽略」的实例）。修法：内部函数删掉 cwd，公开函数保留形参
    纯为兼容，并在 docstring 里写明它不参与路径计算。
    """

    def test_different_cwd_writes_to_the_same_state_file(self, isolated_state):
        from src.workflow import team_persistence as tp

        cwd_a = isolated_state / "proj-a"
        cwd_b = isolated_state / "proj-b"
        cwd_a.mkdir()
        cwd_b.mkdir()

        state = tp.TeamStateData(team_id="t1", task="同一个团队")
        assert tp.write_team_state(state, cwd=str(cwd_a)) is True
        assert tp.write_team_state(state, cwd=str(cwd_b)) is True

        expected = _state_file(isolated_state)
        assert expected.is_file(), f"状态应落在数据目录: {expected}"
        # 传不同 cwd 不得在各自 cwd 下另开一份
        assert not (cwd_a / ".clawd" / "state").exists()
        assert not (cwd_b / ".clawd" / "state").exists()

    def test_private_path_helper_has_no_cwd_parameter(self):
        import inspect

        from src.workflow.team_persistence import _get_team_state_path

        params = list(inspect.signature(_get_team_state_path).parameters)
        assert params == ["session_id"], f"私有路径函数不该再收 cwd: {params}"

    def test_public_api_keeps_cwd_but_documents_it_as_compat_only(self):
        import inspect

        from src.workflow import team_persistence as tp

        for fn in (
            tp.read_team_state,
            tp.write_team_state,
            tp.add_team_member,
            tp.remove_team_member,
            tp.update_member_status,
            tp.add_team_message,
            tp.get_team_messages,
        ):
            assert "cwd" in inspect.signature(fn).parameters, f"{fn.__name__} 丢了 cwd（破坏兼容）"
            assert "仅为兼容保留" in (fn.__doc__ or ""), f"{fn.__name__} 没写明 cwd 不参与落盘路径"

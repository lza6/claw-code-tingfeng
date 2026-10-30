"""`clawd session` 命令组测试（会话持久化此前只能在代码里用，CLI 摸不到）"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.entrypoint import app
from src.core.session_store import StoredSession, save_session

runner = CliRunner()


@pytest.fixture
def sdir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    save_session(StoredSession(
        session_id="root", messages=("u", "a"), input_tokens=10, output_tokens=5,
        title="原始会话", turn_count=1,
    ), d)
    return d


def invoke(*args: str):
    return runner.invoke(app, ["session", *args])


class TestSessionList:
    def test_empty(self, tmp_path: Path):
        d = tmp_path / "empty"
        d.mkdir()
        result = invoke("list", "--dir", str(d))
        assert result.exit_code == 0
        assert "暂无" in result.output

    def test_lists_saved_session(self, sdir: Path):
        result = invoke("list", "--dir", str(sdir))
        assert result.exit_code == 0
        assert "root" in result.output
        assert "原始会话" in result.output

    def test_json_output(self, sdir: Path):
        result = invoke("list", "--json", "--dir", str(sdir))
        assert result.exit_code == 0
        import json as _json
        payload = _json.loads(result.output)
        # 统一契约：{ok, code, sessions, count}（v0.88.6 起不再是裸数组）
        assert payload["ok"] is True and payload["code"] == 0
        rows = payload["sessions"]
        assert payload["count"] == len(rows) >= 1
        assert rows[0]["session_id"] == "root"
        assert rows[0]["title"] == "原始会话"


class TestSessionShow:
    def test_show_details_and_chain(self, sdir: Path):
        invoke("fork", "root", "child", "--dir", str(sdir))
        result = invoke("show", "child", "--dir", str(sdir))

        assert result.exit_code == 0
        import json as _json
        data = _json.loads(result.output)
        assert data["parent_session_id"] == "root"
        assert data["chain"] == ["child", "root"]
        assert data["messages"] == 2

    def test_missing_session_exits_one(self, sdir: Path):
        result = invoke("show", "ghost", "--dir", str(sdir))
        assert result.exit_code == 1
        assert "读取失败" in result.output


class TestSessionFork:
    def test_fork_cli(self, sdir: Path):
        result = invoke("fork", "root", "child", "--title", "实验分支", "--dir", str(sdir))

        assert result.exit_code == 0
        assert "已分叉" in result.output

        import json as _json
        shown = _json.loads(invoke("show", "child", "--dir", str(sdir)).output)
        assert shown["title"] == "实验分支"
        assert shown["parent_session_id"] == "root"

    def test_fork_missing_parent(self, sdir: Path):
        result = invoke("fork", "ghost", "child", "--dir", str(sdir))
        assert result.exit_code == 1
        assert "分叉失败" in result.output


class TestSessionTitle:
    def test_set_title(self, sdir: Path):
        result = invoke("title", "root", "登录接口改造", "--dir", str(sdir))

        assert result.exit_code == 0
        assert "标题已更新" in result.output

        import json as _json
        shown = _json.loads(invoke("show", "root", "--dir", str(sdir)).output)
        assert shown["title"] == "登录接口改造"

    def test_title_missing_session(self, sdir: Path):
        result = invoke("title", "ghost", "x", "--dir", str(sdir))
        assert result.exit_code == 1


class TestEnginePersistenceBridge:
    """核心缺口回归：两套会话存储并存且 schema 不同，CLI 必须都读得到"""

    def test_engine_persist_makes_session_visible_to_cli(self, tmp_path: Path, monkeypatch):
        from src.agent.engine import AgentEngine

        # 安全默认是"测试环境不落盘"（审计 P1-3），此处显式开启以验证落盘链路
        monkeypatch.setenv("CLAWD_FORCE_SESSION_PERSIST", "1")
        monkeypatch.setenv("CLAWD_DATA_DIR", str(tmp_path / ".clawd"))
        engine = AgentEngine(workdir=tmp_path)

        class _FakeSession:
            goal = "实现登录接口"
            total_tokens = 321
            final_result = "已完成"
            steps = []

        engine._persist_session(_FakeSession())

        sess_dir = tmp_path / ".clawd" / "sessions"
        files = list(sess_dir.glob("*.json"))
        assert files, "引擎运行后必须产生会话文件（此前两套实现都没人写）"

        result = invoke("list", "--dir", str(sess_dir))
        assert result.exit_code == 0
        assert "实现登录接口" in result.output

    def test_bridge_reads_engine_format(self, tmp_path: Path):
        from src.core.session_bridge import list_all, persist_agent_session

        persist_agent_session(
            "s1", "任务A", [{"role": "assistant", "content": "步骤1"}],
            final_result="结果", total_tokens=10, directory=tmp_path,
        )

        views = list_all(tmp_path)

        assert len(views) == 1
        assert views[0].fmt == "engine"
        assert views[0].title.startswith("任务A")
        assert any(m["role"] == "user" for m in views[0].messages)
        assert any(m["role"] == "assistant" for m in views[0].messages)

    def test_bridge_reads_legacy_format(self, tmp_path: Path):
        """旧格式（字符串消息）也要能读，不能因为格式不同就看不见"""
        import json

        (tmp_path / "legacy.json").write_text(json.dumps({
            "session_id": "legacy", "messages": ["u1", "a1"],
            "input_tokens": 5, "output_tokens": 2, "title": "老会话",
        }), encoding="utf-8")

        from src.core.session_bridge import load

        view = load("legacy", tmp_path)

        assert view.fmt == "legacy"
        assert len(view.messages) == 2
        assert view.title == "老会话"

    def test_fork_from_legacy_writes_engine_format(self, tmp_path: Path):
        import json

        (tmp_path / "old.json").write_text(json.dumps({
            "session_id": "old", "messages": ["u", "a"],
        }), encoding="utf-8")

        from src.core.session_bridge import fork, load

        fork("old", "new", title="分支", directory=tmp_path)

        assert load("new", tmp_path).fmt == "engine"
        assert load("old", tmp_path).fmt == "legacy"  # 父会话未被改写

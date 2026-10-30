"""会话落盘结构测试（真实运行发现的两个缺口）

1. 工具步骤被压平成 assistant 文本 → `clawd explain` 只能看到"读到了文件内容"，
   看不出"调了哪个工具、成没成功"。
2. `model` / `provider` / 输出 token / 费用根本没写进会话 → `clawd explain` 显示
   "模型: 未知 / 输出 0 tokens / $0.0000"，而真实调用其实花了 262 输出 token。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core import session_bridge
from src.core.session_bridge import persist_agent_session


class TestPersistKeepsToolStructure:
    def test_tool_steps_keep_name_and_ok(self, tmp_path: Path):
        persist_agent_session(
            session_id="s-1",
            goal="读文件",
            steps=[
                {"role": "tool", "name": "FileReadTool", "content": "文件内容", "ok": True},
                {"role": "assistant", "content": "读完了"},
            ],
            final_result="完成",
            total_tokens=100,
            output_tokens=40,
            total_cost=0.0123,
            model="gpt-4o",
            provider="openai",
            directory=tmp_path,
        )
        view = session_bridge.load("s-1", tmp_path)

        tool_messages = [m for m in view.messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0]["name"] == "FileReadTool"
        assert tool_messages[0]["ok"] is True
        assert view.output_tokens == 40
        assert view.total_cost == pytest.approx(0.0123)
        assert view.model == "gpt-4o"
        assert view.provider == "openai"

    def test_failed_tool_step_records_ok_false(self, tmp_path: Path):
        persist_agent_session(
            session_id="s-2",
            goal="跑命令",
            steps=[{"role": "tool", "name": "BashTool", "content": "Error: boom", "ok": False}],
            directory=tmp_path,
        )
        view = session_bridge.load("s-2", tmp_path)
        tool = [m for m in view.messages if m.get("role") == "tool"][0]
        assert tool["ok"] is False


class TestEnginePersistWiring:
    @pytest.fixture
    def engine(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from src.agent.engine import AgentEngine

        monkeypatch.setenv("CLAWD_FORCE_SESSION_PERSIST", "1")
        # 数据目录随 CLAWD_DATA_DIR 走（v0.85.0 起与程序目录分离），测试要隔离到 tmp
        monkeypatch.setenv("CLAWD_DATA_DIR", str(tmp_path / ".clawd"))
        eng = AgentEngine(workdir=tmp_path)

        class _Estimator:
            def get_summary(self):
                return {"total_input_tokens": 111, "total_output_tokens": 22, "total_cost": 0.05}

            def reset(self):
                pass

        class _LLM:
            model = "test-model"
            provider = type("P", (), {"value": "openai"})()

        eng._cost_estimator = _Estimator()
        eng._llm_config = _LLM()
        return eng

    def _fake_session(self):
        from src.agent.engine_session_data import AgentSession, AgentStep

        session = AgentSession(goal="读 README")
        session.steps = [
            AgentStep("execute", "FileReadTool({'file_path': 'README.md'})", "内容", True),
            AgentStep("execute", "BashTool({'command': 'pytest'})", "Error: failed", False),
            AgentStep("report", "完成任务", "完成", True),
        ]
        session.final_result = "完成"
        session.total_tokens = 999  # 应被 estimator 的 111 覆盖
        session.is_complete = True
        return session

    def test_execute_steps_saved_as_tool_messages(self, engine):
        engine._persist_session(self._fake_session())
        views = session_bridge.list_all(engine.workdir / ".clawd" / "sessions")
        assert views, "应当写入一条会话"
        tool_messages = [m for m in views[0].messages if m.get("role") == "tool"]
        assert {m["name"] for m in tool_messages} == {"FileReadTool", "BashTool"}
        assert any(m["ok"] is False for m in tool_messages)
        # report 步骤仍是 assistant
        assert any(m.get("role") == "assistant" for m in views[0].messages)

    def test_usage_taken_from_cost_estimator(self, engine):
        engine._persist_session(self._fake_session())
        view = session_bridge.list_all(engine.workdir / ".clawd" / "sessions")[0]
        assert view.input_tokens == 111
        assert view.output_tokens == 22
        assert view.total_cost == pytest.approx(0.05)

    def test_model_and_provider_recorded(self, engine):
        engine._persist_session(self._fake_session())
        view = session_bridge.list_all(engine.workdir / ".clawd" / "sessions")[0]
        assert view.model == "test-model"
        assert view.provider == "openai"

    def test_estimator_failure_does_not_block_persist(self, engine):
        class _Broken:
            def get_summary(self):
                raise RuntimeError("估算器炸了")

            def reset(self):
                pass

        engine._cost_estimator = _Broken()
        engine._persist_session(self._fake_session())
        assert session_bridge.list_all(engine.workdir / ".clawd" / "sessions"), "估计器失败也要落盘"


class TestExplainUsesRecordedOk:
    def test_explicit_ok_field_wins_over_heuristic(self, tmp_path: Path):
        """持久化里写了 ok=False 时，即使输出看起来正常也必须判失败"""
        from src.cli.explain import explain_session

        persist_agent_session(
            session_id="s-ok",
            goal="跑命令",
            steps=[{"role": "tool", "name": "BashTool", "content": "看起来没报错", "ok": False}],
            directory=tmp_path,
        )
        explanation = explain_session("s-ok", tmp_path)
        assert explanation.tool_calls[0].ok is False
        assert explanation.failed_tools == 1


class TestSessionWorkdirForProjectGrouping:
    """桌面端侧栏要按项目分组，会话必须带 workdir（此前只有 persona）

    没有 workdir 就只能把全部会话平铺成一列 —— 用户真实反馈"分不清哪个是哪个项目"。
    """

    def test_workdir_written_into_metadata(self, tmp_path: Path):
        view = persist_agent_session(
            session_id="s-wd",
            goal="在项目 A 里改代码",
            steps=[{"role": "assistant", "content": "好"}],
            final_result="完成",
            directory=tmp_path,
            workdir=r"D:\work\project-a",
        )
        assert view.metadata.get("workdir") == r"D:\work\project-a"
        saved = session_bridge.load("s-wd", tmp_path)
        assert saved.metadata.get("workdir") == r"D:\work\project-a"

    def test_persona_and_workdir_coexist(self, tmp_path: Path):
        view = persist_agent_session(
            session_id="s-both",
            goal="带角色",
            steps=[{"role": "assistant", "content": "好"}],
            persona="安全审计员",
            directory=tmp_path,
            workdir="/tmp/proj",
        )
        assert view.metadata.get("persona") == "安全审计员"
        assert view.metadata.get("workdir") == "/tmp/proj"

    def test_no_workdir_means_no_key(self, tmp_path: Path):
        """没传 workdir 时不要写空串（前端据此区分"未关联项目"）"""
        view = persist_agent_session(
            session_id="s-nowd",
            goal="无项目",
            steps=[{"role": "assistant", "content": "好"}],
            directory=tmp_path,
        )
        assert "workdir" not in view.metadata

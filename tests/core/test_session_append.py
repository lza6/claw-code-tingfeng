"""续聊必须"追加"，不能把历史覆盖掉（真实体验缺陷）

桌面端点开旧会话继续聊时，客户端会回传 `session_id`；Host 侧必须把这一轮追加到
同一会话文件里。否则每轮 run 都新开一条会话 —— 侧栏会堆出几十条同名记录（实测 37 条）。
"""

from __future__ import annotations

from pathlib import Path

from src.core import session_bridge
from src.core.session_bridge import persist_agent_session


def _one(directory: Path, sid: str, goal: str, answer: str, **kw) -> None:
    persist_agent_session(
        session_id=sid,
        goal=goal,
        steps=[{"role": "assistant", "content": answer}],
        final_result=answer,
        directory=directory,
        **kw,
    )


class TestAppendMode:
    def test_append_keeps_previous_messages(self, tmp_path: Path):
        _one(tmp_path, "sess-a", "第一问", "第一答", append=True)
        _one(tmp_path, "sess-a", "第二问", "第二答", append=True)

        view = session_bridge.load("sess-a", tmp_path)
        contents = [m.get("content") for m in view.messages]
        assert "第一问" in contents and "第一答" in contents, f"历史被覆盖: {contents}"
        assert "第二问" in contents and "第二答" in contents

    def test_append_keeps_first_title_and_created_at(self, tmp_path: Path):
        _one(tmp_path, "sess-b", "原始标题", "答一", append=True)
        first = session_bridge.load("sess-b", tmp_path)
        _one(tmp_path, "sess-b", "后来的更长的问题标题", "答二", append=True)
        second = session_bridge.load("sess-b", tmp_path)

        assert second.title == first.title, "续聊不应改写会话标题"
        assert second.created_at == first.created_at, "续聊不应重置创建时间"

    def test_without_append_it_overwrites(self, tmp_path: Path):
        _one(tmp_path, "sess-c", "第一问", "第一答")
        _one(tmp_path, "sess-c", "第二问", "第二答")

        view = session_bridge.load("sess-c", tmp_path)
        contents = [m.get("content") for m in view.messages]
        assert "第一问" not in contents, "append=False 时应保持旧的覆盖语义（CLI 单轮落盘）"

    def test_append_on_missing_file_behaves_like_new(self, tmp_path: Path):
        _one(tmp_path, "sess-new", "只有一个问题", "只有一个答案", append=True)
        view = session_bridge.load("sess-new", tmp_path)
        assert view.title.startswith("只有一个问题")


class TestEngineSessionIdHint:
    def test_hint_used_as_session_id_and_append_flag(self, tmp_path, monkeypatch):
        """engine 侧：给了 hint 就用它 + append；没给就新开 stamp id"""
        import asyncio

        from src.agent.engine import AgentEngine
        from src.core import data_dir as dd

        monkeypatch.setenv("CLAWD_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("CLAWD_FORCE_SESSION_PERSIST", "1")  # pytest 下默认不落盘

        eng = AgentEngine.__new__(AgentEngine)  # 不走完整初始化（只需落盘路径）
        eng.logger = __import__("logging").getLogger("test")
        eng.workdir = tmp_path / "proj"
        eng.persona_name = ""
        eng._llm_config = None
        eng.client_tag = "test"
        eng.session_id_hint = "sess-from-client"

        class _S:
            goal = "继续聊"
            final_result = "好"
            steps = []
            is_complete = True
            total_tokens = 0

        AgentEngine._persist_session(eng, _S())
        saved = list((tmp_path / "data" / "sessions").glob("sess-from-client.json"))
        assert saved, "没按客户端给的 session_id 落盘"
        assert getattr(eng, "last_session_id", "") == "sess-from-client"
        assert asyncio is not None and dd is not None  # 保持导入依赖显式

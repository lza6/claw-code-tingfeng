"""`/api/sessions` 与 `/api/session` 的数据源契约（真实 HTTP，非 mock）

背景（真实缺陷）：两个端点此前把会话目录硬编码成 `Path.cwd() / '.clawd' / 'sessions'`，
而桌面端的数据目录是 `userData/data/sessions`。于是引擎写进去的会话，
侧栏永远读不到 —— "历史会话一直空着"，但磁盘上明明有文件。

本测试用真实服务 + 真实落盘验证：
1. 端点跟随 `CLAWD_DATA_DIR`（数据目录唯一入口），不跟随 cwd；
2. 列表条目带 `workdir`，供前端按项目分组；
3. 详情端点能按 id 读回消息。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


def _http_get(port: int, path: str):
    import urllib.error
    import urllib.request

    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("CLAWD_DATA_DIR", str(d))
    return d


def _seed_sessions(data_dir: Path) -> None:
    from src.core.session_bridge import persist_agent_session

    sessions_dir = data_dir / "sessions"
    persist_agent_session(
        session_id="sess-proj-a",
        goal="在项目 A 里加个按钮",
        steps=[{"role": "assistant", "content": "改好了"}],
        final_result="完成",
        model="qwen3-coder-plus",
        provider="dashscope",
        directory=sessions_dir,
        workdir=r"D:\work\project-a",
    )
    persist_agent_session(
        session_id="sess-proj-b",
        goal="项目 B 的测试",
        steps=[{"role": "assistant", "content": "跑完了"}],
        final_result="完成",
        directory=sessions_dir,
        workdir="/home/dev/project-b",
    )


def _serve(fn):
    from src.server import create_server

    async def scenario():
        server = create_server(host="127.0.0.1", port=0, token="tok-sess", static_dir=".")
        _host, port = await server.start()
        try:
            return await asyncio.to_thread(fn, port)
        finally:
            await server.stop()

    return asyncio.run(scenario())


class TestSessionsApiUsesDataDir:
    def test_list_reads_from_clawd_data_dir_not_cwd(self, data_dir, tmp_path, monkeypatch):
        # cwd 指向一个**没有** .clawd 的目录：如果端点还硬编码 cwd，这里必然返回 0 条
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        _seed_sessions(data_dir)

        status, body = _serve(lambda port: _http_get(port, "/api/sessions"))

        assert status == 200, body[:300]
        payload = json.loads(body.decode("utf-8"))
        assert payload["count"] == 2, payload
        ids = {s["id"] for s in payload["sessions"]}
        assert ids == {"sess-proj-a", "sess-proj-b"}

    def test_list_items_carry_workdir_for_grouping(self, data_dir):
        _seed_sessions(data_dir)

        status, body = _serve(lambda port: _http_get(port, "/api/sessions"))

        assert status == 200
        payload = json.loads(body.decode("utf-8"))
        by_id = {s["id"]: s for s in payload["sessions"]}
        assert by_id["sess-proj-a"]["workdir"] == r"D:\work\project-a"
        assert by_id["sess-proj-b"]["workdir"] == "/home/dev/project-b"
        # 模型/提供方也带给前端（侧栏 tooltip 用）
        assert by_id["sess-proj-a"]["model"] == "qwen3-coder-plus"
        assert by_id["sess-proj-a"]["provider"] == "dashscope"

    def test_detail_reads_same_dir(self, data_dir):
        _seed_sessions(data_dir)

        status, body = _serve(
            lambda port: _http_get(port, "/api/session?id=sess-proj-a")
        )

        assert status == 200, body[:300]
        payload = json.loads(body.decode("utf-8"))
        assert payload["id"] == "sess-proj-a"
        assert any(m.get("content") == "改好了" for m in payload["messages"])

    def test_missing_session_is_404(self, data_dir):
        _seed_sessions(data_dir)

        status, _body = _serve(lambda port: _http_get(port, "/api/session?id=nope"))

        assert status == 404

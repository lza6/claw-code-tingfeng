"""会话删除/改名的安全边界（P0 回归保护）

真实安全缺陷（v0.88.9 修复前，Critic 实跑发现）：

    GET /api/session/delete?id=../providers   → 200 {"ok": true}
    providers.json（含 API key）被删除

两个根因：
1. `session_bridge` 把 id 直接拼成 `<dir>/<id>.json`，`../providers` 一步穿越到数据目录；
2. `/api/session/*` 这些**破坏性**端点在 HTTP 层完全没有 token 校验
   （本机任意进程、或网页 CSRF 的简单 GET 就能触发）。

本测试同时钉住"带 token 的正常路径仍然可用"，避免修复把功能改坏。
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
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
    (d / "sessions").mkdir(parents=True)
    monkeypatch.setenv("CLAWD_DATA_DIR", str(d))
    # 放一份"含密钥"的配置到数据目录根 —— 正是攻击目标
    (d / "providers.json").write_text('{"providers": {"p1": {"key": "sk-secret"}}}', encoding="utf-8")
    return d


def _seed_session(data_dir: Path, sid: str = "sess-keep") -> None:
    from src.core.session_bridge import persist_agent_session

    persist_agent_session(
        session_id=sid, goal="保留我", steps=[{"role": "assistant", "content": "ok"}],
        directory=data_dir / "sessions",
    )


def _serve(fn):
    from src.server import create_server

    async def scenario():
        server = create_server(host="127.0.0.1", port=0, token="tok-sec", static_dir=".")
        _h, port = await server.start()
        try:
            return await asyncio.to_thread(fn, port)
        finally:
            await server.stop()

    return asyncio.run(scenario())


class TestBridgeRejectsTraversal:
    def test_delete_rejects_dotdot_id(self, data_dir: Path):
        from src.core import session_bridge

        with pytest.raises(ValueError):
            session_bridge.delete_session("../providers", data_dir / "sessions")

        assert (data_dir / "providers.json").is_file(), "providers.json 被穿越删掉了！"

    def test_load_and_rename_reject_traversal(self, data_dir: Path):
        from src.core import session_bridge

        for bad in ("../providers", "..", ".", "a/b", ""):
            with pytest.raises(ValueError):
                session_bridge.load(bad, data_dir / "sessions")
            with pytest.raises(ValueError):
                session_bridge.rename(bad, "x", data_dir / "sessions")
        assert (data_dir / "providers.json").is_file()

    def test_normal_id_still_works(self, data_dir: Path):
        from src.core import session_bridge

        _seed_session(data_dir)
        assert session_bridge.delete_session("sess-keep", data_dir / "sessions") is True
        assert not (data_dir / "sessions" / "sess-keep.json").exists()


class TestHttpRequiresToken:
    def test_delete_without_token_is_403_and_file_survives(self, data_dir: Path):
        _seed_session(data_dir)
        q = urllib.parse.urlencode({"id": "sess-keep"})

        status, body = _serve(lambda port: _http_get(port, f"/api/session/delete?{q}"))

        assert status == 403, f"无 token 的删除必须被拒，实际 {status}: {body[:120]}"
        assert (data_dir / "sessions" / "sess-keep.json").is_file(), "会话被未授权删掉了"

    def test_rename_without_token_is_403(self, data_dir: Path):
        _seed_session(data_dir)
        q = urllib.parse.urlencode({"id": "sess-keep", "title": "hacked"})

        status, _ = _serve(lambda port: _http_get(port, f"/api/session/rename?{q}"))

        assert status == 403

    def test_traversal_with_valid_token_still_blocked(self, data_dir: Path):
        """带 token 也不能穿越（两道防线都要在）"""
        q = urllib.parse.urlencode({"id": "../providers", "token": "tok-sec"})

        status, body = _serve(lambda port: _http_get(port, f"/api/session/delete?{q}"))

        assert status in (400, 404), f"穿越请求应被拒，实际 {status}: {body[:120]}"
        assert (data_dir / "providers.json").is_file(), "providers.json 被穿越删掉了！"

    def test_delete_with_token_works(self, data_dir: Path):
        _seed_session(data_dir)
        q = urllib.parse.urlencode({"id": "sess-keep", "token": "tok-sec"})

        status, body = _serve(lambda port: _http_get(port, f"/api/session/delete?{q}"))

        assert status == 200, body[:200]
        assert json.loads(body)["ok"] is True
        assert not (data_dir / "sessions" / "sess-keep.json").exists()

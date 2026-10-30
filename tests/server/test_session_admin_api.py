"""会话管理：重命名 / 删除（侧栏 ⋯ 菜单背后的契约）

只通过 query 参数操作，且**只动这一条会话文件** —— 删会话不能碰到项目文件或其它会话。
另外顺带钉住 `/api/file` 必须允许数据目录（桌面端图片在 userData/data/uploads，
只认 cwd 会让内联图片一律 403）。
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
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


def _seed(data_dir: Path) -> None:
    from src.core.session_bridge import persist_agent_session

    sessions = data_dir / "sessions"
    persist_agent_session(
        session_id="sess-keep", goal="保留我", steps=[{"role": "assistant", "content": "ok"}],
        directory=sessions, workdir="/proj/a",
    )
    persist_agent_session(
        session_id="sess-drop", goal="删掉我", steps=[{"role": "assistant", "content": "ok"}],
        directory=sessions, workdir="/proj/a",
    )


def _serve(fn):
    from src.server import create_server

    async def scenario():
        server = create_server(host="127.0.0.1", port=0, token="tok", static_dir=".")
        _h, port = await server.start()
        try:
            return await asyncio.to_thread(fn, port)
        finally:
            await server.stop()

    return asyncio.run(scenario())


class TestRenameSession:
    def test_rename_changes_title_only(self, data_dir: Path):
        _seed(data_dir)
        q = urllib.parse.urlencode({"id": "sess-keep", "title": "新标题 ABC"})

        status, body = _serve(lambda port: _http_get(port, f"/api/session/rename?{q}"))

        assert status == 200, body[:200]
        assert json.loads(body)["title"] == "新标题 ABC"

        from src.core import session_bridge

        view = session_bridge.load("sess-keep", data_dir / "sessions")
        assert view.title == "新标题 ABC"
        assert any(m.get("content") == "保留我" for m in view.messages), "改名不能丢消息"

    def test_rename_missing_id_is_400(self, data_dir: Path):
        _seed(data_dir)
        status, _ = _serve(lambda port: _http_get(port, "/api/session/rename?title=x"))
        assert status == 400

    def test_rename_unknown_session_is_404(self, data_dir: Path):
        _seed(data_dir)
        q = urllib.parse.urlencode({"id": "nope", "title": "x"})
        status, _ = _serve(lambda port: _http_get(port, f"/api/session/rename?{q}"))
        assert status == 404


class TestDeleteSession:
    def test_delete_removes_only_that_file(self, data_dir: Path):
        _seed(data_dir)
        q = urllib.parse.urlencode({"id": "sess-drop"})

        status, body = _serve(lambda port: _http_get(port, f"/api/session/delete?{q}"))

        assert status == 200
        assert json.loads(body)["ok"] is True
        assert not (data_dir / "sessions" / "sess-drop.json").exists()
        assert (data_dir / "sessions" / "sess-keep.json").exists(), "不该误删别的会话"

    def test_delete_unknown_returns_ok_false(self, data_dir: Path):
        _seed(data_dir)
        q = urllib.parse.urlencode({"id": "ghost"})
        status, body = _serve(lambda port: _http_get(port, f"/api/session/delete?{q}"))
        assert status == 200
        assert json.loads(body)["ok"] is False


class TestApiFileAllowsDataDir:
    def test_image_under_data_dir_is_served(self, data_dir: Path):
        """桌面端图片在 <数据目录>/uploads，/api/file 必须认它（否则内联图片 403）"""
        up = data_dir / "uploads"
        up.mkdir(parents=True)
        img = up / "shot.png"
        img.write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d494844520000000100000001080600000"
                "01f15c4890000000d49444154789c6360000002000154a24f6f0000000049454e44ae426082"
            )
        )

        status, body = _serve(lambda port: _http_get(port, "/api/file?path=" + urllib.parse.quote(str(img))))

        assert status == 200, f"数据目录里的图片被拒了: {status}"
        assert body.startswith(b"\x89PNG")

    def test_non_image_under_data_dir_is_still_403(self, data_dir: Path):
        secret = data_dir / "providers.json"
        secret.write_text('{"key": "sk-should-not-leak"}', encoding="utf-8")

        status, _ = _serve(lambda port: _http_get(port, "/api/file?path=" + urllib.parse.quote(str(secret))))

        assert status == 403, "只放行图片，配置类文件不能通过 /api/file 读出"

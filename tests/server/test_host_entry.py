"""Host 服务入口测试（真实起 WS 服务，走 loopback 随机端口）"""
import asyncio
import json
from pathlib import Path

import pytest


class TestPortFile:
    def test_write_and_read(self, tmp_path):
        from src.server.host_entry import read_port_file, write_port_file

        pf = write_port_file(tmp_path, 12345, "127.0.0.1", "tok-abc")
        assert pf.name == ".clawd_host_port"
        data = read_port_file(tmp_path)
        assert data == {"port": 12345, "host": "127.0.0.1", "token": "tok-abc"}

    def test_read_missing(self, tmp_path):
        from src.server.host_entry import read_port_file

        assert read_port_file(tmp_path) is None

    def test_read_corrupt(self, tmp_path):
        from src.server.host_entry import read_port_file

        (tmp_path / ".clawd_host_port").write_text("{broken", encoding="utf-8")
        assert read_port_file(tmp_path) is None


class TestHostStartup:
    """真实启动 Host（loopback 随机端口），验证端口文件与可连接性"""

    def test_start_and_port_file(self, tmp_path):
        from src.server import create_server
        from src.server.host_entry import read_port_file

        async def scenario():
            server = create_server(host="127.0.0.1", port=0, token="test-token-123")
            host, port = await server.start()
            from src.server.host_entry import write_port_file

            write_port_file(tmp_path, port, host, "test-token-123")
            await server.stop()  # 同一 loop 内停止
            return host, port

        host, port = asyncio.run(scenario())
        assert port > 0
        data = read_port_file(tmp_path)
        assert data["port"] == port
        assert data["token"] == "test-token-123"

    def test_ws_client_connect_and_auth(self, tmp_path):
        """端到端：真实 WS 客户端连上、认证、ping"""
        import websockets

        from src.server import create_server

        async def scenario():
            server = create_server(host="127.0.0.1", port=0, token="e2e-token")
            host, port = await server.start()
            results = {}
            try:
                async with websockets.connect(f"ws://{host}:{port}") as ws:
                    # 1. 未认证 ping 应被拒（错误格式: 顶层 code 字段）
                    await ws.send(json.dumps({"type": "ping", "id": "1"}))
                    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    results["unauth"] = resp.get("code")
                    # 2. 认证
                    await ws.send(json.dumps({"type": "auth", "token": "e2e-token"}))
                    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    results["auth"] = resp.get("type") != "error"
                    # 3. 认证后 ping
                    await ws.send(json.dumps({"type": "ping", "id": "2"}))
                    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    results["ping"] = resp.get("type") != "error"
            finally:
                await server.stop()
            return results

        results = asyncio.run(scenario())
        assert results["unauth"] == "E_AUTH_REQUIRED"
        assert results["auth"] is True
        assert results["ping"] is True


@pytest.fixture
def web_dir(tmp_path):
    d = tmp_path / "web"
    d.mkdir()
    (d / "index.html").write_text(
        "<html><head><title>Clawd</title></head><body>hi</body></html>",
        encoding="utf-8",
    )
    (d / "app.js").write_text("console.log(1)", encoding="utf-8")
    return d


class TestStaticHosting:
    """静态托管 E2E：同一端口 HTTP 静态页 + WS 共存（DSH 模式核心接缝）"""

    def _http_get(self, port, path):
        import urllib.request

        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_index_served_with_token_inject(self, tmp_path, web_dir):
        from src.server import create_server

        async def scenario():
            server = create_server(
                host="127.0.0.1", port=0, token="tok-xyz",
                static_dir=str(web_dir), static_token="tok-xyz",
            )
            host, port = await server.start()
            try:
                status, _, body = await asyncio.to_thread(self._http_get, port, "/")
                return status, body
            finally:
                await server.stop()

        status, body = asyncio.run(scenario())
        assert status == 200
        assert b"window.__CLAWD_TOKEN__" in body
        assert b"tok-xyz" in body
        assert b"</title>" in body  # 注入点正确（title 标签保持完整）

    def test_path_traversal_blocked(self, tmp_path, web_dir):
        from src.server import create_server

        # 在 web 目录外放一个秘密文件
        secret = tmp_path / "secret.txt"
        secret.write_text("SECRET", encoding="utf-8")

        async def scenario():
            server = create_server(
                host="127.0.0.1", port=0, token="t",
                static_dir=str(web_dir), static_token="t",
            )
            host, port = await server.start()
            try:
                return await asyncio.to_thread(self._http_get, port, "/..%2fsecret.txt")
            finally:
                await server.stop()

        status, _, body = asyncio.run(scenario())
        assert status in (403, 404)  # 穿越被拦截

    def test_404_unknown(self, tmp_path, web_dir):
        from src.server import create_server

        async def scenario():
            server = create_server(
                host="127.0.0.1", port=0, token="t",
                static_dir=str(web_dir), static_token="t",
            )
            host, port = await server.start()
            try:
                return await asyncio.to_thread(self._http_get, port, "/no-such-file.js")
            finally:
                await server.stop()

        status, _, _ = asyncio.run(scenario())
        assert status == 404

    def test_ws_still_works_with_static(self, tmp_path, web_dir):
        """关键共存测试：静态托管开启后 WS 握手不受影响"""
        import websockets as _ws

        from src.server import create_server

        async def scenario():
            server = create_server(
                host="127.0.0.1", port=0, token="coexist",
                static_dir=str(web_dir), static_token="coexist",
            )
            host, port = await server.start()
            out = {}
            try:
                async with _ws.connect(f"ws://{host}:{port}") as sock:
                    await sock.send(json.dumps({"type": "auth", "token": "coexist"}))
                    resp = json.loads(await asyncio.wait_for(sock.recv(), timeout=5))
                    out["auth_ok"] = resp.get("type") != "error"
            finally:
                await server.stop()
            return out

        assert asyncio.run(scenario())["auth_ok"] is True


class TestPluginsApi:
    """插件市场 API（/api/plugins）"""

    def test_mime_whitelist_mapping(self, tmp_path, web_dir):
        """NR-3: 静态托管 Content-Type 走显式白名单，不依赖 mimetypes/注册表"""
        import urllib.request

        from src.server import create_server
        from src.server.websocket_server import ClawdWebSocketServer

        def _http_get(port, path):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, dict(r.headers), r.read()
            except urllib.error.HTTPError as e:
                return e.code, dict(e.headers), e.read()

        (web_dir / "app.js").write_text("console.log(1)", encoding="utf-8")
        (web_dir / "style.css").write_text("body{}", encoding="utf-8")
        (web_dir / "logo.svg").write_text("<svg/>", encoding="utf-8")
        (web_dir / "data.bin").write_bytes(b"\x00\x01")  # 白名单外后缀

        async def scenario():
            server = create_server(
                host="127.0.0.1", port=0, token="t",
                static_dir=str(web_dir), static_token=None,
            )
            host, port = await server.start()
            try:
                results = {}
                for p in ("/app.js", "/style.css", "/logo.svg", "/data.bin"):
                    results[p] = await asyncio.to_thread(_http_get, port, p)
                return results
            finally:
                await server.stop()

        results = asyncio.run(scenario())
        assert results["/app.js"][0] == 200
        assert results["/app.js"][1]["Content-Type"].startswith("application/javascript")
        assert results["/style.css"][0] == 200
        assert results["/style.css"][1]["Content-Type"].startswith("text/css")
        assert results["/logo.svg"][0] == 200
        assert results["/logo.svg"][1]["Content-Type"] == "image/svg+xml"
        # 白名单外后缀拒绝服务（403），不是 application/octet-stream
        assert results["/data.bin"][0] == 403
        # 映射表本身的关键条目
        assert ClawdWebSocketServer._guess_static_mime("a.HTML") == "text/html; charset=utf-8"
        assert ClawdWebSocketServer._guess_static_mime("a.JSON") == "application/json; charset=utf-8"
        assert ClawdWebSocketServer._guess_static_mime("noext") is None

    def test_api_returns_json(self, tmp_path, web_dir):
        import urllib.request
        from src.server import create_server

        async def scenario():
            server = create_server(
                host="127.0.0.1", port=0, token="t",
                static_dir=str(web_dir), static_token="t",
            )
            host, port = await server.start()
            try:
                def get():
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/plugins", timeout=5
                    ) as r:
                        return r.status, json.loads(r.read())
                return await asyncio.to_thread(get)
            finally:
                await server.stop()

        status, data = asyncio.run(scenario())
        assert status == 200
        assert data["count"] >= 4  # 至少 4 个内置能力包
        names = {p["name"] for p in data["plugins"]}
        assert "逆向工具集" in names
        assert "插件市场" not in names  # 自身不在列表

    def test_api_with_plugin_manager(self, tmp_path, web_dir):
        import urllib.request
        import shutil as _shutil

        from src.plugins import PluginManager
        from src.server import create_server

        # 装一个真实插件
        plugins = tmp_path / ".clawd" / "plugins" / "sample_plugin"
        plugins.parent.mkdir(parents=True)
        fixture = Path(__file__).parent.parent / "plugins" / "fixtures" / "sample_plugin"
        _shutil.copytree(fixture, plugins)
        for pyc in plugins.rglob("__pycache__"):
            _shutil.rmtree(pyc, ignore_errors=True)

        pm = PluginManager(workdir=tmp_path)
        pm.load_all()
        assert pm.loaded_names == ["sample-echo"]

        async def scenario():
            server = create_server(
                host="127.0.0.1", port=0, token="t",
                static_dir=str(web_dir), static_token="t",
            )
            server._plugin_manager = pm  # 注入插件管理器
            host, port = await server.start()
            try:
                def get():
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/plugins", timeout=5
                    ) as r:
                        return json.loads(r.read())
                return await asyncio.to_thread(get)
            finally:
                await server.stop()

        data = asyncio.run(scenario())
        sample = next(p for p in data["plugins"] if p["name"] == "sample-echo")
        assert sample["status"] == "loaded"
        assert "工具" in sample["capabilities"]


class TestCmdServe:
    def test_arg_parsing(self):
        from src.server.host_entry import cmd_serve

        # --help 不炸即参数定义合法
        with pytest.raises(SystemExit) as ei:
            cmd_serve(["--help"])
        assert ei.value.code == 0

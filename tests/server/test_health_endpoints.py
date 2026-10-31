"""探针端点 `/healthz` `/readyz` 与未知 API 路径 404 的真实 HTTP 契约。

背景（真实缺陷，2026-10-31 实测）：
- `docker-compose.yml` 的 healthcheck 是 `python -c "import sys; sys.exit(0)"` ——
  容器里什么都没跑也返回 0，等于**没有健康检查**；
- 服务端**根本没有**存活端点：探 `/health` 会掉进静态托管，被 mime 白名单
  （无后缀 → ctype=None）判成 **403 Forbidden**。运维看到 403 会以为是鉴权问题，
  实际是"没有这个端点"。任何想接监控/编排的人都得先猜这个坑。

本文件用**真实监听端口**（create_server + 真 HTTP 请求）验证行为，
不 mock HTTP 层 —— 探针的失效模式恰恰在 HTTP 层。
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest


def _http_get(port: int, path: str):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _serve(fn, **kwargs):
    from src.server import create_server

    async def scenario():
        server = create_server(host="127.0.0.1", port=0, token="tok-probe", **kwargs)
        _host, port = await server.start()
        try:
            return await asyncio.to_thread(fn, port)
        finally:
            await server.stop()

    return asyncio.run(scenario())


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("CLAWD_DATA_DIR", str(d))
    return d


class TestLiveness:
    def test_healthz_needs_no_token_and_reports_version(self, data_dir):
        from src import __version__

        status, body = _serve(lambda port: _http_get(port, "/healthz"), static_dir=".")
        assert status == 200, body[:300]
        payload = json.loads(body.decode("utf-8"))
        assert payload["status"] == "ok"
        assert payload["version"] == __version__
        assert payload["uptime_s"] >= 0
        assert isinstance(payload["connections"], int)

    def test_healthz_does_not_leak_secrets_or_paths(self, data_dir):
        status, body = _serve(lambda port: _http_get(port, "/healthz"), static_dir=".")
        assert status == 200
        text = body.decode("utf-8")
        # 免鉴权端点绝不能出现 token / 密钥 / 绝对路径
        assert "tok-probe" not in text
        assert str(data_dir) not in text
        assert "api_key" not in text.lower()

    def test_healthz_works_without_static_dir(self, data_dir):
        """不带 --static-dir 时也要能探活（容器/服务模式常见）"""
        status, body = _serve(lambda port: _http_get(port, "/healthz"))
        assert status == 200, body[:300]


class TestReadiness:
    def test_readyz_ok_when_data_dir_writable(self, data_dir, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
        status, body = _serve(lambda port: _http_get(port, "/readyz"), static_dir=".")
        payload = json.loads(body.decode("utf-8"))
        names = {c["name"]: c for c in payload["checks"]}
        assert "data_dir_writable" in names and names["data_dir_writable"]["ok"] is True
        # 未配置 key 不算未就绪：真校验要花钱，探针只查"配置项在不在"
        assert status in (200, 503)
        if status == 200:
            assert payload["status"] == "ready"

    def test_readyz_does_not_leak_provider_or_model(self, data_dir):
        """`/readyz` 免鉴权：只回答"配没配"，不回显 provider/model 的值"""
        status, body = _serve(lambda port: _http_get(port, "/readyz"), static_dir=".")
        payload = json.loads(body.decode("utf-8"))
        detail = {c["name"]: c for c in payload["checks"]}["llm_configured"]["detail"]
        assert "LLMProviderEnum" not in detail, f"泄漏枚举 repr: {detail}"
        # 真实配置的模型名不该出现在免鉴权响应里
        from src.core.settings import get_settings

        model = str(getattr(get_settings(), "llm_model", "") or "")
        if model:
            assert model not in json.dumps(payload, ensure_ascii=False), f"泄漏模型名: {model}"

    def test_readyz_503_when_data_dir_unwritable(self, tmp_path, monkeypatch):
        """数据目录不可写 → 必须 503（否则流量被导进一个写不下任何东西的实例）"""
        blocker = tmp_path / "blocked"
        blocker.write_text("i am a file, not a dir", encoding="utf-8")
        monkeypatch.setenv("CLAWD_DATA_DIR", str(blocker))

        status, body = _serve(lambda port: _http_get(port, "/readyz"), static_dir=".")
        payload = json.loads(body.decode("utf-8"))
        by_name = {c["name"]: c for c in payload["checks"]}
        assert status == 503, body[:300]
        assert by_name["data_dir_writable"]["ok"] is False
        # 失败原因只报异常类型，不回显绝对路径
        assert "PermissionError" in by_name["data_dir_writable"]["detail"] or \
               "OSError" in by_name["data_dir_writable"]["detail"] or \
               "NotADirectoryError" in by_name["data_dir_writable"]["detail"] or \
               by_name["data_dir_writable"]["detail"]  # 至少要有原因文本
        assert payload["status"] == "not_ready"


class TestUnknownApiPath:
    def test_unknown_api_path_is_404_json_not_403(self, data_dir):
        """以前返回 403（mime 白名单误判），排障方向被带偏"""
        status, body = _serve(lambda port: _http_get(port, "/api/does-not-exist"), static_dir=".")
        assert status == 404, body[:300]
        payload = json.loads(body.decode("utf-8"))
        assert payload["error"] == "not_found"
        assert payload["path"] == "/api/does-not-exist"

    def test_health_legacy_path_is_404_now(self, data_dir):
        """`/health` 从未存在过；现在明确 404（而不是伪 403）"""
        status, _body = _serve(lambda port: _http_get(port, "/health"), static_dir=".")
        assert status == 404

    def test_static_files_still_served(self, data_dir, tmp_path):
        """回归：真正存在的静态文件仍 200（404 变化不能误伤静态托管）"""
        web = tmp_path / "web"
        web.mkdir()
        (web / "index.html").write_text("<html><title>t</title>hi</html>", encoding="utf-8")

        status, body = _serve(
            lambda port: _http_get(port, "/index.html"), static_dir=str(web)
        )
        assert status == 200, body[:200]
        assert b"hi" in body

    def test_path_traversal_still_blocked(self, data_dir, tmp_path):
        """回归：静态托管的目录穿越防护不能被新分支绕过"""
        web = tmp_path / "web"
        web.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP", encoding="utf-8")

        status, _body = _serve(
            lambda port: _http_get(port, "/../secret.txt"), static_dir=str(web)
        )
        assert status in (403, 404), f"目录穿越未被拦截: {status}"


class TestComposeHealthcheckIsReal:
    """docker-compose 的健康检查必须打真的 HTTP 端点，不能是 `sys.exit(0)`"""

    def test_compose_healthcheck_hits_healthz(self):
        """健康检查命令本身必须打真端点（注释里提到旧写法不算）"""
        import yaml

        root = Path(__file__).resolve().parents[2]
        data = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
        health = data["services"]["clawd-code"]["healthcheck"]
        cmd = " ".join(health["test"])
        assert "/healthz" in cmd, f"healthcheck 未打 /healthz: {cmd}"
        assert "sys.exit(0)" not in cmd, f"健康检查仍是恒真占位: {cmd}"
        assert health.get("start_period"), "缺 start_period（服务起来需要时间，否则首轮必红）"

    def test_compose_runs_a_server_not_interactive_chat(self):
        """服务容器跑 `chat` 时 8765 端口无人监听 —— 声称的"远程访问"不成立"""
        root = Path(__file__).resolve().parents[2]
        text = (root / "docker-compose.yml").read_text(encoding="utf-8")
        assert "serve" in text, "服务容器必须跑 serve，否则端口/健康检查都是假的"

    def test_dockerfile_healthcheck_hits_healthz(self):
        """镜像自带的 HEALTHCHECK 也必须打真端点（第三处容易漏的假健康检查）"""
        root = Path(__file__).resolve().parents[2]
        text = (root / "Dockerfile").read_text(encoding="utf-8")
        health_lines = [ln for ln in text.splitlines() if "HEALTHCHECK" in ln or "urllib.request" in ln]
        joined = " ".join(health_lines)
        assert "/healthz" in joined, f"Dockerfile HEALTHCHECK 未打 /healthz: {joined[:200]}"
        assert "src.utils.features" not in joined, "HEALTHCHECK 仍是「import 一下就 exit 0」的恒真占位"

    def test_dockerfile_default_cmd_is_a_server(self):
        """镜像默认 CMD 必须是服务，否则 EXPOSE 8765 与 HEALTHCHECK 自相矛盾"""
        root = Path(__file__).resolve().parents[2]
        text = (root / "Dockerfile").read_text(encoding="utf-8")
        cmd_lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("CMD")]
        assert cmd_lines, "Dockerfile 缺 CMD"
        assert "serve" in cmd_lines[-1], f"默认 CMD 不是服务: {cmd_lines[-1]}"


class TestBindHost:
    """`clawd serve` 必须尊重 `AGENT_SERVER_HOST`。

    真实事故（2026-10-31）：`run_host()` 里硬编码 `host="127.0.0.1"`，
    于是容器里设了 `AGENT_SERVER_HOST=0.0.0.0` 也无效 —— 端口映射不通、
    健康检查只能在容器内自嗨。默认值仍必须是 loopback（不该默认对外暴露）。
    """

    def test_default_is_loopback(self, monkeypatch):
        from src.server.host_entry import resolve_bind_host

        monkeypatch.delenv("AGENT_SERVER_HOST", raising=False)
        assert resolve_bind_host() == "127.0.0.1"

    def test_env_overrides(self, monkeypatch):
        from src.server.host_entry import resolve_bind_host

        monkeypatch.setenv("AGENT_SERVER_HOST", "0.0.0.0")
        assert resolve_bind_host() == "0.0.0.0"

    def test_blank_env_falls_back(self, monkeypatch):
        from src.server.host_entry import resolve_bind_host

        monkeypatch.setenv("AGENT_SERVER_HOST", "   ")
        assert resolve_bind_host() == "127.0.0.1"

    def test_run_host_passes_bind_host_to_server(self):
        """不能只测 helper：还要确认 run_host 真的把它传给了 create_server

        用 AST 而不是子串：注释里提到旧的 `host="127.0.0.1"` 会让子串断言假红/假绿。
        """
        import ast
        import inspect

        from src.server import host_entry

        tree = ast.parse(inspect.getsource(host_entry.run_host).lstrip())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        create_calls = [
            n for n in calls
            if isinstance(n.func, ast.Name) and n.func.id == "create_server"
        ]
        assert create_calls, "run_host 里没有 create_server 调用"
        host_kw = next(
            (kw.value for kw in create_calls[0].keywords if kw.arg == "host"), None
        )
        assert isinstance(host_kw, ast.Name) and host_kw.id == "bind_host", (
            "create_server 的 host 参数必须是 resolve_bind_host() 的结果（bind_host）"
        )

    def test_port_file_records_client_connectable_host(self):
        """绑 0.0.0.0 时端口文件不能写 0.0.0.0（客户端拿去连必失败）"""
        import inspect

        from src.server import host_entry

        src = inspect.getsource(host_entry.run_host)
        assert 'client_host = "127.0.0.1" if host in' in src, (
            "端口文件仍可能写入 0.0.0.0 —— Electron 壳/浏览器会连不上"
        )
        assert "write_port_file(workdir, actual_port, client_host, token)" in src


class TestPortFileFailureIsNotFatal:
    """端口文件写不进去时，Host 必须继续跑。

    真实事故（2026-10-31，CI Linux runner）：容器以 UID 1000 运行而 /app 属 root，
    `write_port_file(/app/.clawd_host_port)` 抛 PermissionError 直接冒到顶层 →
    `clawd serve` 崩 → `/healthz` 000。端口文件只是"自动发现"的便利机制，
    写不进去应该降级为告警，而不是把服务带走。
    """

    def test_warning_instead_of_raising(self, monkeypatch, tmp_path, caplog):
        import asyncio

        from src.server import host_entry

        def boom(workdir, port, host, token):
            raise PermissionError(13, "Permission denied", str(workdir / ".clawd_host_port"))

        monkeypatch.setattr(host_entry, "write_port_file", boom)

        async def scenario():
            task = asyncio.create_task(
                host_entry.run_host(port=0, workdir=tmp_path / "readonly")
            )
            # 给它时间跑到写端口文件那一步
            await asyncio.sleep(1.5)
            still_running = not task.done()
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001 - 关停路径
                    pass
            return still_running

        try:
            still_running = asyncio.run(asyncio.wait_for(scenario(), timeout=90))
        except Exception as exc:  # noqa: BLE001 - 只判断"没崩"这一件事
            raise AssertionError(f"run_host 在端口文件失败时崩了: {type(exc).__name__}: {exc}")
        assert still_running, "run_host 在端口文件写入失败后不应退出"

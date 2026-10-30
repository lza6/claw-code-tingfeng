"""设置面板与宿主信息 API 的行为测试

背景（2026-10-28）：桌面端 UI 的"设置"按钮此前是假按钮（只打印"后续版本提供"），
`/api/plugins` 的 `_plugin_manager` 恒 None 导致 `.clawd/plugins/` 里的用户插件永不出现，
且 UI 没有任何应用版本信息。本文件锁定修复后的真实行为。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from src.server.auth import AuthManager
from src.server.handlers import MessageRouter

# ==========================================================================
# 设置读写（WS 协议）
# ==========================================================================


class _FakeWs:
    """最小 ws 替身（AuthManager 需要 remote_address 记录来源）"""

    remote_address = ("127.0.0.1", 12345)


@pytest_asyncio.fixture
async def router(tmp_path: Path, monkeypatch):
    """已认证的 MessageRouter（工作目录切到 tmp_path 以便校验落盘）"""
    monkeypatch.chdir(tmp_path)
    manager = AuthManager(token="test-token")
    ws = _FakeWs()
    assert await manager.authenticate(ws, "test-token") is True
    return MessageRouter(auth_manager=manager), ws


class TestSettingsGet:
    async def test_returns_version_and_no_secret(self, router):
        r, ws = router
        res = await r.dispatch(ws, {"type": "settings_get", "id": "s1"})

        data = res["data"]
        assert data["version"] not in (None, "", "unknown")
        assert "python" in data and data["python"]
        assert "api_key_set" in data
        # 绝不下发密钥本体
        assert "api_key" not in data
        assert all("sk-" not in str(v) for v in data.values() if isinstance(v, str))

    async def test_lists_editable_keys(self, router):
        r, ws = router
        data = (await r.dispatch(ws, {"type": "settings_get", "id": "s2"}))["data"]

        assert set(data["editable_keys"]) == {
            "provider", "model", "base_url", "enable_rag", "native_tools"
        }
        assert "api_key" not in data["editable_keys"]


class TestSettingsSet:
    async def test_applies_and_persists(self, router, tmp_path: Path):
        r, ws = router
        res = await r.dispatch(ws, {
            "type": "settings_set",
            "id": "s3",
            "settings": {"model": "gpt-4o-mini", "enable_rag": True},
        })

        data = res["data"]
        assert data["applied"]["model"] == "gpt-4o-mini"
        assert data["applied"]["enable_rag"] is True
        assert data["restart_required"] is True  # model 变更需重启

        persisted = json.loads(
            (tmp_path / ".clawd" / "ui_settings.json").read_text(encoding="utf-8")
        )
        assert persisted["model"] == "gpt-4o-mini"
        assert persisted["enable_rag"] is True

    async def test_rejects_unknown_key(self, router):
        r, ws = router
        res = await r.dispatch(ws, {
            "type": "settings_set",
            "id": "s4",
            "settings": {"shell": "rm -rf /"},
        })

        assert res.get("code") == "E_INVALID_PARAMETER"
        assert "shell" in res.get("message", "")

    async def test_rejects_api_key_over_ws(self, router):
        """密钥禁止经 WS 传输（只能走 .env / 环境变量）"""
        r, ws = router
        res = await r.dispatch(ws, {
            "type": "settings_set",
            "id": "s5",
            "settings": {"api_key": "sk-should-not-be-accepted"},
        })

        assert res.get("code") == "E_INVALID_PARAMETER"
        assert "api_key" in res.get("message", "")

    async def test_rejects_empty_payload(self, router):
        r, ws = router
        res = await r.dispatch(ws, {"type": "settings_set", "id": "s6", "settings": {}})

        assert res.get("code") == "E_INVALID_MESSAGE"

    async def test_requires_auth(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r = MessageRouter(auth_manager=AuthManager(token="t"))
        res = await r.dispatch(_FakeWs(), {"type": "settings_get", "id": "s7"})

        assert res.get("code") == "E_AUTH_REQUIRED"

    async def test_toggle_flags_persist_without_restart(self, router):
        r, ws = router
        res = await r.dispatch(ws, {
            "type": "settings_set",
            "id": "s8",
            "settings": {"native_tools": False},
        })

        data = res["data"]
        assert data["applied"]["native_tools"] is False
        assert data["restart_required"] is False
        assert data["native_tools"] is False


# ==========================================================================
# /api/info 与 /api/plugins
# ==========================================================================


class TestHostInfoEndpoint:
    def test_info_contains_version_and_no_secret(self, tmp_path: Path):
        from src.server import create_server

        server = create_server(
            host="127.0.0.1", port=0, token="t", static_dir=str(tmp_path),
        )
        info = server._collect_info()

        assert info["version"] not in (None, "", "unknown")
        assert "api_key_set" in info
        assert "api_key" not in info
        assert info["features"]["static_ui"] is True

    def test_plugins_lists_user_plugin_from_clawd_dir(self, tmp_path: Path, monkeypatch):
        """UI 承诺"放进 .clawd/plugins/ 即可出现"——必须真的出现"""
        monkeypatch.chdir(tmp_path)
        plugin_dir = tmp_path / ".clawd" / "plugins" / "demo-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "pyproject.toml").write_text(
            # manifest 契约来自 src/plugins：必须有 [tool.clawd.plugin] 且含 name/entry
            '[tool.clawd.plugin]\nname = "demo-plugin"\nentry = "demo:setup"\n'
            'version = "1.2.3"\ndescription = "测试插件"\nprovides_tools = true\n',
            encoding="utf-8",
        )

        from src.server import create_server

        server = create_server(host="127.0.0.1", port=0, token="t", static_dir=str(tmp_path))
        payload = server._collect_plugins()

        names = [p["name"] for p in payload["plugins"]]
        assert "demo-plugin" in names, f"用户插件未出现在市场列表中: {names}"
        demo = next(p for p in payload["plugins"] if p["name"] == "demo-plugin")
        assert demo["version"] == "1.2.3"
        assert demo["status"] == "available"
        assert demo["source"].endswith("demo-plugin")

    def test_broken_manifest_reported_as_error_entry(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bad = tmp_path / ".clawd" / "plugins" / "broken"
        bad.mkdir(parents=True)
        (bad / "pyproject.toml").write_text("this is not toml {{{", encoding="utf-8")

        from src.server import create_server

        server = create_server(host="127.0.0.1", port=0, token="t", static_dir=str(tmp_path))
        payload = server._collect_plugins()

        entry = next((p for p in payload["plugins"] if p["name"] == "broken"), None)
        assert entry is not None
        assert entry["status"] == "error"

    def test_builtin_packages_still_listed(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from src.server import create_server

        server = create_server(host="127.0.0.1", port=0, token="t", static_dir=str(tmp_path))
        payload = server._collect_plugins()

        names = [p["name"] for p in payload["plugins"]]
        assert "逆向工具集" in names
        assert "MCP 桥接" in names

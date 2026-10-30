"""数据目录与 provider JSON 存储测试

真实事故：桌面端把 Host 的 cwd 设成安装目录，`.clawd/` 跟着落在安装目录里 →
升级/重装覆盖 resources/host，用户的 provider 配置、用量、会话一起被清空。
修法：数据目录走 `CLAWD_DATA_DIR`（桌面端=userData/data），provider 配置改存 JSON（可读可手改）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.core import data_dir as data_dir_mod
from src.core import local_db, providers_store, session_bridge


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data = tmp_path / "userdata"
    monkeypatch.setenv("CLAWD_DATA_DIR", str(data))
    return data


class TestDataDir:
    def test_env_var_wins(self, isolated: Path):
        assert data_dir_mod.data_dir() == isolated
        assert data_dir_mod.data_dir("/some/other") == isolated

    def test_fallback_to_workdir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.delenv("CLAWD_DATA_DIR", raising=False)
        assert data_dir_mod.data_dir(tmp_path) == tmp_path / ".clawd"
        assert data_dir_mod.data_dir() == Path.cwd() / ".clawd"

    def test_create_flag(self, isolated: Path):
        target = data_dir_mod.data_path("sessions", create_dir=True)
        assert target.is_dir()

    def test_db_and_sessions_follow_data_dir(self, isolated: Path):
        assert local_db.db_path().parent == isolated
        assert session_bridge._dir(None).parent == isolated
        assert providers_store.store_path().startswith(str(isolated))


class TestProvidersJson:
    def test_save_and_reload(self, isolated: Path):
        providers_store.save_provider(
            {"id": "ds", "name": "DeepSeek", "kind": "deepseek", "model": "deepseek-chat",
             "base_url": "https://api.deepseek.com/v1", "key": "sk-abcdefghij1234"},
        )
        data = json.loads((isolated / "providers.json").read_text(encoding="utf-8"))
        assert data["active"] == "ds"
        assert data["providers"]["ds"]["model"] == "deepseek-chat"

        # 重新读（模拟重启）
        items = providers_store.list_providers()
        assert items[0]["id"] == "ds"
        assert items[0]["has_key"] is True
        assert "sk-abcdefghij1234" not in str(items)  # 只回掩码

    def test_key_survives_edit_without_key(self, isolated: Path):
        providers_store.save_provider({"id": "a", "name": "A", "key": "sk-keep-123456"}, )
        providers_store.save_provider({"id": "a", "name": "A2"})
        assert providers_store.resolve_api_key("a") == "sk-keep-123456"

    def test_env_key_preferred(self, isolated: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MY_PROVIDER_KEY", "env-key")
        providers_store.save_provider({"id": "b", "name": "B", "key_env": "MY_PROVIDER_KEY", "key": "inline-key"})
        assert providers_store.resolve_api_key("b") == "env-key"

    def test_delete_active_promotes_other(self, isolated: Path):
        providers_store.save_provider({"id": "a", "name": "A"})
        providers_store.save_provider({"id": "b", "name": "B"})
        providers_store.set_default("a")
        assert providers_store.delete_provider("a") is True
        assert providers_store.active_provider()["id"] == "b"

    def test_broken_json_does_not_crash(self, isolated: Path):
        isolated.mkdir(parents=True, exist_ok=True)
        (isolated / "providers.json").write_text("{not json", encoding="utf-8")
        assert providers_store.list_providers() == []


class TestRestartPersistence:
    def test_new_process_sees_same_config(self, isolated: Path):
        """模拟"重启后还在"：另一个进程读同一份 JSON"""
        providers_store.save_provider(
            {"id": "persist", "name": "Persist", "kind": "openai", "model": "gpt-4o", "key": "sk-persist-999999"},
        )
        env = dict(os.environ, CLAWD_DATA_DIR=str(isolated), PYTHONIOENCODING="utf-8")
        code = (
            "from src.core import providers_store as ps;"
            "items = ps.list_providers();"
            "print(items[0]['id'], items[0]['model'], items[0]['key_source'])"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "persist gpt-4o inline" in proc.stdout

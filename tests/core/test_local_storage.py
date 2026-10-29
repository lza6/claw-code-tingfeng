"""本地存储测试：多 provider 配置 + 用量记账（SQLite）

用户诉求："能配多个 API 提供商、重启后还在、别把密钥明文吐给前端、能看到详细用量"。
这里覆盖：CRUD、默认切换、密钥掩码、删除默认后自动补位、用量汇总口径、日志倒序。
"""

from __future__ import annotations

import pytest

from pathlib import Path

from src.core import providers_store, usage_store


@pytest.fixture
def wd(tmp_path: Path) -> Path:
    return tmp_path


class TestProviders:
    def test_save_and_list(self, wd: Path):
        providers_store.save_provider(
            {"id": "ds", "name": "DeepSeek", "kind": "openai",
             "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "key": "sk-secret-123456"},
            wd,
        )
        items = providers_store.list_providers(wd)
        assert [i["id"] for i in items] == ["ds"]
        assert items[0]["name"] == "DeepSeek"
        assert items[0]["has_key"] is True

    def test_key_is_masked_never_plaintext(self, wd: Path):
        providers_store.save_provider({"id": "x", "name": "X", "key": "sk-abcdefghijklmnop"}, wd)
        item = providers_store.list_providers(wd)[0]
        assert "sk-abcdefghijklmnop" not in str(item)
        assert item["key_masked"].startswith("sk-ab")

    def test_env_key_takes_priority(self, wd: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MY_TEST_KEY", "env-secret")
        providers_store.save_provider({"id": "e", "name": "E", "key_env": "MY_TEST_KEY"}, wd)
        assert providers_store.resolve_api_key("e", wd) == "env-secret"
        assert providers_store.list_providers(wd)[0]["key_source"] == "env"

    def test_update_keeps_key_when_blank(self, wd: Path):
        providers_store.save_provider({"id": "k", "name": "K", "key": "sk-keepme-000"}, wd)
        providers_store.save_provider({"id": "k", "name": "K2"}, wd)  # 不带 key
        assert providers_store.resolve_api_key("k", wd) == "sk-keepme-000"

    def test_first_provider_becomes_default(self, wd: Path):
        providers_store.save_provider({"id": "a", "name": "A"}, wd)
        assert providers_store.list_providers(wd)[0]["is_default"] is True

    def test_set_default_is_exclusive(self, wd: Path):
        providers_store.save_provider({"id": "a", "name": "A"}, wd)
        providers_store.save_provider({"id": "b", "name": "B"}, wd)
        providers_store.set_default("b", wd)
        defaults = [i["id"] for i in providers_store.list_providers(wd) if i["is_default"]]
        assert defaults == ["b"]

    def test_delete_default_promotes_another(self, wd: Path):
        providers_store.save_provider({"id": "a", "name": "A"}, wd)
        providers_store.save_provider({"id": "b", "name": "B"}, wd)
        providers_store.set_default("a", wd)
        assert providers_store.delete_provider("a", wd) is True
        left = providers_store.list_providers(wd)
        assert len(left) == 1 and left[0]["id"] == "b" and left[0]["is_default"] is True

    def test_invalid_payloads_rejected(self, wd: Path):
        with pytest.raises(ValueError, match="id"):
            providers_store.save_provider({"id": "bad id!", "name": "X"}, wd)
        with pytest.raises(ValueError, match="name"):
            providers_store.save_provider({"id": "ok", "name": "  "}, wd)
        with pytest.raises(ValueError, match="kind"):
            providers_store.save_provider({"id": "ok2", "name": "X", "kind": "nope"}, wd)

    def test_active_provider_returns_default(self, wd: Path):
        providers_store.save_provider({"id": "a", "name": "A"}, wd)
        active = providers_store.active_provider(wd)
        assert active is not None and active["id"] == "a"


class TestUsage:
    def test_record_and_summary(self, wd: Path):
        usage_store.record(provider="openai", model="gpt-4o", prompt_tokens=1000,
                           completion_tokens=200, cache_read_tokens=500, cost=0.01, steps=2, workdir=wd)
        usage_store.record(provider="openai", model="gpt-4o", prompt_tokens=300,
                           completion_tokens=100, cost=0.002, steps=1, workdir=wd)
        data = usage_store.summary("today", wd)
        totals = data["totals"]
        assert totals["requests"] == 2
        assert totals["prompt_tokens"] == 1300
        assert totals["completion_tokens"] == 300
        assert totals["total_tokens"] == 1600
        assert totals["cost"] == pytest.approx(0.012)
        # 缓存命中率 = 500 / (500 + 1300)
        assert totals["cache_hit_rate"] == pytest.approx(500 / 1800, rel=1e-3)

    def test_recent_is_newest_first(self, wd: Path):
        usage_store.record(model="first", workdir=wd)
        usage_store.record(model="second", workdir=wd)
        rows = usage_store.recent(10, wd)
        assert [r["model"] for r in rows][:2] == ["second", "first"]

    def test_empty_db_summary_is_zeroed(self, wd: Path):
        totals = usage_store.summary("today", wd)["totals"]
        assert totals["requests"] == 0
        assert totals["cost"] == 0
        assert totals["cache_hit_rate"] == 0.0

    def test_by_model_grouping(self, wd: Path):
        usage_store.record(model="a", cost=0.5, workdir=wd)
        usage_store.record(model="b", cost=0.1, workdir=wd)
        data = usage_store.summary("today", wd)
        models = [row["model"] for row in data["by_model"]]
        assert set(models) == {"a", "b"}
        # 按成本倒序
        assert models[0] == "a"

    def test_record_failure_does_not_raise(self):
        """记账失败只告警（不能因为磁盘问题打断 agent 主流程）"""
        assert usage_store.record(model="x", workdir="Z:/definitely/not/here") is False


class TestProviderTakesEffect:
    """只存配置不改运行时不叫闭环：默认 provider 必须能产出 LLMConfig 并被 run 用上"""

    def test_build_llm_config_from_provider(self, wd: Path):
        providers_store.save_provider(
            {"id": "ds", "name": "DeepSeek", "kind": "deepseek",
             "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "key": "sk-ds-123456"},
            wd,
        )
        cfg = providers_store.build_llm_config("ds", wd)
        assert cfg.provider.value == "deepseek"
        assert cfg.api_key == "sk-ds-123456"
        assert cfg.base_url == "https://api.deepseek.com/v1"
        assert cfg.model == "deepseek-chat"

    def test_missing_key_raises_with_hint(self, wd: Path):
        providers_store.save_provider({"id": "nokey", "name": "NoKey", "key_env": "NOT_SET_XYZ"}, wd)
        with pytest.raises(ValueError, match="密钥"):
            providers_store.build_llm_config("nokey", wd)

    def test_unknown_kind_falls_back_to_custom(self, wd: Path):
        providers_store.save_provider({"id": "odd", "name": "Odd", "kind": "custom", "key": "k-12345678"}, wd)
        assert providers_store.build_llm_config("odd", wd).provider.value == "custom"

    def test_describe_active(self, wd: Path):
        assert providers_store.describe_active(wd)["configured"] is False
        providers_store.save_provider({"id": "a", "name": "A", "model": "m", "key": "sk-12345678"}, wd)
        desc = providers_store.describe_active(wd)
        assert desc["configured"] is True and desc["id"] == "a" and desc["model"] == "m"


class TestUsageClientDimension:
    """用量要能区分"谁在调用"（桌面端 / CLI / 外部引擎）——截图里那列「应用」"""

    def test_client_recorded_and_grouped(self, wd: Path):
        usage_store.record(model="m", cost=0.3, client="desktop", workdir=wd)
        usage_store.record(model="m", cost=0.1, client="cli", workdir=wd)
        data = usage_store.summary("today", wd)
        by_client = {row["client"]: row for row in data["by_client"]}
        assert set(by_client) == {"desktop", "cli"}
        assert by_client["desktop"]["requests"] == 1
        assert by_client["desktop"]["cost"] == pytest.approx(0.3)

    def test_recent_rows_expose_client(self, wd: Path):
        usage_store.record(model="m", client="desktop", workdir=wd)
        assert usage_store.recent(1, wd)[0]["client"] == "desktop"

    def test_blank_client_is_labelled(self, wd: Path):
        usage_store.record(model="m", workdir=wd)  # 不传 client
        data = usage_store.summary("today", wd)
        assert data["by_client"][0]["client"] == "(未标注)"


class TestUsageCli:
    def test_usage_json(self, wd: Path, monkeypatch: pytest.MonkeyPatch):
        import json

        from typer.testing import CliRunner

        from src.cli import entrypoint

        monkeypatch.chdir(wd)
        usage_store.record(model="m1", cost=0.02, client="cli", workdir=wd)
        result = CliRunner().invoke(entrypoint.app, ["usage", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["totals"]["requests"] == 1
        assert payload["recent"][0]["client"] == "cli"

    def test_usage_table_renders(self, wd: Path, monkeypatch: pytest.MonkeyPatch):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        monkeypatch.chdir(wd)
        usage_store.record(model="m1", cost=0.02, client="desktop", workdir=wd)
        result = CliRunner().invoke(entrypoint.app, ["usage"])
        assert result.exit_code == 0
        assert "用量" in result.output
        assert "desktop" in result.output

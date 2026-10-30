"""插件体系测试（真实加载 fixture 插件，覆盖 manifest/加载/DI/失败降级/reload）"""
import shutil
from pathlib import Path

import pytest

from src.plugins import PluginError, PluginManager, PluginManifest, load_manifest_from_dir

FIXTURE = Path(__file__).parent / "fixtures" / "sample_plugin"


@pytest.fixture
def workdir(tmp_path):
    plugins = tmp_path / ".clawd" / "plugins" / "sample_plugin"
    plugins.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE, plugins)
    # 清理 __pycache__ 防止跨 fixture 污染
    for pyc in plugins.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)
    return tmp_path


class TestManifest:
    def test_load_from_fixture(self, workdir):
        m = load_manifest_from_dir(workdir / ".clawd" / "plugins" / "sample_plugin")
        assert m.name == "sample-echo"
        assert m.entry == "clawd_sample_plugin:setup"
        assert m.version == "0.1.0"

    def test_missing_section(self, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        (d / "pyproject.toml").write_text('[project]\nname="x"\n', encoding="utf-8")
        with pytest.raises(PluginError, match="tool.clawd.plugin"):
            load_manifest_from_dir(d)

    def test_missing_entry(self, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        (d / "pyproject.toml").write_text(
            '[tool.clawd.plugin]\nname="x"\n', encoding="utf-8"
        )
        with pytest.raises(PluginError, match="name/entry"):
            load_manifest_from_dir(d)

    def test_missing_pyproject(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        with pytest.raises(PluginError, match="pyproject"):
            load_manifest_from_dir(d)

    def test_from_pyproject_dataclass(self):
        m = PluginManifest.from_pyproject({
            "tool": {"clawd": {"plugin": {"name": "a", "entry": "m:f"}}}
        })
        assert m.provides_tools is False  # 默认值


class TestPluginManager:
    def test_discover_empty(self, tmp_path):
        pm = PluginManager(workdir=tmp_path)
        assert pm.discover() == []

    def test_load_all_success(self, workdir):
        pm = PluginManager(workdir=workdir)
        results = pm.load_all()
        assert results.get("sample-echo") == "loaded"
        # 工具注册面生效
        tools = pm.get_tools()
        assert any(t.name == "sample_echo" for t in tools)
        # prompt 注入面生效
        assert any("sample_echo" in s for s in pm.get_prompt_sections())
        # expose 服务生效
        assert pm._services["sample-echo:echo"].transform("hi") == "echo: hi"
        assert pm.loaded_names == ["sample-echo"]

    def test_tool_actually_executes(self, workdir):
        pm = PluginManager(workdir=workdir)
        pm.load_all()
        tool = next(t for t in pm.get_tools() if t.name == "sample_echo")
        result = tool.execute(text="hello")
        assert result.is_success
        assert result.output == "echo: hello"

    def test_bad_plugin_degrades(self, tmp_path):
        plugins = tmp_path / ".clawd" / "plugins"
        plugins.mkdir(parents=True)
        # 一个坏插件（缺 entry 函数）
        bad = plugins / "bad_plugin"
        bad.mkdir()
        (bad / "pyproject.toml").write_text(
            '[tool.clawd.plugin]\nname="bad"\nentry="nonexistent_mod:setup"\n',
            encoding="utf-8",
        )
        pm = PluginManager(workdir=tmp_path)
        results = pm.load_all()
        # manifest.name 为 "bad"（结果键统一用 manifest.name）
        assert results.get("bad", "").startswith("error:")

    def test_reload_idempotent(self, workdir):
        pm = PluginManager(workdir=workdir)
        r1 = pm.load_all()
        r2 = pm.load_all()  # reload: dispose → 重新加载
        assert r1 == r2 == {"sample-echo": "loaded"}
        assert len(pm.get_tools()) == 1  # 不会累积重复工具

    def test_shutdown_runs_hooks(self, workdir):
        pm = PluginManager(workdir=workdir)
        pm.load_all()
        pm.shutdown()
        assert pm.get_tools() == []
        assert pm.loaded_names == []

    def test_require_missing_service(self, workdir):
        pm = PluginManager(workdir=workdir)
        pm.load_all()
        with pytest.raises(PluginError, match="公共服务不存在"):
            pm._require_service("nope:thing")

    def test_settings_loaded(self, workdir):
        cfg_dir = workdir / ".clawd" / "plugin_settings"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "sample-echo.json").write_text('{"greeting": "yo"}', encoding="utf-8")
        pm = PluginManager(workdir=workdir)
        pm.load_all()
        assert pm._loaded["sample-echo"] is not None

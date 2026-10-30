"""多引擎统一后端测试（base + registry，零网络/零外部依赖）"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.backends import registry
from src.backends.base import (
    BackendResult,
    BackendUnavailable,
    CliBackend,
    CliEngineProfile,
    resolve_binary,
)

# ==========================================================================
# 结果语义
# ==========================================================================


class TestBackendResult:
    def test_ok_requires_zero_exit_no_errors_no_timeout(self):
        assert BackendResult(exit_code=0).ok is True
        assert BackendResult(exit_code=1).ok is False
        assert BackendResult(exit_code=0, errors=["boom"]).ok is False
        assert BackendResult(exit_code=0, timed_out=True).ok is False

    def test_to_dict_truncates_errors(self):
        r = BackendResult(engine="codex", text="hi", errors=[f"e{i}" for i in range(10)])
        d = r.to_dict()
        assert d["engine"] == "codex"
        assert len(d["errors"]) == 5
        assert d["ok"] is False


# ==========================================================================
# 可执行文件解析（Windows .cmd 兼容）
# ==========================================================================


class TestResolveBinary:
    def test_list_form_validated(self, tmp_path: Path):
        with pytest.raises(BackendUnavailable, match="未找到可执行文件"):
            resolve_binary([str(tmp_path / "nope.exe")])

    def test_list_form_passes_through(self):
        assert resolve_binary([sys.executable]) == [sys.executable]

    def test_empty_list_rejected(self):
        with pytest.raises(BackendUnavailable, match="不能为空"):
            resolve_binary([])

    def test_missing_name_rejected(self):
        with pytest.raises(BackendUnavailable):
            resolve_binary("definitely-not-a-real-binary-xyz")


# ==========================================================================
# 通用 CLI 后端：argv 组装 + 解析 + 执行
# ==========================================================================


PROFILE = CliEngineProfile(
    name="fake",
    binary="fake-engine",
    version_args=("--version",),
    argv_template=("run",),
    json_flag_args=("--format", "json"),
    event_text_keys=("part.text", "text"),
    event_command_keys=("part.command",),
    event_usage_keys=("usage",),
    event_session_keys=("sessionID",),
)


FAKE_ENGINE = """
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
if "--version" in sys.argv:
    print("fake-engine 1.2.3")
    sys.exit(0)
for e in [
    {"type": "session", "sessionID": "s-9"},
    {"type": "msg", "part": {"text": "你好"}},
    {"type": "tool", "part": {"command": "ls -la"}},
    {"type": "done", "usage": {"input_tokens": 3, "output_tokens": 2}},
]:
    print(json.dumps(e, ensure_ascii=False))
"""


@pytest.fixture
def fake_backend(tmp_path: Path) -> CliBackend:
    script = tmp_path / "fake_engine.py"
    script.write_text(FAKE_ENGINE, encoding="utf-8")
    return CliBackend(PROFILE, workdir=tmp_path, binary_override=[sys.executable, str(script)])


class TestCliBackend:
    def test_build_argv_includes_template_and_json_flags(self, fake_backend):
        argv = fake_backend.build_argv("做点事")
        # argv[0] 是解释器、argv[1] 是脚本（binary_override 场景），模板与 JSON 开关在其后
        assert argv[-3:] == ["run", "--format", "json"]

    def test_probe_reports_ready_and_version(self, fake_backend):
        probe = fake_backend.probe()
        assert probe.status == "ready"
        assert probe.version == "fake-engine 1.2.3"
        assert probe.usable is True

    def test_probe_not_installed(self, tmp_path: Path):
        backend = CliBackend(PROFILE, workdir=tmp_path,
                             binary_override=[str(tmp_path / "missing.exe")])
        probe = backend.probe()
        assert probe.status == "not_installed"
        assert probe.usable is False

    def test_probe_detects_incompatible_runtime(self, tmp_path: Path):
        script = tmp_path / "bad_runtime.py"
        script.write_text(
            "import sys; print('Node.js >=22 required (current: v25)'); sys.exit(1)",
            encoding="utf-8",
        )
        backend = CliBackend(PROFILE, workdir=tmp_path,
                             binary_override=[sys.executable, str(script)])
        probe = backend.probe()
        assert probe.status == "incompatible"
        assert "Node.js" in probe.detail

    def test_run_normalizes_events(self, fake_backend):
        result = fake_backend.run("做点事", timeout=60)

        assert result.engine == "fake"
        assert result.text == "你好"
        assert result.session_id == "s-9"
        assert result.commands == [{"command": "ls -la", "exit_code": None}]
        assert result.usage == {"input_tokens": 3, "output_tokens": 2}
        assert result.exit_code == 0

    def test_run_rejects_empty_goal(self, fake_backend):
        with pytest.raises(BackendUnavailable, match="goal 不能为空"):
            fake_backend.run("  ")

    def test_plain_text_engine_falls_back_to_raw_output(self, tmp_path: Path):
        script = tmp_path / "plain.py"
        script.write_text(
            "import sys\nsys.stdout.reconfigure(encoding='utf-8')\nprint('纯文本输出')\n",
            encoding="utf-8",
        )
        backend = CliBackend(PROFILE, workdir=tmp_path,
                             binary_override=[sys.executable, str(script)])
        result = backend.run("x", timeout=60)
        assert "纯文本输出" in result.text


# ==========================================================================
# 注册表
# ==========================================================================


class TestRegistry:
    def test_known_engines_registered(self):
        assert set(registry.ENGINES) == {"codex", "opencode", "openclaw"}

    def test_native_engine_registered_alongside_cli_engines(self):
        """native 是内置引擎（不是 CLI），必须出现在 ALL_ENGINES 里

        回归背景：曾只把 native 加进 get_backend 分支，忘了 probe_all 的过滤
        条件仍是 `in ENGINES`，导致 `clawd engines` / collaborate 默认引擎
        看不见 native —— 自相矛盾。
        """
        assert registry.NATIVE_ENGINE == "native"
        assert "native" in registry.ALL_ENGINES
        assert registry.ALL_ENGINES[0] == "native"

    def test_get_backend_native_returns_native_backend(self):
        backend = registry.get_backend("native")
        assert backend.__class__.__name__ == "NativeBackend"
        assert backend.name == "native"

    def test_probe_native_is_ready(self):
        probe = registry.probe_engine("native")
        assert probe.status == "ready"
        assert probe.usable is True
        assert probe.version == "builtin"

    def test_non_engines_are_explicitly_not_engines(self):
        """grok 是模型代理、pi 是插件包、hermes 无源码 —— 不能当引擎驱动"""
        assert set(registry.NON_ENGINES) == {"grok", "pi", "hermes"}
        for name in registry.NON_ENGINES:
            assert name not in registry.ENGINES

    def test_get_backend_unknown_raises(self):
        with pytest.raises(KeyError, match="未知引擎"):
            registry.get_backend("nope")

    def test_get_backend_returns_codex_specialized_driver(self):
        backend = registry.get_backend("codex", model="m1", sandbox="read-only")
        assert backend.__class__.__name__ == "CodexBackend"
        assert backend.model == "m1"

    def test_get_backend_returns_generic_driver_for_opencode(self):
        backend = registry.get_backend("opencode")
        assert isinstance(backend, CliBackend)
        assert backend.profile.name == "opencode"

    def test_describe_covers_engines_and_non_engines(self):
        described = registry.describe()
        assert set(described) == {
            "native", "codex", "opencode", "openclaw", "grok", "pi", "hermes",
        }
        assert described["native"]["kind"] == "engine"
        assert described["native"]["status"] == "ready"
        assert described["codex"]["kind"] == "engine"
        assert described["grok"]["kind"] == "non-engine"
        # 状态必须是真实探活结果之一
        assert described["codex"]["status"] in {"ready", "not_installed", "incompatible", "error"}

    def test_probe_all_returns_entry_per_engine(self):
        probes = registry.probe_all()
        assert len(probes) == len(registry.ALL_ENGINES)
        assert {p.name for p in probes} == set(registry.ALL_ENGINES)

    def test_ready_engines_always_includes_native(self):
        """内置引擎零外部依赖，必须始终可用（否则 collaborate 默认引擎会失效）"""
        assert "native" in registry.ready_engines()

    def test_probe_all_ignores_unknown_names(self):
        probes = registry.probe_all(["native", "nope"])
        assert [p.name for p in probes] == ["native"]

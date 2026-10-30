"""`clawd onboard` 命令测试（回归：onboarding 模块零调用点 → 上手引导形同不存在）
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from src.cli import entrypoint
from src.utils.onboarding import detect_api_keys, preflight_report, start_oauth_flow

_KEY_ENVS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "VERTEXAI_PROJECT",
    "CLAWD_API_KEY",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for name in _KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class TestPreflightReport:
    def test_reports_not_ready_without_keys(self, clean_env):
        report = preflight_report()
        assert report["ready"] is False
        assert report["keys"] == {}
        assert report["model"] is None
        assert "未检测到" in report["hint"]

    def test_reports_model_when_key_present(self, clean_env):
        clean_env.setenv("OPENAI_API_KEY", "sk-test-not-real")
        report = preflight_report()
        assert report["ready"] is True
        assert report["keys"].get("openai") is True
        assert report["model"] == "gpt-4o"
        assert "gpt-4o" in report["hint"]

    def test_detect_api_keys_only_lists_present(self, clean_env):
        clean_env.setenv("DEEPSEEK_API_KEY", "x")
        assert detect_api_keys() == {"deepseek": True}


class TestOnboardCommand:
    def test_json_mode_outputs_machine_readable(self, clean_env):
        clean_env.setenv("OPENAI_API_KEY", "sk-test-not-real")
        result = CliRunner().invoke(entrypoint.app, ["onboard", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["ready"] is True
        assert payload["model"] == "gpt-4o"

    def test_exit_1_when_not_ready(self, clean_env):
        result = CliRunner().invoke(entrypoint.app, ["onboard"])
        assert result.exit_code == 1
        assert "未检测到" in result.output

    def test_human_output_lists_keys(self, clean_env):
        clean_env.setenv("ANTHROPIC_API_KEY", "x")
        result = CliRunner().invoke(entrypoint.app, ["onboard"])
        assert result.exit_code == 0
        assert "anthropic" in result.output


class TestOAuthIsHonest:
    def test_oauth_flow_says_not_implemented(self):
        """旧实现打印"正在打开浏览器"但什么都不发生 —— 用户会一直等"""

        class _IO:
            def __init__(self) -> None:
                self.errors: list[str] = []
                self.outputs: list[str] = []

            def tool_error(self, msg: str) -> None:
                self.errors.append(msg)

            def tool_output(self, msg: str) -> None:
                self.outputs.append(msg)

        io = _IO()
        assert start_oauth_flow(io) is None
        assert any("尚未实现" in e for e in io.errors)
        assert not any("Opening OpenRouter" in o for o in io.outputs)

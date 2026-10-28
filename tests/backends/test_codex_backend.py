"""Codex 后端适配器测试（零网络：假进程注入 JSONL 事件流）"""

from __future__ import annotations

import json
import sys
import time

from pathlib import Path

import pytest

from src.backends.codex import CodexBackend, CodexBackendError, parse_events


# ==========================================================================
# 事件解析
# ==========================================================================


class TestParseEvents:
    def test_extracts_message_usage_and_thread(self):
        lines = [
            json.dumps({"type": "thread.started", "thread_id": "t-1"}),
            json.dumps({"type": "item.completed",
                        "item": {"item_type": "agent_message", "text": "完成"}}),
            json.dumps({"type": "turn.completed",
                        "usage": {"input_tokens": 10, "output_tokens": 5}}),
        ]

        out = parse_events(lines)

        assert out["thread_id"] == "t-1"
        assert out["text"] == "完成"
        assert out["usage"] == {"input_tokens": 10, "output_tokens": 5}
        assert out["errors"] == []

    def test_extracts_command_executions(self):
        lines = [
            json.dumps({"type": "item.completed",
                        "item": {"item_type": "command_execution",
                                 "command": "pytest -q", "exit_code": 0}}),
        ]

        out = parse_events(lines)

        assert out["commands"] == [{"command": "pytest -q", "exit_code": 0}]

    def test_collects_errors(self):
        lines = [json.dumps({"type": "error", "message": "rate limited"})]
        out = parse_events(lines)
        assert out["errors"] == ["rate limited"]

    def test_ignores_malformed_lines_without_aborting(self):
        lines = ["not json", "", json.dumps({"type": "thread.started", "thread_id": "x"})]
        out = parse_events(lines)
        assert out["thread_id"] == "x"
        assert len(out["events"]) == 1

    def test_multiple_messages_joined(self):
        lines = [
            json.dumps({"type": "item.completed",
                        "item": {"item_type": "agent_message", "text": "A"}}),
            json.dumps({"type": "item.completed",
                        "item": {"item_type": "agent_message", "text": "B"}}),
        ]
        assert parse_events(lines)["text"] == "A\nB"


# ==========================================================================
# 参数组装
# ==========================================================================


class TestBuildArgv:
    def test_default_argv_includes_json_and_sandbox(self):
        backend = CodexBackend(binary=["codex"], sandbox="read-only")
        argv = backend.build_argv("跑测试")

        assert argv[1:3] == ["exec", "--json"]
        assert "--sandbox" in argv and "read-only" in argv
        assert argv[-1] == "跑测试"
        assert "--skip-git-repo-check" in argv

    def test_model_and_provider_overrides(self):
        backend = CodexBackend(binary=["codex"], model="gpt-5", provider="openai")
        argv = backend.build_argv("x")

        joined = " ".join(argv)
        assert 'model="gpt-5"' in joined
        assert 'model_provider="openai"' in joined

    def test_base_url_registers_custom_provider(self):
        """Codex 禁止覆盖内置 provider（openai）→ 必须注册成 openai-custom"""
        backend = CodexBackend(
            binary=["codex"], provider="openai", base_url="https://example.test/v1"
        )
        joined = " ".join(backend.build_argv("x"))

        assert 'model_provider="openai-custom"' in joined
        assert 'model_providers.openai-custom.base_url="https://example.test/v1"' in joined
        assert 'model_providers.openai-custom.env_key="OPENAI_API_KEY"' in joined
        assert 'model_providers.openai-custom.wire_api="responses"' in joined

    def test_custom_provider_name_kept_as_is(self):
        backend = CodexBackend(
            binary=["codex"], provider="clawd", base_url="https://example.test/v1"
        )
        joined = " ".join(backend.build_argv("x"))
        assert 'model_provider="clawd"' in joined
        assert "clawd-custom" not in joined

    def test_extra_config_serialized_as_json(self):
        backend = CodexBackend(binary=["codex"], extra_config={"approval_policy": "never"})
        argv = backend.build_argv("x")

        assert 'approval_policy="never"' in " ".join(argv)

    def test_skip_git_check_can_be_disabled(self):
        backend = CodexBackend(binary=["codex"], skip_git_check=False)
        assert "--skip-git-repo-check" not in backend.build_argv("x")


# ==========================================================================
# 执行（假进程）
# ==========================================================================


FAKE_OK = """
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
events = [
    {"type": "thread.started", "thread_id": "t-42"},
    {"type": "item.completed", "item": {"item_type": "agent_message", "text": "任务完成"}},
    {"type": "item.completed", "item": {"item_type": "command_execution",
                                        "command": "echo hi", "exit_code": 0}},
    {"type": "turn.completed", "usage": {"input_tokens": 7, "output_tokens": 3}},
]
for e in events:
    print(json.dumps(e, ensure_ascii=False))
print("warn-line", file=sys.stderr)
"""

FAKE_FAIL = """
import sys
print("boom", file=sys.stderr)
sys.exit(3)
"""

FAKE_SLEEP = """
import time
time.sleep(30)
"""


def _fake(tmp_path: Path, code: str, name: str = "fake_codex.py") -> list[str]:
    path = tmp_path / name
    path.write_text(code, encoding="utf-8")
    return [sys.executable, str(path)]


class TestRun:
    def test_successful_run_aggregates_result(self, tmp_path: Path):
        backend = CodexBackend(binary=_fake(tmp_path, FAKE_OK), workdir=tmp_path)

        result = backend.run("任务", timeout=60)

        assert result.text == "任务完成"
        assert result.usage == {"input_tokens": 7, "output_tokens": 3}
        assert result.thread_id == "t-42"
        assert len(result.commands) == 1
        assert result.exit_code == 0
        assert result.duration_s > 0
        # stderr 被收进 errors（用来暴露告警），因此 ok 依赖 errors 为空
        assert "warn-line" in result.errors

    def test_nonzero_exit_is_not_ok(self, tmp_path: Path):
        backend = CodexBackend(binary=_fake(tmp_path, FAKE_FAIL), workdir=tmp_path)

        result = backend.run("任务", timeout=60)

        assert result.exit_code == 3
        assert result.ok is False
        assert any("boom" in e for e in result.errors)

    def test_timeout_kills_process_and_flags_it(self, tmp_path: Path):
        backend = CodexBackend(binary=_fake(tmp_path, FAKE_SLEEP), workdir=tmp_path)

        started = time.perf_counter()
        result = backend.run("任务", timeout=1.5)
        elapsed = time.perf_counter() - started

        assert result.timed_out is True
        assert result.ok is False
        # 强杀生效：远小于假进程的 30s 睡眠
        assert elapsed < 20

    def test_empty_goal_rejected(self, tmp_path: Path):
        backend = CodexBackend(binary=_fake(tmp_path, FAKE_OK), workdir=tmp_path)
        with pytest.raises(CodexBackendError, match="goal 不能为空"):
            backend.run("   ")

    def test_missing_binary_reported(self):
        backend = CodexBackend(binary=["definitely-not-a-real-binary-xyz"])
        assert backend.available() is False
        with pytest.raises(CodexBackendError, match="未找到 codex"):
            backend.run("任务")


class TestAvailability:
    def test_available_true_for_real_executable(self):
        backend = CodexBackend(binary=[sys.executable])
        assert backend.available() is True

    def test_version_reads_last_line(self, tmp_path: Path):
        script = tmp_path / "v.py"
        script.write_text("print('codex-cli 9.9.9')", encoding="utf-8")
        backend = CodexBackend(binary=[sys.executable, str(script)])

        assert backend.version() == "codex-cli 9.9.9"

    def test_real_codex_detected_if_installed(self):
        """本机已装 codex 时应能识别（未装则跳过，不算失败）"""
        backend = CodexBackend()
        if not backend.available():
            pytest.skip("本机未安装 codex CLI")
        assert backend.version() and "codex" in backend.version().lower()

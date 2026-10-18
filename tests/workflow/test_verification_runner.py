"""真实验证执行器与 ralph-verify 阶段的回归测试。

## 背景

`pipeline.py` 的验证阶段曾硬编码 `"verification_result": "passed"` ——
从不运行任何测试。随后被改为诚实的 `not_implemented`（不再撒谎），
但"不撒谎"不等于"会验证"。

本文件锁定 `verification_runner` 的真实行为：
以**退出码**判定、未配置时不冒充通过、超时与启动失败都有明确状态。
"""
from __future__ import annotations

import sys

import pytest

from src.workflow.verification_runner import (
    VerificationRun,
    resolve_command,
    run_verification,
)


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


class TestVerificationRunner:
    def test_passing_command_is_verified(self, tmp_path):
        run = run_verification(tmp_path, command=_py("raise SystemExit(0)"))
        assert run.status == "passed"
        assert run.verified is True
        assert run.exit_code == 0

    def test_failing_command_is_not_verified(self, tmp_path):
        run = run_verification(tmp_path, command=_py("raise SystemExit(3)"))
        assert run.status == "failed"
        assert run.verified is False
        assert run.exit_code == 3
        assert "3" in run.reason

    def test_not_configured_never_reports_passed(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAWD_VERIFY_COMMAND", raising=False)
        run = run_verification(tmp_path)
        assert run.status == "not_configured"
        assert run.verified is False
        assert "未" in run.reason

    def test_timeout_is_reported(self, tmp_path):
        run = run_verification(
            tmp_path, command=_py("import time; time.sleep(5)"), timeout=1
        )
        assert run.status == "timeout"
        assert run.verified is False

    def test_unlaunchable_command_is_error(self, tmp_path):
        run = run_verification(tmp_path, command=["definitely-not-a-real-exe-xyz"])
        assert run.status == "error"
        assert run.verified is False
        assert run.exit_code is None

    def test_env_var_is_used(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "CLAWD_VERIFY_COMMAND",
            f'"{sys.executable}" -c "raise SystemExit(0)"',
        )
        run = run_verification(tmp_path)
        assert run.status == "passed"

    def test_output_tail_is_captured(self, tmp_path):
        run = run_verification(
            tmp_path, command=_py("print('hello-verification'); raise SystemExit(1)")
        )
        assert "hello-verification" in run.output_tail

    def test_artifacts_are_json_friendly(self, tmp_path):
        import json

        run = run_verification(tmp_path, command=_py("raise SystemExit(0)"))
        payload = run.to_artifacts()
        json.dumps(payload)  # 不应抛异常
        assert payload["verified"] is True
        assert payload["verification_result"] == "passed"

    def test_resolve_prefers_tests_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAWD_VERIFY_COMMAND", raising=False)
        (tmp_path / "tests").mkdir()
        argv, display = resolve_command(tmp_path)
        assert argv is not None
        assert "pytest" in display

    def test_resolve_returns_none_without_tests(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAWD_VERIFY_COMMAND", raising=False)
        argv, display = resolve_command(tmp_path)
        assert argv is None and display == ""


class TestRalphVerifyStageWiring:
    """阶段状态必须与验证结论一致。"""

    @pytest.mark.asyncio
    async def test_passing_verification_completes(self, tmp_path, monkeypatch):
        from src.workflow.pipeline import create_ralph_verify_stage
        from src.workflow.types import StageContext, StageStatus

        monkeypatch.setenv(
            "CLAWD_VERIFY_COMMAND",
            f'"{sys.executable}" -c "raise SystemExit(0)"',
        )
        stage = create_ralph_verify_stage(max_iterations=1)
        result = await stage.run(StageContext(task="t", cwd=tmp_path))

        assert result.status == StageStatus.SUCCESS
        assert result.artifacts["verified"] is True

    @pytest.mark.asyncio
    async def test_failing_verification_fails_stage(self, tmp_path, monkeypatch):
        from src.workflow.pipeline import create_ralph_verify_stage
        from src.workflow.types import StageContext, StageStatus

        monkeypatch.setenv(
            "CLAWD_VERIFY_COMMAND",
            f'"{sys.executable}" -c "raise SystemExit(2)"',
        )
        stage = create_ralph_verify_stage(max_iterations=1)
        result = await stage.run(StageContext(task="t", cwd=tmp_path))

        assert result.status == StageStatus.FAILED
        assert result.artifacts["verified"] is False

    @pytest.mark.asyncio
    async def test_unconfigured_verification_is_skipped(self, tmp_path, monkeypatch):
        from src.workflow.pipeline import create_ralph_verify_stage
        from src.workflow.types import StageContext, StageStatus

        monkeypatch.delenv("CLAWD_VERIFY_COMMAND", raising=False)
        stage = create_ralph_verify_stage(max_iterations=1)
        result = await stage.run(StageContext(task="t", cwd=tmp_path))

        assert result.status == StageStatus.SKIPPED
        assert result.artifacts["verified"] is False

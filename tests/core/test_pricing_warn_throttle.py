"""定价过期提醒节流（此前每条命令都打印 5 行提示，把真实输出挤没了）"""

from __future__ import annotations

import os
import time

from pathlib import Path

import pytest

from src.core.cost_estimator.cost_estimator import _should_warn_pricing


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAWD_PRICING_WARN", raising=False)
    return tmp_path


class TestThrottle:
    def test_first_call_warns_and_writes_marker(self, workdir: Path):
        assert _should_warn_pricing() is True
        assert (workdir / ".clawd" / "pricing_warned").is_file()

    def test_second_call_within_24h_is_silent(self, workdir: Path):
        _should_warn_pricing()
        assert _should_warn_pricing() is False

    def test_warns_again_after_24h(self, workdir: Path):
        now = time.time()
        _should_warn_pricing(now=now)
        assert _should_warn_pricing(now=now + 86401) is True

    def test_env_always_forces_warn(self, workdir: Path, monkeypatch):
        _should_warn_pricing()
        monkeypatch.setenv("CLAWD_PRICING_WARN", "always")
        assert _should_warn_pricing() is True

    def test_env_never_silences(self, workdir: Path, monkeypatch):
        monkeypatch.setenv("CLAWD_PRICING_WARN", "never")
        assert _should_warn_pricing() is False

    def test_corrupt_marker_warns_again(self, workdir: Path):
        marker = workdir / ".clawd" / "pricing_warned"
        marker.parent.mkdir(parents=True)
        marker.write_text("not-a-number", encoding="utf-8")
        assert _should_warn_pricing() is True

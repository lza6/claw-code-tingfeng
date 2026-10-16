"""工具执行线程池配置回归测试。

## 背景

工具通过 `ThreadPoolExecutor` 执行，规模硬编码为 10。实测 200 个并发
bash 调用被压成 20 波，吞吐仅 11 req/s —— 批量 / 服务化场景下这是瓶颈。

现开放为环境变量 `CLAWD_TOOL_EXECUTOR_MAX_WORKERS`，**默认值保持 10 不变**
（不改变既有行为）。

## 关键风险

线程池大小配错会让**全部**工具执行失败 —— `ThreadPoolExecutor(max_workers=0)`
直接抛 `ValueError`。这种低级配置错误不应导致整个 agent 不可用，
因此非法值必须回退到默认而非透传。
"""

from __future__ import annotations

import asyncio

import pytest
from src.agent.tool_executor import (
    _DEFAULT_EXECUTOR_MAX_WORKERS,
    _EXECUTOR_MAX_WORKERS_ENV,
    _resolve_max_workers,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(_EXECUTOR_MAX_WORKERS_ENV, raising=False)


class TestResolveMaxWorkers:
    def test_defaults_to_ten_when_unset(self):
        assert _resolve_max_workers() == _DEFAULT_EXECUTOR_MAX_WORKERS == 10

    @pytest.mark.parametrize("value", ["1", "7", "32", "256"])
    def test_valid_override_is_honoured(self, monkeypatch, value: str):
        monkeypatch.setenv(_EXECUTOR_MAX_WORKERS_ENV, value)
        assert _resolve_max_workers() == int(value)

    @pytest.mark.parametrize("value", ["0", "-5", "-1"])
    def test_non_positive_falls_back_not_crashes(self, monkeypatch, value: str):
        """max_workers=0 会让 ThreadPoolExecutor 直接抛 ValueError，
        进而让**所有**工具执行失败 —— 必须回退。"""
        monkeypatch.setenv(_EXECUTOR_MAX_WORKERS_ENV, value)
        assert _resolve_max_workers() == _DEFAULT_EXECUTOR_MAX_WORKERS

    @pytest.mark.parametrize("value", ["abc", "3.5", "  ", "0x10"])
    def test_non_integer_falls_back(self, monkeypatch, value: str):
        monkeypatch.setenv(_EXECUTOR_MAX_WORKERS_ENV, value)
        assert _resolve_max_workers() == _DEFAULT_EXECUTOR_MAX_WORKERS

    def test_absurd_value_is_capped(self, monkeypatch):
        """线程数超过一定量级只会加剧上下文切换，不会提升吞吐"""
        monkeypatch.setenv(_EXECUTOR_MAX_WORKERS_ENV, "99999")
        resolved = _resolve_max_workers()
        assert resolved == 256
        assert resolved <= 256

    def test_fallback_never_zero(self, monkeypatch):
        """无论输入什么，返回值必须是可用的正数"""
        for raw in ("0", "-1", "abc", "", "1e9"):
            monkeypatch.setenv(_EXECUTOR_MAX_WORKERS_ENV, raw)
            assert _resolve_max_workers() > 0, f"{raw!r} 产生了非法值"


class TestExecutorActuallyUsesConfig:
    def test_executor_created_with_configured_size(self, monkeypatch):
        import src.agent.tool_executor as te

        monkeypatch.setenv(_EXECUTOR_MAX_WORKERS_ENV, "7")
        monkeypatch.setattr(te, "_BOUNDED_EXECUTOR", None)

        executor = asyncio.run(te._get_bounded_executor())
        assert executor._max_workers == 7

        executor.shutdown(wait=False)
        monkeypatch.setattr(te, "_BOUNDED_EXECUTOR", None)

    def test_executor_default_when_unset(self, monkeypatch):
        import src.agent.tool_executor as te

        monkeypatch.setattr(te, "_BOUNDED_EXECUTOR", None)
        executor = asyncio.run(te._get_bounded_executor())
        assert executor._max_workers == _DEFAULT_EXECUTOR_MAX_WORKERS

        executor.shutdown(wait=False)
        monkeypatch.setattr(te, "_BOUNDED_EXECUTOR", None)


class TestEnvExampleDocumentsIt:
    def test_env_example_has_the_switch(self):
        from pathlib import Path
        text = (Path.cwd() / ".env.example").read_text(encoding="utf-8")
        assert _EXECUTOR_MAX_WORKERS_ENV in text

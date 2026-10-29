"""NativeBackend 测试 —— 重点验证 `timeout` 真实生效（不是装饰参数）

回归背景：`NativeBackend.run(self, goal, timeout=900.0)` 曾接受 timeout 却完全忽略，
调用方以为有墙钟上限，实际会无限等下去（本仓库 skill 记录的头号陷阱：
"参数被接受但被忽略"）。这里用假引擎把协程睡住，用真实时钟断言超时生效。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from src.backends.base import BackendUnavailable
from src.backends.native import NativeBackend


class _FakeSession:
    final_result = "done"
    steps: list = []
    total_tokens = 7
    is_complete = True


class _FastEngine:
    async def run(self, goal):  # noqa: D401 - 测试替身
        return _FakeSession()


class _SlowEngine:
    async def run(self, goal):
        await asyncio.sleep(30)
        return _FakeSession()


class _BoomEngine:
    async def run(self, goal):
        raise RuntimeError("引擎炸了")


class TestNativeBackendMeta:
    def test_name_and_probe(self):
        backend = NativeBackend()
        assert backend.name == "native"
        probe = backend.probe()
        assert probe.name == "native"
        assert probe.status == "ready"
        assert probe.usable is True

    def test_available_and_version(self):
        backend = NativeBackend()
        assert backend.available() is True
        assert backend.version()


class TestNativeBackendRun:
    def test_rejects_empty_goal(self):
        with pytest.raises(BackendUnavailable, match="goal 不能为空"):
            NativeBackend(engine=_FastEngine()).run("   ")

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(BackendUnavailable, match="timeout 必须为正数"):
            NativeBackend(engine=_FastEngine()).run("x", timeout=0)

    def test_happy_path_returns_result(self):
        result = NativeBackend(engine=_FastEngine()).run("x", timeout=10)
        assert result.ok is True
        assert result.text == "done"
        assert result.usage == {"total_tokens": 7}
        assert result.timed_out is False

    def test_timeout_actually_interrupts_waiting(self):
        """慢引擎 + 0.3s 上限 → 必须快速返回 timed_out，而不是等 30s"""
        started = time.perf_counter()
        result = NativeBackend(engine=_SlowEngine()).run("x", timeout=0.3)
        elapsed = time.perf_counter() - started

        assert result.timed_out is True
        assert result.ok is False
        assert result.exit_code == 1
        assert any("超时" in e for e in result.errors)
        assert elapsed < 5.0, f"超时未生效，实际耗时 {elapsed:.1f}s"

    def test_engine_exception_becomes_error_result(self):
        result = NativeBackend(engine=_BoomEngine()).run("x", timeout=10)
        assert result.ok is False
        assert result.exit_code == 1
        assert any("RuntimeError" in e for e in result.errors)


class TestRunCoroLoopSafety:
    def test_run_inside_running_event_loop_uses_thread(self):
        """已在事件循环里时不能直接 asyncio.run（会 RuntimeError）"""

        async def payload():
            return "ok"

        async def main():
            return NativeBackend._run_coro(payload())

        assert asyncio.run(main()) == "ok"

    def test_run_without_loop_uses_plain_asyncio_run(self):
        async def payload():
            return 42

        assert NativeBackend._run_coro(payload()) == 42

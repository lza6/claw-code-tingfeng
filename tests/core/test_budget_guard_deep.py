"""BudgetGuard 深度行为测试 — 预算熔断、资源探测与降级路径

覆盖目标（src/core/budget_guard.py）：
    1. 预算耗尽判定（时间 / 成本 / Token 三类阈值，含"刚好相等"的边界）
    2. 耗尽副作用（BUDGET_EXHAUSTED 事件、干预日志）与两者的非致命失败
    3. 预算生命周期（extend / set_total / clear / reset / status / validate）
    4. 事件总线回调（token / cost 两种 payload 形态）
    5. 资源探测（PSI、Cgroup、Psutil 进程 RSS、健康分级、5 秒缓存）
    6. 降级路径（psutil 未安装、探测抛异常、/proc 与 /sys 不存在）

关于外部协作的边界：
    - psutil 探测的是本机真实资源（Windows 上无 PSI/Cgroup），因此验证 Linux
      分支时用 fake_linux_fs 模拟 /proc/pressure/memory 与 /sys/fs/cgroup/*
      的**文件内容**，被测的解析与分级逻辑仍是真实代码。
    - "psutil 根本装不上"用子进程 + 屏蔽 import 验证，避免 reload 污染同进程
      里已被其它模块绑定的类对象。
"""
from __future__ import annotations

import builtins
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import budget_guard as bg
from src.core.budget_guard import (
    BudgetConfig,
    BudgetGuard,
    ResourceThresholds,
    parse_budget_string,
)
from src.core.durable.surfaces.resource_state import ResourceHealthState
from src.core.events import EventType
from src.core.exceptions import ClawdError, ErrorCode

MB = 1024 * 1024
PSI_HEALTHY = (
    "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
    "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
)
CGROUP_ROOT = "/sys/fs/cgroup"


@pytest.fixture
def run_dir(tmp_path: Path) -> str:
    return str(tmp_path / "run")


@pytest.fixture
def guard(run_dir: str) -> BudgetGuard:
    return BudgetGuard(BudgetConfig(), run_dir=run_dir)


@pytest.fixture
def make_guard(run_dir: str):
    def _make(config: BudgetConfig | None = None) -> BudgetGuard:
        return BudgetGuard(config or BudgetConfig(), run_dir=run_dir)

    return _make


@pytest.fixture
def fake_linux_fs(monkeypatch):
    """把 budget_guard 看到的 /proc 与 /sys 换成内存里的一组文件。"""

    def _install(files: dict[str, str]) -> None:
        real_open = builtins.open

        def _fake_open(file, *args, **kwargs):
            key = str(file)
            if key in files:
                return io.StringIO(files[key])
            return real_open(file, *args, **kwargs)

        class _FakePath:
            def exists(self, path):
                return str(path) in files

        class _FakeOS:
            path = _FakePath()

        monkeypatch.setattr(bg, "os", _FakeOS())
        monkeypatch.setattr(bg, "platform", SimpleNamespace(system=lambda: "Linux"))
        monkeypatch.setattr(builtins, "open", _fake_open)

    return _install


def intervention_events(guard: BudgetGuard) -> list[dict]:
    """读取该 guard 的干预日志（真实落盘文件）。"""
    path = Path(guard.intervention_logger.log_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ===== 1. 预算是如何被判定的 =====


class TestBudgetExhaustion:
    def test_time_limit_triggers_at_exact_boundary(self, make_guard, monkeypatch, clean_event_bus):
        g = make_guard(BudgetConfig(max_duration_seconds=100))
        monkeypatch.setattr(bg, "time", SimpleNamespace(time=lambda: 1000.0))
        g.start_time = 900.0  # 恰好用满 100 秒

        assert g.check() is True
        assert g.is_exhausted is True
        assert "时间超限" in g.exhaustion_reason
        assert "100.0s >= 100s" in g.exhaustion_reason

    def test_time_limit_not_triggered_one_second_before(self, make_guard, monkeypatch):
        g = make_guard(BudgetConfig(max_duration_seconds=100))
        monkeypatch.setattr(bg, "time", SimpleNamespace(time=lambda: 1000.0))
        g.start_time = 901.0  # 99 秒

        assert g.check() is False
        assert g.is_exhausted is False

    def test_time_limit_ignored_without_start_time(self, make_guard, monkeypatch):
        g = make_guard(BudgetConfig(max_duration_seconds=1))
        monkeypatch.setattr(bg, "time", SimpleNamespace(time=lambda: 10_000.0))

        assert g.check() is False  # 未 start 不计时

    def test_cost_limit_is_strictly_greater_than(self, make_guard, clean_event_bus):
        """成本阈值用 `>`：正好等于上限仍允许继续。"""
        g = make_guard(BudgetConfig(max_cost_usd=1.0))

        g.record_usage(cost=1.0)
        assert g.is_exhausted is False

        g.record_usage(cost=0.0001)
        assert g.is_exhausted is True
        assert "成本超限" in g.exhaustion_reason

    def test_token_limit_triggers_on_equal(self, make_guard, clean_event_bus):
        """Token 阈值用 `>=`：正好等于上限即熔断（与成本阈值口径不同，此处锁定现状）。"""
        g = make_guard(BudgetConfig(max_tokens=100))

        g.record_usage(tokens=99)
        assert g.is_exhausted is False

        g.record_usage(tokens=1)
        assert g.is_exhausted is True
        assert "Token 超限 (100 >= 100)" in g.exhaustion_reason

    def test_last_violation_wins(self, make_guard, monkeypatch, clean_event_bus):
        """三类都超限时，原因取最后判定的那一类（顺序: 时间 → 成本 → Token）。"""
        g = make_guard(BudgetConfig(max_duration_seconds=1, max_cost_usd=1.0, max_tokens=10))
        monkeypatch.setattr(bg, "time", SimpleNamespace(time=lambda: 1000.0))
        g.start_time = 800.0

        g.record_usage(cost=5.0, tokens=50)

        assert g.is_exhausted is True
        assert g.exhaustion_reason.startswith("Token 超限")

    def test_check_short_circuits_when_already_exhausted(self, make_guard, monkeypatch, clean_event_bus):
        g = make_guard(BudgetConfig(max_tokens=10))
        g.record_usage(tokens=10)
        reason = g.exhaustion_reason

        # 即使此刻时间已经超限，也不应改写原因（check 第一行就返回 True）
        monkeypatch.setattr(bg, "time", SimpleNamespace(time=lambda: 10_000.0))
        g.start_time = 1.0
        assert g.check() is True
        assert g.exhaustion_reason == reason

    def test_no_limits_never_exhausts(self, make_guard):
        g = make_guard()
        g.record_usage(cost=1000.0, tokens=10**9)
        assert g.is_exhausted is False
        assert g.check() is False

    def test_zero_limits_are_treated_as_unset(self, make_guard):
        """`0` 是 falsy：max_tokens=0 不会让任务立刻熔断。"""
        g = make_guard(BudgetConfig(max_tokens=0, max_cost_usd=0.0, max_duration_seconds=0))
        g.record_usage(cost=5.0, tokens=100)
        assert g.is_exhausted is False


class TestExhaustionSideEffects:
    def test_publishes_budget_exhausted_event(self, make_guard, clean_event_bus):
        received: list = []
        clean_event_bus.subscribe(EventType.BUDGET_EXHAUSTED, received.append)
        g = make_guard(BudgetConfig(max_tokens=5))

        g.record_usage(tokens=5)

        assert len(received) == 1
        assert "reason" in received[0].data

    def test_writes_intervention_log_entry(self, make_guard, clean_event_bus):
        g = make_guard(BudgetConfig(max_tokens=5))
        g.record_usage(tokens=5)

        events = intervention_events(g)
        assert len(events) == 1
        assert events[0]["kind"] == "budget_exhausted"
        assert events[0]["source"] == "guard"
        assert "Token 超限" in events[0]["message"]

    def test_publish_failure_is_non_fatal(self, make_guard, monkeypatch, caplog):
        g = make_guard(BudgetConfig(max_tokens=5))

        def _boom():
            raise RuntimeError("event bus down")

        monkeypatch.setattr(bg, "get_event_bus", _boom)

        g.record_usage(tokens=5)

        assert g.is_exhausted is True  # 事件发布失败不影响熔断结论
        assert "发布预算耗尽事件失败" in caplog.text

    def test_intervention_log_failure_is_non_fatal(self, make_guard, monkeypatch, caplog, clean_event_bus):
        g = make_guard(BudgetConfig(max_tokens=5))

        def _boom(**kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(g.intervention_logger, "record", _boom)

        g.record_usage(tokens=5)

        assert g.is_exhausted is True
        assert "写入预算耗尽干预日志失败" in caplog.text


# ===== 2. 预算生命周期 =====


class TestBudgetLifecycle:
    def test_extend_adds_to_existing_limits(self, make_guard, clean_event_bus):
        g = make_guard(BudgetConfig(max_duration_seconds=10, max_cost_usd=1.0, max_tokens=100))
        g.record_usage(tokens=100)
        assert g.is_exhausted is True

        g.extend_budget(duration_seconds=5, cost_usd=0.5, tokens=50)

        assert g.config.max_duration_seconds == 15
        assert g.config.max_cost_usd == pytest.approx(1.5)
        assert g.config.max_tokens == 150
        assert g.is_exhausted is False  # 扩展后解除熔断
        assert g.exhaustion_reason == ""

    def test_extend_sets_limit_when_absent(self, make_guard):
        g = make_guard()

        g.extend_budget(duration_seconds=60, cost_usd=2.0, tokens=500)

        assert g.config.max_duration_seconds == 60
        assert g.config.max_cost_usd == pytest.approx(2.0)
        assert g.config.max_tokens == 500

    def test_extend_with_zeroes_keeps_limits(self, make_guard):
        g = make_guard(BudgetConfig(max_tokens=100))

        g.extend_budget()

        assert g.config.max_tokens == 100
        assert g.config.max_duration_seconds is None
        assert g.config.max_cost_usd is None
        assert intervention_events(g)[-1]["kind"] == "budget_extend"

    def test_set_total_budget_only_touches_given_fields(self, make_guard):
        g = make_guard(BudgetConfig(max_duration_seconds=10, max_cost_usd=1.0, max_tokens=100))

        g.set_total_budget(duration_seconds=120, cost_usd=3.0)

        assert g.config.max_duration_seconds == 120
        assert g.config.max_cost_usd == pytest.approx(3.0)
        assert g.config.max_tokens == 100
        assert intervention_events(g)[-1]["kind"] == "budget_set_total"

    def test_set_total_budget_tokens_only(self, make_guard):
        g = make_guard(BudgetConfig(max_duration_seconds=10))

        g.set_total_budget(tokens=42)

        assert g.config.max_tokens == 42
        assert g.config.max_duration_seconds == 10

    def test_set_total_budget_accepts_explicit_zero(self, make_guard):
        """`set_total_budget` 用 `is not None` 判断，因此 0 也会被写入（与 extend 不同）。"""
        g = make_guard(BudgetConfig(max_tokens=100))

        g.set_total_budget(tokens=0)

        assert g.config.max_tokens == 0

    def test_clear_budget_removes_all_limits(self, make_guard, clean_event_bus):
        g = make_guard(BudgetConfig(max_duration_seconds=10, max_cost_usd=1.0, max_tokens=10))
        g.record_usage(tokens=10)

        g.clear_budget()

        assert g.config.max_duration_seconds is None
        assert g.config.max_cost_usd is None
        assert g.config.max_tokens is None
        assert g.is_exhausted is False
        assert g.check() is False
        assert intervention_events(g)[-1]["kind"] == "budget_clear"

    def test_reset_for_run_keeps_config_and_allows_recheck(self, make_guard, clean_event_bus):
        g = make_guard(BudgetConfig(max_tokens=10))
        g.start_time = 123.0
        g.record_usage(tokens=10)

        g.reset_for_run()

        assert g.start_time is None
        assert g.accumulated_tokens == 0
        assert g.is_exhausted is False
        assert g.config.max_tokens == 10  # 配置保留
        g.record_usage(tokens=10)
        assert g.is_exhausted is True  # 复位后仍能重新判定

    def test_get_status_reports_usage_and_limits(self, make_guard, monkeypatch):
        g = make_guard(BudgetConfig(max_duration_seconds=60, max_cost_usd=2.0, max_tokens=1000))

        assert g.get_status()["usage"]["elapsed_seconds"] == 0.0

        g.start_time = 1000.0
        monkeypatch.setattr(bg, "time", SimpleNamespace(time=lambda: 1012.34))
        g.record_usage(cost=0.1234567, tokens=77)

        status = g.get_status()
        assert status["exhausted"] is False
        assert status["usage"]["elapsed_seconds"] == 12.3
        assert status["usage"]["cost_usd"] == pytest.approx(0.123457)
        assert status["usage"]["tokens"] == 77
        assert status["limits"] == {"duration": 60, "cost": 2.0, "tokens": 1000}

    def test_validate_raises_structured_error_when_exhausted(self, make_guard, clean_event_bus):
        g = make_guard(BudgetConfig(max_tokens=10))
        g.record_usage(tokens=10)

        with pytest.raises(ClawdError) as excinfo:
            g.validate()

        assert excinfo.value.code == ErrorCode.TOKEN_LIMIT_EXCEEDED
        assert excinfo.value.recoverable is False
        assert excinfo.value.details["budget_reason"] == g.exhaustion_reason

    def test_validate_is_noop_within_budget(self, make_guard):
        g = make_guard(BudgetConfig(max_tokens=10))
        g.record_usage(tokens=9)
        g.validate()  # 不抛异常


# ===== 3. 启动与事件订阅 =====


class _RecordingBus:
    def __init__(self, fail_on: EventType | None = None):
        self.subscriptions: list[EventType] = []
        self.published: list = []
        self._fail_on = fail_on

    def subscribe(self, event_type, handler):
        if event_type == self._fail_on:
            raise RuntimeError("subscribe failed")
        self.subscriptions.append(event_type)

    def publish(self, event):
        self.published.append(event)


class TestStartAndHandlers:
    def test_start_subscribes_three_events_and_sets_start_time(self, make_guard, monkeypatch):
        bus = _RecordingBus()
        monkeypatch.setattr(bg, "get_event_bus", lambda: bus)
        g = make_guard(BudgetConfig(max_tokens=10))

        g.start()

        assert g.start_time is not None
        assert bus.subscriptions == [
            EventType.COST_RECORDED,
            EventType.AGENT_COST_UPDATE,
            EventType.AGENT_TOKEN_USAGE,
        ]

    def test_start_is_idempotent(self, make_guard, monkeypatch):
        bus = _RecordingBus()
        monkeypatch.setattr(bg, "get_event_bus", lambda: bus)
        g = make_guard()

        g.start()
        first_start = g.start_time
        g.start()

        assert g.start_time == first_start
        assert len(bus.subscriptions) == 3  # 未重复订阅

    def test_start_raises_when_subscription_fails(self, make_guard, monkeypatch):
        bus = _RecordingBus(fail_on=EventType.AGENT_TOKEN_USAGE)
        monkeypatch.setattr(bg, "get_event_bus", lambda: bus)
        g = make_guard()

        with pytest.raises(RuntimeError, match="预算守卫初始化失败"):
            g.start()

    def test_on_token_event_reads_tokens_field(self, make_guard, monkeypatch):
        monkeypatch.setattr(bg, "get_event_bus", lambda: _RecordingBus())
        g = make_guard(BudgetConfig(max_tokens=10))

        g._on_token_event(SimpleNamespace(data={"tokens": 4}))
        assert g.accumulated_tokens == 4

    def test_on_token_event_falls_back_to_usage_total_tokens(self, make_guard, monkeypatch):
        monkeypatch.setattr(bg, "get_event_bus", lambda: _RecordingBus())
        g = make_guard(BudgetConfig(max_tokens=10))

        g._on_token_event(SimpleNamespace(data={"usage": {"total_tokens": 7}}))
        assert g.accumulated_tokens == 7

    def test_on_token_event_ignores_missing_payload(self, make_guard, monkeypatch):
        monkeypatch.setattr(bg, "get_event_bus", lambda: _RecordingBus())
        g = make_guard(BudgetConfig(max_tokens=10))

        g._on_token_event(SimpleNamespace(data={}))

        assert g.accumulated_tokens == 0
        assert g.is_exhausted is False

    def test_on_cost_event_records_cost_and_tokens(self, make_guard, monkeypatch):
        bus = _RecordingBus()
        monkeypatch.setattr(bg, "get_event_bus", lambda: bus)
        g = make_guard(BudgetConfig(max_cost_usd=1.0))

        g._on_cost_event(SimpleNamespace(data={"cost": 0.25, "tokens": 30}))

        assert g.accumulated_cost == pytest.approx(0.25)
        assert g.accumulated_tokens == 30


# ===== 4. 预算字符串解析 =====


class TestParseBudgetString:
    @pytest.mark.parametrize(
        ("raw", "duration", "cost", "tokens"),
        [
            ("1h", 3600, None, None),
            ("90m", 5400, None, None),
            ("10usd", None, 10.0, None),
            ("0.5USD", None, 0.5, None),
            ("8000t", None, None, 8000),
            ("8000T", None, None, 8000),
            ("1h 10usd 500t", 3600, 10.0, 500),
        ],
    )
    def test_parses_units(self, raw, duration, cost, tokens):
        config = parse_budget_string(raw)

        assert config.max_duration_seconds == duration
        assert config.max_cost_usd == cost
        assert config.max_tokens == tokens

    def test_empty_string_yields_no_limits(self):
        config = parse_budget_string("")
        assert config.max_duration_seconds is None
        assert config.max_cost_usd is None
        assert config.max_tokens is None

    def test_unrecognized_string_yields_no_limits(self):
        config = parse_budget_string("unlimited please")
        assert config.max_duration_seconds is None
        assert config.max_cost_usd is None
        assert config.max_tokens is None

    def test_hours_win_over_minutes(self):
        """组合写法 '1h30m' 只取小时部分（记录现状，不视为缺陷：CLI 只承诺单单位）。"""
        config = parse_budget_string("1h30m")
        assert config.max_duration_seconds == 3600

    def test_parsed_config_keeps_default_thresholds(self):
        config = parse_budget_string("1h")
        assert isinstance(config.resource_thresholds, ResourceThresholds)
        assert config.resource_thresholds.memory_percent_max == 90.0


# ===== 5. 资源探测 =====


class TestResourceStateProbe:
    def test_probes_host_and_process_on_real_machine(self, make_guard):
        g = make_guard()

        state = g.get_resource_state()

        assert isinstance(state.state, ResourceHealthState)
        assert state.host.mem_total_bytes > 0
        assert state.goalx_processes.master_rss_bytes > 0
        assert state.headroom_bytes > 0
        # 探测成功后写入缓存
        assert g._cached_resource_state is not None
        assert g._last_resource_check > 0

    def test_second_call_hits_cache(self, make_guard, monkeypatch):
        g = make_guard()
        first = g.get_resource_state()
        last_check = g._last_resource_check

        def _must_not_be_called():
            raise AssertionError("缓存命中时不应再次探测 psutil")

        monkeypatch.setattr(bg.psutil, "virtual_memory", _must_not_be_called)
        second = g.get_resource_state()

        assert second.state == first.state
        assert second.host.mem_total_bytes == first.host.mem_total_bytes
        assert g._last_resource_check == last_check

    def test_cache_expires_after_interval(self, make_guard, monkeypatch):
        g = make_guard()
        g.get_resource_state()
        previous_check = g._last_resource_check

        later = previous_check + g._resource_check_interval + 1

        def _boom():
            raise OSError("probe failed")

        monkeypatch.setattr(bg, "time", SimpleNamespace(time=lambda: later))
        monkeypatch.setattr(bg.psutil, "virtual_memory", _boom)

        state = g.get_resource_state()

        # 缓存过期后重新探测，探测失败 → UNKNOWN，且失败不会刷新缓存时间戳
        assert state.state is ResourceHealthState.UNKNOWN
        assert g._last_resource_check == previous_check

    def test_probe_failure_yields_unknown_but_stays_permissive(self, make_guard, monkeypatch, caplog):
        g = make_guard()

        def _boom():
            raise OSError("no such device")

        monkeypatch.setattr(bg.psutil, "virtual_memory", _boom)

        state = g.get_resource_state()

        assert state.state is ResourceHealthState.UNKNOWN
        assert any("no such device" in reason for reason in state.reasons)
        assert "获取资源状态失败" in caplog.text

        ok, reason = g.check_resource_pressure()
        assert ok is True  # 无法判定时默认放行
        assert reason == "resource monitoring unavailable"

        can, can_reason = g.can_execute()
        assert can is True
        assert can_reason == "ready to execute"

    def test_psutil_unavailable_marks_unknown_and_skips_cache(self, make_guard, monkeypatch, caplog):
        g = make_guard()
        monkeypatch.setattr(bg, "PSUTIL_AVAILABLE", False)

        state = g.get_resource_state()

        assert state.state is ResourceHealthState.UNKNOWN
        assert state.reasons == ["psutil not installed"]
        assert g._cached_resource_state is None  # 降级路径不写缓存

        ok, reason = g.check_resource_pressure()
        assert ok is True
        assert reason == "resource monitoring unavailable"
        assert "资源状态未知" in caplog.text

    def test_module_starts_without_psutil_installed(self, tmp_path):
        """真实 ImportError 路径：在子进程里屏蔽 psutil 导入后模块仍可加载。"""
        repo_root = Path(__file__).resolve().parents[2]
        script = "\n".join(
            [
                "import builtins",
                "real_import = builtins.__import__",
                "def blocked(name, *args, **kwargs):",
                "    if name == 'psutil':",
                "        raise ImportError('psutil absent')",
                "    return real_import(name, *args, **kwargs)",
                "builtins.__import__ = blocked",
                "from src.core.budget_guard import PSUTIL_AVAILABLE, BudgetConfig, BudgetGuard",
                f"guard = BudgetGuard(BudgetConfig(), run_dir=r'{tmp_path}')",
                "state = guard.get_resource_state()",
                "print('AVAILABLE', PSUTIL_AVAILABLE)",
                "print('STATE', state.state.value, state.reasons)",
                "print('PRESSURE', guard.check_resource_pressure())",
            ]
        )

        # 必须显式 utf-8：Windows 默认 GBK，子进程输出的中文会让
        # `_readerthread` 抛 UnicodeDecodeError（PytestUnhandledThreadExceptionWarning）。
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )

        assert result.returncode == 0, result.stderr
        assert "AVAILABLE False" in result.stdout
        assert "STATE unknown ['psutil not installed']" in result.stdout
        assert "PRESSURE (True, 'resource monitoring unavailable')" in result.stdout

    def test_probe_without_linux_pseudo_fs(self, make_guard):
        """本机（Windows）无 /proc/pressure 与 /sys/fs/cgroup → PSI/Cgroup 保持零值。"""
        g = make_guard()

        state = g.get_resource_state()

        assert state.psi.memory_some.avg10 == 0.0
        assert state.psi.memory_full.avg10 == 0.0
        assert state.cgroup.memory_max_bytes == 0
        assert state.cgroup.events.has_oom() is False


# ===== 6. PSI / Cgroup 阈值分级 =====


class TestPsiThresholds:
    def test_psi_full_critical_blocks_execution(self, make_guard, fake_linux_fs):
        fake_linux_fs(
            {
                "/proc/pressure/memory": (
                    "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
                    "full avg10=45.00 avg60=0.00 avg300=0.00 total=0\n"
                )
            }
        )
        g = make_guard()

        state = g.get_resource_state()

        assert state.state is ResourceHealthState.CRITICAL
        assert any("PSI memory_full avg10 critical" in r for r in state.reasons)

        ok, reason = g.check_resource_pressure()
        assert ok is False
        assert reason.startswith("CRITICAL:")

        can, can_reason = g.can_execute()
        assert can is False
        assert can_reason.startswith("resource pressure unsafe: CRITICAL:")

    def test_psi_some_tight_does_not_block(self, make_guard, fake_linux_fs):
        """TIGHT（紧张）不等于拒绝：只有 CRITICAL 才会让 can_execute 返回 False。"""
        fake_linux_fs(
            {
                "/proc/pressure/memory": (
                    "some avg10=40.00 avg60=0.00 avg300=0.00 total=0\n"
                    "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
                )
            }
        )
        g = make_guard()

        state = g.get_resource_state()

        assert state.state is ResourceHealthState.TIGHT
        assert any("PSI memory_some avg10 tight" in r for r in state.reasons)
        assert g.check_resource_pressure() == (True, "resource pressure normal")
        assert g.can_execute() == (True, "ready to execute")

    def test_psi_at_exact_critical_threshold_is_not_critical(self, make_guard, fake_linux_fs):
        """阈值用严格大于：avg10 正好等于 30（full 的 critical 阈值）仍是 tight。"""
        fake_linux_fs(
            {
                "/proc/pressure/memory": (
                    "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
                    "full avg10=30.00 avg60=0.00 avg300=0.00 total=0\n"
                )
            }
        )
        g = make_guard()

        state = g.get_resource_state()

        assert state.state is ResourceHealthState.TIGHT
        assert any("tight" in r for r in state.reasons)

    def test_unparsable_psi_content_is_tolerated(self, make_guard, fake_linux_fs, caplog):
        """PSI 内容损坏时只记警告，不中断资源探测。"""
        fake_linux_fs({"/proc/pressure/memory": "some avg10=not_a_number\n"})
        g = make_guard()

        state = g.get_resource_state()

        assert "读取 PSI 数据失败" in caplog.text
        assert state.psi.memory_some.avg10 == 0.0  # 解析失败时保持默认零值
        assert state.state is ResourceHealthState.HEALTHY  # 仍给出判定而非 UNKNOWN

    def test_healthy_psi_reports_no_reasons(self, make_guard, fake_linux_fs):
        fake_linux_fs({"/proc/pressure/memory": PSI_HEALTHY})
        g = make_guard()

        state = g.get_resource_state()

        assert state.state is ResourceHealthState.HEALTHY
        assert state.reasons == []


class TestCgroupThresholds:
    def test_cgroup_usage_critical(self, make_guard, fake_linux_fs):
        fake_linux_fs(
            {
                f"{CGROUP_ROOT}/memory.current": str(950 * MB),
                f"{CGROUP_ROOT}/memory.max": str(1000 * MB),
            }
        )
        g = make_guard()

        state = g.get_resource_state()

        assert state.cgroup.memory_max_bytes == 1000 * MB
        assert state.cgroup.usage_ratio() == pytest.approx(0.95)
        assert state.state is ResourceHealthState.CRITICAL
        assert any("Cgroup usage critical" in r for r in state.reasons)
        # headroom 被 cgroup 剩余量（50MB < 128MB）压低
        assert state.headroom_bytes == 50 * MB
        assert any("Headroom critical" in r for r in state.reasons)

    def test_cgroup_memory_max_equals_literal_max(self, make_guard, fake_linux_fs):
        """`memory.max` 内容为 'max' 表示无限制 → 解析为 0，usage_ratio 为 0。"""
        fake_linux_fs(
            {
                f"{CGROUP_ROOT}/memory.current": str(100 * MB),
                f"{CGROUP_ROOT}/memory.max": "max\n",
                f"{CGROUP_ROOT}/memory.high": "max\n",
            }
        )
        g = make_guard()

        state = g.get_resource_state()

        assert state.cgroup.memory_max_bytes == 0
        assert state.cgroup.memory_high_bytes == 0
        assert state.cgroup.usage_ratio() == 0.0
        assert state.state is ResourceHealthState.HEALTHY

    def test_cgroup_oom_events_force_critical(self, make_guard, fake_linux_fs):
        fake_linux_fs(
            {
                f"{CGROUP_ROOT}/memory.current": str(10 * MB),
                f"{CGROUP_ROOT}/memory.max": str(1000 * MB),
                f"{CGROUP_ROOT}/memory.events": (
                    "low 0\nhigh 3\nmax 1\noom 1\noom_kill 0\n"
                ),
            }
        )
        g = make_guard()

        state = g.get_resource_state()

        assert state.cgroup.events.has_oom() is True
        assert state.state is ResourceHealthState.CRITICAL
        assert state.reasons == ["OOM events detected: immediate action required"]
        assert g.check_resource_pressure()[0] is False

    def test_cgroup_events_skip_unknown_keys_and_malformed_lines(self, make_guard, fake_linux_fs):
        """memory.events 里出现未知 key 或字段数不足时只跳过，不影响已知计数。"""
        fake_linux_fs(
            {
                f"{CGROUP_ROOT}/memory.current": str(10 * MB),
                f"{CGROUP_ROOT}/memory.max": str(1000 * MB),
                f"{CGROUP_ROOT}/memory.events": "low 2\nswap 1\nsingle\noom 1\n",
            }
        )
        g = make_guard()

        state = g.get_resource_state()

        assert state.cgroup.events.low == 2
        assert state.cgroup.events.high == 0
        assert state.cgroup.events.oom == 1
        assert state.cgroup.events.has_oom() is True

    def test_probe_cgroup_info_without_pseudo_fs(self, guard):
        """真实路径：/sys/fs/cgroup 不存在时全部归零，不抛异常。"""
        limits = guard._probe_cgroup_info()

        assert limits.memory_current_bytes == 0
        assert limits.memory_max_bytes == 0
        assert limits.events.to_dict() == {"low": 0, "high": 0, "max": 0, "oom": 0, "oom_kill": 0}


# ===== 7. PSI 文本解析 =====


class TestParsePsiData:
    def test_parses_some_and_full_lines(self, guard):
        data = (
            "some avg10=1.50 avg60=0.20 avg300=0.10 total=99\n"
            "full avg10=2.50 avg60=0.30 avg300=0.20 total=88\n"
        )

        psi = guard._parse_psi_data(data)

        assert psi.memory_some.avg10 == 1.5
        assert psi.memory_some.avg60 == 0.2
        assert psi.memory_some.avg300 == 0.1
        assert psi.memory_full.avg10 == 2.5
        assert psi.memory_full.avg60 == 0.3

    def test_missing_fields_default_to_zero(self, guard):
        psi = guard._parse_psi_data("some avg10=5.00")

        assert psi.memory_some.avg10 == 5.0
        assert psi.memory_some.avg60 == 0.0
        assert psi.memory_full.avg10 == 0.0

    def test_empty_content_returns_zeroed_data(self, guard):
        psi = guard._parse_psi_data("")

        assert psi.to_dict() == {
            "memory_some_avg10": 0.0,
            "memory_some_avg60": 0.0,
            "memory_some_avg300": 0.0,
            "memory_full_avg10": 0.0,
            "memory_full_avg60": 0.0,
            "memory_full_avg300": 0.0,
        }

    def test_unknown_labels_and_blank_lines_are_skipped(self, guard):
        psi = guard._parse_psi_data("\n\nother avg10=9.99\n  \nsome avg10=1.00\n")

        assert psi.memory_some.avg10 == 1.0
        assert psi.memory_full.avg10 == 0.0

    def test_tokens_without_equals_are_skipped(self, guard):
        """PSI 行里混入无法解析的裸 token 时只跳过该 token。"""
        psi = guard._parse_psi_data("some avg10=2.00 stray avg60=1.00\n")

        assert psi.memory_some.avg10 == 2.0
        assert psi.memory_some.avg60 == 1.0
        assert psi.memory_some.avg300 == 0.0


# ===== 8. 组合判定 =====


class TestCanExecute:
    def test_budget_exhaustion_takes_priority(self, make_guard, clean_event_bus):
        g = make_guard(BudgetConfig(max_tokens=1))
        g.record_usage(tokens=1)

        can, reason = g.can_execute()

        assert can is False
        assert reason.startswith("budget exhausted: Token 超限")


def test_thresholds_dataclass_defaults():
    """ResourceThresholds 是公开配置对象；当前 guard 未消费这些字段（见交付报告）。"""
    thresholds = ResourceThresholds()

    assert thresholds.memory_percent_max == 90.0
    assert thresholds.cpu_percent_max == 95.0
    assert thresholds.disk_percent_max == 95.0


def test_dataclass_instances_are_independent():
    first = BudgetConfig()
    second = BudgetConfig()
    first.resource_thresholds.memory_percent_max = 10.0

    assert second.resource_thresholds.memory_percent_max == 90.0


def test_module_exposes_psutil_flag():
    assert isinstance(bg.PSUTIL_AVAILABLE, bool)
    assert bg.psutil is not None or bg.PSUTIL_AVAILABLE is False

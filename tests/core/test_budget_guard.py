from __future__ import annotations

import time
from unittest.mock import Mock

import pytest

from src.core.budget_guard import BudgetConfig, BudgetGuard
from src.core.events import EventType


class TestBudgetGuardStart:
    def test_start_raises_when_subscription_fails(self, monkeypatch):
        bus = Mock()

        def fail_on_second_subscribe(event_type, _handler):
            if event_type == EventType.AGENT_COST_UPDATE:
                raise RuntimeError("boom")

        bus.subscribe.side_effect = fail_on_second_subscribe
        monkeypatch.setattr("src.core.budget_guard.get_event_bus", lambda: bus)

        guard = BudgetGuard(BudgetConfig(max_tokens=1000), run_dir="test-run")

        with pytest.raises(RuntimeError, match="预算守卫初始化失败"):
            guard.start()

    def test_start_subscribes_all_budget_events(self, monkeypatch):
        bus = Mock()
        monkeypatch.setattr("src.core.budget_guard.get_event_bus", lambda: bus)

        guard = BudgetGuard(BudgetConfig(max_tokens=1000), run_dir="test-run")
        guard.start()

        subscribed_events = [call.args[0] for call in bus.subscribe.call_args_list]
        assert EventType.COST_RECORDED in subscribed_events
        assert EventType.AGENT_COST_UPDATE in subscribed_events
        assert EventType.AGENT_TOKEN_USAGE in subscribed_events
        assert len(subscribed_events) == 3


class TestResetForRun:
    """同一 guard 跨轮复用必须复位运行期状态。

    `WorkflowEngine.run()` 为保留调用方注入的配置/替身，改为复用同一个
    BudgetGuard；但 `start()` 在 start_time 非空时是空操作，`check()` 一旦
    is_exhausted 为真立即返回 True —— 不复位就会让第二次 run() 继承上一轮
    的消耗并直接判定耗尽（实测复现）。
    """

    def test_reset_clears_runtime_state(self):
        from src.core.budget_guard import BudgetConfig, BudgetGuard

        g = BudgetGuard(BudgetConfig(max_cost_usd=1.0))
        g.record_usage(cost=2.0)
        g.start()

        assert g.accumulated_cost == 2.0
        assert g.is_exhausted is True

        g.reset_for_run()

        assert g.accumulated_cost == 0.0
        assert g.accumulated_tokens == 0
        assert g.is_exhausted is False
        assert g.start_time is None
        assert g.exhaustion_reason == ""
        # 配置不被清除
        assert g.config.max_cost_usd == 1.0

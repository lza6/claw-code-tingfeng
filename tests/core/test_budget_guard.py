from __future__ import annotations

from unittest.mock import Mock

import pytest

import time

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

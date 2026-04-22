#!/usr/bin/env python3
"""Integration verification - Verify integrated modules work"""

from __future__ import annotations

import sys


def test_notification_events() -> bool:
    """Verify notification event count"""
    try:
        from src.notification.types import NotificationEvent
        count = len(NotificationEvent)
        expected = 38
        if count == expected:
            print(f"[OK] NotificationEvent: {count} events")
            return True
        else:
            print(f"[FAIL] NotificationEvent: {count} events (expected {expected})")
            return False
    except Exception as e:
        print(f"[FAIL] NotificationEvent import: {e}")
        return False


def test_worktree_manager() -> bool:
    """Verify WorktreeManager can be instantiated"""
    try:
        from src.agent.swarm.worktree_manager import WorktreeManager
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            mgr = WorktreeManager(base_dir=tmp)
            print(f"[OK] WorktreeManager instantiated")
            return True
    except Exception as e:
        print(f"[FAIL] WorktreeManager: {e}")
        return False


def test_mode_config() -> bool:
    """Verify ModeConfigRouter can be instantiated"""
    try:
        from src.core.config.mode_config import ModeConfigRouter
        router = ModeConfigRouter()
        print(f"[OK] ModeConfigRouter instantiated")
        return True
    except Exception as e:
        print(f"[FAIL] ModeConfigRouter: {e}")
        return False


def test_team_exec_stage() -> bool:
    """Verify TeamExecStage class can be imported"""
    try:
        from src.workflow.stages.team_exec_stage import TeamExecStage, TeamExecConfig
        config = TeamExecConfig(worker_count=2)
        stage = TeamExecStage(config)
        print(f"[OK] TeamExecStage: name={stage.name}")
        return True
    except Exception as e:
        print(f"[FAIL] TeamExecStage: {e}")
        return False


def test_hook_events() -> bool:
    """Verify HookPoint enum expansion"""
    try:
        from src.core.hook_registry.enums import HookPoint
        count = len(HookPoint)
        if count >= 35:
            print(f"[OK] HookPoint: {count} events")
            return True
        else:
            print(f"[FAIL] HookPoint: {count} events (< 35)")
            return False
    except Exception as e:
        print(f"[FAIL] HookPoint: {e}")
        return False


def main() -> int:
    print("=" * 50)
    print("Integration Verification")
    print("=" * 50)

    checks = [
        test_notification_events,
        test_worktree_manager,
        test_mode_config,
        test_team_exec_stage,
        test_hook_events,
    ]

    results = [check() for check in checks]
    passed = sum(results)
    total = len(results)

    print(f"\nResults: {passed}/{total} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
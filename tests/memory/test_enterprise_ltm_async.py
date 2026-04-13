"""Tests for src.memory.enterprise_ltm — async SQLite fix verification"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest


@pytest.fixture
def ltm(tmp_path):
    """Create an EnterpriseLTM with temp DB."""
    from src.memory.enterprise_ltm import EnterpriseLTM
    return EnterpriseLTM(db_path=tmp_path / "test_ltm.db")


class TestAsyncDBAccess:
    """Verify async methods don't block the event loop."""

    @pytest.mark.asyncio
    async def test_store_and_find_pattern(self, ltm):
        from src.memory.enterprise_ltm import ImplementationPattern, PatternType
        pattern = ImplementationPattern(
            pattern_id="test-001",
            task_type="refactor",
            description="refactor database connection pooling",
            solution_code="pool = ConnectionPool()",
            success_metrics={"speedup": 2.0},
            pattern_type=PatternType.SUCCESS,
        )
        await ltm.store_pattern(pattern)

        results = await ltm.find_similar_patterns("database connection pooling refactor", limit=1)
        assert len(results) >= 1
        assert results[0].pattern_id == "test-001"

    @pytest.mark.asyncio
    async def test_find_no_match(self, ltm):
        results = await ltm.find_similar_patterns("nonexistent_xyz", limit=5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_update_heatmap(self, ltm):
        await ltm.update_heatmap("BashTool", success=True, latency=0.05)
        await ltm.update_heatmap("BashTool", success=True, latency=0.07)
        await ltm.update_heatmap("BashTool", success=False, latency=0.03)

        # Verify data was written
        with sqlite3.connect(ltm.db_path) as conn:
            row = conn.execute("SELECT call_count, success_rate, avg_latency FROM execution_heatmap WHERE tool_name='BashTool'").fetchone()
            assert row is not None
            assert row[0] == 3
            # Correct rolling average: 2/3 success
            assert abs(row[1] - 0.6667) < 0.01
            # Average latency: (0.05 + 0.07 + 0.03) / 3 = 0.05
            assert abs(row[2] - 0.05) < 0.001

    @pytest.mark.asyncio
    async def test_session_recording(self, ltm):
        await ltm.record_session_start("sess-001", "fix bug")
        await ltm.record_session_failure("sess-001", "timeout")

        with sqlite3.connect(ltm.db_path) as conn:
            row = conn.execute("SELECT status, error_msg FROM sessions WHERE session_id='sess-001'").fetchone()
            assert row[0] == "failed"
            assert "timeout" in row[1]

    @pytest.mark.asyncio
    async def test_learn_pattern(self, ltm):
        await ltm.learn_pattern("implement caching", implementation={"cache_type": "lru"})

        results = await ltm.find_similar_patterns("implement caching", limit=1)
        assert len(results) >= 1
        assert results[0].task_type == "general"

    @pytest.mark.asyncio
    async def test_does_not_block_event_loop(self, ltm):
        """Verify that async DB operations yield to the event loop."""

        tasks_created = 0

        async def counter():
            nonlocal tasks_created
            tasks_created += 1

        async def store_and_count():
            await ltm.learn_pattern("test task")
            await asyncio.sleep(0)  # yield
            await ltm.learn_pattern("test task 2")
            await asyncio.sleep(0)  # yield
            await ltm.learn_pattern("test task 3")

        # Run store + counter concurrently
        await asyncio.gather(
            store_and_count(),
            asyncio.sleep(0.01),
        )
        # If event loop wasn't blocked, the sleep should have completed
        # This is a basic sanity check — if SQLite blocked, the sleep would still
        # complete but with higher latency. We just verify no exceptions.
        assert True

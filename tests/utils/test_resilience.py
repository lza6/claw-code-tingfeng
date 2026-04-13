"""Tests for src/utils/resilience.py - Retry decorators with exponential backoff."""
import asyncio

import pytest

from src.utils.resilience import async_retry, sync_retry


class TestAsyncRetry:
    """Tests for async_retry decorator."""

    @pytest.mark.asyncio
    async def test_async_retry_success_first_try(self):
        """Test that successful function returns immediately."""
        call_count = 0

        @async_retry(retries=3, base_delay=0.01)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await succeed()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_retry_eventual_success(self):
        """Test that function succeeds after retries."""
        call_count = 0

        @async_retry(retries=3, base_delay=0.01)
        async def eventually_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "success"

        result = await eventually_succeed()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_retry_all_fail(self):
        """Test that all retries fail raises the last exception."""
        call_count = 0

        @async_retry(retries=2, base_delay=0.01)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            await always_fail()
        assert call_count == 3  # Initial + 2 retries

    @pytest.mark.asyncio
    async def test_async_retry_custom_exception(self):
        """Test that only specified exceptions trigger retry."""
        call_count = 0

        @async_retry(retries=3, base_delay=0.01, exceptions=(ValueError,))
        async def custom_exception():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TypeError("not caught")  # Different exception type
            return "success"

        # TypeError is not in exceptions tuple, so it raises immediately
        with pytest.raises(TypeError):
            await custom_exception()


class TestSyncRetry:
    """Tests for sync_retry decorator."""

    def test_sync_retry_success_first_try(self):
        """Test that successful sync function returns immediately."""
        call_count = 0

        @sync_retry(retries=3, base_delay=0.001)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "success"

        result = succeed()
        assert result == "success"
        assert call_count == 1

    def test_sync_retry_eventual_success(self):
        """Test that sync function succeeds after retries."""
        call_count = 0

        @sync_retry(retries=3, base_delay=0.001)
        def eventually_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "success"

        result = eventually_succeed()
        assert result == "success"
        assert call_count == 3

    def test_sync_retry_all_fail(self):
        """Test that all retries fail raises the last exception."""
        call_count = 0

        @sync_retry(retries=2, base_delay=0.001)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            always_fail()
        assert call_count == 3

    def test_sync_retry_custom_max_delay(self):
        """Test that max_delay is respected."""
        call_count = 0

        @sync_retry(retries=10, base_delay=1.0, max_delay=0.001)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        with pytest.raises(ValueError):
            always_fail()
        # Should stop after max_delay caps at 0.001, not exponential growth
        assert call_count > 1
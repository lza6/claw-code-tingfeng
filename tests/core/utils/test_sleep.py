"""Tests for sleep utilities."""

import asyncio
import time
import pytest
from src.core.utils.sleep import (
    sleep,
    sleep_sync,
    sleep_until,
    sleep_with_progress,
    Sleeper,
)


@pytest.mark.asyncio
async def test_sleep_basic():
    """Test basic async sleep."""
    start = time.time()
    await sleep(100)  # 100ms
    elapsed = time.time() - start
    assert 0.08 <= elapsed <= 0.15  # Allow some tolerance


@pytest.mark.asyncio
async def test_sleep_with_signal():
    """Test sleep can be interrupted."""
    signal = asyncio.Event()
    
    # Start sleep that would take 1 second
    async def sleeper():
        await sleep(1000, signal)
    
    task = asyncio.create_task(sleeper())
    
    # Wait a bit then signal
    await asyncio.sleep(0.05)
    signal.set()
    
    start = time.time()
    await task
    elapsed = time.time() - start
    
    # Should complete quickly after signal
    assert elapsed < 0.2


def test_sleep_sync():
    """Test synchronous sleep."""
    start = time.time()
    sleep_sync(100)  # 100ms
    elapsed = time.time() - start
    assert 0.08 <= elapsed <= 0.2


def test_sleep_until():
    """Test sleeping until specific time."""
    target = time.time() + 0.5  # 500ms from now
    start = time.time()
    sleep_until(target)
    elapsed = time.time() - start
    assert 0.4 <= elapsed <= 0.7


@pytest.mark.asyncio
async def test_sleep_with_progress_completes():
    """Test sleep_with_progress completes normally."""
    progress_calls = []
    
    def track_progress(elapsed, total):
        progress_calls.append((elapsed, total))
    
    result = await sleep_with_progress(
        total_ms=200,
        check_interval_ms=50,
        progress_callback=track_progress,
    )
    
    assert result is True
    assert len(progress_calls) >= 2  # Should have been called at least twice


@pytest.mark.asyncio
async def test_sleep_with_progress_interrupted():
    """Test sleep_with_progress can be interrupted."""
    stop_event = asyncio.Event()
    
    async def interrupter():
        await asyncio.sleep(0.1)
        stop_event.set()
    
    asyncio.create_task(interrupter())
    
    result = await sleep_with_progress(
        total_ms=1000,
        stop_event=stop_event,
    )
    
    assert result is False


def test_sleeper_default():
    """Test Sleeper with default settings."""
    sleeper = Sleeper()
    assert sleeper.default_ms == 1000
    assert sleeper.check_interval_ms == 100


def test_sleeper_custom():
    """Test Sleeper with custom settings."""
    sleeper = Sleeper(default_ms=500, check_interval_ms=50)
    assert sleeper.default_ms == 500
    assert sleeper.check_interval_ms == 50


@pytest.mark.asyncio
async def test_sleeper_async_sleep():
    """Test Sleeper async sleep."""
    sleeper = Sleeper(default_ms=100)
    start = time.time()
    await sleeper.sleep()
    elapsed = time.time() - start
    assert 0.05 <= elapsed <= 0.2


def test_sleeper_sync_sleep():
    """Test Sleeper sync sleep."""
    sleeper = Sleeper(default_ms=100)
    start = time.time()
    sleeper.sleep_sync()
    elapsed = time.time() - start
    assert 0.05 <= elapsed <= 0.2

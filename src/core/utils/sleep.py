"""Sleep Utilities

Provides both async and sync sleep functions with precision,
inspired by oh-my-codex's sleep.ts.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from threading import Condition

logger = logging.getLogger(__name__)


async def sleep(ms: int, signal: asyncio.Event | None = None) -> None:
    """Asynchronous sleep for specified milliseconds.
    
    Args:
        ms: Milliseconds to sleep
        signal: Optional asyncio.Event to interrupt sleep early
        
    Example:
        await sleep(1000)  # Sleep for 1 second
        await sleep(5000, interrupt_event)  # Sleep up to 5s or until event set
    """
    seconds = ms / 1000.0

    if signal is not None:
        try:
            await asyncio.wait_for(signal.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass  # Normal timeout
    else:
        await asyncio.sleep(seconds)


def sleep_sync(ms: int) -> None:
    """Synchronous sleep for specified milliseconds.
    
    Uses threading.Condition.wait() for precise timing.
    
    Args:
        ms: Milliseconds to sleep
        
    Example:
        sleep_sync(1000)  # Sleep for 1 second
    """
    seconds = ms / 1000.0

    condition = Condition()
    with condition:
        condition.wait(timeout=seconds)


def sleep_until(target_time: float) -> None:
    """Sleep until a specific epoch time.
    
    Args:
        target_time: Target time in seconds since epoch
        
    Example:
        target = time.time() + 10  # 10 seconds from now
        sleep_until(target)
    """
    now = time.time()
    remaining = target_time - now

    if remaining > 0:
        sleep_sync(int(remaining * 1000))


async def sleep_with_progress(
    total_ms: int,
    check_interval_ms: int = 100,
    progress_callback: Callable | None = None,
    stop_event: asyncio.Event | None = None,
) -> bool:
    """Sleep with progress updates and early termination.
    
    Args:
        total_ms: Total sleep duration in milliseconds
        check_interval_ms: How often to check for stop/update
        progress_callback: Called with (elapsed_ms, total_ms) periodically
        stop_event: Event that can interrupt sleep
        
    Returns:
        True if completed normally, False if interrupted
    """
    elapsed = 0
    interval_seconds = check_interval_ms / 1000.0
    total_seconds = total_ms / 1000.0

    while elapsed < total_seconds:
        if stop_event and stop_event.is_set():
            return False

        # Sleep for interval or remaining time
        remaining = total_seconds - elapsed
        sleep_time = min(interval_seconds, remaining)

        try:
            await asyncio.wait_for(
                asyncio.sleep(sleep_time),
                timeout=sleep_time + 0.1,
            )
        except asyncio.TimeoutError:
            pass

        elapsed += sleep_time

        if progress_callback:
            try:
                progress_callback(int(elapsed * 1000), total_ms)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    return True


class Sleeper:
    """Reusable sleeper with configurable behavior."""

    def __init__(
        self,
        default_ms: int = 1000,
        check_interval_ms: int = 100,
    ):
        """Initialize sleeper.
        
        Args:
            default_ms: Default sleep duration
            check_interval_ms: Check interval for interruptible sleeps
        """
        self.default_ms = default_ms
        self.check_interval_ms = check_interval_ms

    async def sleep(
        self,
        ms: int | None = None,
        signal: asyncio.Event | None = None,
    ) -> None:
        """Sleep for configured or specified duration."""
        duration = ms if ms is not None else self.default_ms
        await sleep(duration, signal)

    def sleep_sync(self, ms: int | None = None) -> None:
        """Synchronous sleep for configured or specified duration."""
        duration = ms if ms is not None else self.default_ms
        sleep_sync(duration)

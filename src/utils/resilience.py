"""Resilience Module — Enterprise High Availability

Implementation of exponential backoff retries and other reliability patterns
for async and sync operations.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)

def async_retry(
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exceptions: tuple[type[Exception], ...] = (Exception,)
):
    """Retry decorator with exponential backoff and jitter."""
    def decorator(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_err = None
            for attempt in range(retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_err = e
                    if attempt == retries:
                        break

                    # Exponential backoff + Jitter
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = delay * 0.1 * random.uniform(-1, 1)
                    actual_delay = delay + jitter

                    logger.warning(
                        f"Retrying {func.__name__} in {actual_delay:.2f}s... "
                        f"(Attempt {attempt + 1}/{retries}, Error: {e})"
                    )
                    await asyncio.sleep(actual_delay)

            logger.error(f"Failed {func.__name__} after {retries} retries.")
            raise last_err
        return wrapper
    return decorator

def sync_retry(
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exceptions: tuple[type[Exception], ...] = (Exception,)
):
    """Synchronous version of the retry decorator."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_err = None
            for attempt in range(retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_err = e
                    if attempt == retries:
                        break

                    delay = min(base_delay * (2 ** attempt), max_delay)
                    time.sleep(delay + (delay * 0.1 * random.uniform(-1, 1)))
                    logger.warning(f"Retrying SYNC {func.__name__} (Attempt {attempt + 1}/{retries}, Error: {e})")
            raise last_err
        return wrapper
    return decorator

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def default_should_retry(error: Exception) -> bool:
    """Default retry policy (Ported from Project B's isRetryableError).

    Retries on:
    - Network errors (timeout, connection reset, etc.)
    - HTTP 429 (Too Many Requests)
    - HTTP 5xx (Server Errors)
    - Specific Qwen/Alibaba Cloud transient errors
    """
    status = get_error_status(error)
    if status is not None:
        # Retry on 429 and all 5xx errors
        return bool(status == 429 or 500 <= status <= 599)

    # Check for network-related errors
    error_msg = str(error).lower()
    network_indicators = [
        'timeout', 'connection', 'network', 'socket',
        'temporarily unavailable', 'try again later'
    ]
    if any(indicator in error_msg for indicator in network_indicators):
        return True

    # Qwen-specific error codes
    qwen_transient_codes = ['Throttling.RateQuota', 'ServiceUnavailable']
    return bool(any(code in str(error) for code in qwen_transient_codes))


def get_error_status(error: Exception) -> int | None:
    """Extract HTTP status code from exception if available."""
    # Try common attributes
    for attr in ['status_code', 'status', 'code']:
        if hasattr(error, attr):
            val = getattr(error, attr)
            if isinstance(val, int):
                return val

    # Try to parse from error message
    import re
    match = re.search(r'status[:\s]+(\d{3})', str(error), re.IGNORECASE)
    if match:
        return int(match.group(1))

    return None

@dataclass
class RetryPolicy:
    """Declarative retry policy configuration.

    Inspired by ClawGod's patch.js pattern matching philosophy:
    - Decoupled retry logic from business code
    - Customizable retry conditions (like ClawGod's `validate` callback)
    - Easy to unit test and compose

    Usage:
        # Simple usage
        policy = RetryPolicy(max_retries=3)
        result = await policy.execute(my_async_func, arg1, arg2)

        # Advanced usage with custom callbacks
        policy = RetryPolicy(
            max_retries=5,
            base_delay=2.0,
            should_retry=lambda e: isinstance(e, ConnectionError),
            on_retry=lambda attempt, error, delay: logger.info(f"Retry {attempt}: {error}")
        )
        result = policy.execute_sync(sync_func, arg1)
    """
    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_factor: float = 0.3  # +/- 30%
    should_retry: Callable[[Exception], bool] = field(default=default_should_retry)
    on_retry: Callable[[int, Exception, float], None] | None = None  # (attempt, error, delay)
    respect_retry_after: bool = True

    def _calculate_delay(self, attempt: int, retry_after_ms: int = 0) -> float:
        """Calculate delay with exponential backoff and optional jitter."""
        if retry_after_ms > 0 and self.respect_retry_after:
            return retry_after_ms / 1000.0

        # Exponential backoff
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)

        # Add jitter
        if self.jitter:
            jitter_range = delay * self.jitter_factor
            jitter = random.uniform(-jitter_range, jitter_range)
            delay = max(0, delay + jitter)

        return delay

    async def execute(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        """Execute an async function with retry policy.

        Args:
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result from func

        Raises:
            Last exception if all retries exhausted
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                return result

            except Exception as e:
                last_exception = e

                # Check if we should retry
                if not self.should_retry(e):
                    logger.debug(f"Non-retryable error: {e}")
                    raise

                # Check if we've exhausted retries
                if attempt >= self.max_retries:
                    logger.error(f"All {self.max_retries + 1} attempts failed")
                    raise

                # Calculate delay
                retry_after_ms = get_retry_after_ms(e) if self.respect_retry_after else 0
                delay = self._calculate_delay(attempt, retry_after_ms)

                # Notify callback
                if self.on_retry:
                    try:
                        self.on_retry(attempt + 1, e, delay)
                    except Exception as cb_err:
                        logger.warning(f"on_retry callback failed: {cb_err}")

                logger.warning(
                    f"Attempt {attempt + 1}/{self.max_retries + 1} failed ({type(e).__name__}: {e}). "
                    f"Retrying in {delay:.2f}s..."
                )

                await asyncio.sleep(delay)

        # Should never reach here, but just in case
        raise last_exception

    def execute_sync(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute a sync function with retry policy.

        Same as execute() but for synchronous functions.
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                return result

            except Exception as e:
                last_exception = e

                if not self.should_retry(e):
                    logger.debug(f"Non-retryable error: {e}")
                    raise

                if attempt >= self.max_retries:
                    logger.error(f"All {self.max_retries + 1} attempts failed")
                    raise

                retry_after_ms = get_retry_after_ms(e) if self.respect_retry_after else 0
                delay = self._calculate_delay(attempt, retry_after_ms)

                if self.on_retry:
                    try:
                        self.on_retry(attempt + 1, e, delay)
                    except Exception as cb_err:
                        logger.warning(f"on_retry callback failed: {cb_err}")

                logger.warning(
                    f"Attempt {attempt + 1}/{self.max_retries + 1} failed ({type(e).__name__}: {e}). "
                    f"Retrying in {delay:.2f}s..."
                )

                time.sleep(delay)

        raise last_exception


def with_retry(policy: RetryPolicy | None = None, **policy_kwargs):
    """Decorator to apply retry policy to a function.

    Usage:
        @with_retry(max_retries=3, base_delay=1.0)
        async def my_function():
            ...

        # Or with custom policy
        policy = RetryPolicy(max_retries=5)
        @with_retry(policy)
        async def another_function():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        # Create or use provided policy
        retry_policy = policy or RetryPolicy(**policy_kwargs)

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await retry_policy.execute(func, *args, **kwargs)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                return retry_policy.execute_sync(func, *args, **kwargs)
            return sync_wrapper

    return decorator



def get_retry_after_ms(error: Any) -> int:
    """Extract Retry-After from error headers (if available).

    Compatible with Project B's getRetryAfterDelayMs.
    """
    if hasattr(error, 'response') and hasattr(error.response, 'headers'):
        headers = error.response.headers
        retry_after = headers.get('Retry-After') or headers.get('retry-after')
        if retry_after:
            try:
                # Try parsing as seconds
                return int(retry_after) * 1000
            except ValueError:
                # Try parsing as HTTP date
                for fmt in ("%a, %d %b %Y %H:%M:%S GMT", "%A, %d-%b-%y %H:%M:%S GMT", "%a %b %d %H:%M:%S %Y"):
                    try:
                        dt = datetime.strptime(retry_after, fmt)
                        diff = dt.timestamp() - time.time()
                        return int(max(0, diff) * 1000)
                    except ValueError:
                        continue
    return 0

def is_qwen_quota_exceeded(error: Exception) -> bool:
    """Detection for Qwen OAuth/Corporate quota exceeded (Ported from Project B)."""
    error_msg = str(error).lower()
    # Broaden detection to catch more variants seen in Project B
    return "quota exceeded" in error_msg and ("qwen" in error_msg or "alibabacloud" in error_msg)

async def retry_with_backoff(
    func: Callable[[], Awaitable[T]],
    max_attempts: int = 7,
    initial_delay_ms: int = 1500,
    max_delay_ms: int = 30000,
    should_retry: Callable[[Exception], bool] = default_should_retry,
    should_retry_on_content: Callable[[T], bool] | None = None,
    auth_type: str | None = None,
) -> T:
    """Retries an async function with exponential backoff and jitter.

    Enhanced Features (Ported from Project B):
    - Qwen Corporate/OAuth quota exceeded detection with immediate termination.
    - Exponential backoff with jitter (+/- 30%).
    - Respects 'Retry-After' header.
    """
    if max_attempts <= 0:
        raise ValueError("max_attempts must be a positive number")

    attempt = 0
    current_delay = initial_delay_ms

    while attempt < max_attempts:
        attempt += 1
        try:
            result = await func()

            # Check content-aware retries
            if should_retry_on_content and should_retry_on_content(result):
                if attempt >= max_attempts:
                    return result

                jitter = current_delay * 0.3 * (random.uniform(-1, 1))
                delay_with_jitter = max(0, current_delay + jitter)
                logger.warning(f"Attempt {attempt} result failed content check. Retrying...")
                await asyncio.sleep(delay_with_jitter / 1000.0)
                current_delay = min(max_delay_ms, current_delay * 2)
                continue

            return result

        except Exception as e:
            # Special handling for Qwen Quota Exceeded (from Project B)
            if is_qwen_quota_exceeded(e):
                logger.error("Qwen quota exceeded. Terminating retry chain.")
                message = (
                    "Qwen OAuth quota exceeded: Your free daily quota has been reached.\n"
                    "To continue using Qwen Code without waiting, upgrade to the Alibaba Cloud Coding Plan:\n"
                    "  China:       https://help.aliyun.com/zh/model-studio/coding-plan\n"
                    "  Global/Intl: https://www.alibabacloud.com/help/en/model-studio/coding-plan\n"
                )
                # Raise a more descriptive error
                raise RuntimeError(message) from e

            if attempt >= max_attempts or not should_retry(e):
                raise e

            retry_after_ms = get_retry_after_ms(e)
            if retry_after_ms > 0:
                logger.warning(f"Attempt {attempt} failed. Respecting Retry-After: {retry_after_ms}ms")
                await asyncio.sleep(retry_after_ms / 1000.0)
                # After respecting Retry-After, we reset to initial delay for future transient errors
                current_delay = initial_delay_ms
            else:
                # Exponential backoff with jitter: +/- 30% (Consistent with Project B)
                # Standardized Multiplier: 2.0, Jitter: 0.3
                jitter = current_delay * 0.3 * (random.uniform(-1, 1))
                delay_with_jitter = max(0, current_delay + jitter)
                logger.warning(f"Attempt {attempt} failed ({e}). Retrying in {delay_with_jitter:.0f}ms...")
                await asyncio.sleep(delay_with_jitter / 1000.0)
                current_delay = min(max_delay_ms, current_delay * 2.0)

    raise Exception("Retry attempts exhausted")

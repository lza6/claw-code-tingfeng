"""Tracing Context — Distributed Request Tracing

Provides context-aware request ID propagation across async call chains.
Inspired by ClawGod's pattern matching philosophy for cross-cutting concerns.

Features:
    - Thread-safe context variables using contextvars
    - Automatic trace ID generation
    - Context manager for scoped tracing
    - Integration with structured logging

Usage:
    from src.utils.tracing import TracingContext

    # Auto-generate trace ID
    with TracingContext.trace_block("my_operation"):
        # All logs in this block will have the same trace_id
        logger.info("Processing...")

    # Manual trace ID
    TracingContext.set_request_id("custom-trace-123")
    rid = TracingContext.get_request_id()
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Context variable for request/trace ID
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    'request_id',
    default=None
)

# Context variable for operation label
_operation_label: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    'operation_label',
    default=None
)


class TracingContext:
    """Distributed tracing context manager.

    Provides automatic trace ID propagation across async boundaries
    using Python's contextvars module.

    Example:
        >>> with TracingContext.trace_block("database_query"):
        ...     # All operations here share the same trace_id
        ...     result = await db.query(...)
        ...     logger.info("Query completed")  # Includes trace_id
    """

    @staticmethod
    def generate_request_id() -> str:
        """Generate a unique request/trace ID.

        Returns:
            UUID4 string (e.g., 'a1b2c3d4-e5f6-7890-abcd-ef1234567890')
        """
        return str(uuid.uuid4())

    @staticmethod
    def set_request_id(rid: str) -> contextvars.Token:
        """Set the current request/trace ID.

        Args:
            rid: Request/trace ID string

        Returns:
            Context token for resetting later
        """
        token = _request_id.set(rid)
        logger.debug(f"Trace ID set: {rid}")
        return token

    @staticmethod
    def get_request_id() -> str | None:
        """Get the current request/trace ID.

        Returns:
            Current trace ID or None if not set
        """
        return _request_id.get()

    @staticmethod
    def ensure_request_id() -> str:
        """Ensure a request ID exists, generating one if needed.

        Returns:
            Current or newly generated trace ID
        """
        rid = _request_id.get()
        if rid is None:
            rid = TracingContext.generate_request_id()
            _request_id.set(rid)
            logger.debug(f"Auto-generated trace ID: {rid}")
        return rid

    @staticmethod
    def clear_request_id(token: contextvars.Token | None = None):
        """Clear the current request ID.

        Args:
            token: Optional context token from set_request_id()
        """
        if token is not None:
            _request_id.reset(token)
        else:
            _request_id.set(None)
        logger.debug("Trace ID cleared")

    @staticmethod
    def set_operation_label(label: str) -> contextvars.Token:
        """Set the current operation label.

        Args:
            label: Operation description (e.g., "database_query")

        Returns:
            Context token for resetting later
        """
        token = _operation_label.set(label)
        logger.debug(f"Operation label set: {label}")
        return token

    @staticmethod
    def get_operation_label() -> str | None:
        """Get the current operation label.

        Returns:
            Current operation label or None
        """
        return _operation_label.get()

    @staticmethod
    @contextmanager
    def trace_block(
        label: str | None = None,
        request_id: str | None = None
    ) -> Generator[str, None, None]:
        """Context manager for scoped tracing.

        Automatically generates/sets trace ID and operation label,
        then cleans up after the block completes.

        Args:
            label: Operation label (optional)
            request_id: Specific request ID to use (optional, auto-generated if None)

        Yields:
            The trace ID being used

        Example:
            >>> with TracingContext.trace_block("api_call") as trace_id:
            ...     logger.info(f"Starting API call with trace {trace_id}")
            ...     response = await make_api_call()
            ...     logger.info("API call completed")
        """
        # Save current context
        _request_id.get()
        _operation_label.get()

        # Set new context
        rid = request_id or TracingContext.generate_request_id()
        rid_token = _request_id.set(rid)

        label_token = None
        if label:
            label_token = _operation_label.set(label)

        try:
            logger.debug(f"[{rid}] {label or 'operation'} started")
            yield rid
        except Exception as e:
            logger.error(f"[{rid}] {label or 'operation'} failed: {e}")
            raise
        finally:
            # Restore context
            _request_id.reset(rid_token)
            if label_token:
                _operation_label.reset(label_token)

            logger.debug(f"[{rid}] {label or 'operation'} completed")

    @staticmethod
    def get_context_dict() -> dict[str, str | None]:
        """Get current tracing context as a dictionary.

        Useful for including in structured log entries.

        Returns:
            Dictionary with 'trace_id' and 'operation' keys
        """
        return {
            'trace_id': _request_id.get(),
            'operation': _operation_label.get(),
        }

    @staticmethod
    def format_trace_prefix() -> str:
        """Get formatted trace prefix for log messages.

        Returns:
            Formatted string like "[trace-id] " or "" if no trace
        """
        rid = _request_id.get()
        if rid:
            return f"[{rid[:8]}] "
        return ""


# Convenience functions for common patterns

def get_current_trace_id() -> str | None:
    """Shorthand for TracingContext.get_request_id()."""
    return TracingContext.get_request_id()


def ensure_trace_id() -> str:
    """Shorthand for TracingContext.ensure_request_id()."""
    return TracingContext.ensure_request_id()


@contextmanager
def trace_operation(label: str) -> Generator[str, None, None]:
    """Shorthand for TracingContext.trace_block().

    Example:
        >>> with trace_operation("db_query") as trace_id:
        ...     result = await db.execute(query)
    """
    with TracingContext.trace_block(label) as rid:
        yield rid


def traced(operation_name: str | None = None):
    """Decorator to automatically add tracing to async functions.

    Inspired by ClawGod's cross-cutting concern pattern.

    Args:
        operation_name: Name of the operation (defaults to function name)

    Returns:
        Decorated function with automatic trace context

    Example:
        >>> @traced("agent_handle_message")
        ... async def handle_message(self, message):
        ...     # Automatically has trace_id in logs
        ...     pass
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        op_name = operation_name or func.__name__

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with TracingContext.trace_block(op_name):
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with TracingContext.trace_block(op_name):
                    return func(*args, **kwargs)
            return sync_wrapper

    return decorator

"""Safe JSON Parsing Utilities

Provides safe JSON parsing with fallback values, inspired by
oh-my-codex's safe-json.ts.
"""

import json
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar('T')


def safe_json_parse(raw: str, fallback: T) -> T:
    """Safely parse JSON string, returning fallback on error.
    
    Args:
        raw: JSON string to parse
        fallback: Value to return if parsing fails
        
    Returns:
        Parsed JSON value or fallback
    """
    if not raw:
        return fallback

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


def safe_json_dump(
    obj: Any,
    indent: int = 2,
    ensure_ascii: bool = False,
    default: Callable[[Any], Any] | None = None,
) -> str:
    """Safely serialize object to JSON string.
    
    Args:
        obj: Object to serialize
        indent: Indentation level
        ensure_ascii: Whether to escape non-ASCII characters
        default: Custom serializer for non-serializable objects
        
    Returns:
        JSON string
    """
    try:
        return json.dumps(
            obj,
            indent=indent,
            ensure_ascii=ensure_ascii,
            default=default,
        )
    except (TypeError, ValueError):
        # If serialization fails, return empty JSON object
        return "{}"


def safe_json_loads(
    raw: str | None,
    fallback: T | None = None,
) -> Any:
    """Alias for safe_json_parse for compatibility."""
    return safe_json_parse(raw, fallback)


class SafeJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles common non-serializable types."""

    def default(self, obj: Any) -> Any:  # type: ignore
        """Handle non-serializable types."""
        # Handle datetime
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        # Handle set
        if isinstance(obj, (set, frozenset)):
            return list(obj)
        # Handle bytes
        if isinstance(obj, bytes):
            return obj.decode('utf-8', errors='replace')
        # Handle objects with __dict__
        if hasattr(obj, '__dict__'):
            return obj.__dict__

        return super().default(obj)


def safe_json_parse_with_type(raw: str, fallback: T) -> T:
    """Parse JSON with type preservation (for generic use).
    
    Args:
        raw: JSON string
        fallback: Fallback value with desired type
        
    Returns:
        Parsed value with type matching fallback
    """
    return safe_json_parse(raw, fallback)

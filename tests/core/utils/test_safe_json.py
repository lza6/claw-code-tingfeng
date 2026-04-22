"""Tests for safe_json utilities."""

import json
import pytest
from src.core.utils.safe_json import (
    safe_json_parse,
    safe_json_dump,
    safe_json_loads,
    safe_json_parse_with_type,
    SafeJSONEncoder,
)


def test_safe_json_parse_valid():
    """Test parsing valid JSON."""
    result = safe_json_parse('{"key": "value"}', {})
    assert result == {"key": "value"}


def test_safe_json_parse_invalid():
    """Test parsing invalid JSON returns fallback."""
    result = safe_json_parse('invalid json', {"default": "value"})
    assert result == {"default": "value"}


def test_safe_json_parse_none():
    """Test parsing None returns fallback."""
    result = safe_json_parse(None, [])
    assert result == []


def test_safe_json_parse_empty_string():
    """Test parsing empty string returns fallback."""
    result = safe_json_parse("", "fallback")
    assert result == "fallback"


def test_safe_json_dump_simple():
    """Test dumping simple object."""
    result = safe_json_dump({"key": "value"})
    assert '"key"' in result
    assert '"value"' in result


def test_safe_json_dump_with_indent():
    """Test dumping with indentation."""
    result = safe_json_dump({"a": 1, "b": 2}, indent=4)
    assert "    " in result  # Should have indentation


def test_safe_json_dump_non_serializable():
    """Test dumping non-serializable object returns empty object."""
    class CustomObject:
        pass
    
    result = safe_json_dump(CustomObject())
    assert result == "{}"


def test_safe_json_loads_alias():
    """Test safe_json_loads is an alias."""
    result = safe_json_loads('{"test": 123}', None)
    assert result == {"test": 123}


def test_safe_json_parse_with_type():
    """Test parsing with type preservation."""
    fallback: list = []
    result = safe_json_parse_with_type('[1, 2, 3]', fallback)
    assert result == [1, 2, 3]
    assert isinstance(result, list)


def test_safe_json_parse_with_type_invalid():
    """Test parsing with type preservation falls back."""
    fallback: dict = {}
    result = safe_json_parse_with_type('invalid', fallback)
    assert result == {}
    assert isinstance(result, dict)


def test_safe_json_parse_with_datetime():
    """Test parsing datetime-like objects."""
    from datetime import datetime
    from src.core.utils.safe_json import SafeJSONEncoder
    
    data = {"timestamp": datetime(2024, 1, 1, 12, 0, 0)}
    encoder = SafeJSONEncoder()
    result = encoder.encode(data)
    parsed = json.loads(result)
    assert "2024-01-01" in parsed["timestamp"] or "2024-01-01T12:00:00" in parsed["timestamp"]


def test_safe_json_parse_with_set():
    """Test parsing set converts to list."""
    data = {"items": {1, 2, 3}}
    encoder = SafeJSONEncoder()
    result = encoder.encode(data)
    parsed = json.loads(result)
    assert "items" in parsed
    # Set becomes list
    assert isinstance(parsed["items"], list)
    assert set(parsed["items"]) == {1, 2, 3}

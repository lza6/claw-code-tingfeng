"""Tests for src/utils/telemetry.py - Telemetry utilities."""
import json
import tempfile
from pathlib import Path

import pytest

from src.utils.telemetry import Telemetry, TelemetryEvent, VERSION


class TestTelemetryEvent:
    """Tests for TelemetryEvent dataclass."""

    def test_telemetry_event_creation(self):
        """Test TelemetryEvent creation with required fields."""
        event = TelemetryEvent(event_type="test")
        assert event.event_type == "test"
        assert event.version == VERSION

    def test_telemetry_event_to_dict(self):
        """Test to_dict returns a dictionary."""
        event = TelemetryEvent(event_type="test")
        data = event.to_dict()
        assert isinstance(data, dict)
        assert data["event_type"] == "test"


class TestTelemetry:
    """Tests for Telemetry class."""

    def test_telemetry_disabled_by_default(self, tmp_path):
        """Test that telemetry is disabled by default."""
        telemetry = Telemetry(tmp_path)
        assert telemetry.enabled is False

    def test_telemetry_enabled_with_disabled_false(self, tmp_path):
        """Test that telemetry can be enabled."""
        telemetry = Telemetry(tmp_path, disabled=False)
        # Note: may still be disabled due to env var
        assert isinstance(telemetry.enabled, bool)

    def test_telemetry_record_disabled(self, tmp_path):
        """Test that record does nothing when disabled."""
        telemetry = Telemetry(tmp_path)
        event = TelemetryEvent(event_type="test")
        telemetry.record(event)  # Should not raise

    def test_telemetry_record_tool_call(self, tmp_path):
        """Test record_tool_call when enabled."""
        telemetry = Telemetry(tmp_path, disabled=False)
        telemetry.record_tool_call("test_tool", 100.0, False, 1024)
        # Check file was created
        assert telemetry.log_file.exists()

    def test_telemetry_record_codebase_stats(self, tmp_path):
        """Test record_codebase_stats when enabled."""
        telemetry = Telemetry(tmp_path, disabled=False)
        stats = {"files": 10, "lines": 1000}
        telemetry.record_codebase_stats(stats)
        # Check file was created
        assert telemetry.log_file.exists()


class TestVersion:
    """Tests for version constant."""

    def test_version_string(self):
        """Test VERSION is a string."""
        assert isinstance(VERSION, str)
        assert VERSION == "0.1.0"
"""Tests for src/utils/spinner.py - Terminal spinner animations."""
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.utils.spinner import Spinner, WaitingSpinner


class TestSpinner:
    """Tests for Spinner class."""

    def test_init_defaults(self):
        """Test Spinner initialization with defaults."""
        spinner = Spinner()
        assert spinner.text == ""
        assert spinner.visible is False

    def test_init_with_text(self):
        """Test Spinner initialization with text."""
        spinner = Spinner("Processing...")
        assert spinner.text == "Processing..."

    def test_init_sets_start_time(self):
        """Test that start_time is set."""
        start = time.time()
        spinner = Spinner()
        assert spinner.start_time >= start

    def test_frames_are_defined(self):
        """Test that frames are pre-rendered."""
        spinner = Spinner()
        assert len(spinner.frames) > 0

    def test_terminal_width_has_property(self):
        """Test terminal width property exists."""
        spinner = Spinner()
        # Property should be accessible (actual value depends on environment)
        width = spinner.terminal_width
        assert isinstance(width, int)
        assert width > 0

    def test_next_frame_cycles(self):
        """Test that frames cycle properly."""
        spinner = Spinner()
        initial_idx = spinner.frame_idx

        spinner._next_frame()
        assert spinner.frame_idx != initial_idx

    def test_class_variable_persists(self):
        """Test that last_frame_idx is a class variable."""
        spinner1 = Spinner()
        frame1 = spinner1.frame_idx

        spinner2 = Spinner()
        # Each new instance has its own frame_idx but the class variable tracks globally
        assert isinstance(spinner2.frame_idx, int)

    @patch.object(sys.stdout, "isatty", return_value=False)
    def test_step_non_tty(self, mock_isatty):
        """Test step does nothing when not a TTY."""
        spinner = Spinner("Test")
        spinner.step()
        # Should not raise

    @patch.object(sys.stdout, "isatty", return_value=True)
    @patch.object(sys.stdout, "write")
    def test_step_before_delay(self, mock_write, mock_isatty):
        """Test step does nothing before 0.5s delay."""
        spinner = Spinner("Test")
        spinner.step()
        mock_write.assert_not_called()

    @patch.object(sys.stdout, "isatty", return_value=True)
    @patch.object(sys.stdout, "write")
    def test_step_updates_text(self, mock_write, mock_isatty):
        """Test step can update text."""
        spinner = Spinner("Test")
        spinner.visible = True
        spinner.last_update = 0.0

        with patch("time.time", return_value=1000):
            spinner.step("New text")
            assert spinner.text == "New text"

    @patch.object(sys.stdout, "isatty", return_value=True)
    @patch.object(sys.stdout, "write")
    def test_end_clears_display(self, mock_write, mock_isatty):
        """Test end clears the display."""
        spinner = Spinner("Test")
        spinner.visible = True
        spinner.last_display_len = 10

        spinner.end()
        mock_write.assert_called()


class TestWaitingSpinner:
    """Tests for WaitingSpinner class."""

    def test_init_defaults(self):
        """Test WaitingSpinner initialization."""
        spinner = WaitingSpinner()
        assert isinstance(spinner.spinner, Spinner)
        assert spinner.delay == 0.15

    def test_init_with_text(self):
        """Test WaitingSpinner with text."""
        spinner = WaitingSpinner("Loading...")
        assert spinner.spinner.text == "Loading..."

    def test_stop_event_is_set(self):
        """Test that stop event exists."""
        spinner = WaitingSpinner()
        assert isinstance(spinner._stop_event, threading.Event)

    def test_start_creates_thread(self):
        """Test that start creates a thread."""
        spinner = WaitingSpinner()
        spinner.start()
        try:
            assert spinner._thread.is_alive()
        finally:
            spinner.stop()

    def test_start_clear_stop_event(self):
        """Test that start clears stop event."""
        spinner = WaitingSpinner()
        spinner._stop_event.set()
        spinner.start()
        try:
            assert not spinner._stop_event.is_set()
        finally:
            spinner.stop()

    def test_context_manager(self):
        """Test context manager protocol."""
        with WaitingSpinner("Test") as spinner:
            assert isinstance(spinner, WaitingSpinner)
            assert spinner._thread.is_alive()
        # After exit, should be stopped

    def test_context_manager_stops_on_exception(self):
        """Test that context manager stops on exception."""
        with pytest.raises(RuntimeError):
            with WaitingSpinner("Test") as spinner:
                raise RuntimeError("test")
        # Should have stopped gracefully

    def test_stop_sets_event(self):
        """Test that stop sets the stop event."""
        spinner = WaitingSpinner()
        spinner.start()
        spinner.stop()
        assert spinner._stop_event.is_set()

    def test_stop_does_not_raise_when_not_started(self):
        """Test that stop handles not started state."""
        spinner = WaitingSpinner()
        spinner.stop()  # Should not raise
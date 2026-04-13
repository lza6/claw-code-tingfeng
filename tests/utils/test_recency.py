"""Tests for src/utils/recency.py - Recency tracking utilities."""
import tempfile
from pathlib import Path

import pytest

from src.utils.recency import RecencyTracker


class TestRecencyTracker:
    """Tests for RecencyTracker class."""

    def test_init(self, tmp_path):
        """Test RecencyTracker initialization."""
        tracker = RecencyTracker(tmp_path)
        assert tracker.root_dir == tmp_path
        assert tracker.max_tracked == 1000
        assert tracker.current_sequence == 0

    def test_init_custom_max_tracked(self, tmp_path):
        """Test with custom max_tracked."""
        tracker = RecencyTracker(tmp_path, max_tracked=100)
        assert tracker.max_tracked == 100

    def test_scan_empty_directory(self, tmp_path):
        """Test scan on empty directory."""
        tracker = RecencyTracker(tmp_path)
        tracker.scan()
        assert len(tracker.file_mtimes) == 0

    def test_scan_with_files(self, tmp_path):
        """Test scan finds files."""
        # Create test files
        (tmp_path / "file1.py").write_text("print('hello')")
        (tmp_path / "file2.py").write_text("print('world')")

        tracker = RecencyTracker(tmp_path)
        tracker.scan()

        assert len(tracker.file_mtimes) == 2

    def test_scan_excludes_directories(self, tmp_path):
        """Test that scan excludes specified directories."""
        # Create .git directory
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("")

        tracker = RecencyTracker(tmp_path)
        tracker.scan()

        # .git should be excluded
        assert ".git" not in tracker.file_mtimes

    def test_touch_increments_sequence(self, tmp_path):
        """Test touch increments sequence."""
        tracker = RecencyTracker(tmp_path)
        tracker.touch("test.py")

        assert tracker.current_sequence == 1
        assert "test.py" in tracker.file_sequences

    def test_touch_multiple(self, tmp_path):
        """Test multiple touches."""
        tracker = RecencyTracker(tmp_path)
        tracker.touch("file1.py")
        tracker.touch("file2.py")

        assert tracker.current_sequence == 2
        assert tracker.file_sequences["file1.py"] == 1
        assert tracker.file_sequences["file2.py"] == 2

    def test_get_hot_files_empty(self, tmp_path):
        """Test get_hot_files on empty tracker."""
        tracker = RecencyTracker(tmp_path)
        tracker.scan()

        hot = tracker.get_hot_files()
        assert hot == []

    def test_get_hot_files_with_limit(self, tmp_path):
        """Test get_hot_files respects limit."""
        # Create multiple files
        for i in range(15):
            (tmp_path / f"file{i}.py").write_text(f"print({i})")

        tracker = RecencyTracker(tmp_path)
        tracker.scan()

        hot = tracker.get_hot_files(limit=5)
        assert len(hot) == 5

    def test_get_hot_files_with_touch(self, tmp_path):
        """Test get_hot_files prioritizes touched files."""
        (tmp_path / "file1.py").write_text("old")
        (tmp_path / "file2.py").write_text("new")

        tracker = RecencyTracker(tmp_path)
        tracker.scan()
        tracker.touch("file1.py")  # Touch file1

        hot = tracker.get_hot_files(limit=2)
        # file1 should be first due to touch
        assert "file1.py" in hot

    def test_get_stats(self, tmp_path):
        """Test get_stats returns dict."""
        tracker = RecencyTracker(tmp_path)
        tracker.scan()

        stats = tracker.get_stats()
        assert isinstance(stats, dict)
        assert "total_files" in stats

    def test_update_file_new(self, tmp_path):
        """Test update_file for new file."""
        tracker = RecencyTracker(tmp_path)
        (tmp_path / "new.py").write_text("new")

        tracker.update_file("new.py")
        assert "new.py" in tracker.file_mtimes

    def test_update_file_deleted(self, tmp_path):
        """Test update_file when file is deleted."""
        tracker = RecencyTracker(tmp_path)
        # Initially tracked
        tracker.file_mtimes["deleted.py"] = 123.0

        # Update with non-existent file
        tracker.update_file("deleted.py")
        # Should be removed from mtimes
        assert "deleted.py" not in tracker.file_mtimes
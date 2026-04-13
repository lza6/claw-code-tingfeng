"""Tests for src/utils/editor.py - Editor interaction utilities."""
import os
import platform
import tempfile
from pathlib import Path

import pytest

from src.utils.editor import (
    DEFAULT_EDITOR_NIX,
    DEFAULT_EDITOR_OS_X,
    DEFAULT_EDITOR_WINDOWS,
    discover_editor,
    get_environment_editor,
    write_temp_file,
)


class TestWriteTempFile:
    """Tests for write_temp_file function."""

    def test_write_temp_file_basic(self):
        """Test basic temp file creation."""
        filepath = write_temp_file("test content")
        try:
            assert Path(filepath).exists()
            with open(filepath, encoding="utf-8") as f:
                assert f.read() == "test content"
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_write_temp_file_with_suffix(self):
        """Test temp file with suffix."""
        filepath = write_temp_file("content", suffix="py")
        try:
            assert filepath.endswith(".py")
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_write_temp_file_with_prefix(self):
        """Test temp file with prefix."""
        filepath = write_temp_file("content", prefix="mytest")
        try:
            assert "mytest" in filepath
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_write_temp_file_empty_content(self):
        """Test temp file with empty content."""
        filepath = write_temp_file("")
        try:
            assert Path(filepath).exists()
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)


class TestGetEnvironmentEditor:
    """Tests for get_environment_editor function."""

    def test_get_editor_with_visual_env(self, monkeypatch):
        """Test that VISUAL env takes precedence."""
        monkeypatch.setenv("VISUAL", "vim")
        monkeypatch.setenv("EDITOR", "nano")
        assert get_environment_editor() == "vim"

    def test_get_editor_with_editor_env(self, monkeypatch):
        """Test that EDITOR env is used when VISUAL is not set."""
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.setenv("EDITOR", "nano")
        assert get_environment_editor() == "nano"

    def test_get_editor_with_default(self, monkeypatch):
        """Test that default is used when no env vars."""
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)
        assert get_environment_editor("code") == "code"

    def test_get_editor_returns_none_when_no_default(self, monkeypatch):
        """Test that None is returned when no env vars and no default."""
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)
        assert get_environment_editor() is None


class TestDiscoverEditor:
    """Tests for discover_editor function."""

    def test_discover_editor_windows(self, monkeypatch):
        """Test that Windows uses notepad."""
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)
        assert discover_editor() == DEFAULT_EDITOR_WINDOWS

    def test_discover_editor_darwin(self, monkeypatch):
        """Test that macOS uses vim."""
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)
        assert discover_editor() == DEFAULT_EDITOR_OS_X

    def test_discover_editor_linux(self, monkeypatch):
        """Test that Linux uses vi."""
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.delenv("EDITOR", raising=False)
        assert discover_editor() == DEFAULT_EDITOR_NIX

    def test_discover_editor_override(self, monkeypatch):
        """Test that editor_override is respected."""
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        assert discover_editor("code") == "code"

    def test_discover_editor_with_env(self, monkeypatch):
        """Test that env vars override defaults."""
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.setenv("VISUAL", "emacs")
        assert discover_editor() == "emacs"


class TestConstants:
    """Tests for editor constants."""

    def test_default_editor_constants_defined(self):
        """Test that all default editors are defined."""
        assert DEFAULT_EDITOR_NIX == "vi"
        assert DEFAULT_EDITOR_OS_X == "vim"
        assert DEFAULT_EDITOR_WINDOWS == "notepad"
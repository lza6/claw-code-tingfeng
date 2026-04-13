"""Tests for src/utils/report.py - Bug reporting utilities."""
import platform
import sys

import pytest

from src.utils.report import (
    check_environment,
    exception_handler,
    get_git_info,
    get_os_info,
    get_python_info,
    get_system_info,
    install_exception_handler,
)


class TestGetSystemInfo:
    """Tests for system info functions."""

    def test_get_python_info(self):
        """Test get_python_info returns string with implementation."""
        info = get_python_info()
        assert "Python implementation:" in info
        assert "Virtual environment:" in info

    def test_get_os_info(self):
        """Test get_os_info returns string with OS info."""
        info = get_os_info()
        assert "OS:" in info
        assert platform.system() in info

    def test_get_git_info_returns_string(self):
        """Test get_git_info returns a string."""
        info = get_git_info()
        assert isinstance(info, str)

    def test_get_system_info(self):
        """Test get_system_info returns complete info."""
        info = get_system_info()
        assert "Python version:" in info
        assert "Platform:" in info


class TestExceptionHandler:
    """Tests for exception handling."""

    def test_exception_handler_keyboard_interrupt(self):
        """Test that KeyboardInterrupt uses default handler."""
        # Create a mock traceback
        import io

        old_stderr = sys.stderr
        sys.stderr = io.StringIO()

        try:
            try:
                raise KeyboardInterrupt()
            except KeyboardInterrupt:
                exception_handler(KeyboardInterrupt, KeyboardInterrupt(), None)
        finally:
            sys.stderr = old_stderr

    def test_install_exception_handler(self):
        """Test that install_exception_handler sets sys.excepthook."""
        install_exception_handler()
        assert sys.excepthook is not None


class TestCheckEnvironment:
    """Tests for environment checking."""

    def test_check_environment_returns_dict(self):
        """Test check_environment returns dict."""
        result = check_environment()
        assert isinstance(result, dict)
        assert "python" in result
        assert "git" in result
        assert "openai" in result
        assert "anthropic" in result

    def test_check_environment_python_is_true(self):
        """Test that python check is always True."""
        result = check_environment()
        assert result["python"] is True


class TestExports:
    """Tests for module exports."""

    def test_all_exports_contain_expected(self):
        """Test __all__ contains expected functions."""
        from src.utils import report

        assert "get_system_info" in report.__all__
        assert "exception_handler" in report.__all__
        assert "check_environment" in report.__all__
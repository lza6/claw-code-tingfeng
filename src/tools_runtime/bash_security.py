"""Bash Tool 安全检查模块

包含命令解析、安全验证等函数。
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
from pathlib import Path

from .bash_constants import (
    _WINDOWS_BUILTIN_COMMANDS,
    _WINDOWS_DANGEROUS_CHARS,
)


def _parse_command_to_list(command: str) -> list[str]:
    """将命令字符串安全解析为参数列表

    Unix: 使用 shlex.split
    Windows: 使用 shlex.split(posix=False) 或手动分割
    """
    if sys.platform != 'win32':
        return shlex.split(command)

    # Windows 解析：使用 shlex 的 posix=False 模式
    try:
        return shlex.split(command, posix=False)
    except ValueError:
        return command.split()


def find_git_bash_path() -> str | None:
    """探测 Windows 上的 Git Bash 路径 (Ported from Project B)"""
    if sys.platform != 'win32':
        return 'bash'

    # 常见路径
    common_paths = [
        Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe',
        Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Git/bin/bash.exe',
        Path('C:/Program Files/Git/usr/bin/bash.exe'),
    ]

    for p in common_paths:
        if p.exists():
            return str(p)

    # 检查 PATH
    return shutil.which('bash.exe') or shutil.which('bash')


# --- Project B Ported Security Logic ---

READ_ONLY_ROOT_COMMANDS = {
    'awk', 'basename', 'cat', 'cd', 'column', 'cut', 'df', 'dirname', 'du',
    'echo', 'env', 'find', 'git', 'grep', 'head', 'less', 'ls', 'more',
    'printenv', 'printf', 'ps', 'pwd', 'rg', 'ripgrep', 'sed', 'sort',
    'stat', 'tail', 'tree', 'uniq', 'wc', 'which', 'where', 'whoami',
}

READ_ONLY_GIT_SUBCOMMANDS = {
    'blame', 'branch', 'cat-file', 'diff', 'grep', 'log', 'ls-files',
    'remote', 'rev-parse', 'show', 'status', 'describe',
}

BLOCKED_GIT_REMOTE_ACTIONS = {'add', 'remove', 'rename', 'set-url', 'prune', 'update'}
BLOCKED_GIT_BRANCH_FLAGS = {'-d', '-D', '--delete', '--move', '-m'}

BLOCKED_FIND_FLAGS = {'-delete', '-exec', '-execdir', '-ok', '-okdir'}
BLOCKED_FIND_PREFIXES = ('-fprint', '-fprintf')

# AWK side-effect patterns (Ported from Project B)
AWK_SIDE_EFFECT_PATTERNS = [
    re.compile(r'system\s*\('),
    re.compile(r'print\s+[^>|]*>\s*"[^"]*"'),
    re.compile(r'printf\s+[^>|]*>\s*"[^"]*"'),
    re.compile(r'print\s+[^>|]*>>\s*"[^"]*"'),
    re.compile(r'printf\s+[^>|]*>>\s*"[^"]*"'),
    re.compile(r'print\s+[^|]*\|\s*"[^"]*"'),
    re.compile(r'printf\s+[^|]*\|\s*"[^"]*"'),
    re.compile(r'getline\s*<\s*"[^"]*"'),
    re.compile(r'"[^"]*"\s*\|\s*getline'),
    re.compile(r'close\s*\('),
]

# SED side-effect patterns (Ported from Project B)
SED_SIDE_EFFECT_PATTERNS = [
    re.compile(r'[^\\]e\s'),
    re.compile(r'^e\s'),
    re.compile(r'[^\\]w\s'),
    re.compile(r'^w\s'),
    re.compile(r'[^\\]r\s'),
    re.compile(r'^r\s'),
]


def strip_shell_wrapper(command: str) -> str:
    """Peels off common shell wrappers like bash -c or sh -c.

    Ported from Project B's stripShellWrapper.
    """
    command = command.strip()

    # Common shell wrapper patterns: bash -c "...", sh -c '...', /bin/bash -c ...
    patterns = [
        r'^(?:/bin/|/usr/bin/)?(?:bash|sh|zsh|dash)\s+-c\s+["\'](.*)["\']\s*$',
        r'^(?:/bin/|/usr/bin/)?(?:bash|sh|zsh|dash)\s+-c\s+(.*)\s*$',
    ]

    for pattern in patterns:
        match = re.match(pattern, command, re.IGNORECASE | re.DOTALL)
        if match:
            inner = match.group(1).strip()
            # If it's still quoted, unquote it
            if (inner.startswith('"') and inner.endswith('"')) or \
               (inner.startswith("'") and inner.endswith("'")):
                inner = inner[1:-1].strip()
            return inner

    return command


def contains_write_redirection(command: str) -> bool:
    """Checks for '>' or '>>' outside of quotes. (Ported from Project B)"""
    in_single = False
    in_double = False
    escaped = False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == '\\' and not in_single:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if not in_single and not in_double and char == '>':
            return True
    return False


def evaluate_find_command(args: list[str]) -> bool:
    """Evaluate if a find command has side-effects. (Ported from Project B)"""
    for arg in args:
        lower = arg.lower()
        if lower in BLOCKED_FIND_FLAGS:
            return False
        if lower.startswith(BLOCKED_FIND_PREFIXES):
            return False
    return True


def evaluate_git_command(args: list[str]) -> bool:
    """Evaluate if a git command is read-only. (Enhanced from Project B)"""
    if not args:
        return True

    # 1. Skip global flags (e.g., git -C /path status)
    idx = 0
    while idx < len(args) and args[idx].startswith('-'):
        # Global flags that don't change state
        if args[idx].lower() in ('--version', '--help', '--exec-path', '--html-path', '--man-path', '--info-path'):
            return True
        # Flags with values
        if args[idx] in ('-C', '-c'):
            idx += 1
        idx += 1

    if idx >= len(args):
        return True

    subcommand = args[idx].lower()
    if subcommand not in READ_ONLY_GIT_SUBCOMMANDS:
        return False

    sub_args = args[idx+1:]

    # 2. Granular check for specific subcommands
    if subcommand == 'remote':
        # git remote (list) is OK, but git remote add/remove/etc is NOT
        return not any(a.lower() in BLOCKED_GIT_REMOTE_ACTIONS for a in sub_args)
    if subcommand == 'branch':
        # git branch (list) is OK, but git branch -d/-D/-m/-v is NOT
        return not any(a in BLOCKED_GIT_BRANCH_FLAGS for a in sub_args)
    if subcommand == 'show':
        # git show is usually OK, but double check for dangerous ref names?
        # (Actually git show is read-only by design)
        return True

    return True


def evaluate_sed_command(args: list[str]) -> bool:
    """Evaluate if a sed command has side-effects. (Enhanced from Project B)"""
    # Block in-place editing (-i, --in-place)
    if any(a.startswith('-i') or a == '--in-place' for a in args):
        return False

    # Check script content for executing commands or writing files
    script = ' '.join(args)
    return not any(p.search(script) for p in SED_SIDE_EFFECT_PATTERNS)


def evaluate_awk_command(args: list[str]) -> bool:
    """Evaluate if a awk command has side-effects."""
    script = ' '.join(args)
    return not any(p.search(script) for p in AWK_SIDE_EFFECT_PATTERNS)


def split_commands(command: str) -> list[str]:
    """Splits a shell command into individual commands, respecting quotes and operators.

    Ported from Project B's splitCommands.
    """
    commands = []
    current = ""
    in_single = False
    in_double = False
    i = 0

    while i < len(command):
        char = command[i]
        next_char = command[i+1] if i + 1 < len(command) else None

        # Handle escaping
        if char == '\\' and not in_single and next_char:
            current += char + next_char
            i += 2
            continue

        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double

        if not in_single and not in_double:
            # Check for delimiters: &&, ||, ;, |
            if (char == '&' and next_char == '&') or (char == '|' and next_char == '|'):
                commands.append(current.strip())
                current = ""
                i += 1
            elif char == '|' or char == ';':
                commands.append(current.strip())
                current = ""
            elif char in ('\n', '\r'):
                commands.append(current.strip())
                current = ""
                if char == '\r' and next_char == '\n':
                    i += 1
            else:
                current += char
        else:
            current += char
        i += 1

    if current.strip():
        commands.append(current.strip())

    return [c for c in commands if c]


def is_shell_command_read_only(command: str) -> bool:
    """Sophisticated check if a shell command is read-only. (Enhanced from Project B)"""
    if not command.strip():
        return True

    # Strip shell wrappers (Ported from B: Recursive peeling)
    stripped = strip_shell_wrapper(command)
    if stripped != command:
        return is_shell_command_read_only(stripped)

    # Check for command substitution first (global check)
    if detect_command_substitution(command):
        return False

    # Split into individual segments
    segments = split_commands(command)
    if not segments:
        return True

    for segment in segments:
        # If segment is another shell call, recurse
        inner = strip_shell_wrapper(segment)
        if inner != segment:
             if not is_shell_command_read_only(inner):
                 return False
             continue

        # Check for redirection in segment
        if contains_write_redirection(segment):
            return False

        # Parse tokens for bitwise check
        try:
            tokens = _parse_command_to_list(segment)
        except Exception:
            return False

        if not tokens:
            continue

        # Environment assignments skip
        root_idx = 0
        while root_idx < len(tokens) and '=' in tokens[root_idx]:
            root_idx += 1

        if root_idx >= len(tokens):
            continue

        root = tokens[root_idx].lower()
        if root not in READ_ONLY_ROOT_COMMANDS:
            return False

        args = tokens[root_idx+1:]

        if root == 'git':
            if not evaluate_git_command(args):
                return False
        elif root == 'find':
            if not evaluate_find_command(args):
                return False
        elif root == 'sed':
            if not evaluate_sed_command(args):
                return False
        elif root == 'awk' and not evaluate_awk_command(args):
            return False

    return True


def detect_command_substitution(command: str) -> bool:
    """Detects command substitution patterns in a shell command.

    Ported from Project B's detectCommandSubstitution. Handles quotes and backticks.
    """
    in_single = False
    in_double = False
    i = 0
    while i < len(command):
        char = command[i]
        next_char = command[i+1] if i + 1 < len(command) else None

        if char == '\\' and not in_single and next_char:
            i += 2
            continue

        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double

        if not in_single:
            # $(...) or `...`
            if char == '$' and next_char == '(':
                return True
            if char == '`':
                return True
            # Process substitution <(...) or >(...)
            if not in_double and char in ('<', '>') and next_char == '(':
                return True
        i += 1
    return False


def _wrap_windows_builtin(cmd_list: list[str]) -> list[str]:
    """如果是 Windows 内置命令，包装为 cmd.exe /c 形式"""
    if sys.platform != 'win32' or not cmd_list:
        return cmd_list

    base_cmd = cmd_list[0].lower().strip()
    if base_cmd in _WINDOWS_BUILTIN_COMMANDS:
        # 检查参数中是否包含危险字符
        for param in cmd_list[1:]:
            if any(char in param for char in _WINDOWS_DANGEROUS_CHARS):
                raise ValueError(
                    f"参数包含危险字符，可能导致命令注入: {param}"
                )
        return ['cmd.exe', '/c', *cmd_list]
    return cmd_list

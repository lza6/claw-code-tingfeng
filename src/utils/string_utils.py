"""String and shell utilities for claw-code-tingfeng.

参考: oh-my-codex-main/src/utils/paths.ts 中的字符串处理
提供 TOML 转义、Shell 引号、会话名清理等通用函数。
"""

import fnmatch
import re

__all__ = [
    'build_detached_session_name',
    'build_shell_command',
    'build_tmux_session_name',
    'escape_toml_string',
    'parse_toml_string_value',
    'quote_powershell_arg',
    'quote_shell_arg',
    'sanitize_session_token',
    'unescape_toml_string',
]


# ---------------------------------------------------------------------------
# TOML String Escaping
# ---------------------------------------------------------------------------

def escape_toml_string(value: str) -> str:
    """转义字符串以在 TOML 双引号字符串中安全使用。

    转义规则:
    - \\  →  \\\\
    - "  →  \\"

    Args:
        value: 原始字符串

    Returns:
        转义后的字符串
    """
    return value.replace('\\', '\\\\').replace('"', '\\"')


def unescape_toml_string(value: str) -> str:
    """撤销 TOML 双引号字符串的转义。

    Args:
        value: 可能已转义的字符串（含外层引号）

    Returns:
        去引号并解转义的原始字符串
    """
    trimmed = value.strip()
    # 移除外层双引号或单引号
    if len(trimmed) >= 2 and trimmed[0] == '"' and trimmed[-1] == '"':
        inner = trimmed[1:-1]
        return inner.replace('\\"', '"').replace('\\\\', '\\')
    if len(trimmed) >= 2 and trimmed[0] == "'" and trimmed[-1] == "'":
        inner = trimmed[1:-1]
        return inner.replace("\\'", "'").replace('\\\\', '\\')
    return trimmed


def parse_toml_string_value(value: str) -> str:
    """从 TOML 键值行解析字符串值。

    例: `key = "value"` → `"value"` → `value`

    Args:
        value: 等号右侧的原始值（含引号）

    Returns:
        解析后的字符串值
    """
    return unescape_toml_string(value)


# ---------------------------------------------------------------------------
# Shell Argument Quoting
# ---------------------------------------------------------------------------

def quote_shell_arg(value: str) -> str:
    """POSIX shell 单引号转义。

    将值包装在单引号中，并转义内部单引号。
    例: `O'Reilly` → `'O'"'"'Reilly'`

    Args:
        value: 参数值

    Returns:
        安全的单引号包装字符串
    """
    if not value:
        return "''"
    # 替换 ' 为 '\'' (关闭引号、转义、重新开启引号)
    escaped = value.replace("'", "'\"'\"'")
    return f"'{escaped}'"


def quote_powershell_arg(value: str) -> str:
    """PowerShell 单引号转义。

    PowerShell 中单引号内不处理转义序列，只需双写单引号。

    Args:
        value: 参数值

    Returns:
        安全的 PowerShell 单引号字符串
    """
    if not value:
        return "''"
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def build_shell_command(command: str, args: list[str]) -> str:
    """构建 POSIX shell 命令字符串。

    Args:
        command: 命令/脚本路径
        args: 参数列表

    Returns:
        可安全传递给 `sh -c` 的命令字符串
    """
    parts = [command] + args
    return ' '.join(quote_shell_arg(arg) for arg in parts)


# ---------------------------------------------------------------------------
# Session / Token Sanitization
# ---------------------------------------------------------------------------

def sanitize_session_token(value: str) -> str:
    """清理字符串使其适合作为 tmux 会话名或环境变量后缀。

    规则:
    - 转小写
    - 非 [a-z0-9] 替换为短横线
    - 去除首尾短横线

    Args:
        value: 原始值

    Returns:
        清理后的安全令牌
    """
    cleaned = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    return cleaned or 'unknown'


def build_tmux_session_name(cwd: str, session_id: str) -> str:
    """构建 tmux 会话名，长度限制下安全截断。

    格式: `omx-{repo}-{dir}-{branch}-{token}`

    Args:
        cwd: 当前工作目录
        session_id: 原始会话 ID（含时间戳/随机串）

    Returns:
        符合 tmux 限制的会话名（≤120 字符）
    """
    import os

    parent = os.path.dirname(cwd)
    dir_name = os.path.basename(cwd)
    grandparent = os.path.dirname(parent)

    # 识别 worktree 命名模式
    parent_dir = os.path.basename(parent)
    if parent_dir.endswith('.omx-worktrees'):
        repo_dir = parent_dir[:-len('.omx-worktrees')]
        dir_token = sanitize_session_token(f'{repo_dir}-{dir_name}')
    elif parent_dir == 'worktrees' and os.path.basename(grandparent) == '.omx':
        repo_dir = os.path.basename(grandparent)
        dir_token = sanitize_session_token(f'{repo_dir}-{dir_name}')
    else:
        dir_token = sanitize_session_token(dir_name)

    # 分支名（若可获取，外部传入更佳）
    branch_token = 'detached'
    try:
        import subprocess
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=cwd, capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0 and result.stdout.strip():
            branch_token = sanitize_session_token(result.stdout.strip())
    except Exception:
        pass

    session_token = sanitize_session_token(session_id.replace('omx-', ''))
    name = f'omx-{dir_token}-{branch_token}-{session_token}'
    return name[:120] if len(name) > 120 else name


def build_detached_session_name(base: str, timestamp: int | None = None) -> str:
    """生成唯一 detached 会话名。

    Args:
        base: 基础名称
        timestamp: 时间戳（默认当前 ms）

    Returns:
        唯一会话名
    """
    import time
    ts = timestamp or int(time.time() * 1000)
    return f'{base}-{ts}'


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def build_detached_windows_bootstrap_script(
    session_name: str,
    command_text: str,
    delay_ms: int = 2500
) -> str:
    """构建 Windows  detached 会话启动脚本（Node.js 代码）。

    用于在 Windows 上延迟启动 codex 到 tmux pane。

    Args:
        session_name: tmux 会话名
        command_text: 要执行的命令
        delay_ms: 延迟毫秒数

    Returns:
        Node.js 脚本代码
    """
    import json  # 延迟导入避免未使用错误
    delay = max(100, int(delay_ms))  # 最小 100ms
    target = json.dumps(f'{session_name}:0.0')
    cmd = json.dumps(command_text)

    return '\n'.join([
        'const { execFileSync } = require("child_process");',
        'setTimeout(() => {',
        f'  try {{ execFileSync("tmux", ["send-keys", "-t", {target}, "-l", "--", {cmd}], {{ stdio: "ignore" }}); }} catch {{}}',
        f'  try {{ execFileSync("tmux", ["send-keys", "-t", {target}, "C-m"], {{ stdio: "ignore" }}); }} catch {{}}',
        f'}}, {delay});'
    ])


def truncate_string(value: str, max_len: int = 80, suffix: str = '...') -> str:
    """截断字符串，保留尾部信息。

    适用于会话名、日志标识等有限长度的场景。

    Args:
        value: 原字符串
        max_len: 最大长度
        suffix: 截断后缀

    Returns:
        截断后字符串
    """
    if len(value) <= max_len:
        return value
    return value[:max_len - len(suffix)] + suffix


# ---------------------------------------------------------------------------
# Pattern Matching
# ---------------------------------------------------------------------------

def matches_glob(pattern: str, path: str) -> bool:
    """检查路径是否匹配 glob 模式。

    Args:
        pattern: glob 模式（支持 *, ?, []）
        path: 目标路径

    Returns:
        是否匹配
    """
    return fnmatch.fnmatch(path, pattern)

"""Platform and subprocess utilities for cross-platform command execution.

参考: oh-my-codex-main/src/utils/platform-command.ts
提供跨平台命令路径解析、Windows 特殊处理、平台命令规范构建。

设计目标:
- 统一所有子进程调用入口
- 正确处理 Windows .exe/.bat/.ps1 的包装
- 提供错误分类 (missing/blocked/error)
- 支持 retry 策略 (e.g., 用 node 运行 .js 脚本)
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum

__all__ = [
    'PlatformCommandExecutor',
    'PlatformCommandSpec',
    'ProbedPlatformCommand',
    'SpawnErrorKind',
    'build_platform_command_spec',
    'classify_spawn_error',
    'resolve_command_path_for_platform',
    'spawn_platform_command_sync',
]

# ---------------------------------------------------------------------------
# Types & Enums
# ---------------------------------------------------------------------------

class SpawnErrorKind(str, Enum):
    """子进程启动错误分类。"""
    MISSING = 'missing'      # ENOENT - 命令未找到
    BLOCKED = 'blocked'      # EPERM/EACCES - 权限不足或策略阻止
    ERROR = 'error'          # 其他错误


@dataclass(frozen=True)
class PlatformCommandSpec:
    """平台命令规范（跨平台统一描述）。"""
    command: str           # 实际执行的命令
    args: list[str]        # 参数列表
    resolved_path: str | None = None   # 解析后的完整路径（Windows）


@dataclass
class ProbedPlatformCommand:
    """命令执行结果封装。"""
    spec: PlatformCommandSpec
    result: subprocess.CompletedProcess


# ---------------------------------------------------------------------------
# Windows PATHEXT handling
# ---------------------------------------------------------------------------

WINDOWS_DEFAULT_PATHEXT = ['.com', '.exe', '.bat', '.cmd', '.ps1']
WINDOWS_DIRECT_EXTENSIONS = {'.com', '.exe'}
WINDOWS_CMD_Extensions = {'.bat', '.cmd'}
WINDOWS_EXTENSION_PRIORITY = ['.exe', '.com', '.ps1', '.cmd', '.bat']
NODE_HOSTED_SCRIPT_EXTENSIONS = {'.js', '.mjs', '.cjs'}


def _is_windows_path_like(command: str) -> bool:
    """判断是否为 Windows 绝对/相对路径格式。

    Args:
        command: 命令字符串

    Returns:
        是否类似 Windows 路径
    """
    return bool(command[:2].isalpha() and command[2:4] in (':\\', ':/')) or ('\\' in command or '/' in command)


def _normalize_windows_pathext(env: dict | None = None) -> list[str]:
    """获取排序后的 PATHEXT 扩展名列表。

    优先级: .exe, .com 优先，其余按系统顺序。
    """
    import os
    raw = (env or os.environ).get('PATHEXT', '')
    entries = [e.strip().lower() for e in raw.split(';') if e.strip()]

    ordered = list(WINDOWS_EXTENSION_PRIORITY)
    for e in entries:
        if e not in ordered:
            ordered.append(e)

    # 去重保持顺序
    seen = set()
    result = []
    for e in ordered:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result


def _classify_windows_command_path(path: str) -> str:
    """分类 Windows 命令类型。

    Returns:
        'direct'   - .exe/.com 直接执行
        'cmd'      - .bat/.cmd 需通过 cmd.exe /c
        'powershell' - .ps1 需通过 powershell.exe
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in WINDOWS_CMD_Extensions:
        return 'cmd'
    if ext == '.ps1':
        return 'powershell'
    if ext in WINDOWS_DIRECT_EXTENSIONS:
        return 'direct'
    return 'direct'


def _resolve_windows_command_path(
    command: str,
    env: dict | None = None,
    exists_fn=None
) -> str | None:
    """在 Windows 上解析命令完整路径。

    搜索顺序:
    1. 如命令含路径分隔符，直接组合候选并测试存在性
    2. 按 PATHEXT 优先级依次尝试带扩展名版本
    3. 搜索 PATH 中每个目录

    Args:
        command: 命令名（可能含路径）
        env: 环境变量（含 PATH, PATHEXT）
        exists_fn: 文件存在性检查函数（可 mock）

    Returns:
        解析后的完整路径，未找到则返回 None
    """
    env = env or os.environ
    pathext = _normalize_windows_pathext(env)
    if exists_fn is None:
        exists_fn = os.path.exists
    path_var = env.get('Path', env.get('PATH', ''))

    def add_candidates(base: str, candidates: list[str]) -> None:
        """添加基础路径的各种扩展名候选。"""
        ext = os.path.splitext(base)[1].lower()
        if ext:  # 已有扩展名 → 仅添加自身
            candidates.append(base)
            return
        for ext_name in pathext:
            candidates.append(base + ext_name)
        candidates.append(base)  # 无扩展名版本

    # 路径含分隔符 → 相对/绝对路径，不查 PATH
    if _is_windows_path_like(command):
        if os.path.isabs(command):
            base = command
        else:
            base = os.path.abspath(command)
        candidates: list[str] = []
        add_candidates(base, candidates)
        for cand in candidates:
            if exists_fn(cand):
                return cand
        return None

    # 搜索 PATH
    for entry in path_var.split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        base = os.path.join(entry, command)
        candidates = []
        add_candidates(base, candidates)
        for cand in candidates:
            if exists_fn(cand):
                return cand

    return None


def _resolve_posix_command_path(
    command: str,
    env: dict | None = None,
    exists_fn=None
) -> str | None:
    """在 POSIX 系统解析命令完整路径。

    如果命令含 '/' → 按相对/绝对路径直接解析。
    否则搜索 PATH。
    """
    env = env or os.environ
    if exists_fn is None:
        exists_fn = os.path.exists
    trimmed = command.strip()
    if not trimmed:
        return None

    # 路径含 / → 不算 PATH，直接解析
    if '/' in trimmed:
        candidate = os.path.abspath(trimmed) if not os.path.isabs(trimmed) else trimmed
        return candidate if exists_fn(candidate) else None

    # 搜索 PATH
    path_var = env.get('PATH', '')
    for entry in path_var.split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        candidate = os.path.join(entry, trimmed)
        if exists_fn(candidate):
            return candidate

    return None


# ---------------------------------------------------------------------------
# Platform Command Building
# ---------------------------------------------------------------------------

def _build_cmd_launch(command_path: str, args: list[str], env: dict) -> PlatformCommandSpec:
    """构建通过 cmd.exe /c 运行的命令规范。

    用于 .bat/.cmd 脚本，确保在正确上下文中执行。
    """

    # 构造命令行为单个字符串
    cmd_line = [command_path] + args
    # Windows 命令行引号转义
    quoted = _windows_quote_command_line(cmd_line)
    return PlatformCommandSpec(
        command=env.get('ComSpec', 'cmd.exe'),
        args=['/d', '/s', '/c', f'"{quoted}"'],
        resolved_path=command_path,
    )


def _build_powershell_launch(command_path: str, args: list[str]) -> PlatformCommandSpec:
    """构建通过 powershell.exe -File 运行的命令规范。"""
    return PlatformCommandSpec(
        command='powershell.exe',
        args=['-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', command_path, *args],
        resolved_path=command_path,
    )


def _windows_quote_command_line(args: list[str]) -> str:
    """Windows 命令行引号包装 (模拟 CommandLineToArgvW 逆向)。"""
    result = []
    for arg in args:
        if not arg:
            result.append('""')
            continue
        # 含空格或特殊字符则加双引号
        if any(c in arg for c in ' \t"'):
            # 转义内部双引号
            escaped = arg.replace('"', '\\"')
            result.append(f'"{escaped}"')
        else:
            result.append(arg)
    return ' '.join(result)


def build_platform_command_spec(
    command: str,
    args: list[str],
    platform: str = sys.platform,
    env: dict | None = None
) -> PlatformCommandSpec:
    """构建平台无关的命令执行规范。

    Windows 上处理 .bat/.ps1 自动包装，POSIX 上直接透传。

    Args:
        command: 命令名
        args: 参数列表
        platform: 目标平台标识
        env: 环境变量

    Returns:
        平台命令规范
    """
    if platform != 'win32':
        return PlatformCommandSpec(command=command, args=list(args))

    # Windows: 先解析完整路径
    resolved = _resolve_windows_command_path(command, env)
    if not resolved:
        # 未找到，返回原命令（让 spawn 报错）
        return PlatformCommandSpec(command=command, args=list(args))

    kind = _classify_windows_command_path(resolved)
    if kind == 'cmd':
        return _build_cmd_launch(resolved, args, env or os.environ)
    if kind == 'powershell':
        return _build_powershell_launch(resolved, args)

    # 直接可执行
    return PlatformCommandSpec(
        command=resolved,
        args=list(args),
        resolved_path=resolved,
    )


# ---------------------------------------------------------------------------
# Error Classification
# ---------------------------------------------------------------------------

def classify_spawn_error(error: Exception | None) -> SpawnErrorKind | None:
    """将 subprocess 异常分类。

    Args:
        error: subprocess.CalledProcessError 或 OSError

    Returns:
        错误类型枚举，非启动错误返回 None
    """
    if error is None:
        return None
    if isinstance(error, OSError):
        code = getattr(error, 'errno', None)
        if code == 2:  # ENOENT
            return SpawnErrorKind.MISSING
        if code in (13, 14):  # EACCES, EPERM
            return SpawnErrorKind.BLOCKED
    return SpawnErrorKind.ERROR


# ---------------------------------------------------------------------------
# Resolve Command Path
# ---------------------------------------------------------------------------

def resolve_command_path_for_platform(
    command: str,
    platform: str | None = None,
    env: dict | None = None,
    exists_fn=os.path.exists
) -> str | None:
    """跨平台命令路径解析。

    Args:
        command: 要查找的命令
        platform: 平台名，默认 auto
        env: 环境变量
        exists_fn: 可注入的存在性检查

    Returns:
        完整路径或 None
    """
    platform = platform or sys.platform
    if platform == 'win32':
        return _resolve_windows_command_path(command, env, exists_fn)
    return _resolve_posix_command_path(command, env, exists_fn)


# ---------------------------------------------------------------------------
# Spawn Wrapper
# ---------------------------------------------------------------------------

def spawn_platform_command_sync(
    command: str,
    args: list[str],
    options: dict | None = None,
    platform: str | None = None,
    env: dict | None = None,
    exists_fn=os.path.exists,
    spawn_fn=subprocess.run
) -> ProbedPlatformCommand:
    """同步执行平台命令，自动处理 Windows 差异。

    这是所有子进程调用的统一入口。

    Args:
        command: 命令
        args: 参数
        options: subprocess.run 选项 (如 cwd, capture_output)
        platform: 平台标识
        env: 环境变量
        exists_fn: 可注入的存在性检查（测试用）
        spawn_fn: 可注入的启动函数（测试用）

    Returns:
        命令执行结果

    Raises:
        FileNotFoundError: 命令未找到
        PermissionError: 权限不足
        subprocess.CalledProcessError: 命令执行失败
    """
    platform = platform or sys.platform
    options = options or {}
    env = env or os.environ

    spec = build_platform_command_spec(command, args, platform, env)

    # 默认选项
    run_options = dict(options)
    if platform == 'win32':
        run_options.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)

    try:
        # 合并 command 和 args 为单个参数列表
        full_args = [spec.command] + spec.args
        result = spawn_fn(full_args, **run_options, env=env)
        return ProbedPlatformCommand(spec=spec, result=result)
    except (OSError, subprocess.SubprocessError) as e:
        kind = classify_spawn_error(e)
        if kind == SpawnErrorKind.MISSING:
            raise FileNotFoundError(f"Command not found: {spec.command}") from e
        if kind == SpawnErrorKind.BLOCKED:
            raise PermissionError(f"Command blocked: {spec.command}") from e
        raise


class PlatformCommandExecutor:
    """平台命令执行器（可配置版本）。"""

    def __init__(
        self,
        platform: str | None = None,
        env: dict | None = None,
        timeout: int | None = None
    ):
        """初始化执行器。

        Args:
            platform: 平台标识
            env: 环境变量
            timeout: 默认超时（秒）
        """
        self.platform = platform or sys.platform
        self.env = env or os.environ.copy()
        self.timeout = timeout

    def run(
        self,
        command: str,
        args: list[str] = None,
        cwd: str | None = None,
        capture: bool = True,
        timeout: int | None = None
    ) -> subprocess.CompletedProcess:
        """执行命令。

        Args:
            command: 命令
            args: 参数
            cwd: 工作目录
            capture: 是否捕获输出
            timeout: 超时（覆盖默认值）

        Returns:
            完成进程结果
        """
        options = {
            'cwd': cwd or os.getcwd(),
            'timeout': timeout or self.timeout,
            'capture_output': capture,
            'text': True,
        }
        probed = spawn_platform_command_sync(
            command, args or [], options, self.platform, env=self.env
        )
        return probed.result

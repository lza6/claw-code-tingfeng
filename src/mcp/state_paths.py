"""
MCP State Paths - 状态路径管理模块

从 oh-my-codex-main/src/mcp/state-paths.ts 汲取。
管理 .omx/state 目录中的状态文件路径。

功能:
- validate_session_id(): 验证会话 ID 格式
- validate_state_mode_segment(): 验证状态模式段
- resolve_working_directory_for_state(): 解析工作目录
- get_state_dir(): 获取状态目录路径
- get_state_path(): 获取状态文件路径
- resolve_state_scope(): 解析状态作用域
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ===== 常量 =====
SESSION_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
STATE_MODE_SEGMENT_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
STATE_FILE_SUFFIX = '-state.json'
WORKDIR_ALLOWLIST_ENV = 'OMX_MCP_WORKDIR_ROOTS'


# ===== 类型定义 =====
@dataclass
class ModeStateFileRef:
    """模式状态文件引用"""
    mode: str
    path: str
    scope: str  # 'root' | 'session'


@dataclass
class ResolvedStateScope:
    """解析后的状态作用域"""
    source: str  # 'explicit' | 'session' | 'root'
    session_id: Optional[str] = None
    state_dir: str = ""


# ===== 验证函数 =====
def validate_session_id(session_id: Optional[str]) -> Optional[str]:
    """验证会话 ID 格式

    参数:
        session_id: 会话 ID

    返回:
        验证通过的 ID 或 None
    """
    if session_id is None:
        return None
    if not isinstance(session_id, str):
        raise TypeError('session_id must be a string')
    if not SESSION_ID_PATTERN.match(session_id):
        raise ValueError('session_id must match ^[A-Za-z0-9_-]{1,64}$')
    return session_id


def validate_state_mode_segment(mode: str) -> str:
    """验证状态模式段

    参数:
        mode: 模式字符串

    返回:
        验证后的模式字符串
    """
    if not isinstance(mode, str):
        raise TypeError('mode must be a string')

    normalized = mode.strip()
    if not normalized:
        raise ValueError('mode must be a non-empty string')

    if '..' in normalized:
        raise ValueError('mode must not contain ".."')

    if '/' in normalized or '\\' in normalized:
        raise ValueError('mode must not contain path separators')

    if not STATE_MODE_SEGMENT_PATTERN.match(normalized):
        raise ValueError('mode must match ^[A-Za-z0-9_-]{1,64}$')

    return normalized


def _get_state_filename(mode: str) -> str:
    """获取状态文件名"""
    return f"{validate_state_mode_segment(mode)}{STATE_FILE_SUFFIX}"


def _is_within_root(path: str, root: str) -> bool:
    """检查路径是否在根目录内"""
    rel = os.path.relpath(path, root)
    return rel == '' or (not rel.startswith('..') and not os.path.isabs(rel))


def _parse_allowed_working_directory_roots() -> list[str]:
    """解析允许的工作目录根列表"""
    raw = os.environ.get(WORKDIR_ALLOWLIST_ENV, '')
    if not isinstance(raw, str) or not raw.strip():
        return []

    roots = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            # 移除 NUL 字节
            if '\0' in part:
                raise ValueError(f'{WORKDIR_ALLOWLIST_ENV} contains an invalid root with a NUL byte')
            roots.append(os.path.abspath(part))

    return list(set(roots))


def _enforce_working_directory_policy(resolved_working_directory: str) -> None:
    """强制执行工作目录策略"""
    roots = _parse_allowed_working_directory_roots()
    if not roots:
        return

    allowed = any(_is_within_root(resolved_working_directory, root) for root in roots)
    if not allowed:
        raise ValueError(
            f'workingDirectory "{resolved_working_directory}" is outside allowed roots ({WORKDIR_ALLOWLIST_ENV})'
        )


# ===== 公共 API =====
def resolve_working_directory_for_state(working_directory: Optional[str] = None) -> str:
    """解析状态工作目录

    参数:
        working_directory: 指定的工作目录，默认当前目录

    返回:
        解析后的绝对路径
    """
    raw = working_directory.strip() if isinstance(working_directory, str) else ''

    if '\0' in raw:
        raise ValueError('workingDirectory contains a NUL byte')

    if not raw:
        cwd = os.path.abspath(os.getcwd())
        _enforce_working_directory_policy(cwd)
        return cwd

    normalized = raw
    import platform
    if platform.system() == 'Windows':
        if normalized.startswith('/mnt/'):
            # WSL path conversion
            match = re.match(r'^/mnt/([a-zA-Z])(?:/(.*))?$', normalized)
            if match:
                drive = match.group(1).upper()
                rest = match.group(2).replace('/', '\\') if match.group(2) else ''
                normalized = f"{drive}:\\{rest}"
    else:
        # Unix-like to Windows path conversion
        match = re.match(r'^([a-zA-Z]):[\\/]', normalized)
        if match:
            converted = _convert_windows_to_wsl_path(normalized)
            if converted != normalized:
                raise ValueError('workingDirectory Windows path is not available on this host')
            normalized = converted

    if '\0' in normalized:
        raise ValueError('workingDirectory contains a NUL byte')

    resolved = os.path.abspath(normalized)
    _enforce_working_directory_policy(resolved)
    return resolved


def _convert_windows_to_wsl_path(raw: str) -> str:
    """转换 Windows 路径到 WSL 路径"""
    match = re.match(r'^([a-zA-Z]):[\\/](.*)$', raw)
    if not match:
        return raw
    drive = match.group(1).lower()
    rest = (match.group(2) or '').replace('\\', '/')
    mount_root = f"/mnt/{drive}"
    if not os.path.exists(mount_root):
        return raw
    return f"{mount_root}/{rest}" if rest else mount_root


def get_base_state_dir(working_directory: Optional[str] = None) -> str:
    """获取基础状态目录

    参数:
        working_directory: 工作目录

    返回:
        .omx/state 目录路径
    """
    env_root = os.environ.get('OMX_TEAM_STATE_ROOT', '').strip()
    if (working_directory is None or working_directory == '') and env_root:
        try:
            return os.path.join(
                resolve_working_directory_for_state(env_root),
                '.omx', 'state'
            )
        except (ValueError, TypeError):
            pass

    return os.path.join(
        resolve_working_directory_for_state(working_directory),
        '.omx', 'state'
    )


def get_state_dir(working_directory: Optional[str] = None, session_id: Optional[str] = None) -> str:
    """获取状态目录

    参数:
        working_directory: 工作目录
        session_id: 会话 ID

    返回:
        状态目录路径
    """
    base = get_base_state_dir(working_directory)
    if session_id:
        return os.path.join(base, 'sessions', session_id)
    return base


def get_state_path(mode: str, working_directory: Optional[str] = None, session_id: Optional[str] = None) -> str:
    """获取状态文件路径

    参数:
        mode: 模式名称
        working_directory: 工作目录
        session_id: 会话 ID

    返回:
        状态文件完整路径
    """
    return os.path.join(
        get_state_dir(working_directory, session_id),
        _get_state_filename(mode)
    )


async def read_current_session_id(working_directory: Optional[str] = None) -> Optional[str]:
    """读取当前会话 ID

    参数:
        working_directory: 工作目录

    返回:
        会话 ID 或 None
    """
    import json
    session_path = os.path.join(get_base_state_dir(working_directory), 'session.json')
    if not os.path.exists(session_path):
        return None

    try:
        with open(session_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        session_id = data.get('session_id')
        return validate_session_id(session_id)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


async def resolve_state_scope(
    working_directory: Optional[str] = None,
    explicit_session_id: Optional[str] = None,
) -> ResolvedStateScope:
    """解析状态作用域

    参数:
        working_directory: 工作目录
        explicit_session_id: 显式指定的会话 ID

    返回:
        ResolvedStateScope 对象
    """
    validated_explicit = validate_session_id(explicit_session_id)
    if validated_explicit:
        return ResolvedStateScope(
            source='explicit',
            session_id=validated_explicit,
            state_dir=get_state_dir(working_directory, validated_explicit),
        )

    current_session_id = await read_current_session_id(working_directory)
    if current_session_id:
        return ResolvedStateScope(
            source='session',
            session_id=current_session_id,
            state_dir=get_state_dir(working_directory, current_session_id),
        )

    return ResolvedStateScope(
        source='root',
        state_dir=get_state_dir(working_directory),
    )


async def get_read_scoped_state_dirs(
    working_directory: Optional[str] = None,
    explicit_session_id: Optional[str] = None,
) -> list[str]:
    """获取读取作用域的状态目录列表

    读取优先级:
    - explicit session_id => 仅 session 路径
    - implicit current session => session 路径优先，root 作为兼容回退
    - no session => 仅 root 路径
    """
    scope = await resolve_state_scope(working_directory, explicit_session_id)

    if scope.source == 'root':
        return [scope.state_dir]

    root_dir = get_base_state_dir(working_directory)
    if scope.source == 'explicit':
        if os.path.exists(scope.state_dir):
            return [scope.state_dir]
        return [scope.state_dir, root_dir]

    # session source
    return [scope.state_dir, root_dir]


async def get_read_scoped_state_paths(
    mode: str,
    working_directory: Optional[str] = None,
    explicit_session_id: Optional[str] = None,
) -> list[str]:
    """获取读取作用域的状态文件路径列表"""
    dirs = await get_read_scoped_state_dirs(working_directory, explicit_session_id)
    filename = _get_state_filename(mode)
    return [os.path.join(d, filename) for d in dirs]


def is_mode_state_filename(filename: str) -> bool:
    """检查文件名是否为模式状态文件"""
    return filename.endswith(STATE_FILE_SUFFIX) and filename != 'session.json'


async def list_mode_state_files_with_scope_preference(
    working_directory: Optional[str] = None,
    explicit_session_id: Optional[str] = None,
) -> list[ModeStateFileRef]:
    """列出具有作用域优先级的模式状态文件

    按模式名称排序，较高优先级的作用域会覆盖同名的较低优先级文件。
    """
    read_dirs = await get_read_scoped_state_dirs(working_directory, explicit_session_id)
    root_dir = get_base_state_dir(working_directory)
    preferred: dict[str, ModeStateFileRef] = {}

    # 兼容性回退: root 在前，然后更高优先级的 scope 覆盖
    for dir_path in reversed(read_dirs):
        scope: str = 'root' if dir_path == root_dir else 'session'
        if os.path.isdir(dir_path):
            try:
                files = os.listdir(dir_path)
            except OSError:
                files = []

            for file in files:
                if is_mode_state_filename(file):
                    mode = file[:-len(STATE_FILE_SUFFIX)]
                    preferred[mode] = ModeStateFileRef(
                        mode=mode,
                        path=os.path.join(dir_path, file),
                        scope=scope,
                    )

    return sorted(preferred.values(), key=lambda x: x.mode)


# ===== 导出 =====
__all__ = [
    "validate_session_id",
    "validate_state_mode_segment",
    "resolve_working_directory_for_state",
    "get_base_state_dir",
    "get_state_dir",
    "get_state_path",
    "resolve_state_scope",
    "read_current_session_id",
    "get_read_scoped_state_dirs",
    "get_read_scoped_state_paths",
    "is_mode_state_filename",
    "list_mode_state_files_with_scope_preference",
    "ModeStateFileRef",
    "ResolvedStateScope",
]
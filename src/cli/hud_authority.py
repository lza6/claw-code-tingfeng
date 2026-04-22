"""HUD Authority - 权限和时间控制模块

从 oh-my-codex-main/src/hud/authority.ts 汲取。

功能:
- run_hud_authority_tick(): 运行 HUD 权限守护进程心跳
- 写入权限所有者文件到 .omx/state/
- 非阻塞执行，错误被吞掉以避免阻塞钩子

用法:
    from src.cli.hud_authority import run_hud_authority_tick

    # 在后台运行 HUD 权限守护进程
    await run_hud_authority_tick(cwd=".", timeout_ms=5000)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ===== 常量 =====
DEFAULT_POLL_MS = 75
DEFAULT_TIMEOUT_MS = 5_000
MIN_POLL_MS = 1
MIN_TIMEOUT_MS = 100


# ===== 类型定义 =====
@dataclass
class HudAuthorityOptions:
    """HUD Authority 选项"""
    cwd: str
    node_path: str | None = None
    package_root: str | None = None
    poll_ms: int = DEFAULT_POLL_MS
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    env: dict | None = None


@dataclass
class HudAuthorityDeps:
    """HUD Authority 依赖（用于测试注入）"""
    run_process: callable | None = None


# ===== 辅助函数 =====
def _get_default_package_root() -> str:
    """获取默认包根目录"""
    # 尝试从当前模块位置推断包根
    current_file = Path(__file__).resolve()
    # src/cli/hud_authority.py -> 项目根
    package_root = current_file.parent.parent.parent
    return str(package_root)


def _get_watcher_script_path(package_root: str) -> str:
    """获取 watcher 脚本路径"""
    return os.path.join(package_root, 'dist', 'scripts', 'notify-fallback-watcher.js')


def _get_notify_script_path(package_root: str) -> str:
    """获取 notify 脚本路径"""
    return os.path.join(package_root, 'dist', 'scripts', 'notify-hook.js')


def _ensure_state_dir(cwd: str) -> str:
    """确保状态目录存在，返回路径"""
    state_dir = os.path.join(cwd, '.omx', 'state')
    os.makedirs(state_dir, exist_ok=True)
    return state_dir


def _write_authority_owner(cwd: str, pid: int) -> None:
    """写入权限所有者文件"""
    state_dir = _ensure_state_dir(cwd)
    owner_path = os.path.join(state_dir, 'notify-fallback-authority-owner.json')

    data = {
        'owner': 'hud',
        'pid': pid,
        'cwd': cwd,
        'heartbeat_at': datetime.utcnow().isoformat() + 'Z',
    }

    try:
        with open(owner_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except OSError:
        # 非阻塞: 写入失败则静默跳过
        pass


def _default_run_process(
    node_path: str,
    args: list[str],
    cwd: str,
    env: dict,
    timeout_ms: int,
) -> None:
    """默认进程运行函数"""
    result = subprocess.run(
        [node_path] + args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_ms / 1000,
        shell=sys.platform == 'win32',
    )
    if result.returncode != 0:
        error_msg = (result.stderr or result.stdout or '').strip()
        if not error_msg:
            error_msg = f'hud authority tick failed with status {result.returncode}'
        raise RuntimeError(error_msg)


# ===== 公共 API =====
async def run_hud_authority_tick(
    cwd: str,
    node_path: str | None = None,
    package_root: str | None = None,
    poll_ms: int = DEFAULT_POLL_MS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    env: dict | None = None,
    deps: HudAuthorityDeps | None = None,
) -> None:
    """运行 HUD 权限守护进程心跳

    参数:
        cwd: 工作目录
        node_path: Node.js 路径，默认 sys.executable
        package_root: 包根目录，默认自动检测
        poll_ms: 轮询间隔（毫秒），默认 75
        timeout_ms: 超时时间（毫秒），默认 5000
        env: 环境变量，默认继承当前进程
        deps: 依赖注入（用于测试）
    """
    # 参数校验
    poll_ms = max(MIN_POLL_MS, poll_ms)
    timeout_ms = max(MIN_TIMEOUT_MS, timeout_ms)

    # 解析路径
    node_path = node_path or sys.executable
    package_root = package_root or _get_default_package_root()

    # 检查必要的脚本是否存在
    watcher_script = _get_watcher_script_path(package_root)
    notify_script = _get_notify_script_path(package_root)

    if not os.path.exists(watcher_script):
        raise FileNotFoundError(f'Watcher script not found: {watcher_script}')
    if not os.path.exists(notify_script):
        raise FileNotFoundError(f'Notify script not found: {notify_script}')

    # 写入权限所有者
    _write_authority_owner(cwd, os.getpid())

    # 构建环境变量
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    full_env['OMX_HUD_AUTHORITY'] = '1'

    # 获取运行函数
    run_process = deps.run_process if deps and deps.run_process else _default_run_process

    # 运行 watcher
    await run_process(
        node_path,
        [
            watcher_script,
            '--once',
            '--authority-only',
            '--cwd',
            cwd,
            '--notify-script',
            notify_script,
            '--poll-ms',
            str(poll_ms),
        ],
        cwd=cwd,
        env=full_env,
        timeout_ms=timeout_ms,
    )


def is_hud_authority_enabled() -> bool:
    """检查 HUD Authority 是否启用

    通过环境变量 OMX_HUD_AUTHORITY 判断。
    """
    return os.environ.get('OMX_HUD_AUTHORITY') == '1'


def read_authority_owner(cwd: str) -> dict | None:
    """读取权限所有者信息

    参数:
        cwd: 工作目录

    返回:
        权限所有者数据或 None
    """
    owner_path = os.path.join(cwd, '.omx', 'state', 'notify-fallback-authority-owner.json')
    if not os.path.exists(owner_path):
        return None

    try:
        with open(owner_path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def is_authority_owner_alive(cwd: str) -> bool:
    """检查权限所有者进程是否存活

    参数:
        cwd: 工作目录

    返回:
        进程是否存活
    """
    owner = read_authority_owner(cwd)
    if not owner:
        return False

    pid = owner.get('pid')
    if not pid:
        return False

    try:
        # Windows: 使用 tasklist 检查进程
        if sys.platform == 'win32':
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}'],
                capture_output=True,
                text=True,
                shell=True,
            )
            return str(pid) in result.stdout
        else:
            # Unix: 使用 kill -0 检查
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


# ===== 导出 =====
__all__ = [
    "HudAuthorityDeps",
    "HudAuthorityOptions",
    "is_authority_owner_alive",
    "is_hud_authority_enabled",
    "read_authority_owner",
    "run_hud_authority_tick",
]

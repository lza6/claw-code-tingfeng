"""Version Checker — 版本检查模块（从 Aider versioncheck.py 移植）

提供：
1. PyPI 版本检查
2. 自动升级提示
3. 开发版本安装

用法:
    from src.utils.version_check import check_version, install_upgrade

    # 检查更新
    has_update = check_version(io)

    # 安装最新版本
    install_upgrade(io)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from ..utils import get_logger

logger = get_logger(__name__)

# 版本检查缓存文件
VERSION_CHECK_FNAME = Path.home() / ".clawd" / "caches" / "versioncheck"

# PyPI API
PYPI_API_URL = "https://pypi.org/pypi/claw-code-tingfeng/json"


def check_version(
    just_check: bool = False,
    verbose: bool = False,
    io: Any | None = None,
) -> bool | None:
    """检查版本更新

    参数:
        just_check: 仅检查不提示
        verbose: 详细输出
        io: IO 对象（可选）

    Returns:
        是否有更新可用，或 None（检查失败）
    """
    # 检查缓存
    if not just_check and VERSION_CHECK_FNAME.exists():
        day = 60 * 60 * 24
        since = time.time() - os.path.getmtime(VERSION_CHECK_FNAME)
        if 0 < since < day:
            if verbose:
                hours = since / 60 / 60
                logger.debug(f"Too soon to check version: {hours:.1f} hours")
            return None

    try:
        import requests
    except ImportError:
        logger.debug("requests not installed, skipping version check")
        return None

    try:
        response = requests.get(PYPI_API_URL, timeout=10)
        data = response.json()
        latest_version = data["info"]["version"]

        # 获取当前版本
        try:
            from src import __version__ as current_version
        except ImportError:
            current_version = "0.0.0"

        if just_check or verbose:
            _output(f"Current version: {current_version}", io)
            _output(f"Latest version: {latest_version}", io)

        # 比较版本
        try:
            import packaging.version
            is_update_available = packaging.version.parse(latest_version) > packaging.version.parse(current_version)
        except Exception:
            is_update_available = latest_version != current_version

    except Exception as err:
        logger.warning(f"Error checking pypi for new version: {err}")
        return None
    finally:
        # 更新缓存
        VERSION_CHECK_FNAME.parent.mkdir(parents=True, exist_ok=True)
        VERSION_CHECK_FNAME.touch()

    if just_check or verbose:
        if is_update_available:
            _output("Update available", io)
        else:
            _output("No update available", io)

    if just_check:
        return is_update_available

    if not is_update_available:
        return False

    # 提示升级
    install_upgrade(io, latest_version)
    return True


def install_upgrade(io: Any | None = None, latest_version: str | None = None) -> bool:
    """安装最新版本

    参数:
        io: IO 对象
        latest_version: 最新版本号

    Returns:
        是否成功
    """
    if latest_version:
        new_ver_text = f"Newer version v{latest_version} is available."
    else:
        new_ver_text = "Install latest version?"

    _output(new_ver_text, io)

    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "claw-code-tingfeng"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            _output("Upgrade successful. Re-run to use new version.", io)
            return True
        else:
            _output(f"Upgrade failed: {result.stderr}", io)
    except Exception as e:
        _output(f"Upgrade error: {e}", io)

    return False


def install_from_main_branch(io: Any | None = None) -> bool:
    """从 main 分支安装开发版本

    参数:
        io: IO 对象

    Returns:
        是否成功
    """
    _output("Install the development version from main branch?", io)

    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "git+https://github.com/claw-code-tingfeng/claw-code-tingfeng.git"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            _output("Installation successful. Re-run to use new version.", io)
            return True
    except Exception as e:
        _output(f"Installation error: {e}", io)

    return False


def _output(msg: str, io: Any | None) -> None:
    """输出消息"""
    if io and hasattr(io, 'tool_output'):
        io.tool_output(msg)
    else:
        print(msg)


# ==================== 便捷函数 ====================

def is_latest_version() -> bool | None:
    """检查是否为最新版本（仅检查，不提示）"""
    return check_version(just_check=True)


def get_latest_version() -> str | None:
    """获取最新版本号"""
    try:
        import requests
        response = requests.get(PYPI_API_URL, timeout=10)
        data = response.json()
        return data["info"]["version"]
    except Exception:
        return None


# 导出
__all__ = [
    "check_version",
    "get_latest_version",
    "install_from_main_branch",
    "install_upgrade",
    "is_latest_version",
]

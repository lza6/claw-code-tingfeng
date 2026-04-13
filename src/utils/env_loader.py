"""零依赖 .env 文件自动加载器

功能:
- 自动查找并加载 .env 文件（从当前目录向上查找）
- 不覆盖已存在的环境变量
- 支持注释行（# 开头）和空行
- 支持 KEY=VALUE 和 KEY="VALUE" 和 KEY='VALUE' 格式
- 零外部依赖（仅使用标准库）

使用:
    from src.utils.env_loader import load_env

    load_env()  # 在应用启动时调用一次
"""
from __future__ import annotations

import os
from pathlib import Path


# 从 .features 延迟加载避免循环导入
def _init_features(workdir: Path | None):
    try:
        from .features import features
        features.initialize(workdir)
    except Exception:
        pass

logger = None

def _get_logger():
    """懒加载日志器，避免循环导入"""
    global logger
    if logger is None:
        from .logger import get_logger as _get_logger_func
        logger = _get_logger_func('env_loader')
    return logger


def load_env(env_path: Path | str | None = None) -> dict[str, str]:
    """加载 .env 文件到环境变量

    参数:
        env_path: .env 文件路径，为 None 时自动查找（从当前目录向上）

    返回:
        加载的环境变量字典
    """
    if env_path is None:
        env_path = _find_env_file()

    if env_path is None or not Path(env_path).is_file():
        _get_logger().debug('未找到 .env 文件，跳过加载')
        # 即使没有 .env，也尝试初始化特征开关 (Project B 核心逻辑)
        _init_features(None)
        return {}

    env_path = Path(env_path)
    _init_features(env_path.parent)
    _get_logger().debug(f'正在加载 .env 文件: {env_path}')

    loaded: dict[str, str] = {}
    try:
        content = env_path.read_text(encoding='utf-8')
        for line in content.splitlines():
            line = line.strip()

            # 跳过空行和注释
            if not line or line.startswith('#'):
                continue

            # 解析 KEY=VALUE
            if '=' not in line:
                continue

            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip()

            # 移除引号
            if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]

            # 不覆盖已存在的环境变量
            if key not in os.environ:
                os.environ[key] = value
                loaded[key] = value
                _get_logger().debug(f'已加载环境变量: {key}')
            else:
                _get_logger().debug(f'跳过已存在的环境变量: {key}')

        _get_logger().debug(f'已加载 {len(loaded)} 个环境变量')
        return loaded

    except (OSError, PermissionError) as e:
        _get_logger().warning(f'.env 文件加载失败: {e}')
        return {}


def _find_env_file(start_path: Path | None = None) -> Path | None:
    """从当前目录向上查找 .env 文件

    参数:
        start_path: 起始查找路径，为 None 时使用当前工作目录

    返回:
        .env 文件路径，未找到返回 None
    """
    current = Path(start_path or Path.cwd()).resolve()

    # 最多向上查找 10 层
    for _ in range(10):
        env_file = current / '.env'
        if env_file.is_file():
            return env_file

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def get_env(key: str, default: str = '') -> str:
    """获取环境变量（便捷函数）

    参数:
        key: 环境变量名称
        default: 默认值

    返回:
        环境变量值
    """
    return os.environ.get(key, default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """获取布尔环境变量

    参数:
        key: 环境变量名称
        default: 默认值

    返回:
        布尔值
    """
    value = os.environ.get(key, '').lower()
    if value in ('true', '1', 'yes', 'on'):
        return True
    if value in ('false', '0', 'no', 'off'):
        return False
    return default


def get_env_int(key: str, default: int = 0) -> int:
    """获取整数环境变量

    参数:
        key: 环境变量名称
        default: 默认值

    返回:
        整数值
    """
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default

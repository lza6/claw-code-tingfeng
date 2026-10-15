"""Clawd Code — AI 编程代理框架"""

from .core.cost_estimator import CostEstimator
from .core.events import Event, EventBus, EventType, get_event_bus
from .core.exceptions import ClawdError, ErrorCode
from .core.session_store import StoredSession, list_sessions, load_session, save_session


def _resolve_version() -> str:
    """解析版本号，保证与 pyproject.toml 单一真相源一致。

    历史问题：版本号曾被硬编码在本文件，与 pyproject.toml / README.md /
    CHANGELOG.md 各自漂移（曾同时存在 0.45.0 / 0.46.0 / 0.50.0 三个值）。
    改为按以下优先级解析，杜绝手工同步：

        1. 已安装发行版的元数据（pip install -e . 之后自动同步）
        2. 仓库根目录的 pyproject.toml（直接从源码运行时的兜底）
        3. "0.0.0+unknown"（都没有时的显式降级，而非静默给错版本）
    """
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    try:
        return _pkg_version("clawd-code")
    except PackageNotFoundError:
        pass

    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            return "0.0.0+unknown"

    pyproject = __import__("pathlib").Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        with pyproject.open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except (OSError, KeyError, ValueError):
        return "0.0.0+unknown"


__version__ = _resolve_version()

__all__ = [
    'ClawdError',
    'CostEstimator',
    'ErrorCode',
    'Event',
    'EventBus',
    'EventType',
    'StoredSession',
    '__version__',
    'get_event_bus',
    'list_sessions',
    'load_session',
    'save_session',
]


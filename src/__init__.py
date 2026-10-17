"""Clawd Code — AI 编程代理框架

## 为什么这里的导出是惰性的

`src` 包的 `__init__` 会被**任何** `import src.xxx` 触发。此前它在顶层
`from .core.cost_estimator import CostEstimator`，而 `src.core.__init__`
又导入 git_integration / hook_registry / telemetry 等一大片 ——
结果 `clawd --version` 也要先付几秒钟的导入成本。

现在改为 PEP 562 惰性属性：只有真正访问 `src.CostEstimator` 等名字时才导入。
`__version__` 仍是即时的（它只读 pyproject，代价可忽略）。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# 静态可达性锚点：运行时**不导入**（TYPE_CHECKING 恒为 False），
# 但 `scripts/reachability.py` 靠 AST 里的 import 语句建图 ——
# 只有 `_LAZY_EXPORTS` 字典而没有任何 import 语句时，这些模块会被误判为
# "生产不可达"（实测可达数从 429 掉到 427）。
if TYPE_CHECKING:  # pragma: no cover
    from .core.cost_estimator import CostEstimator
    from .core.events import Event, EventBus, EventType, get_event_bus
    from .core.exceptions import ClawdError, ErrorCode
    from .core.session_store import (
        StoredSession,
        list_sessions,
        load_session,
        save_session,
    )

#: 名字 → (子模块, 属性名)
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "CostEstimator": (".core.cost_estimator", "CostEstimator"),
    "Event": (".core.events", "Event"),
    "EventBus": (".core.events", "EventBus"),
    "EventType": (".core.events", "EventType"),
    "get_event_bus": (".core.events", "get_event_bus"),
    "ClawdError": (".core.exceptions", "ClawdError"),
    "ErrorCode": (".core.exceptions", "ErrorCode"),
    "StoredSession": (".core.session_store", "StoredSession"),
    "list_sessions": (".core.session_store", "list_sessions"),
    "load_session": (".core.session_store", "load_session"),
    "save_session": (".core.session_store", "save_session"),
}


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


def __getattr__(name: str) -> Any:
    """PEP 562：按需导入公开符号。"""
    if name in _LAZY_EXPORTS:
        module_path, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_path, __name__)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)


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

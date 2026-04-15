"""
Runtime - 运行时模块

导出运行时桥接功能。
"""

from .bridge import (
    RuntimeSnapshot,
    AuthoritySnapshot,
    read_runtime_snapshot,
    read_authority_snapshot,
    is_runtime_ready,
    get_bridge_enabled,
)


__all__ = [
    "RuntimeSnapshot",
    "AuthoritySnapshot",
    "read_runtime_snapshot",
    "read_authority_snapshot",
    "is_runtime_ready",
    "get_bridge_enabled",
]

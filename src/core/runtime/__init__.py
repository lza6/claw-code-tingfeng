"""Runtime - 运行时系统 (从 GoalX 汲取)

包含:
- LeaseManager: 心跳租约系统
"""
from .lease_manager import Lease, LeaseManager

__all__ = [
    "Lease",
    "LeaseManager",
]
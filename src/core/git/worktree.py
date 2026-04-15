"""
Worktree compatibility layer
"""

from .worktree.manager import WorktreeManager
from .worktree.merge_strategy import MergeStrategy
from .worktree.safety import SafetyChecker

__all__ = ["MergeStrategy", "SafetyChecker", "WorktreeManager"]

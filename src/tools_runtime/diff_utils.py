from __future__ import annotations

# 向后兼容导入 (v0.62.0: 逻辑已移至 src.core.patch.diff_engine)
from ..core.patch.diff_engine import (
    format_diff_summary,
    show_diff,
)

__all__ = [
    "format_diff_summary",
    "show_diff",
]

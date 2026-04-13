from __future__ import annotations

# 向后兼容导入 (v0.62.0: 逻辑已移至 src.core.patch.diff_engine)
from ..core.patch.diff_engine import (
    create_progress_bar,
    format_diff_line,
    is_diff_hunk_header,
    simple_diff,
)
from ..core.patch.diff_engine import (
    find_last_non_deleted_line as find_last_non_deleted,
)
from ..core.patch.diff_engine import (
    generate_partial_update_diff as diff_partial_update,
)
from ..core.patch.diff_engine import (
    get_diff_stats as diff_stats,
)

__all__ = [
    "create_progress_bar",
    "diff_partial_update",
    "diff_stats",
    "find_last_non_deleted",
    "format_diff_line",
    "is_diff_hunk_header",
    "simple_diff",
]

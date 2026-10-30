"""模糊匹配 —— 实现已下沉到 `src/core/patch/fuzzy_matcher.py`

保留这个模块只为兼容既有 import（`tools_runtime.code_edit.fuzzy_matcher`）；
新代码请直接用 core 的那份。
"""

from __future__ import annotations

from ...core.patch.fuzzy_matcher import (  # noqa: F401  (re-export，保持旧引用可用)
    compute_similarity,
    find_similar_lines,
    match_but_for_leading_whitespace,
    perfect_or_whitespace,
    perfect_replace,
    prep,
    replace_closest_edit_distance,
    replace_most_similar_chunk,
    replace_part_with_missing_leading_whitespace,
    try_dotdotdots,
)

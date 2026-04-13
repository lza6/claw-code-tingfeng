from __future__ import annotations

import enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class PatchOperation(str, enum.Enum):
    INSERT = "insert"
    DELETE = "delete"
    REPLACE = "replace"
    RENAME = "rename"
    DIFF = "diff"
    SEARCH_REPLACE = "search_replace"

class AtomicChange(BaseModel):
    """最小原子代码变更单元"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    op: PatchOperation
    path: Path
    line_start: int | None = None
    line_end: int | None = None
    content: str = ""
    old_content: str | None = None  # 用于安全校验 (Checksum)

class PatchResult(BaseModel):
    """补丁执行结果"""
    success: bool
    path: Path
    applied_changes: int = 0
    error_message: str | None = None
    diff_summary: str | None = None

"""
Ralph Progress Ledger - RALPH 进度账本

从 oh-my-codex-main/src/ralph/persistence.ts 汲取。
用于持久化 RALPH 循环的进度、视觉反馈和验证结果。

特点:
- PRD 迁移支持（从旧格式转换）
- 视觉反馈记录
- 稳定 JSON 序列化（键排序）
- 迁移标记
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# 常量
LEGACY_PRD_PATH = ".omx/prd.json"
LEGACY_PROGRESS_PATH = ".omx/progress.txt"
DEFAULT_VISUAL_THRESHOLD = 90
VISUAL_NEXT_ACTIONS_LIMIT = 20


def _sha256(text: str) -> str:
    """计算 SHA256 哈希"""
    return hashlib.sha256(text.encode()).hexdigest()


def _slugify(raw: str) -> str:
    """将字符串转换为 URL 友好的 slug"""
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', raw.lower())
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')[:48] or 'legacy'
    return slug


def _stable_json(value: Any) -> str:
    """稳定 JSON 序列化（键排序）"""
    if value is None or not isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, list):
        return f"[{','.join(_stable_json(item) for item in value)}]"
    # Sort keys for stability
    items = sorted(value.items(), key=lambda x: x[0])
    pairs = [f"{json.dumps(k)}:{_stable_json(v)}" for k, v in items]
    return f"{{{','.join(pairs)}}}"


def _stable_json_pretty(value: Any) -> str:
    """美化的稳定 JSON"""
    # First stable sort, then pretty print
    if isinstance(value, dict):
        sorted_dict = {k: value[k] for k in sorted(value.keys())}
        return json.dumps(sorted_dict, indent=2, ensure_ascii=False)
    return json.dumps(value, indent=2, ensure_ascii=False)


# ===== 数据类 =====

@dataclass
class RalphVisualFeedback:
    """视觉反馈"""
    score: int
    verdict: str  # "pass", "fail", "partial"
    category_match: bool
    differences: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    reasoning: str = ""
    threshold: int = DEFAULT_VISUAL_THRESHOLD


@dataclass
class RalphProgressEntry:
    """进度条目"""
    index: int
    text: str
    recorded_at: str = ""


@dataclass
class RalphProgressLedger:
    """进度账本"""
    schema_version: int = 2
    source: str = ""
    source_sha256: str = ""
    strategy: str = ""
    created_at: str = ""
    updated_at: str = ""
    entries: list[dict[str, Any]] = field(default_factory=list)
    visual_feedback: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "strategy": self.strategy,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entries": self.entries,
            "visual_feedback": self.visual_feedback,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RalphProgressLedger:
        return cls(
            schema_version=data.get("schema_version", 2),
            source=data.get("source", ""),
            source_sha256=data.get("source_sha256", ""),
            strategy=data.get("strategy", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            entries=data.get("entries", []),
            visual_feedback=data.get("visual_feedback", []),
        )


# ===== 核心函数 =====

def get_ralph_progress_path(cwd: str = ".", session_id: Optional[str] = None) -> Path:
    """获取 RALPH 进度文件路径"""
    if session_id:
        state_root = Path(cwd) / ".clawd" / "state" / session_id
    else:
        state_root = Path(cwd) / ".clawd" / "state"
    state_root.mkdir(parents=True, exist_ok=True)
    return state_root / "ralph-progress.json"


def _ensure_progress_ledger(path: Path) -> RalphProgressLedger:
    """确保进度账本文件存在"""
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return RalphProgressLedger.from_dict(data)
        except:
            pass

    now = datetime.now().isoformat()
    ledger = RalphProgressLedger(
        schema_version=2,
        created_at=now,
        updated_at=now,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(_stable_json_pretty(ledger.to_dict()) + "\n")
    return ledger


def read_ralph_progress(cwd: str = ".", session_id: Optional[str] = None) -> RalphProgressLedger:
    """读取 RALPH 进度账本"""
    path = get_ralph_progress_path(cwd, session_id)
    return _ensure_progress_ledger(path)


def add_progress_entry(
    text: str,
    cwd: str = ".",
    session_id: Optional[str] = None,
) -> RalphProgressLedger:
    """添加进度条目"""
    path = get_ralph_progress_path(cwd, session_id)
    ledger = _ensure_progress_ledger(path)

    entry = {
        "index": len(ledger.entries) + 1,
        "text": text,
        "recorded_at": datetime.now().isoformat(),
    }
    ledger.entries.append(entry)
    ledger.updated_at = datetime.now().isoformat()

    with open(path, 'w', encoding='utf-8') as f:
        f.write(_stable_json_pretty(ledger.to_dict()) + "\n")

    return ledger


def record_visual_feedback(
    feedback: RalphVisualFeedback,
    cwd: str = ".",
    session_id: Optional[str] = None,
) -> RalphProgressLedger:
    """记录视觉反馈"""
    path = get_ralph_progress_path(cwd, session_id)
    ledger = _ensure_progress_ledger(path)

    next_actions = (
        feedback.suggestions +
        [f"Resolve difference: {diff}" for diff in feedback.differences]
    )
    next_actions = [a.strip() for a in next_actions if a.strip()][:VISUAL_NEXT_ACTIONS_LIMIT]

    entry = {
        "recorded_at": datetime.now().isoformat(),
        "score": feedback.score,
        "verdict": feedback.verdict,
        "category_match": feedback.category_match,
        "threshold": feedback.threshold,
        "passes_threshold": feedback.score >= feedback.threshold,
        "differences": feedback.differences,
        "suggestions": feedback.suggestions,
        "reasoning": feedback.reasoning,
        "next_actions": next_actions,
    }

    ledger.visual_feedback.append(entry)
    # Keep only last 30 entries
    ledger.visual_feedback = ledger.visual_feedback[-30:]
    ledger.updated_at = datetime.now().isoformat()

    with open(path, 'w', encoding='utf-8') as f:
        f.write(_stable_json_pretty(ledger.to_dict()) + "\n")

    return ledger


def get_latest_visual_feedback(cwd: str = ".", session_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """获取最新的视觉反馈"""
    ledger = read_ralph_progress(cwd, session_id)
    if ledger.visual_feedback:
        return ledger.visual_feedback[-1]
    return None


def migrate_legacy_progress(
    cwd: str = ".",
    session_id: Optional[str] = None,
) -> bool:
    """迁移旧格式进度文件"""
    legacy_path = Path(cwd) / LEGACY_PROGRESS_PATH
    if not legacy_path.exists():
        return False

    canonical_path = get_ralph_progress_path(cwd, session_id)
    if canonical_path.exists():
        return False

    try:
        with open(legacy_path, 'r', encoding='utf-8') as f:
            raw = f.read()

        lines = [line.strip() for line in raw.split('\n') if line.strip()]

        ledger = RalphProgressLedger(
            schema_version=2,
            source=LEGACY_PROGRESS_PATH,
            source_sha256=_sha256(raw),
            strategy="one-way-read-only",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            entries=[
                {"index": i + 1, "text": line}
                for i, line in enumerate(lines)
            ],
        )

        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        with open(canonical_path, 'w', encoding='utf-8') as f:
            f.write(_stable_json_pretty(ledger.to_dict()) + "\n")

        return True
    except Exception:
        return False


# ===== 导出 =====
__all__ = [
    "RalphVisualFeedback",
    "RalphProgressEntry",
    "RalphProgressLedger",
    "get_ralph_progress_path",
    "read_ralph_progress",
    "add_progress_entry",
    "record_visual_feedback",
    "get_latest_visual_feedback",
    "migrate_legacy_progress",
    "DEFAULT_VISUAL_THRESHOLD",
]
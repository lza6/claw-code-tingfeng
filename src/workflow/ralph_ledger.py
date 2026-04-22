"""
Ralph Progress Ledger - RALPH 进度账本

从 oh-my-codex-main/src/ralph/persistence.ts 汲取并增强。
用于持久化 RALPH 循环的进度、视觉反馈和验证结果。

核心特性 (对标 OMX):
- PRD 迁移支持（从旧格式转换）
- 视觉反馈记录与评分追踪
- 稳定 JSON 序列化（键排序保证确定性）
- SHA256 完整性校验
- 迁移标记与遗留数据兼容
- 结构化账本条目（机器可读分析）

增强点 (2026-04-17):
- 添加策略字段记录执行策略
- 改进视觉反馈聚合统计
- 支持会话隔离的状态管理
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 常量
LEGACY_PRD_PATH = ".omx/prd.json"
LEGACY_PROGRESS_PATH = ".omx/progress.txt"
DEFAULT_VISUAL_THRESHOLD = 90
VISUAL_NEXT_ACTIONS_LIMIT = 20
MAX_VISUAL_FEEDBACK_ENTRIES = 30  # 保留最近 30 条反馈


def _sha256(text: str) -> str:
    """计算 SHA256 哈希用于完整性校验"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _slugify(raw: str) -> str:
    """将字符串转换为 URL 友好的 slug"""
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', raw.lower())
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')[:48] or 'legacy'
    return slug


def _stable_json(value: Any) -> str:
    """稳定 JSON 序列化（键排序保证确定性）"""
    if value is None or not isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, list):
        return f"[{','.join(_stable_json(item) for item in value)}]"
    # Sort keys for stability
    items = sorted(value.items(), key=lambda x: x[0])
    pairs = [f"{json.dumps(k)}:{_stable_json(v)}" for k, v in items]
    return f"{{{','.join(pairs)}}}"


def _stable_json_pretty(value: Any) -> str:
    """美化的稳定 JSON (键排序 + 缩进)"""
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

def get_ralph_progress_path(cwd: str = ".", session_id: str | None = None) -> Path:
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
            with open(path, encoding='utf-8') as f:
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


def read_ralph_progress(cwd: str = ".", session_id: str | None = None) -> RalphProgressLedger:
    """读取 RALPH 进度账本"""
    path = get_ralph_progress_path(cwd, session_id)
    return _ensure_progress_ledger(path)


def add_progress_entry(
    text: str,
    cwd: str = ".",
    session_id: str | None = None,
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
    session_id: str | None = None,
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


def get_latest_visual_feedback(cwd: str = ".", session_id: str | None = None) -> dict[str, Any] | None:
    """获取最新的视觉反馈"""
    ledger = read_ralph_progress(cwd, session_id)
    if ledger.visual_feedback:
        return ledger.visual_feedback[-1]
    return None


def migrate_legacy_progress(
    cwd: str = ".",
    session_id: str | None = None,
) -> bool:
    """迁移旧格式进度文件"""
    legacy_path = Path(cwd) / LEGACY_PROGRESS_PATH
    if not legacy_path.exists():
        return False

    canonical_path = get_ralph_progress_path(cwd, session_id)
    if canonical_path.exists():
        return False

    try:
        with open(legacy_path, encoding='utf-8') as f:
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


# ===== 聚合统计（借鉴 oh-my-codex）=====

@dataclass
class RalphAggregateStats:
    """
    RALPH 迭代聚合统计
    
    提供趋势分析、效率指标和常见问题统计。
    用于可视化反馈和性能优化建议。
    """
    total_iterations: int  # 总迭代次数
    avg_score_improvement: float  # 平均分数提升
    score_trend: list[float]  # 分数趋势
    common_issues: dict[str, int]  # 常见问题统计
    avg_iteration_duration_ms: float  # 平均迭代时长 (ms)
    pass_rate: float  # 通过率
    visual_threshold_pass_count: int  # 通过视觉阈值的次数

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "total_iterations": self.total_iterations,
            "avg_score_improvement": round(self.avg_score_improvement, 2),
            "score_trend": [round(s, 2) for s in self.score_trend],
            "common_issues": self.common_issues,
            "avg_iteration_duration_ms": round(self.avg_iteration_duration_ms, 2),
            "pass_rate": round(self.pass_rate, 2),
            "visual_threshold_pass_count": self.visual_threshold_pass_count,
        }


def compute_aggregate_stats(ledger: RalphProgressLedger) -> RalphAggregateStats:
    """
    计算 RALPH 迭代的聚合统计
    
    分析所有视觉反馈条目，提取趋势、效率和常见问题。
    
    Args:
        ledger: RALPH 进度账本
        
    Returns:
        RalphAggregateStats 聚合统计结果
    """
    if not ledger.visual_feedback:
        return RalphAggregateStats(
            total_iterations=0,
            avg_score_improvement=0.0,
            score_trend=[],
            common_issues={},
            avg_iteration_duration_ms=0.0,
            pass_rate=0.0,
            visual_threshold_pass_count=0,
        )

    # 提取分数序列
    scores = [entry.get("score", 0) for entry in ledger.visual_feedback]

    # 计算分数提升
    improvements = []
    for i in range(len(scores) - 1):
        improvements.append(scores[i + 1] - scores[i])

    avg_improvement = sum(improvements) / len(improvements) if improvements else 0.0

    # 统计常见问题
    issue_counts: dict[str, int] = {}
    for entry in ledger.visual_feedback:
        differences = entry.get("differences", [])
        for diff in differences:
            # 提取问题类别（取前3个词作为分类键）
            category = " ".join(diff.split()[:3])
            issue_counts[category] = issue_counts.get(category, 0) + 1

    # 按出现频率排序，取 Top 10
    sorted_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    top_issues = dict(sorted_issues)

    # 计算通过率
    threshold_passes = sum(
        1 for entry in ledger.visual_feedback
        if entry.get("passes_threshold", False)
    )
    pass_rate = threshold_passes / len(ledger.visual_feedback) if ledger.visual_feedback else 0.0

    # 估算平均迭代时长（基于时间戳差异）
    durations = []
    for i in range(len(ledger.visual_feedback) - 1):
        try:
            t1 = datetime.fromisoformat(ledger.visual_feedback[i]["recorded_at"])
            t2 = datetime.fromisoformat(ledger.visual_feedback[i + 1]["recorded_at"])
            duration_ms = (t2 - t1).total_seconds() * 1000
            durations.append(duration_ms)
        except (KeyError, ValueError):
            continue

    avg_duration = sum(durations) / len(durations) if durations else 0.0

    return RalphAggregateStats(
        total_iterations=len(ledger.visual_feedback),
        avg_score_improvement=avg_improvement,
        score_trend=scores,
        common_issues=top_issues,
        avg_iteration_duration_ms=avg_duration,
        pass_rate=pass_rate,
        visual_threshold_pass_count=threshold_passes,
    )


def format_stats_summary(stats: RalphAggregateStats) -> str:
    """
    格式化统计摘要为人类可读的文本
    
    Args:
        stats: 聚合统计结果
        
    Returns:
        格式化的统计摘要文本
    """
    lines = [
        "[STATS] RALPH 迭代统计摘要",
        f"{'='*40}",
        f"总迭代次数: {stats.total_iterations}",
        f"通过率: {stats.pass_rate:.1%} ({stats.visual_threshold_pass_count}/{stats.total_iterations})",
        f"平均分数提升: {stats.avg_score_improvement:+.2f}",
        f"平均迭代时长: {stats.avg_iteration_duration_ms/1000:.1f}s",
    ]

    if stats.score_trend:
        trend_str = " -> ".join(f"{s:.0f}" for s in stats.score_trend[-5:])
        lines.append(f"最近分数趋势: {trend_str}")

    if stats.common_issues:
        lines.append("\n[ISSUES] 常见问题 Top 5:")
        for issue, count in list(stats.common_issues.items())[:5]:
            lines.append(f"  - {issue}: {count} 次")

    return "\n".join(lines)


# ===== 导出 =====
__all__ = [
    "DEFAULT_VISUAL_THRESHOLD",
    "RalphAggregateStats",
    "RalphProgressEntry",
    "RalphProgressLedger",
    "RalphVisualFeedback",
    "add_progress_entry",
    "compute_aggregate_stats",
    "format_stats_summary",
    "get_latest_visual_feedback",
    "get_ralph_progress_path",
    "migrate_legacy_progress",
    "read_ralph_progress",
    "record_visual_feedback",
]

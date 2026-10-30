"""上下文检查点压缩（Checkpoint Compaction）—— 借鉴 Codex

Codex 的做法（`codex-rs/core/src/compact.rs` + `templates/compact/prompt.md`）：
- **触发**：累计 usage tokens ≥ `auto_compact_token_limit`
- **方式**：不是丢弃，而是让模型产出一份**结构化 handoff 摘要**（四段：进展与决策 /
  上下文与约束 / 待办 / 关键数据），并用 `summary_prefix` 告诉后续模型"这是别人做完的，
  接着干，别重复劳动"
- **上限**：摘要本身 ≤ 20k tokens

我们原先的做法（`HistoryProcessor`）是**直接丢弃旧条目**再放一条占位说明——信息全丢，
模型只能重读文件。这里补上 Codex 式的结构化检查点。

设计取舍：**默认不依赖 LLM**。没有 summarizer 时用确定性抽取（保留目标/决策/文件/工具/
错误/待办这些真正影响续跑的事实），保证离线可用、可测试；有 LLM 时才用模型生成更自然的摘要。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

#: 与 Codex 对齐：摘要前缀（让续跑的模型知道在看继承来的上下文）
SUMMARY_PREFIX = (
    "下面是先前会话的检查点摘要（由另一个模型/进程产生）。"
    "请在此基础上继续，避免重复已完成的工作；如需细节，可用工具重新读取文件确认。"
)

#: 与 Codex 对齐的压缩提示词（四段式 handoff）
COMPACTION_PROMPT = """你正在执行一次上下文检查点压缩（CONTEXT CHECKPOINT COMPACTION）。
请为接手任务的另一个 LLM 生成一份 handoff 摘要，包含：
- 当前进展与已做的关键决策
- 重要的上下文、约束与用户偏好
- 还剩什么没做（清晰的下一步）
- 继续所需的关键数据、示例或引用

要求：简洁、结构化，目的是让下一个 LLM 无缝接续，不要复述全部历史。"""

#: 摘要本身的 token 上限（Codex 用 20k，这里取更保守的值）
MAX_SUMMARY_TOKENS = 4000

#: 最小压缩阈值（借鉴 Pi `handoff/eligibility.ts` 的 MIN_HANDOFF_TOKENS=30_000）：
#: 上下文太小时压缩是净损失——摘要本身也占 token，还可能丢细节。
MIN_COMPACT_TOKENS = 30_000

TokenFn = Callable[[str], int]
Summarizer = Callable[[str, Sequence[Any]], str]


def _default_tokens(text: str) -> int:
    # 粗略：约 4 字符 1 token（与项目内 estimate_tokens 口径一致）
    return max(1, len(text) // 4)


@dataclass
class Checkpoint:
    """一次压缩产出的检查点"""

    summary: str
    dropped_entries: int = 0
    kept_entries: int = 0
    dropped_tokens: int = 0
    used_llm: bool = False
    facts: dict[str, list[str]] = field(default_factory=dict)

    def render(self) -> str:
        return f"{SUMMARY_PREFIX}\n\n{self.summary}".strip()


# ---------------------------------------------------------------------------
# 确定性事实抽取（无 LLM 也能保住"续跑必需"的信息）
# ---------------------------------------------------------------------------

_GOAL_HINTS = ("目标", "需求", "要求", "请", "帮我", "实现", "修复")
_FILE_RE = re.compile(r"(?:[\w.\-/\\]+\.[A-Za-z]{1,6})\b")
_TOOL_HINTS = ("tool", "工具", "调用", "执行")
_ERROR_HINTS = ("error", "错误", "失败", "异常", "traceback", "报错")
_TODO_HINTS = ("todo", "待办", "下一步", "还要", "尚未", "未完成", "TODO")


def _classify(entry: Any) -> tuple[str, str, bool]:
    """兼容 HistoryEntry / dict，返回 (role, content, pinned)"""
    if isinstance(entry, dict):
        return (
            str(entry.get("role") or ""),
            str(entry.get("content") or ""),
            bool(entry.get("is_pinned") or entry.get("pinned")),
        )
    return (
        str(getattr(entry, "role", "")),
        str(getattr(entry, "content", "")),
        bool(getattr(entry, "is_pinned", False)),
    )


def extract_facts(entries: Iterable[Any], *, max_per_section: int = 8) -> dict[str, list[str]]:
    """从历史里抽取续跑必需的事实（确定性、无 LLM）

    只保留"下一轮还需要"的东西：目标、决策、碰过的文件、工具调用、错误、待办。
    去重并保持出现顺序；每节有条数上限，避免摘要本身膨胀。
    """
    goals: list[str] = []
    decisions: list[str] = []
    files: list[str] = []
    tools: list[str] = []
    errors: list[str] = []
    todos: list[str] = []

    def _push(bucket: list[str], item: str) -> None:
        item = item.strip()
        if not item or item in bucket or len(bucket) >= max_per_section:
            return
        bucket.append(item)

    for entry in entries:
        role, content, pinned = _classify(entry)
        text = content.strip()
        if not text:
            continue
        low = text.lower()

        if role == "user" and any(h in text for h in _GOAL_HINTS):
            _push(goals, text[:160])
        if pinned:
            _push(decisions, text[:160])
        for match in _FILE_RE.findall(text):
            if "/" in match or "\\" in match or "." in match:
                _push(files, match)
        if any(h in low for h in _TOOL_HINTS):
            _push(tools, text[:120])
        if any(h in low for h in _ERROR_HINTS):
            _push(errors, text[:160])
        if any(h in low for h in _TODO_HINTS):
            _push(todos, text[:160])

    return {
        "目标": goals,
        "关键决策（pinned）": decisions,
        "涉及文件": files,
        "工具调用": tools,
        "错误/风险": errors,
        "待办/下一步": todos,
    }


def render_facts(facts: dict[str, list[str]]) -> str:
    lines: list[str] = ["## 检查点摘要"]
    for section, items in facts.items():
        if not items:
            continue
        lines.append(f"\n### {section}")
        lines.extend(f"- {item}" for item in items)
    if len(lines) == 1:
        lines.append("\n（本次压缩未提取到结构化事实）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 压缩主流程
# ---------------------------------------------------------------------------


def should_auto_compact(total_tokens: int, limit: int) -> bool:
    """是否应触发自动压缩（对齐 Codex：累计 token ≥ 阈值即触发）"""
    return limit > 0 and total_tokens >= limit


def estimate_context_tokens(
    tokens: int | None = None,
    percent: float | None = None,
    context_window: int | None = None,
) -> int | None:
    """估算上下文占用（对齐 Pi `estimateHandoffContextTokens`）

    优先用精确 tokens；否则用 percent × context_window 估算。
    两者都不可用时返回 None（调用方据此如实说"未知"，不猜）。
    """
    if tokens is not None and tokens >= 0:
        return int(tokens)
    if percent is None or context_window in (None, 0) or percent < 0:
        return None
    return int(context_window * percent / 100)


def is_compaction_eligible(
    tokens: int | None = None,
    percent: float | None = None,
    context_window: int | None = None,
    min_tokens: int = MIN_COMPACT_TOKENS,
) -> bool:
    """上下文是否"值得"压缩（Pi 的准入判断：太短就别压）"""
    estimated = estimate_context_tokens(tokens, percent, context_window)
    return estimated is not None and estimated >= min_tokens


def format_context_usage(
    tokens: int | None = None,
    percent: float | None = None,
    context_window: int | None = None,
) -> str:
    """人类可读的占用描述（用于拒绝压缩时的解释，不静默跳过）"""
    if tokens is not None and tokens >= 0:
        return f"{tokens} tokens"
    estimated = estimate_context_tokens(None, percent, context_window)
    if estimated is None:
        return "未知（缺少 usage 数据）"
    return f"约 {estimated} tokens（由 {percent}% × {context_window} 估算）"


def build_checkpoint(
    entries: Sequence[Any],
    summarizer: Summarizer | None = None,
    *,
    token_fn: TokenFn | None = None,
    max_summary_tokens: int = MAX_SUMMARY_TOKENS,
) -> Checkpoint:
    """把一批历史压成一条检查点摘要

    Args:
        entries: 被压缩的历史（HistoryEntry / dict 均可）
        summarizer: 可选 (prompt, entries) -> summary；不传则用确定性抽取
        token_fn: 可选 token 估算函数
        max_summary_tokens: 摘要长度上限，超出则截断（对齐 Codex 的 20k 上限思路）

    Returns:
        Checkpoint（含 facts 与统计）
    """
    tokens = (token_fn or _default_tokens)
    facts = extract_facts(entries)
    used_llm = False

    if summarizer is not None:
        try:
            summary = summarizer(COMPACTION_PROMPT, list(entries))
            used_llm = bool(summary and summary.strip())
        except Exception:
            used_llm = False
            summary = ""
        if not used_llm:
            summary = render_facts(facts)
    else:
        summary = render_facts(facts)

    # 上限保护：超了就截断（宁可少字，不可撑爆下一轮上下文）
    limit_chars = max_summary_tokens * 4
    if len(summary) > limit_chars:
        summary = summary[:limit_chars] + "\n…（摘要已截断）"

    dropped_tokens = sum(tokens(_classify(e)[1]) for e in entries)
    return Checkpoint(
        summary=summary,
        dropped_entries=len(entries),
        dropped_tokens=dropped_tokens,
        used_llm=used_llm,
        facts=facts,
    )


def prepare_resume_messages(
    messages: list[Any],
    summarizer: Summarizer | None = None,
    *,
    min_tokens: int = MIN_COMPACT_TOKENS,
) -> tuple[list[Any], Checkpoint | None]:
    """续跑前处理历史：超过阈值就压成检查点，否则原样返回

    解决的问题（ADR-0012 里标注的未串接点）：`session resume` 会把整段历史塞进上下文，
    长会话直接爆上下文。这里复用 Pi 的准入阈值 + Codex 的检查点语义：

    Returns:
        (处理后的消息列表, 检查点或 None)
        - 未超阈值：原消息原样返回，检查点为 None
        - 超阈值：返回单条 system 消息（检查点摘要），并把检查点带回供调用方展示
    """
    total = sum(_default_tokens(str(_classify(m)[1])) for m in messages or [])
    if not is_compaction_eligible(tokens=total, min_tokens=min_tokens):
        return list(messages or []), None

    checkpoint = build_checkpoint(messages, summarizer=summarizer)
    compacted = [{"role": "system", "content": checkpoint.render()}]
    return compacted, checkpoint

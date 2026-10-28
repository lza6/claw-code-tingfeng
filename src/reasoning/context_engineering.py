"""Context Engineering — 长会话上下文工程（参考 SWE-agent HistoryProcessor 模式）

解决长逆向会话的 token 膨胀：
- ObservationTruncator: 观察截断 + 引导性提示（超限时引导模型改用过滤/重定向）
- HistoryProcessor: 滑动窗口压缩历史，保留关键节点（决策/结论/反思）
- estimate_tokens: 粗估 token 数（中文≈1字1token，英文≈4字符1token）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """粗估 token 数：CJK 字符按 1 token，其余按 4 字符 1 token"""
    if not text:
        return 0
    cjk = len(re.findall(r"[一-鿿぀-ヿ]", text))
    other = len(text) - cjk
    return cjk + (other + 3) // 4


class ObservationTruncator:
    """观察截断器：超长观察截断并附引导性提示，帮模型改用更精确的查询"""

    def __init__(self, max_chars: int = 20000):
        self.max_chars = max_chars

    def truncate(self, observation: str, tool_name: str = "") -> str:
        if len(observation) <= self.max_chars:
            return observation
        # 保留头 2/3 + 尾 1/3（尾部常有汇总信息）
        head = observation[: int(self.max_chars * 2 / 3)]
        tail = observation[-int(self.max_chars / 3):]
        omitted = len(observation) - self.max_chars
        guide = (
            f"\n\n[输出被截断，省略 {omitted} 字符。"
            "提示：改用更精确的查询（缩小范围/加过滤条件/用 grep 工具定向搜索）"
            "或把结果重定向到文件后分段读取。]"
        )
        tool_hint = f"（工具: {tool_name}）" if tool_name else ""
        logger.info(f"观察截断{tool_hint}: {len(observation)} → {self.max_chars} 字符")
        return head + "\n...[中间内容省略]...\n" + tail + guide


@dataclass
class HistoryEntry:
    """一条历史记录"""
    role: str  # user | assistant | tool
    content: str
    is_pinned: bool = False  # 关键节点：决策/结论/反思，不参与压缩丢弃
    tokens: int = 0

    def __post_init__(self):
        if not self.tokens:
            self.tokens = estimate_tokens(self.content)


class HistoryProcessor:
    """历史压缩器：滑动窗口 + 关键节点保留

    策略：
    1. pinned 条目永远保留
    2. 非 pinned 条目从最旧开始丢弃，直到总 token ≤ 预算
    3. 被丢弃的连续区段替换为一条摘要占位
    """

    def __init__(self, token_budget: int = 60000, keep_recent: int = 5):
        self.token_budget = token_budget
        self.keep_recent = keep_recent  # 最近 N 条非 pinned 也不丢弃
        self.entries: list[HistoryEntry] = []

    def add(self, role: str, content: str, pinned: bool = False) -> None:
        self.entries.append(HistoryEntry(role=role, content=content, is_pinned=pinned))

    def total_tokens(self) -> int:
        return sum(e.tokens for e in self.entries)

    def process(self) -> list[HistoryEntry]:
        """返回压缩后的历史（不修改原 entries）"""
        kept: list[HistoryEntry | None] = list(self.entries)
        total = self.total_tokens()
        if total <= self.token_budget:
            return list(self.entries)

        # 可丢弃候选：非 pinned 且不在最近 keep_recent 条非 pinned 里
        non_pinned_idx = [i for i, e in enumerate(self.entries) if not e.is_pinned]
        droppable = set(non_pinned_idx[: max(0, len(non_pinned_idx) - self.keep_recent)])

        for i in sorted(droppable):  # 从最旧开始丢
            if total <= self.token_budget:
                break
            total -= kept[i].tokens if kept[i] else 0
            kept[i] = None

        # 压缩连续丢弃区段为**结构化检查点摘要**（借鉴 Codex：
        # 原先是丢弃后放一句"已省略 N 条"，信息全丢；现在保留目标/决策/文件/工具/错误/待办）
        from ..agent.compaction import build_checkpoint

        result: list[HistoryEntry] = []
        i = 0
        while i < len(kept):
            if kept[i] is not None:
                result.append(kept[i])
                i += 1
                continue
            j = i
            dropped: list[HistoryEntry] = []
            while j < len(kept) and kept[j] is None:
                dropped.append(self.entries[j])
                j += 1
            checkpoint = build_checkpoint(dropped)
            summary = HistoryEntry(
                role="system",
                content=(
                    f"[历史检查点: 已压缩 {len(dropped)} 条早期记录"
                    f"（约 {checkpoint.dropped_tokens} tokens）]\n"
                    f"{checkpoint.render()}"
                ),
                is_pinned=True,  # 摘要本身必须保留，否则下一轮又丢
            )
            result.append(summary)
            i = j
        logger.info(
            f"历史压缩: {len(self.entries)} 条 / {self.total_tokens()} tokens "
            f"→ {len(result)} 条 / {sum(e.tokens for e in result)} tokens"
        )
        return result

    def render(self) -> str:
        """渲染为文本（供 prompt 拼装）"""
        lines = []
        for e in self.process():
            marker = "📌 " if e.is_pinned else ""
            lines.append(f"{marker}[{e.role}] {e.content}")
        return "\n".join(lines)


def build_default_processor(token_budget: int = 60000) -> HistoryProcessor:
    """clawd 默认历史处理器"""
    return HistoryProcessor(token_budget=token_budget)

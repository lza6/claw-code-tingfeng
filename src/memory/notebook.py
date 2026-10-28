"""会话笔记本（Notebook）—— 借鉴 Pi 的 notebook 原语

Pi（`pi-agenticoding/notebook/`）的模型：
- **page（页面/主题）**：agent 与人都可以往里写内容，主题名归一化成 slug
- **active topic + boundary hint**：当前主题变更时给出提示，避免长会话跑题
- **两级式删除**（`prepareNotebookDiscard` → `commitNotebookDiscard`）：
  先"准备"（算出要删什么、留快照），等压缩真的成功后再"提交"删除。
  这样压缩失败时页面不会丢——我们照抄这个安全模型。

用途：长程任务里，把"决定/结论/接口约定"落成页面，而不是全靠上下文窗口。
"""

from __future__ import annotations

import json
import re
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PREVIEW_MAX_CHARS = 80
_TOPIC_MAX = 80


def normalize_topic(name: str) -> str:
    """主题归一化（对齐 Pi `normalizeNotebookTopic`）"""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:_TOPIC_MAX]


def format_page_preview(content: str, max_chars: int = PREVIEW_MAX_CHARS) -> str:
    text = " ".join((content or "").split())
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


@dataclass
class DiscardPlan:
    """两级式删除的"准备"结果（还没真删）"""

    token: str
    topics: list[str]
    snapshot: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @property
    def is_empty(self) -> bool:
        return not self.topics


class Notebook:
    """持久化会话笔记本（每页一个 markdown 文件 + 一个状态文件）"""

    def __init__(self, root: Path | str, *, subdir: str = ".clawd/notebook"):
        self.root = Path(root).resolve()
        self.dir = (self.root / subdir).resolve()
        self.state_file = self.dir / "_state.json"
        self._pending: dict[str, DiscardPlan] = {}

    # ---------- 内部 ----------
    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def _page_path(self, topic: str) -> Path:
        slug = normalize_topic(topic)
        if not slug:
            raise ValueError(f"主题名无效（归一化后为空）: {topic!r}")
        return self.dir / f"{slug}.md"

    def _load_state(self) -> dict[str, Any]:
        if not self.state_file.is_file():
            return {}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self._ensure_dir()
        self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 页面读写 ----------
    def save_page(self, topic: str, content: str, *, source: str = "agent") -> str:
        """写入/覆盖一页，返回归一化主题名"""
        path = self._page_path(topic)
        self._ensure_dir()
        body = content if content.endswith("\n") else content + "\n"
        path.write_text(body, encoding="utf-8")
        state = self._load_state()
        pages = state.setdefault("pages", {})
        pages[normalize_topic(topic)] = {
            "updated_at": time.time(), "source": source, "chars": len(content),
        }
        self._save_state(state)
        return normalize_topic(topic)

    def read_page(self, topic: str) -> str | None:
        path = self._page_path(topic)
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def list_pages(self) -> list[dict[str, Any]]:
        """列出页面（主题 + 预览），按更新时间倒序"""
        state = self._load_state()
        meta = state.get("pages") or {}
        items: list[dict[str, Any]] = []
        if not self.dir.is_dir():
            return items
        for path in sorted(self.dir.glob("*.md")):
            topic = path.stem
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            items.append({
                "topic": topic,
                "preview": format_page_preview(content),
                "chars": len(content),
                "updated_at": (meta.get(topic) or {}).get("updated_at", path.stat().st_mtime),
            })
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items

    def format_page_list(self) -> str:
        pages = self.list_pages()
        if not pages:
            return "（笔记本为空）"
        return "\n".join(
            f"- {p['topic']}: {p['preview']}" for p in pages
        )

    # ---------- active topic（Pi 的 boundary hint） ----------
    def set_active_topic(self, topic: str, *, source: str = "agent") -> dict[str, Any]:
        slug = normalize_topic(topic)
        if not slug:
            raise ValueError(f"主题名无效: {topic!r}")
        state = self._load_state()
        previous = state.get("active_topic")
        state["active_topic"] = slug
        state["active_topic_source"] = source
        boundary = None
        if previous and previous != slug:
            boundary = {
                "from": previous, "to": slug, "source": source,
                "hint": f"主题已从 {previous} 切换到 {slug}；"
                        f"新主题下的结论请写入笔记本对应页面。",
            }
        state["pending_boundary_hint"] = boundary
        self._save_state(state)
        return {"changed": previous != slug, "previous": previous,
                "current": slug, "boundary_hint": boundary}

    def active_topic(self) -> str | None:
        return self._load_state().get("active_topic")

    # ---------- 两级式删除（Pi: prepare → commit） ----------
    def prepare_discard(self, topics: list[str]) -> DiscardPlan:
        """准备删除：只算计划 + 留快照，不动文件

        与 Pi 的 `prepareNotebookDiscard` 同构：压缩失败时页面不会丢。
        """
        normalized = [normalize_topic(t) for t in topics]
        existing = [t for t in normalized if t and self._page_path(t).is_file()]
        snapshot = {
            t: self._page_path(t).read_text(encoding="utf-8", errors="replace")
            for t in existing
        }
        token = f"discard-{int(time.time() * 1000)}-{len(existing)}"
        plan = DiscardPlan(token=token, topics=existing, snapshot=snapshot)
        self._pending[token] = plan
        return plan

    def commit_discard(self, token: str) -> list[str]:
        """提交删除：真正删除文件（调用方须在压缩成功后调用）"""
        plan = self._pending.pop(token, None)
        if plan is None:
            raise KeyError(f"未知的删除计划: {token}（或已提交/已放弃）")
        removed: list[str] = []
        for topic in plan.topics:
            path = self._page_path(topic)
            try:
                if path.is_file():
                    path.unlink()
                    removed.append(topic)
            except OSError:
                continue
        state = self._load_state()
        pages = state.get("pages") or {}
        for topic in removed:
            pages.pop(topic, None)
        state["pages"] = pages
        self._save_state(state)
        return removed

    def abort_discard(self, token: str) -> None:
        """放弃删除计划（文件未动）"""
        self._pending.pop(token, None)

    def pending_plans(self) -> list[str]:
        return list(self._pending)

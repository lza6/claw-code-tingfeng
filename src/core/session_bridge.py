"""会话存储桥 —— 统一两套并存实现的读写（避免"接错层"）

**为什么需要**：项目里有两套会话持久化，且都指向 `.clawd/sessions/*.json`：
- `src/memory/session_manager.py`（引擎侧，消息带 role，有 status/updated_at）
- `src/core/session_store.py`（早期实现，消息是字符串元组 + tokens/cost）

两者 schema 不兼容：CLI 若只读其中一套，看另一套写入的会话就是空白/错乱。
本桥按文件内容**自动识别格式**，对外给出统一视图，并统一用引擎侧格式写盘
（这样 `clawd session` 与 Agent 运行时看到的是同一份数据）。
"""

from __future__ import annotations

import json
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(".clawd") / "sessions"  # 兼容旧调用；实际以 _default_dir() 为准


@dataclass
class SessionView:
    """统一视图（两套格式的并集）"""

    session_id: str
    title: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    status: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    turn_count: int = 0
    parent_session_id: str = ""
    summary_message_id: str = ""
    model: str = ""
    provider: str = ""
    fmt: str = "engine"  # engine | legacy
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "messages": len(self.messages),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_cost": round(self.total_cost, 6),
            "turn_count": self.turn_count,
            "parent_session_id": self.parent_session_id,
            "summary_message_id": self.summary_message_id,
            "model": self.model,
            "provider": self.provider,
            "format": self.fmt,
        }


def _default_dir() -> Path:
    """默认会话目录：跟随数据目录（桌面端在 userData 下，升级不丢）"""
    try:
        from .data_dir import data_path

        return data_path("sessions", create_dir=True)
    except Exception:  # noqa: BLE001 — 极端情况下退回旧行为
        return DEFAULT_DIR


def _dir(directory: Path | str | None) -> Path:
    return Path(directory) if directory is not None else _default_dir()


def _detect_and_parse(path: Path) -> SessionView | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    raw_messages = data.get("messages") or []
    is_engine_format = bool(raw_messages) and isinstance(raw_messages[0], dict)

    if is_engine_format:
        meta = data.get("metadata") or {}
        return SessionView(
            session_id=str(data.get("session_id") or path.stem),
            title=str(data.get("title") or ""),
            messages=[m for m in raw_messages if isinstance(m, dict)],
            status=str(data.get("status") or ""),
            created_at=float(data.get("created_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
            input_tokens=int(meta.get("input_tokens") or 0),
            output_tokens=int(meta.get("output_tokens") or 0),
            total_cost=float(meta.get("total_cost") or 0.0),
            turn_count=int(meta.get("turn_count") or 0),
            parent_session_id=str(meta.get("parent_session_id") or ""),
            summary_message_id=str(meta.get("summary_message_id") or ""),
            model=str(meta.get("model") or ""),
            provider=str(meta.get("provider") or ""),
            fmt="engine",
            metadata=meta,
        )

    # 旧格式：messages 是字符串元组
    return SessionView(
        session_id=str(data.get("session_id") or path.stem),
        title=str(data.get("title") or ""),
        messages=[{"role": "unknown", "content": str(m)} for m in raw_messages],
        created_at=float(data.get("created_at") or 0.0),
        updated_at=float(data.get("started_at") or 0.0) or path.stat().st_mtime,
        input_tokens=int(data.get("input_tokens") or 0),
        output_tokens=int(data.get("output_tokens") or 0),
        total_cost=float(data.get("total_cost") or 0.0),
        turn_count=int(data.get("turn_count") or 0),
        parent_session_id=str(data.get("parent_session_id") or ""),
        summary_message_id=str(data.get("summary_message_id") or ""),
        model=str(data.get("model") or ""),
        provider=str(data.get("provider") or ""),
        fmt="legacy",
        metadata={},
    )


def list_all(directory: Path | str | None = None) -> list[SessionView]:
    """列出全部会话（两套格式都能读），按更新时间倒序"""
    d = _dir(directory)
    if not d.is_dir():
        return []
    views: list[SessionView] = []
    for path in d.glob("*.json"):
        view = _detect_and_parse(path)
        if view is not None:
            views.append(view)
    views.sort(key=lambda v: v.updated_at or 0.0, reverse=True)
    return views


def load(session_id: str, directory: Path | str | None = None) -> SessionView:
    d = _dir(directory)
    path = d / f"{session_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"会话不存在: {path}")
    view = _detect_and_parse(path)
    if view is None:
        raise ValueError(f"会话文件损坏: {path}")
    return view


def save(session: SessionView, directory: Path | str | None = None) -> Path:
    """以**引擎格式**保存（与 Agent 运行时同源）"""
    d = _dir(directory)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{session.session_id}.json"
    now = time.time()
    meta = dict(session.metadata or {})
    meta.update({
        "input_tokens": session.input_tokens,
        "output_tokens": session.output_tokens,
        "total_cost": session.total_cost,
        "turn_count": session.turn_count,
        "parent_session_id": session.parent_session_id,
        "summary_message_id": session.summary_message_id,
        "model": session.model,
        "provider": session.provider,
    })
    payload = {
        "session_id": session.session_id,
        "user_id": session.metadata.get("user_id") if session.metadata else None,
        "title": session.title,
        "status": session.status or "completed",
        "messages": session.messages,
        "created_at": session.created_at or now,
        "updated_at": now,
        "metadata": meta,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def fork(parent_id: str, new_id: str, *, title: str = "",
         directory: Path | str | None = None) -> SessionView:
    """分叉会话（复制消息，标记 parent，不改父）"""
    parent = load(parent_id, directory)
    forked = SessionView(
        session_id=new_id,
        title=title or (f"{parent.title} (fork)" if parent.title else ""),
        messages=list(parent.messages),
        status="active",
        created_at=time.time(),
        updated_at=time.time(),
        input_tokens=parent.input_tokens,
        output_tokens=parent.output_tokens,
        total_cost=parent.total_cost,
        turn_count=parent.turn_count,
        parent_session_id=parent.session_id,
        summary_message_id=parent.summary_message_id,
        model=parent.model,
        provider=parent.provider,
        fmt="engine",
        metadata=dict(parent.metadata or {}),
    )
    save(forked, directory)
    return forked


def set_title(session_id: str, title: str, directory: Path | str | None = None) -> SessionView:
    view = load(session_id, directory)
    view.title = title
    save(view, directory)
    return view


def chain(session_id: str, directory: Path | str | None = None) -> list[str]:
    """回溯分叉链（环形保护）"""
    out: list[str] = []
    seen: set[str] = set()
    current = session_id
    while current and current not in seen:
        out.append(current)
        seen.add(current)
        try:
            current = load(current, directory).parent_session_id
        except (FileNotFoundError, ValueError):
            break
    return out


# ---------------------------------------------------------------------------
# Agent 运行时落盘（补齐"实现了但没人写"的缺口）
# ---------------------------------------------------------------------------


def persist_agent_session(
    session_id: str,
    goal: str,
    steps: list[dict[str, Any]] | None = None,
    *,
    final_result: str = "",
    total_tokens: int = 0,
    model: str = "",
    provider: str = "",
    output_tokens: int = 0,
    total_cost: float = 0.0,
    persona: str = "",
    directory: Path | str | None = None,
    workdir: str = "",
    append: bool = False,
) -> SessionView:
    """把一次 Agent 运行写入会话存储（供 `clawd session list` 看到真实数据）

    `steps` 里的**工具步骤必须保留结构**（`role="tool"` + `name` + `ok`）：
    此前一律压平成 assistant 文本，导致 `clawd explain` 只能看到"读到了文件内容"，
    却看不出"调用了哪个工具、成没成功"（真实运行发现）。
    """
    # 续聊（append=True）：在**同一会话**上追加本轮消息，而不是覆盖掉之前的对话。
    # 真实体验问题 —— 覆盖会让"点开历史继续聊"变成"历史被这一轮替换"。
    prev: SessionView | None = None
    if append and directory:
        try:
            existing_path = _dir(directory) / f"{session_id}.json"
            if existing_path.is_file():
                prev = _detect_and_parse(existing_path)
        except (OSError, ValueError):
            prev = None

    messages: list[dict[str, Any]] = list(prev.messages) if prev else []
    messages.append({"role": "user", "content": goal, "timestamp": time.time()})
    for step in steps or []:
        role = str(step.get("role") or "assistant")
        content = str(step.get("content") or "")
        if not content:
            continue
        message: dict[str, Any] = {"role": role, "content": content, "timestamp": time.time()}
        name = step.get("name")
        if name:
            message["name"] = str(name)
        if "ok" in step:
            message["ok"] = bool(step["ok"])
        messages.append(message)
    if final_result:
        last_ai = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)
        if not (last_ai and str(last_ai.get("content") or "").strip() == str(final_result).strip()):
            messages.append({"role": "assistant", "content": final_result, "timestamp": time.time()})

    view = SessionView(
        session_id=session_id,
        title=(prev.title if prev and prev.title else
               ((goal[:60] + ("…" if len(goal) > 60 else "")) if goal else "")),
        messages=messages,
        status="completed",
        created_at=(prev.created_at if prev and prev.created_at else time.time()),
        updated_at=time.time(),
        input_tokens=total_tokens,
        output_tokens=output_tokens,
        total_cost=float(total_cost),
        turn_count=max(1, sum(1 for m in messages if m.get("role") == "user")),
        model=model,
        provider=provider,
        fmt="engine",
        metadata={
            **({"persona": persona} if persona else {}),
            **({"workdir": workdir} if workdir else {}),
        },
    )
    save(view, directory)
    return view

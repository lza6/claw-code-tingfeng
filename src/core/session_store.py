from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredSession:
    """会话持久化数据模型

    v0.26.0 增强:
    - 新增 started_at, ended_at 时间戳
    - 新增 model, provider 字段
    - 新增 total_cost, turn_count 字段
    - 持久化路径改为 .clawd/sessions/
    """
    session_id: str
    messages: tuple[str, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    # v0.26.0 新增字段
    started_at: str = ''
    ended_at: str = ''
    model: str = ''
    provider: str = ''
    total_cost: float = 0.0
    turn_count: int = 0
    # v0.67.0：借鉴 OpenCode `internal/session/session.go` 的 Session 模型
    parent_session_id: str = ''   # 分叉来源（空 = 根会话）
    title: str = ''               # 人类可读标题（便于 list/恢复时辨认）
    summary_message_id: str = ''  # 指向压缩检查点消息，便于续跑时先加载摘要


DEFAULT_SESSION_DIR = Path('.clawd') / 'sessions'


def save_session(session: StoredSession, directory: Path | None = None) -> Path:
    """持久化会话到 JSON 文件"""
    target_dir = directory or DEFAULT_SESSION_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f'{session.session_id}.json'
    data = asdict(session)
    # tuple → list for JSON serialization
    data['messages'] = list(data['messages'])
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return path


def load_session(session_id: str, directory: Path | None = None) -> StoredSession:
    """从 JSON 文件加载会话"""
    target_dir = directory or DEFAULT_SESSION_DIR
    session_file = target_dir / f'{session_id}.json'
    if not session_file.exists():
        # 向后兼容：尝试旧路径
        old_dir = Path('.port_sessions')
        old_file = old_dir / f'{session_id}.json'
        if old_file.exists():
            session_file = old_file
        else:
            raise FileNotFoundError(f'会话文件不存在: {session_file} (session_id={session_id})')
    try:
        data = json.loads(session_file.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        raise ValueError(f'会话文件损坏: {session_file}: {e}') from e
    return StoredSession(
        session_id=data['session_id'],
        messages=tuple(data.get('messages', ())),
        input_tokens=data.get('input_tokens', 0),
        output_tokens=data.get('output_tokens', 0),
        started_at=data.get('started_at', ''),
        ended_at=data.get('ended_at', ''),
        model=data.get('model', ''),
        provider=data.get('provider', ''),
        total_cost=data.get('total_cost', 0.0),
        turn_count=data.get('turn_count', 0),
        parent_session_id=data.get('parent_session_id', ''),
        title=data.get('title', ''),
        summary_message_id=data.get('summary_message_id', ''),
    )


def list_sessions(directory: Path | None = None) -> list[dict]:
    """列出所有已保存的会话摘要"""
    target_dir = directory or DEFAULT_SESSION_DIR
    if not target_dir.exists():
        return []
    sessions = []
    for f in sorted(target_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            sessions.append({
                'session_id': data.get('session_id', f.stem),
                'model': data.get('model', ''),
                'started_at': data.get('started_at', ''),
                'turn_count': data.get('turn_count', 0),
                'total_cost': data.get('total_cost', 0.0),
                'title': data.get('title', ''),
                'parent_session_id': data.get('parent_session_id', ''),
                'input_tokens': data.get('input_tokens', 0),
                'output_tokens': data.get('output_tokens', 0),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return sessions


# ---------------------------------------------------------------------------
# 分叉与元数据（借鉴 OpenCode 的 ParentSessionID / Title / SummaryMessageID）
# ---------------------------------------------------------------------------


def fork_session(
    parent_id: str,
    new_id: str,
    *,
    title: str = '',
    directory: Path | None = None,
) -> StoredSession:
    """从已有会话分叉出新会话（保留历史，标记 parent）

    用途：想从某个节点走另一条路时，不必破坏原会话的历史。
    与 OpenCode 的 `ParentSessionID` 语义一致。
    """
    parent = load_session(parent_id, directory)
    forked = StoredSession(
        session_id=new_id,
        messages=parent.messages,
        input_tokens=parent.input_tokens,
        output_tokens=parent.output_tokens,
        started_at=parent.started_at,
        ended_at='',
        model=parent.model,
        provider=parent.provider,
        total_cost=parent.total_cost,
        turn_count=parent.turn_count,
        parent_session_id=parent.session_id,
        title=title or (parent.title + ' (fork)' if parent.title else ''),
        summary_message_id=parent.summary_message_id,
    )
    save_session(forked, directory)
    return forked


def update_session_meta(
    session_id: str,
    *,
    title: str | None = None,
    summary_message_id: str | None = None,
    directory: Path | None = None,
) -> StoredSession:
    """更新会话元数据（标题 / 摘要消息关联），其余字段不变"""
    from dataclasses import replace

    current = load_session(session_id, directory)
    updated = replace(
        current,
        title=current.title if title is None else title,
        summary_message_id=(
            current.summary_message_id if summary_message_id is None else summary_message_id
        ),
    )
    save_session(updated, directory)
    return updated


def session_chain(session_id: str, directory: Path | None = None) -> list[str]:
    """回溯分叉链（从当前到根会话），防止环形引用导致死循环"""
    chain: list[str] = []
    seen: set[str] = set()
    current = session_id
    while current and current not in seen:
        chain.append(current)
        seen.add(current)
        try:
            current = load_session(current, directory).parent_session_id
        except (FileNotFoundError, ValueError):
            break
    return chain

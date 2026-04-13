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
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return sessions

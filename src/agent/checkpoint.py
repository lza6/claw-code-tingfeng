"""Agent session checkpoint persistence

Save and restore agent loop state (messages, iteration, tool_call_history)
to disk so that sessions can survive crashes or restarts.
"""
from __future__ import annotations

import contextlib
import gzip
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CheckpointState:
    """可序列化的 agent 状态"""
    messages: list[dict[str, str]]
    iteration: int
    max_iterations: int
    tool_call_history: list[tuple[str, str]]
    goal: str
    timestamp: float
    model: str = ''


def _serialize_tool_history(history: list[tuple[str, str]]) -> list[list[str]]:
    return [[name, sig] for name, sig in history]


def _deserialize_tool_history(data: list[list[str]]) -> list[tuple[str, str]]:
    return [(name, sig) for name, sig in data]


def save_checkpoint(
    path: str | Path,
    messages: list[Any],
    iteration: int,
    max_iterations: int,
    tool_call_history: list[tuple[str, str]],
    goal: str,
    model: str = '',
) -> Path:
    """保存 checkpoint 到磁盘。

    参数:
        path: 保存路径（.json 或 .json.gz）
        messages: 消息列表（LLMMessage 对象或 dict）
        iteration: 当前迭代计数
        max_iterations: 最大迭代数
        tool_call_history: 工具调用历史记录
        goal: 原始目标
        model: 使用的模型名称

    返回:
        已写入的文件路径
    """
    p = Path(path)

    msg_data = []
    for m in messages:
        if isinstance(m, dict):
            msg_data.append(m)
        elif hasattr(m, 'role') and hasattr(m, 'content'):
            msg_data.append({'role': m.role, 'content': m.content})
        else:
            msg_data.append({'role': 'unknown', 'content': str(m)})

    state = {
        'messages': msg_data,
        'iteration': iteration,
        'max_iterations': max_iterations,
        'tool_call_history': _serialize_tool_history(tool_call_history),
        'goal': goal,
        'timestamp': time.time(),
        'model': model,
    }

    p.parent.mkdir(parents=True, exist_ok=True)

    if str(p).endswith('.gz'):
        raw = json.dumps(state, ensure_ascii=False, indent=2).encode('utf-8')
        p.write_bytes(gzip.compress(raw, compresslevel=6))
    else:
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

    return p


def load_checkpoint(path: str | Path) -> CheckpointState:
    """从磁盘加载 checkpoint。

    参数:
        path: checkpoint 文件路径

    返回:
        CheckpointState 实例
    """
    p = Path(path)
    raw: bytes | str
    if str(p).endswith('.gz'):
        raw = gzip.decompress(p.read_bytes())
        data = json.loads(raw.decode('utf-8'))
    else:
        raw = p.read_text(encoding='utf-8')
        data = json.loads(raw)

    return CheckpointState(
        messages=data['messages'],
        iteration=data['iteration'],
        max_iterations=data['max_iterations'],
        tool_call_history=_deserialize_tool_history(data['tool_call_history']),
        goal=data['goal'],
        timestamp=data['timestamp'],
        model=data.get('model', ''),
    )


def list_checkpoints(checkpoint_dir: str | Path) -> list[Path]:
    """列出所有 checkpoint（按时间倒序）"""
    p = Path(checkpoint_dir)
    if not p.is_dir():
        return []
    files = sorted(
        p.glob('checkpoint_*'),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return files


def cleanup_old_checkpoints(checkpoint_dir: str | Path, keep_last: int = 3) -> list[Path]:
    """清理旧 checkpoint，保留最近 N 个"""
    checkpoints = list_checkpoints(checkpoint_dir)
    to_delete = checkpoints[keep_last:]
    for cp in to_delete:
        with contextlib.suppress(OSError):
            cp.unlink()
    return to_delete

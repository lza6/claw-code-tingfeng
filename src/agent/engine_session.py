"""会话管理与持久化模块"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .engine_session_data import AgentSession


class SessionManager:
    """负责 Agent 会话生命周期、Checkpoint 和 Transcript"""

    def __init__(self, workdir: Path, transcript_path: str | None = None):
        self.workdir = workdir
        self.transcript = None
        self._init_transcript(transcript_path)

    def _init_transcript(self, transcript_path: str | None):
        try:
            from ..core.transcript import TranscriptStore
            _tp = Path(transcript_path) if transcript_path else None
            if _tp is None and self.workdir:
                _tp = self.workdir / '.clawd' / 'transcript.json'
            self.transcript = TranscriptStore(persist_path=_tp)
        except Exception:
            self.transcript = None

    def record_user_goal(self, goal: str):
        if self.transcript:
            self.transcript.append(goal, role='user')

    def record_assistant_result(self, session: AgentSession):
        if self.transcript and session.final_result:
            self.transcript.append(session.final_result, role='assistant')
            self.transcript.compact(keep_last=20)

    def save_checkpoint(
        self,
        path: str | Path | None = None,
        messages: list | None = None,
        iteration: int = 0,
        max_iterations: int = 10,
        tool_history: list[tuple[str, str]] | None = None,
        goal: str = '',
        model: str = '',
    ) -> Path:
        from .checkpoint import save_checkpoint as _save_cp
        cp_path = path or (self.workdir / '.clawd' / 'checkpoints' / f'cp_{int(time.time())}.json')
        return _save_cp(
            path=cp_path,
            messages=messages or [],
            iteration=iteration,
            max_iterations=max_iterations,
            tool_call_history=tool_history or [],
            goal=goal,
            model=model,
        )

    def load_checkpoint(self, path: str | Path) -> dict[str, Any]:
        from .checkpoint import load_checkpoint as _load_cp
        state = _load_cp(path)
        return {
            'messages': state.messages,
            'iteration': state.iteration,
            'tool_call_history': state.tool_call_history,
            'goal': state.goal,
        }

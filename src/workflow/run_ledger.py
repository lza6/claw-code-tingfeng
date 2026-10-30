"""统一运行账本视图 —— 收敛 `mode_state` 与 `ralph_ledger` 两套账本

背景（审计 2.4 风险表第三条）：
    `src/workflow/mode_state.py`（889 行，模式/阶段状态）与
    `src/workflow/ralph_ledger.py`（451 行，进度条目/统计）**语义重叠**：
    都记"长任务跑到哪了"，但格式、落盘位置、写入时机都不同 →
    中断恢复时两边可能各说一套（split-brain）。

裁定（ADR 0020）：
- **语义分家，入口归一**：`mode_state` = 状态真相（当前处于哪个模式/阶段），
  `ralph_ledger` = 进度真相（一步步做了什么）。两者职责不同，**不合并存储**；
- **读**只走 `RunLedger.snapshot()`（合并视图 + 一致性检查）；
- **写**走 `RunLedger.record_stage()`（一次写两处，避免只写一半）；
- 任何直接调用底层 manager 的新代码都应视为绕过账本，评审时要求改回本模块。

命令行：`clawd ledger [--json]`（快照 + 一致性诊断）。
"""
from __future__ import annotations

import logging

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 两个账本的 updated_at 相差超过这个秒数，就认为可能 split-brain
DRIFT_SECONDS = 3600


@dataclass
class ModeRecord:
    mode: str
    task: str = ""
    phase: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "task": self.task, "phase": self.phase, "updated_at": self.updated_at}


@dataclass
class RunSnapshot:
    modes: list[ModeRecord] = field(default_factory=list)
    progress: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "modes": [m.to_dict() for m in self.modes],
            "progress_count": len(self.progress),
            "progress": self.progress[-20:],
            "stats": self.stats,
            "consistent": self.consistent,
            "issues": self.issues,
        }

    def summary_line(self) -> str:
        state = "一致" if self.consistent else f"{len(self.issues)} 项不一致"
        mode = self.modes[0].mode if self.modes else "(无模式)"
        return f"账本[{mode}] 模式 {len(self.modes)} 个 · 进度 {len(self.progress)} 条 · {state}"


class RunLedger:
    """两套账本的统一读写门面"""

    def __init__(self, cwd: str | Path = ".") -> None:
        self.cwd = str(Path(cwd))

    # ---------- 底层访问 ----------
    def _mode_manager(self):
        from .mode_state import ModeStateManager

        return ModeStateManager(self.cwd)

    def _read_progress(self):
        from .ralph_ledger import read_ralph_progress

        return read_ralph_progress(self.cwd)

    # ---------- 读 ----------
    def snapshot(self) -> RunSnapshot:
        snap = RunSnapshot()
        modes_dir = Path(self.cwd) / ".clawd" / "state"
        if modes_dir.is_dir():
            for path in sorted(modes_dir.glob("mode-*.json")):
                try:
                    import json

                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                snap.modes.append(ModeRecord(
                    mode=str(data.get("mode") or path.stem.replace("mode-", "")),
                    task=str(data.get("task") or "")[:120],
                    phase=str(data.get("current_phase") or ""),
                    updated_at=str(data.get("updated_at") or ""),
                ))
        try:
            ledger = self._read_progress()
            snap.progress = list(getattr(ledger, "entries", []) or [])
            try:
                from .ralph_ledger import compute_aggregate_stats

                snap.stats = (compute_aggregate_stats(ledger).to_dict()
                              if hasattr(compute_aggregate_stats(ledger), "to_dict")
                              else dict(compute_aggregate_stats(ledger)))
            except Exception as exc:  # noqa: BLE001 — 统计失败不影响快照
                logger.debug(f"统计计算失败: {exc}")
        except Exception as exc:  # noqa: BLE001
            snap.issues.append(f"读取 ralph 进度失败: {type(exc).__name__}: {exc}")

        snap.issues.extend(self._consistency_issues(snap))
        return snap

    def _consistency_issues(self, snap: RunSnapshot) -> list[str]:
        issues: list[str] = []
        if snap.modes and not snap.progress:
            issues.append("mode_state 里有模式状态，但 ralph 进度为空（只写了一本账）")
        if snap.progress and not snap.modes:
            issues.append("ralph 有进度条目，但找不到对应的模式状态（孤儿进度）")
        if snap.modes and snap.progress:
            last_mode = snap.modes[-1].updated_at
            last_progress = str(snap.progress[-1].get("recorded_at") or "")
            if last_mode and last_progress:
                try:
                    from datetime import datetime

                    dm = datetime.fromisoformat(last_mode).timestamp()
                    dp = datetime.fromisoformat(last_progress).timestamp()
                    if abs(dm - dp) > DRIFT_SECONDS:
                        issues.append(
                            f"两本账更新时间相差 {int(abs(dm - dp) // 60)} 分钟（> {DRIFT_SECONDS // 60}），可能 split-brain"
                        )
                except ValueError as exc:
                    # 时间戳格式不认识（旧数据/手改）→ 跳过这条漂移判断，但要留痕
                    logger.debug(f"账本时间戳无法解析（跳过漂移判断）: {last_progress!r} / {exc}")
        return issues

    # ---------- 写 ----------
    def record_stage(self, mode: str, phase: str, note: str = "", task: str = "") -> bool:
        """写一个阶段：状态写 mode_state、进度写 ralph_ledger（一次写两处）

        返回 True 表示**两本账都写成功**；只成功一本会返回 False 并记录原因，
        避免调用方以为"记上了"。
        """
        ok_state = False
        ok_progress = False
        try:
            manager = self._mode_manager()
            state = manager.read_state(mode)
            if state is None:
                manager.start_mode(mode, task or mode)
                state = manager.read_state(mode)
            if state is not None:
                manager.update_state(mode, {"current_phase": phase})
                ok_state = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"写 mode_state 失败: {exc}")

        try:
            from .ralph_ledger import add_progress_entry

            add_progress_entry(f"[{mode}] {phase}{(' — ' + note) if note else ''}", cwd=self.cwd)
            ok_progress = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"写 ralph_ledger 失败: {exc}")

        if ok_state and ok_progress:
            return True
        logger.warning(f"账本只写了一半: mode_state={ok_state} ralph_ledger={ok_progress}")
        return False


def ledger_snapshot(cwd: str | Path = ".") -> RunSnapshot:
    return RunLedger(cwd).snapshot()


__all__ = ["DRIFT_SECONDS", "ModeRecord", "RunLedger", "RunSnapshot", "ledger_snapshot"]

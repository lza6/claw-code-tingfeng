"""pipeline 必须把**用户目标**传给每个阶段（真实入口级回归）

真实缺陷（Critic 实跑发现，v0.88.9 修复前）：

    $ asyncio.run(p.run("实现一个登录接口"))
    阶段真正拿到的 ctx.task = '52b9551adf3d'   # ← session_id 的 hex 串
    ctx.session_id           = '52b9551adf3d'

根因：`PipelineModeState` 没有 `task` 字段，`_initialize_state(task, ...)` 收到的目标
初始化完就丢了，构建 `StageContext` 时只能填 `session_id`。
后果：`TeamExecStage` / `RalplanStage` 全程在跑一个 hex 串当任务。

**这个测试必须走真实 `run()` 入口** —— 手工构造 `StageContext(task=...)` 会让缺陷永远看不见
（这正是上一版测试假绿的原因）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.workflow.pipeline import PipelineOrchestrator, PipelineModeState
from src.workflow.types import PipelineStage, StageContext, StageResult, StageStatus


class _ProbeStage(PipelineStage):
    """记录它实际收到的 ctx（不做事）"""

    def __init__(self, sink: dict[str, Any], name: str = "probe") -> None:
        self._sink = sink
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def can_skip(self, ctx: StageContext) -> bool:
        return False

    async def run(self, ctx: StageContext) -> StageResult:
        self._sink["task"] = ctx.task
        self._sink["session_id"] = ctx.session_id
        self._sink["cwd"] = ctx.cwd
        return StageResult(status=StageStatus.SUCCESS, artifacts={})


def _run(tmp_path: Path, task: str) -> dict[str, Any]:
    sink: dict[str, Any] = {}
    orch = PipelineOrchestrator(workdir=tmp_path, enable_persistence=False)
    orch.configure([_ProbeStage(sink)])
    asyncio.run(orch.run(task))
    return sink


class TestTaskPropagation:
    def test_stage_receives_real_task(self, tmp_path: Path):
        sink = _run(tmp_path, "实现一个登录接口")

        assert sink["task"] == "实现一个登录接口", f"阶段拿到的不是用户目标: {sink['task']!r}"
        assert sink["task"] != sink["session_id"], "task 又被 session_id 顶替了"

    def test_task_survives_multiple_stages(self, tmp_path: Path):
        a: dict[str, Any] = {}
        b: dict[str, Any] = {}
        orch = PipelineOrchestrator(workdir=tmp_path, enable_persistence=False)
        orch.configure([_ProbeStage(a, "s1"), _ProbeStage(b, "s2")])
        asyncio.run(orch.run("修一个 bug"))

        assert a["task"] == b["task"] == "修一个 bug"

    def test_state_persists_task_field(self):
        state = PipelineModeState(
            active=True, pipeline_name="p", pipeline_stages=[], pipeline_stage_index=0,
            pipeline_stage_results={}, current_phase="idle", session_id="s1",
            created_at="2026-01-01T00:00:00Z", task="目标是这个",
        )
        assert state.to_dict()["task"] == "目标是这个"
        assert PipelineModeState.from_dict(state.to_dict()).task == "目标是这个"

    def test_from_dict_tolerates_old_state_without_task(self):
        """旧状态文件没有 task 字段，不能因此 TypeError"""
        old = {
            "active": True, "pipeline_name": "p", "pipeline_stages": [],
            "pipeline_stage_index": 0, "pipeline_stage_results": {},
            "current_phase": "idle", "session_id": "s1",
            "created_at": "2026-01-01T00:00:00Z",
        }
        state = PipelineModeState.from_dict(old)
        assert state.task == ""
        assert state.session_id == "s1"

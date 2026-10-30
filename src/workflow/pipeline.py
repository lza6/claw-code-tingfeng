"""Pipeline Orchestrator — 可配置阶段式执行管道

借鉴 oh-my-codex 的 Pipeline 设计，将固定 5 阶段重构为可配置、可组合的阶段式架构。
支持阶段跳过、状态持久化、恢复执行和 artifact 传递。

设计原则:
- 单一职责：每个阶段只负责一个明确目标
- 组合模式：主管道组合各阶段，不继承
- 向后兼容：保持原有 WorkflowEngine API 不变
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.events import Event, EventBus, EventType, get_event_bus
from ..core.exceptions import ClawdError, ErrorCode
from .types import (
    PipelineStage,
    StageContext,
    StageResult,
    StageStatus,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Pipeline 状态管理
# ============================================================================

@dataclass
class PipelineModeState:
    """Pipeline 模式状态（持久化用）

    用于跨会话恢复和状态查询。保存 pipeline 执行的完整状态，
    包括当前阶段、已完成的阶段结果、artifacts 等。
    """
    active: bool
    pipeline_name: str
    pipeline_stages: list[str]
    pipeline_stage_index: int
    pipeline_stage_results: dict[str, dict[str, Any]]
    current_phase: str
    session_id: str
    created_at: str
    #: 用户给的目标（真实缺陷：此前没有这个字段，`run(task)` 的目标初始化后就丢了，
    #: 每个阶段拿到的是 session_id 那串 hex —— team-exec/ralplan 全程在跑空任务）
    task: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)
    max_ralph_iterations: int = 10
    worker_count: int = 2
    agent_type: str = "executor"
    version: str = "1.0"
    updated_at: str | None = None

    def __post_init__(self):
        if self.updated_at is None:
            self.updated_at = self.created_at

    def touch(self):
        """更新修改时间戳"""
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（用于 JSON 持久化）"""
        d = asdict(self)
        # 确保枚举值正确
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineModeState:
        """从字典反序列化（兼容旧状态文件）

        旧文件没有 `task` 字段，直接 `cls(**data)` 会 TypeError；
        这里只取已知字段，缺失的走 dataclass 默认值。
        """
        from dataclasses import fields as _fields

        known = {f.name for f in _fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class PipelineOrchestrator:
    """Pipeline 编排器

    负责阶段式顺序执行、状态持久化、恢复支持和 artifact 传递。

    特性:
    - 可配置阶段序列
    - 自动跳过满足条件的阶段
    - 状态持久化到 .clawd/state/pipeline.json
    - 支持从失败阶段恢复
    - 事件驱动架构
    - 异步执行支持
    """

    def __init__(
        self,
        workdir: Path | None = None,
        event_bus: EventBus | None = None,
        enable_persistence: bool = True,
    ) -> None:
        """初始化 Pipeline 编排器

        Args:
            workdir: 工作目录（默认当前目录）
            event_bus: 事件总线（可选）
            enable_persistence: 是否启用状态持久化
        """
        self.workdir = workdir or Path.cwd()
        self._event_bus = event_bus or get_event_bus()
        self.enable_persistence = enable_persistence
        self._state_file = self.workdir / ".clawd" / "state" / "pipeline.json"
        self._logger = logger

        # 运行时状态
        self._stages: list[PipelineStage] = []
        self._state: PipelineModeState | None = None
        self._session_id: str = str(uuid.uuid4().hex[:12])
        self._start_time: float | None = None

        # 统计信息
        self._total_stages_executed = 0
        self._total_duration_ms = 0

    # -----------------------------------------------------------------------
    # 配置
    # -----------------------------------------------------------------------

    def configure(self, stages: list[PipelineStage]) -> PipelineOrchestrator:
        """配置执行阶段序列

        Args:
            stages: 阶段列表，按执行顺序排列

        Returns:
            self（支持链式调用）

        Example:
            >>> orchestrator = PipelineOrchestrator()
            >>> orchestrator.configure([
            ...     create_ralplan_stage(),
            ...     create_team_exec_stage(worker_count=3),
            ...     create_ralph_verify_stage(max_iterations=10),
            ... ])
        """
        self._stages = stages
        stage_names = [s.name for s in stages]
        self._logger.info(f"Pipeline configured with stages: {stage_names}")
        return self

    # -----------------------------------------------------------------------
    # 执行入口
    # -----------------------------------------------------------------------

    async def run(
        self,
        task: str,
        initial_artifacts: dict[str, Any] | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        """执行 Pipeline

        Args:
            task: 任务描述
            initial_artifacts: 初始 artifacts（用于传递上下文）
            resume: 是否从上次中断处恢复

        Returns:
            最终 artifacts 集合（包含所有阶段的产出）

        Raises:
            ClawdError: 配置错误或阶段执行失败
            Exception: 未捕获的执行异常

        Note:
            - 如果 resume=True，会尝试从 .clawd/state/pipeline.json 恢复
            - 恢复后会跳过已完成的阶段
            - 状态会在每个阶段后持久化
        """
        if not self._stages:
            raise ClawdError(
                ErrorCode.CONFIG_MISSING,
                "Pipeline stages not configured. Call configure() first."
            )

        self._logger.info(
            f"Pipeline starting (session={self._session_id}, "
            f"task={task[:50]}, resume={resume})"
        )
        self._start_time = time.time()

        # 发送启动事件
        await self._emit_event("pipeline.start", {
            "session_id": self._session_id,
            "task": task,
            "stages": [s.name for s in self._stages],
        })

        try:
            # 加载或初始化状态
            if resume:
                self._state = self._load_state()
                if not self._state or not self._state.active:
                    self._logger.warning("No resumable state found, starting fresh")
                    resume = False

            if not resume:
                self._initialize_state(task, initial_artifacts or {})

            # 执行阶段循环
            final_artifacts = await self._execute_stages()

            # 回写 artifacts 到状态（否则 get_artifact() 恒 None、状态文件 artifacts 恒空）
            self._state.artifacts = dict(final_artifacts)

            # 标记完成
            self._state.active = False
            self._state.current_phase = "complete"
            self._state.touch()
            self._save_state()

            # 统计
            self._total_duration_ms = int((time.time() - self._start_time) * 1000)
            self._logger.info(
                f"Pipeline completed in {self._total_duration_ms}ms "
                f"({self._total_stages_executed} stages executed)"
            )

            # 发送完成事件
            await self._emit_event("pipeline.complete", {
                "session_id": self._session_id,
                "duration_ms": self._total_duration_ms,
                "artifacts_count": len(final_artifacts),
            })

            return final_artifacts

        except Exception as e:
            self._logger.error(f"Pipeline failed: {e}", exc_info=True)
            if self._state:
                self._state.active = False
                self._state.current_phase = "failed"
                self._state.touch()
                self._save_state()

            # 发送失败事件
            await self._emit_event("pipeline.failed", {
                "session_id": self._session_id,
                "error": str(e),
            })

            raise

    # -----------------------------------------------------------------------
    # 内部实现
    # -----------------------------------------------------------------------

    def _initialize_state(
        self,
        task: str,
        initial_artifacts: dict[str, Any],
    ) -> None:
        """初始化 pipeline 状态"""
        stage_names = [s.name for s in self._stages]

        self._state = PipelineModeState(
            active=True,
            pipeline_name="default",
            pipeline_stages=stage_names,
            pipeline_stage_index=0,
            pipeline_stage_results={},
            current_phase=f"stage:{stage_names[0]}" if stage_names else "idle",
            session_id=self._session_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            task=str(task or ""),
            artifacts=initial_artifacts,
        )

        self._ensure_state_dir()
        self._save_state()

        self._logger.info(f"Pipeline state initialized (session={self._session_id})")

    def _load_state(self) -> PipelineModeState | None:
        """从磁盘加载持久化状态"""
        if not self._state_file.exists():
            return None

        try:
            with open(self._state_file, encoding='utf-8') as f:
                data = json.load(f)

            state = PipelineModeState.from_dict(data)
            self._logger.info(
                f"Pipeline state loaded (session={state.session_id}, "
                f"stage_index={state.pipeline_stage_index})"
            )
            return state
        except Exception as e:
            self._logger.error(f"Failed to load pipeline state: {e}")
            return None

    def _save_state(self) -> None:
        """保存状态到磁盘"""
        if not self.enable_persistence or not self._state:
            return

        self._ensure_state_dir()

        try:
            # 原子写入：先写临时文件，再重命名
            temp_file = self._state_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self._state.to_dict(), f, indent=2, ensure_ascii=False)
            temp_file.replace(self._state_file)
        except Exception as e:
            self._logger.error(f"Failed to save pipeline state: {e}")

    def _ensure_state_dir(self) -> None:
        """确保状态目录存在"""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    async def _execute_stages(self) -> dict[str, Any]:
        """顺序执行所有阶段

        Returns:
            最终 artifacts 集合
        """
        start_index = self._state.pipeline_stage_index
        artifacts = dict(self._state.artifacts)

        self._logger.info(
            f"Executing stages from index {start_index}/{len(self._stages)}"
        )

        for i in range(start_index, len(self._stages)):
            stage = self._stages[i]
            stage_start = time.time()

            # 构建上下文
            ctx = StageContext(
                # 用真实目标；老状态文件没有 task 时才退回 session_id（并会在下面告警）
                task=self._state.task or self._state.session_id,
                artifacts=artifacts,
                previous_stage_result=None,  # TODO: 传递前一阶段结果
                cwd=self.workdir,
                session_id=self._state.session_id,
                pipeline_config=self._state.to_dict(),
            )

            # 检查是否应该跳过
            if stage.can_skip(ctx):
                self._logger.info(f"Stage '{stage.name}' can be skipped")
                result = stage._skip("Condition met for skipping")
            else:
                # 执行阶段
                self._logger.info(f"Executing stage '{stage.name}'")
                self._state.current_phase = f"stage:{stage.name}"
                self._state.pipeline_stage_index = i
                self._state.touch()
                self._save_state()

                try:
                    result = await stage.run(ctx)
                    self._total_stages_executed += 1
                except Exception as e:
                    # 阶段抛出异常，转换为 FAILED 状态
                    result = StageResult(
                        status=StageStatus.FAILED,
                        error=str(e),
                    )

            result.duration_ms = int((time.time() - stage_start) * 1000)

            # 记录结果
            self._state.pipeline_stage_results[stage.name] = {
                "status": result.status.value,
                "duration_ms": result.duration_ms,
                "error": result.error,
                "skipped_reason": result.skipped_reason,
            }
            self._state.touch()
            self._save_state()

            # 合并 artifacts
            artifacts.update(result.artifacts)

            # 处理失败
            if result.status == StageStatus.FAILED:
                error_msg = f"Stage '{stage.name}' failed: {result.error}"
                self._logger.error(error_msg)
                raise ClawdError(
                    ErrorCode.WORKFLOW_EXECUTION_ERROR,
                    error_msg,
                )

        return artifacts

    # -----------------------------------------------------------------------
    # 状态查询
    # -----------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """获取当前 pipeline 状态

        Returns:
            状态字典，包含：
            - active: 是否正在运行
            - session_id: 会话 ID
            - current_phase: 当前阶段名称
            - current_stage_index: 当前阶段索引
            - completed_stages: 已完成阶段列表
            - artifacts_count: artifacts 数量
        """
        if not self._state:
            return {"active": False, "message": "No pipeline running"}

        stage_names = self._state.pipeline_stages
        current_index = self._state.pipeline_stage_index

        return {
            "active": self._state.active,
            "session_id": self._state.session_id,
            "current_phase": self._state.current_phase,
            "current_stage_index": current_index,
            "current_stage": stage_names[current_index]
                if current_index < len(stage_names) else None,
            "completed_stages": list(self._state.pipeline_stage_results.keys()),
            "artifacts_count": len(self._state.artifacts),
            "total_stages": len(stage_names),
            "progress": f"{current_index}/{len(stage_names)}",
            "created_at": self._state.created_at,
            "updated_at": self._state.updated_at,
        }

    def cancel(self) -> None:
        """取消 pipeline 执行"""
        if self._state:
            self._state.active = False
            self._state.current_phase = "cancelled"
            self._state.touch()
            self._save_state()
            self._logger.info("Pipeline cancelled")

    def list_stages(self) -> list[str]:
        """列出所有配置的阶段名称"""
        return [s.name for s in self._stages]

    def get_artifact(self, key: str, default: Any = None) -> Any:
        """获取指定 artifact"""
        if self._state:
            return self._state.artifacts.get(key, default)
        return default

    # -----------------------------------------------------------------------
    # 事件
    # -----------------------------------------------------------------------

    async def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """发送事件"""
        try:
            event = Event(
                type=EventType(event_type),
                source="pipeline",
                data=data,
            )
            await self._event_bus.emit(event)
        except Exception as e:
            self._logger.debug(f"Failed to emit event {event_type}: {e}")


# ============================================================================
# 内置阶段工厂
# ============================================================================

def create_ralplan_stage() -> PipelineStage:
    """创建 RALPLAN 共识规划阶段

    该阶段集成 Planner、Architect、Critic 三方博弈，生成:
    - 实施计划 (plan)
    - 产品需求文档 (prd)
    - 测试规范 (test_spec)

    Returns:
        配置好的 RALPLAN 阶段实例
    """

    class RalplanStage(PipelineStage):
        _logger = logger  # 基类不提供；类属性避免每个 __init__ 都要设置
        @property
        def name(self) -> str:
            return "ralplan"

        async def run(self, ctx: StageContext) -> StageResult:
            self._logger.info("Running RALPLAN consensus planning")

            # 接入真实规划引擎（此前是返回 "<未实现>" 的占位实现，
            # 却仍报 SUCCESS —— 会让调用方以为计划已经产出）。
            try:
                from .ralplan import RalplanEngine

                engine = RalplanEngine(workdir=Path(ctx.cwd), max_rounds=1)
                plan = await engine.run(ctx.task)
            except Exception as exc:
                self._logger.error("RALPLAN 阶段失败: %s: %s", type(exc).__name__, exc)
                return StageResult(
                    status=StageStatus.FAILED,
                    artifacts={"plan_implemented": False, "planning_completed": False},
                    error=f"RALPLAN 失败: {type(exc).__name__}: {exc}",
                )

            artifacts = {
                # chosen_option 是 PlanOption 对象，artifacts 要能 JSON 序列化，
                # 只保留名称；完整信息在 prd/tasks 里。
                "plan": (plan.chosen_option.name if plan.chosen_option else ""),
                "prd": plan.prd,
                "test_spec": plan.tasks,
                "confidence": plan.confidence,
                "risks": plan.risks,
                "plan_implemented": True,
                "planning_completed": True,
            }

            return StageResult(
                status=StageStatus.SUCCESS,
                artifacts=artifacts,
            )

    return RalplanStage()


def _finish_team_state(stage, ctx, member_ids: list[str], *, ok: bool, note: str) -> None:
    """收尾：把成员状态与最终阶段写回团队状态文件（失败只记 debug，不影响主流程）"""
    try:
        from .team_persistence import (
            add_team_message,
            read_team_state,
            update_member_status,
            write_team_state,
        )

        now = datetime.now().isoformat()
        _sid = getattr(ctx, "session_id", None) or None
        for mid in member_ids:
            update_member_status(mid, "idle" if ok else "offline", cwd=str(ctx.cwd), session_id=_sid)
        state = read_team_state(str(ctx.cwd), session_id=_sid)
        state.phase = "completed" if ok else "failed"
        state.completed_at = now
        write_team_state(state, str(ctx.cwd), session_id=_sid)
        add_team_message(member_id="system", content=note, msg_type="system",
                         cwd=str(ctx.cwd), session_id=_sid)
    except Exception as exc:  # noqa: BLE001
        stage._logger.debug("团队状态收尾失败（不影响结果）: %s: %s", type(exc).__name__, exc)


def create_team_exec_stage(
    worker_count: int = 2,
    agent_type: str = "executor",
) -> PipelineStage:
    """创建 Team 执行阶段

    该阶段使用 Swarm 引擎并行执行任务。

    Args:
        worker_count: worker 数量（并发度）
        agent_type: agent 类型（executor/architect/auditor）

    Returns:
        配置好的 Team 执行阶段实例
    """
    class TeamExecStage(PipelineStage):
        _logger = logger  # 基类不提供；类属性避免每个 __init__ 都要设置
        def __init__(self, worker_count: int, agent_type: str):
            self.worker_count = worker_count
            self.agent_type = agent_type

        @property
        def name(self) -> str:
            return "team-exec"

        def can_skip(self, ctx: StageContext) -> bool:
            # 如果已有执行结果，可跳过
            return "execution_result" in ctx.artifacts

        async def run(self, ctx: StageContext) -> StageResult:
            self._logger.info(
                f"Running team-exec with {self.worker_count} "
                f"{self.agent_type} workers"
            )

            # 团队状态落盘（此前 `team_persistence` 270 行只有 re-export、零调用点）
            team_started_at = datetime.now().isoformat()
            _sid = getattr(ctx, "session_id", None) or None
            member_ids: list[str] = []
            try:
                from .team_persistence import (
                    TeamMemberState,
                    add_team_member,
                    add_team_message,
                    read_team_state,
                    update_member_status,
                    write_team_state,
                )

                state = read_team_state(str(ctx.cwd), session_id=_sid)
                state.task = (ctx.task or "")[:500]
                state.phase = "executing"
                state.started_at = state.started_at or team_started_at
                state.team_id = state.team_id or f"team-{int(time.time())}"
                write_team_state(state, str(ctx.cwd), session_id=_sid)
                for idx in range(max(1, self.worker_count)):
                    mid = f"worker-{idx + 1}"
                    added = add_team_member(
                        TeamMemberState(
                            id=mid, name=mid, role=self.agent_type, status="busy",
                            current_task=(ctx.task or "")[:120],
                            joined_at=team_started_at, last_active_at=team_started_at,
                        ),
                        str(ctx.cwd), session_id=_sid,
                    )
                    if added:
                        member_ids.append(mid)
                add_team_message(
                    member_id="system",
                    content=f"team-exec 开始：{self.worker_count} × {self.agent_type}",
                    msg_type="system",
                    cwd=str(ctx.cwd),
                    session_id=_sid,
                )
            except Exception as exc:  # noqa: BLE001 — 状态落盘失败不能挡住真正执行
                self._logger.debug("团队状态落盘失败（不影响执行）: %s: %s", type(exc).__name__, exc)

            # 接入真实 Swarm 引擎（此前是返回 "<未实现>" 的占位实现，
            # 却仍报 SUCCESS —— 会让调用方以为 worker 真的执行过）。
            try:
                from ..agent.swarm.config import SwarmConfig
                from ..agent.swarm.engine import SwarmEngine

                engine = SwarmEngine(
                    config=SwarmConfig(
                        max_workers=max(1, self.worker_count),
                        fallback_to_single_agent=True,
                    ),
                    workdir=Path(ctx.cwd),
                    intent=self.agent_type,
                )
                result = await engine.run(ctx.task)
            except BaseException as exc:  # noqa: BLE001 — 含 CancelledError/KeyboardInterrupt
                # 异常/取消也要收尾，否则 team-state.json 永远停在 "executing"、
                # 成员一直是 busy（R8）。收尾后再按语义决定是否继续抛。
                _finish_team_state(self, ctx, member_ids, ok=False,
                                   note=f"team-exec 异常: {type(exc).__name__}: {exc}")
                if not isinstance(exc, Exception):
                    raise  # CancelledError / KeyboardInterrupt 不能吞掉
                self._logger.error("team-exec 阶段失败: %s: %s", type(exc).__name__, exc)
                return StageResult(
                    status=StageStatus.FAILED,
                    artifacts={"execution_implemented": True, "execution_completed": False},
                    error=f"team-exec 失败: {type(exc).__name__}: {exc}",
                )

            artifacts = {
                "execution_result": (result.final_result or "")[:4000],
                "worker_count": self.worker_count,
                "agent_type": self.agent_type,
                "elapsed_seconds": getattr(result, "elapsed_seconds", 0),
                "errors": list(getattr(result, "errors", []) or [])[:10],
                "execution_implemented": True,
                "execution_completed": bool(result.success),
            }

            _finish_team_state(
                self, ctx, member_ids, ok=bool(result.success),
                note=f"team-exec 结束：success={bool(result.success)} errors={artifacts['errors']}",
            )
            return StageResult(
                status=StageStatus.SUCCESS if result.success else StageStatus.FAILED,
                artifacts=artifacts,
                error=None if result.success else "; ".join(artifacts["errors"]) or "执行失败",
            )

    return TeamExecStage(worker_count, agent_type)


def create_ralph_verify_stage(
    max_iterations: int = 10,
) -> PipelineStage:
    """创建 Ralph 验证阶段

    **本阶段只做一次真实验证**，不做迭代重试：
    验证失败后没有任何"重新实现"步骤，重复执行同一条命令只会得到同样结果
    （原 docstring 声称"持久循环"，与实现不符，已更正）。

    Args:
        max_iterations: 仅为配置兼容而保留，会记录进 artifacts，但当前不触发重试。

    Returns:
        配置好的 Ralph 验证阶段实例
    """
    class RalphVerifyStage(PipelineStage):
        _logger = logger  # 基类不提供；类属性避免每个 __init__ 都要设置
        def __init__(self, max_iterations: int):
            self.max_iterations = max_iterations

        @property
        def name(self) -> str:
            return "ralph-verify"

        async def run(self, ctx: StageContext) -> StageResult:
            self._logger.info(
                f"Running ralph-verify (max_iterations={self.max_iterations})"
            )

            # 真实验证：跑命令并以退出码判定，而不是返回硬编码结果。
            #
            # 历史：这里曾固定返回 "verification_result": "passed" ——
            # 从不运行任何测试却永远报告通过。v0.55.0 改成诚实的
            # "not_implemented"，现在接上真实执行器。
            #
            # 状态语义：
            #   passed          → SUCCESS
            #   failed / timeout / error → FAILED（让管道停下来，而不是继续假装完成）
            #   not_configured  → SKIPPED（没配置验证，不冒充通过）
            from .verification_runner import run_verification

            vr = run_verification(Path(ctx.cwd))

            artifacts = {
                "verification_result": vr.status,
                "verified": vr.verified,
                "iterations": 1,
                "max_iterations": self.max_iterations,
                "verification_completed": vr.status in ("passed", "failed"),
                **vr.to_artifacts(),
                "evidence": vr.result.to_dict(),
            }
            if self.max_iterations > 1:
                artifacts["note"] = (
                    "本阶段为单次验证；验证失败后没有重新实现步骤，"
                    "因此不会重复执行同一命令（max_iterations 仅记录，不触发重试）"
                )

            if vr.status == "passed":
                return StageResult(status=StageStatus.SUCCESS, artifacts=artifacts)
            if vr.status == "not_configured":
                return StageResult(
                    status=StageStatus.SKIPPED,
                    artifacts=artifacts,
                    skipped_reason=vr.reason,
                )
            return StageResult(
                status=StageStatus.FAILED,
                artifacts=artifacts,
                error=vr.reason,
            )

    return RalphVerifyStage(max_iterations)


def create_precontext_intake_stage() -> PipelineStage:
    """创建 Pre-context Intake 阶段

    该阶段在任务执行前自动收集上下文，创建快照。
    如果任务模糊，会触发澄清流程。

    Returns:
        配置好的 Intake 阶段实例
    """

    class PreContextIntakeStage(PipelineStage):
        _logger = logger  # 基类不提供；类属性避免每个 __init__ 都要设置
        @property
        def name(self) -> str:
            return "precontext-intake"

        async def run(self, ctx: StageContext) -> StageResult:
            self._logger.info("Running pre-context intake")

            # 真实的最小上下文摄入：扫描目标目录的源码文件并给出摘要。
            #
            # 历史：这里 `from .intake import IntakeGate` —— 该模块**从未存在**，
            # 异常被捕获后仍返回 SUCCESS，等于永远"成功"地什么都没做。
            # 现改为不依赖任何占位模块的真实扫描。
            try:
                root = Path(ctx.cwd)
                py_files = sorted(
                    (p for p in root.rglob("*.py") if p.is_file()),
                    key=lambda p: p.stat().st_size,
                    reverse=True,
                )[:2000]

                key_files = [str(p.relative_to(root)) for p in py_files[:10]]
                total_lines = 0
                for p in py_files:
                    try:
                        with p.open(encoding="utf-8", errors="replace") as fh:
                            total_lines += sum(1 for _ in fh)
                    except OSError:
                        continue

                artifacts = {
                    "codebase_summary": (
                        f"{len(py_files)} Python files, {total_lines} lines; "
                        f"largest: {', '.join(key_files[:3]) or '(none)'}"
                    ),
                    "key_files": key_files,
                    "file_count": len(py_files),
                    "line_count": total_lines,
                    "intake_completed": True,
                }

                self._logger.info(
                    "Context intake: %d files / %d lines", len(py_files), total_lines
                )
                return StageResult(status=StageStatus.SUCCESS, artifacts=artifacts)
            except Exception as e:
                # Intake 失败不应阻止 pipeline，但**不能报 SUCCESS**：
                # 用 SKIPPED 表示"本阶段没做成事但允许继续"。
                self._logger.warning(f"Intake failed: {e}")
                return StageResult(
                    status=StageStatus.SKIPPED,
                    artifacts={"intake_failed": True, "intake_error": str(e)},
                    skipped_reason=f"Intake 失败: {type(e).__name__}: {e}",
                )

    return PreContextIntakeStage()


# ============================================================================
# Pipeline 配置工厂
# ============================================================================

def create_autopilot_pipeline_config(
    task: str,
    stages: list[PipelineStage] | None = None,
    worker_count: int = 2,
    max_ralph_iterations: int = 10,
    enable_intake: bool = True,
) -> dict[str, Any]:
    """创建 Autopilot Pipeline 配置

    默认管道: Precontext Intake → RALPLAN → team-exec → ralph-verify

    Args:
        task: 任务描述
        stages: 自定义阶段列表（为 None 则使用默认）
        worker_count: Team 执行阶段的工作器数量
        max_ralph_iterations: Ralph 验证阶段的最大迭代次数
        enable_intake: 是否启用 Pre-context Intake 阶段

    Returns:
        包含 stages、session_id 等信息的配置字典
    """
    if stages is None:
        stages = []

        # 1. Pre-context Intake（可选）
        if enable_intake:
            stages.append(create_precontext_intake_stage())

        # 2. RALPLAN 共识规划
        stages.append(create_ralplan_stage())

        # 3. Team 执行
        stages.append(create_team_exec_stage(
            worker_count=worker_count,
            agent_type="executor",
        ))

        # 4. Ralph 验证
        stages.append(create_ralph_verify_stage(
            max_iterations=max_ralph_iterations,
        ))

    return {
        "task": task,
        "stages": stages,
        "worker_count": worker_count,
        "max_ralph_iterations": max_ralph_iterations,
        "enable_intake": enable_intake,
        "session_id": str(uuid.uuid4().hex[:12]),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# 便捷函数
# ============================================================================

async def run_pipeline(
    task: str,
    workdir: Path | None = None,
    worker_count: int = 2,
    max_iterations: int = 10,
    **kwargs,
) -> dict[str, Any]:
    """快速执行 Pipeline（单函数入口）

    Args:
        task: 任务描述
        workdir: 工作目录
        worker_count: worker 数量
        max_iterations: Ralph 最大迭代次数
        **kwargs: 传递给 PipelineOrchestrator 的其他参数

    Returns:
        执行结果 artifacts
    """
    config = create_autopilot_pipeline_config(
        task=task,
        worker_count=worker_count,
        max_ralph_iterations=max_iterations,
    )

    orchestrator = PipelineOrchestrator(workdir=workdir, **kwargs)
    orchestrator.configure(config["stages"])

    return await orchestrator.run(task)

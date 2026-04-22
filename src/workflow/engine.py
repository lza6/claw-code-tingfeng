"""Workflow Engine — 5 阶段执行管道 (重构版 - 模块化)

Phase 1 (IDENTIFY) → 扫描/画像/发现优化点 → CodeScanner
Phase 2 (PLAN)     → 生成 TODO 列表，动态拆分 → TaskPlanner
Phase 3 (EXECUTE)  → 逐步执行 + 逐步验证 + 全量验证 → HealableExecutor
Phase 4 (REVIEW)   → 全局审查 + 清理 + 文档 + 完成报告 → ReviewDiscoverer
Phase 5 (DISCOVER) → 发现新优化点 → 如果有 → 回 Phase 1 迭代 → ReviewDiscoverer

设计原则:
- 单一职责：每个模块只负责一个阶段
- 组合模式：主引擎组合各模块，不继承
- 向后兼容：保持原有 API 不变
"""

from __future__ import annotations

import ast
import asyncio
import logging
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from ..agent.swarm.debate import DebateEngine
from ..agent.swarm.message_bus import MessageBus
from ..agent.swarm.orchestrator import OrchestratorAgent
from ..brain.world_model import RepositoryWorldModel
from ..core.budget_guard import BudgetGuard, parse_budget_string
from ..core.events import Event, EventBus, EventType, get_event_bus
from ..core.exceptions import ClawdError, ErrorCode
from ..core.git.worktree import WorktreeManager
from ..core.intervention import InterventionLogger
from ..core.liveness import LivenessMonitor
from ..core.observability import StructuredLogger
from ..core.persistence.run_state import RunStateManager
from ..core.resource_monitor import ResourceMonitor
from ..core.runtime.host import RuntimeHost
from ..llm.model_manager import ModelManager
from ..mcp import get_state_server
from ..memory.manager import MemoryManager
from ..memory.models import JournalEntry
from ..rag.code_graph import CodeGraph
from .assurance import AssuranceManager
from .code_scanner import CodeIssue
from .code_scanner_engine import CodeScanner
from .contract import ContractManager
from .feedback_loop import ExceptionFeedbackLoop
from .healable_executor import HealableExecutor
from .models import (
    ObjectiveClause,
    ObjectiveClauseKind,
    ObjectiveContract,
    ObjectiveRequiredSurface,
    WorkflowIntent,
    WorkflowPhase,
    WorkflowPhaseCategory,
    WorkflowResult,
    WorkflowStatus,
    WorkflowTask,
)
from .objective import GoalItem, GoalItemRole, GoalState
from .quality_debt import QualityDebtCollector
from .review_discoverer import ReviewDiscoverer
from .task_planner import TaskPlanner


class WorkflowEngine:
    """五阶段工作流执行引擎 — 模块化版本

    组合以下模块:
    - CodeScanner: 代码扫描 (Phase 1)
    - TaskPlanner: 任务规划 (Phase 2)
    - HealableExecutor: 自愈执行 (Phase 3)
    - ReviewDiscoverer: 审查与发现 (Phase 4 & 5)
    """

    def __init__(
        self,
        workdir: Path | None = None,
        max_iterations: int = 3,
        event_bus: EventBus | None = None,
        enable_feedback_loop: bool = True,
        experience_storage_path: Path | None = None,
        enable_meta_self_correction: bool = True,
        budget_str: str | None = None,
        intent: WorkflowIntent = WorkflowIntent.DELIVER,
    ) -> None:
        self.logger = logging.getLogger("workflow.engine")
        self.workdir = workdir or Path.cwd()
        self.max_iterations = max_iterations
        self._event_bus = event_bus or get_event_bus()
        self._is_running = False
        self._enable_meta_self_correction = enable_meta_self_correction
        self.intent = intent

        # 结构化日志
        self._slogger = StructuredLogger(
            component="workflow_engine",
            log_file=self.workdir / "logs" / "workflow.jsonl",
        )

        # 初始化各模块（懒加载）
        self._code_scanner: CodeScanner | None = None
        self._code_graph: CodeGraph | None = None
        self._task_planner: TaskPlanner | None = None
        self._executor: HealableExecutor | None = None
        self._reviewer: ReviewDiscoverer | None = None

        # 自愈式异常反馈回路
        self._enable_feedback_loop = enable_feedback_loop
        self._feedback_loop: ExceptionFeedbackLoop | None = None
        self._experience_storage_path = experience_storage_path
        if enable_feedback_loop:
            self._feedback_loop = ExceptionFeedbackLoop(
                workdir=self.workdir,
                event_bus=self._event_bus,
                experience_storage=experience_storage_path,
            )

        # Meta-Self-Correction 懒加载
        self._meta_correction = None

        # 整合 goalx 状态
        self.goal_state = GoalState()
        self.debt_collector = QualityDebtCollector(str(self.workdir))
        self._debate_engine = None
        self.current_contract: ObjectiveContract | None = None
        self._memory_manager = MemoryManager(use_sqlite=True)  # 集成记忆管理器

        # GoalX 基础设施
        self.contract_manager = ContractManager(ModelManager())
        self.worktree_manager = WorktreeManager(self.workdir)
        from ..llm.prompts.protocol_manager import ProtocolManager
        self.protocol_manager = ProtocolManager()
        self.resource_monitor = ResourceMonitor()
        self._use_isolation = (self.workdir / ".git").exists()

        # [新增] 集成 OMX 状态管理
        self.state_manager = get_state_server(self.workdir / ".clawd" / "state")
        self.liveness_monitor = None
        self.budget_guard = BudgetGuard(parse_budget_string(budget_str))
        self.assurance_manager = None
        self.intervention_logger = None
        self.runtime_host: RuntimeHost | None = None

    def _get_meta_correction(self):
        """懒加载 Meta-Self-Correction"""
        if self._meta_correction is None and self._enable_meta_self_correction:
            try:
                from ..self_healing.experience_bank import VectorExperienceBank
                from ..self_healing.meta_self_correction import MetaSelfCorrection

                exp_dir = self.workdir / ".clawd" / "experience"
                bank = VectorExperienceBank(exp_dir)
                bank.load()
                self._meta_correction = MetaSelfCorrection(experience_bank=bank)
            except Exception as e:
                self.logger.warning(f"Meta-Self-Correction 初始化失败: {e}")
                self._meta_correction = None
        return self._meta_correction

    # 向后兼容静态方法（委托给 TaskPlanner）
    @staticmethod
    def _safe_parse_ast(source: str, filename: str):
        """安全解析 AST (向后兼容)"""
        try:
            return ast.parse(source, filename=filename)
        except SyntaxError:
            return None

    @staticmethod
    def _consolidate_similar_tasks(tasks: list[WorkflowTask]) -> list[WorkflowTask]:
        """合并同类型问题 (向后兼容 - 委托给 TaskPlanner)"""
        return TaskPlanner._consolidate_similar_tasks(tasks)

    @staticmethod
    def _split_tasks(tasks: list[WorkflowTask]) -> list[WorkflowTask]:
        """拆分任务 (向后兼容 - 委托给 TaskPlanner)"""
        return TaskPlanner._split_tasks(tasks)

    def _scan_codebase(self):
        """向后兼容: 委托给 CodeScanner"""
        scanner = self._get_code_scanner()
        return scanner.scan_codebase("")

    # 向后兼容: 修复策略委托给 HealableExecutor
    def _fix_long_function(self, task: WorkflowTask) -> str:
        return self._get_executor()._fix_long_function(task)

    def _fix_deep_nesting(self, task: WorkflowTask) -> str:
        return self._get_executor()._fix_deep_nesting(task)

    def _fix_import_star(self, task: WorkflowTask) -> str:
        return self._get_executor()._fix_import_star(task)

    def _fix_bare_except(self, task: WorkflowTask) -> str:
        return self._get_executor()._fix_bare_except(task)

    def _fix_long_lines(self, task: WorkflowTask) -> str:
        return self._get_executor()._fix_long_lines(task)

    def _parse_file_location(self, desc: str) -> dict[str, str] | None:
        return HealableExecutor._parse_file_location(desc)

    async def _execute_with_healing(
        self, task: WorkflowTask
    ) -> tuple[str, WorkflowStatus, bool]:
        """向后兼容: 委托给 HealableExecutor"""
        return await self._get_executor().execute_with_healing(task)

    def _get_code_scanner(self) -> CodeScanner:
        """获取或创建 CodeScanner"""
        if self._code_scanner is None:
            self._code_scanner = CodeScanner(self.workdir)
        return self._code_scanner

    def _get_task_planner(self) -> TaskPlanner:
        """获取 TaskPlanner (静态方法包装)"""
        if self._task_planner is None:
            self._task_planner = TaskPlanner()
        return self._task_planner

    def _get_executor(self) -> HealableExecutor:
        """获取或创建 HealableExecutor"""
        if self._executor is None:
            self._executor = HealableExecutor(
                workdir=self.workdir,
                feedback_loop=self._feedback_loop,
                meta_correction=self._get_meta_correction(),
                event_bus=self._event_bus,
                intent="implement",  # 显式设置意图
                worktree_manager=self.worktree_manager,
                assurance_manager=self.assurance_manager,
            )
        return self._executor

    def _get_reviewer(self) -> ReviewDiscoverer:
        """获取或创建 ReviewDiscoverer"""
        if self._reviewer is None:
            self._reviewer = ReviewDiscoverer(
                workdir=self.workdir,
                event_bus=self._event_bus,
            )
        return self._reviewer

    # ===== 公共接口 =====

    async def run(
        self, goal: str, recover: bool = False, intent: WorkflowIntent | None = None
    ) -> WorkflowResult:
        """执行完整 5 阶段工作流 (汲取 GoalX 核心演进逻辑)"""
        self._is_running = True
        if intent:
            self.intent = intent

        # 0. 初始化运行环境
        # 汲取 GoalX: 自动生成或恢复 Run ID
        run_id = None
        if recover:
            # 尝试查找最近的运行记录
            runs_dir = self.workdir / ".clawd" / "runs"
            if runs_dir.exists():
                existing_runs = sorted(
                    [d.name for d in runs_dir.iterdir() if d.is_dir()], reverse=True
                )
                if existing_runs:
                    run_id = existing_runs[0]
                    self.logger.info(f"正在恢复最近的运行: {run_id}")

        if not run_id:
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.logger.info(f"启动新运行: {run_id}")

        self.state_manager = RunStateManager(self.workdir, run_id)
        self.assurance_manager = AssuranceManager(
            self.workdir, run_id, surface_manager=self.state_manager.surface_manager
        )
        self.budget_guard = BudgetGuard(
            self.budget_guard.config, str(self.workdir / ".clawd" / "runs" / run_id)
        )
        self.liveness_monitor = LivenessMonitor(
            str(self.workdir / ".clawd" / "runs" / run_id), self.resource_monitor
        )
        self.intervention_logger = InterventionLogger(
            str(self.workdir / ".clawd" / "runs" / run_id)
        )
        # 启动 RuntimeHost (心跳/资源监控/优雅停机)
        self.runtime_host = RuntimeHost(
            run_dir=self.workdir / ".clawd" / "runs" / run_id,
            session_id=run_id,
            resource_monitor=self.resource_monitor,
        )
        await self.runtime_host.start()
        self._use_isolation = (self.workdir / ".git").exists()

        self.budget_guard.start()
        phase_summaries: dict[WorkflowPhase, str] = {}
        all_tasks: list[WorkflowTask] = []
        optimization_points: list[str] = []
        start_iteration = 0

        # 1. 恢复或初始化持久化状态 (Durable State)
        if recover:
            cached = self.state_manager.load()
            if cached:
                self.logger.info(
                    f"从持久化状态恢复工作流 (Run ID: {self.state_manager.run_dir.name})..."
                )
                state = cached.get("state", cached)
                goal = state.get("goal", goal)
                self.intent = WorkflowIntent(state.get("intent", self.intent.value))
                start_iteration = state.get("iteration", 0)
                optimization_points = state.get("optimization_points", [])

                # 恢复合同与义务
                # 已在下方的合同签署/恢复部分处理

                # 恢复任务列表
                cached_tasks = state.get("tasks", [])
                for ct_data in cached_tasks:
                    try:
                        # 汲取 GoalX: 处理枚举和嵌套结构
                        ct_data_clean = {
                            k: v for k, v in ct_data.items() if k != "updated_at"
                        }
                        if "phase" in ct_data_clean:
                            ct_data_clean["phase"] = WorkflowPhase(
                                ct_data_clean["phase"]
                            )
                        if "status" in ct_data_clean:
                            ct_data_clean["status"] = WorkflowStatus(
                                ct_data_clean["status"]
                            )

                        # 恢复维度
                        from .models import (
                            Dimension,
                            DimensionSource,
                            DispatchableSlice,
                        )

                        if "dimensions" in ct_data_clean:
                            ct_data_clean["dimensions"] = [
                                Dimension(
                                    name=d["name"],
                                    guidance=d["guidance"],
                                    source=DimensionSource(d["source"]),
                                )
                                for d in ct_data_clean["dimensions"]
                            ]

                        # 恢复切片
                        if "slices" in ct_data_clean:
                            ct_data_clean["slices"] = [
                                DispatchableSlice(**s) for s in ct_data_clean["slices"]
                            ]

                        t = WorkflowTask(**ct_data_clean)

                        # [Phase 6] Session Persistence: 处理处于 RUNNING 状态的遗留任务
                        if t.status == WorkflowStatus.RUNNING and t.worktree_id:
                            # 检查隔离环境是否仍然有效
                            wt_path = self.workdir / ".clawd" / "worktrees" / t.worktree_id
                            if not wt_path.exists():
                                self.logger.warning(f"任务 {t.task_id} 的隔离环境已丢失，将其重置为 PENDING。")
                                t = replace(t, status=WorkflowStatus.PENDING, worktree_id=None)
                                self.state_manager.update_task(t.task_id, WorkflowStatus.PENDING, worktree_id=None)

                        all_tasks.append(t)
                    except Exception as e:
                        self.logger.warning(
                            f"恢复任务 {ct_data.get('task_id')} 失败: {e}"
                        )

                self._publish(
                    EventType.WORKFLOW_STARTED, {"goal": goal, "recovered": True}
                )
            else:
                self.logger.warning("未找到可恢复的状态，将从头开始。")
                self._publish(EventType.WORKFLOW_STARTED, {"goal": goal})
        else:
            self._publish(EventType.WORKFLOW_STARTED, {"goal": goal})

        # 2. [汲取 GoalX] 目标合同签署阶段 (Contract Signing)
        # 这是最高层级的持久化表面，一旦锁定，后续所有义务必须覆盖合同条款。
        self.current_contract = None
        if not recover:
            try:
                self._publish(EventType.WORKFLOW_PHASE_STARTED, {"phase": "contract"})
                self.current_contract = await self.contract_manager.sign_contract(goal)
                self.state_manager.save_contract(self.current_contract)
                self.logger.info("执行契约已签署并通过持久化确认。")
                self._publish(EventType.WORKFLOW_PHASE_COMPLETED, {"phase": "contract"})
            except Exception as e:
                self.logger.warning(f"契约签署过程出现异常: {e}")
        else:
            contract_data = self.state_manager.load_contract()
            if contract_data:
                try:
                    clauses = [
                        ObjectiveClause(
                            id=c["id"],
                            text=c["text"],
                            kind=ObjectiveClauseKind(c["kind"]),
                            source_excerpt=c["source_excerpt"],
                            required_surfaces=[
                                ObjectiveRequiredSurface(s)
                                for s in c.get("required_surfaces", [])
                            ],
                        )
                        for c in contract_data.get("clauses", [])
                    ]

                    self.current_contract = ObjectiveContract(
                        version=contract_data.get("version", 1),
                        objective_hash=contract_data.get("objective_hash", ""),
                        state=contract_data.get("state", "locked"),
                        clauses=clauses,
                        created_at=contract_data.get("created_at", ""),
                        locked_at=contract_data.get("locked_at", ""),
                    )
                except Exception as e:
                    self.logger.warning(f"从持久化状态恢复合同失败: {e}")

        # [Phase 6] 渲染主协议 (Protocol Template)
        try:
            protocol_data = self.protocol_manager.get_default_data(
                self.workdir, run_id, goal, self.intent.value
            )
            # 如果有当前合同，添加合同信息
            if self.current_contract:
                protocol_data["objective"] = self.current_contract.objective_hash[:16]
            self.protocol_manager.render_master(
                self.state_manager.run_dir, protocol_data
            )
            self.logger.info(f"主协议已渲染: {self.state_manager.run_dir / 'master.md'}")
        except Exception as e:
            self.logger.debug(f"渲染主协议失败 (非致命): {e}")

        # 3. 迭代循环 (Evolution Loop)
        try:
            iteration = start_iteration
            while True:
                if (
                    self.intent == WorkflowIntent.EVOLVE
                    and self.budget_guard.config.max_duration_seconds is None
                    and self.budget_guard.config.max_cost_usd is None
                    and self.budget_guard.config.max_tokens is None
                    and iteration >= self.max_iterations
                ):
                    # EVOLVE 在无预算配置时回退到 max_iterations，防止无界循环
                    break
                if (
                    self.intent != WorkflowIntent.EVOLVE
                    and iteration >= self.max_iterations
                ):
                    break
                # 汲取 GoalX: 资源安全检查
                rstate = self.resource_monitor.check_health()
                if not rstate.is_healthy:
                    self.logger.warning(
                        f"系统资源压力过大，正在暂停或降级执行: {rstate}"
                    )
                    # 在严重情况下可以选择中断
                    if rstate.memory_rss_mb > 8192:  # 8GB 强制中断
                        raise ClawdError(
                            code=ErrorCode.WORKFLOW_EXECUTION_ERROR,
                            message=f"Memory limit exceeded: {rstate.memory_rss_mb}MB",
                            details={"memory_rss_mb": rstate.memory_rss_mb},
                            recoverable=False,
                        )

                # 检查预算是否已耗尽
                if self.budget_guard.check():
                    if self.intent == WorkflowIntent.EVOLVE:
                        self.logger.info(
                            f"EVOLVE 模式下预算已耗尽，正常结束。原因: {self.budget_guard.exhaustion_reason}"
                        )
                        break
                    raise ClawdError(
                        code=ErrorCode.TOKEN_LIMIT_EXCEEDED,
                        message=f"Budget exhausted during iteration: {self.budget_guard.exhaustion_reason}",
                        details={"budget_reason": self.budget_guard.exhaustion_reason},
                        recoverable=False,
                    )

                self._slogger.start_timer(f"iteration_{iteration}")
                self.logger.info(
                    f"迭代 {iteration + 1}/{self.max_iterations} (意图: {self.intent.value})"
                )
                self.liveness_monitor.beat(f"iteration_{iteration}")

                # Phase 1: IDENTIFY (扫描/画像)
                if not all_tasks:
                    self._slogger.start_timer("phase_identify")
                    identify_result = await self._phase_identify(goal)
                    self._slogger.stop_timer(
                        "phase_identify", event="PHASE_COMPLETED", phase="IDENTIFY"
                    )

                    points = identify_result.get("issues", [])
                    phase_summaries[WorkflowPhase.IDENTIFY] = (
                        f"{len(points)} issues found"
                    )
                    optimization_points.extend(
                        f"[{iss.category}/{iss.severity}] {iss.file}:{iss.line} - {iss.description}"
                        for iss in points
                    )
                else:
                    points = []

                # Phase 2: PLAN (规划/义务模型化)
                if not all_tasks:
                    self._slogger.start_timer("phase_plan")
                    tasks = await self._phase_plan(points)
                    self._slogger.stop_timer(
                        "phase_plan", event="PHASE_COMPLETED", phase="PLAN"
                    )
                    all_tasks.extend(tasks)

                    # 汲取 GoalX: 生成并保存义务模型 (Obligation Model)
                    # 将 tasks 映射为 ObligationItem (Durable Obligation)
                    contract_hash = ""
                    if self.current_contract:
                        contract_hash = self.current_contract.objective_hash

                    from src.core.durable.surfaces.obligation_model import (
                        Obligation as DurableObligation,
                    )
                    from src.core.durable.surfaces.obligation_model import (
                        ObligationModel as DurableObligationModel,
                    )
                    from src.core.durable.surfaces.obligation_model import (
                        ObligationStatus as DurableObligationStatus,
                    )

                    durable_obligations = [
                        DurableObligation(
                            id=t.task_id,
                            text=t.description,
                            kind="outcome",
                            source="master",
                            status=DurableObligationStatus.OPEN,
                            assurance_required=True,
                            covers_clauses=[c.id for c in (self.current_contract.clauses if self.current_contract else [])]
                        )
                        for t in tasks
                    ]

                    obligation_model = DurableObligationModel(
                        version=1,
                        objective_contract_hash=contract_hash,
                        required=durable_obligations,
                    )

                    if self.state_manager and self.state_manager.surface_manager:
                        self.state_manager.surface_manager.save_surface("obligation_model", obligation_model)
                        self.logger.info(f"Durable Obligation Model 已保存，包含 {len(durable_obligations)} 个义务。")

                    # [Phase 6] 为生成的任务渲染协议文档
                    for task in tasks:
                        try:
                            # 准备渲染上下文
                            task_context = {
                                "goal_description": task.description,
                                "acceptance_criteria": [task.title], # 简化处理，将标题作为第一个标准
                                "evidence": [],
                                "budget_hours": (self.intent == WorkflowIntent.EVOLVE and 8.0) or 0.0,
                                "max_iterations": self.max_iterations,
                                "task_id": task.task_id
                            }
                            self.protocol_manager.render_task_protocol(
                                self.state_manager.run_dir,
                                self.intent.value,
                                task_context
                            )
                        except Exception as e:
                            self.logger.debug(f"渲染任务协议失败 (task_id: {task.task_id}): {e}")

                    # 生成质保计划 (Assurance Plan)
                    self.assurance_manager.generate_from_tasks(tasks)
                    self.assurance_manager.save()
                else:
                    tasks = [
                        t for t in all_tasks if t.status != WorkflowStatus.COMPLETED
                    ]
                    self.assurance_manager.load()

                phase_summaries[WorkflowPhase.PLAN] = f"{len(all_tasks)} tasks ready"

                # 同步 Durable State
                self._sync_state(goal, iteration, all_tasks, optimization_points)

                # [Phase 2] 更新 StatusSummary
                self._update_status_summary(
                    phase="executing",
                    progress_percentage=0.0,
                    tasks=all_tasks,
                )

                # Phase 3: EXECUTE (隔离执行 + 证据记录)
                self._slogger.start_timer("phase_execute")
                if self.intent == WorkflowIntent.EXPLORE:
                    execute_result = "EXPLORE 模式为只读调查，跳过代码修改执行阶段"
                    self.logger.info(execute_result)
                else:
                    # EVOLVE 模式下预算耗尽时优雅退出，而非抛异常
                    if (
                        self.intent == WorkflowIntent.EVOLVE
                        and self.budget_guard.check()
                    ):
                        self.logger.info(
                            "EVOLVE 模式在执行阶段检测到预算耗尽，提前结束。"
                        )
                        break
                    self.budget_guard.validate()
                    execute_result = await self._phase_execute_isolated(tasks)

                # 将最新任务状态同步回 all_tasks，保证状态一致性
                task_by_id = {t.task_id: t for t in all_tasks}
                for task in tasks:
                    task_by_id[task.task_id] = task
                all_tasks = list(task_by_id.values())

                self._slogger.stop_timer(
                    "phase_execute", event="PHASE_COMPLETED", phase="EXECUTE"
                )

                # 执行后立即持久化，防止中途中断导致状态丢失
                self._sync_state(goal, iteration, all_tasks, optimization_points)

                phase_summaries[WorkflowPhase.EXECUTE] = execute_result

                # Phase 4: REVIEW
                self._slogger.start_timer("phase_review")
                review_result = await self._phase_review(tasks)
                self._slogger.stop_timer(
                    "phase_review", event="PHASE_COMPLETED", phase="REVIEW"
                )
                phase_summaries[WorkflowPhase.REVIEW] = review_result

                # Phase 5: DISCOVER
                self._slogger.start_timer("phase_discover")
                new_points = await self._phase_discover(goal, all_tasks)
                self._slogger.stop_timer(
                    "phase_discover", event="PHASE_COMPLETED", phase="DISCOVER"
                )
                phase_summaries[WorkflowPhase.DISCOVER] = (
                    f"{len(new_points)} new points"
                )

                self._slogger.stop_timer(
                    f"iteration_{iteration}", event="ITERATION_COMPLETED"
                )

                if not new_points:
                    break
                if (
                    self.intent != WorkflowIntent.EVOLVE
                    and iteration >= self.max_iterations - 1
                ):
                    break

                # 准备下一轮迭代
                optimization_points.extend(new_points)
                all_tasks = []  # 清空以便重新规划

                iteration += 1

        except ClawdError as exc:
            self.logger.error(f"工作流因 ClawdError 中断: {exc}")
            return self._finalize_run(
                goal, phase_summaries, all_tasks, optimization_points, error=str(exc)
            )

        return self._finalize_run(goal, phase_summaries, all_tasks, optimization_points)

    async def _phase_execute_isolated(self, tasks: list[WorkflowTask]) -> str:
        """[汲取 GoalX] 隔离执行 Phase: 为每个任务创建 Worktree 并记录证据"""
        completed = 0
        failed = 0
        executor = self._get_executor()

        for task in tasks:
            self._publish(EventType.WORKFLOW_TASK_STARTED, {"task_id": task.task_id})

            worktree_path = None
            if self._use_isolation:
                try:
                    # 0. 创建任务前快照
                    self.worktree_manager.create_snapshot(f"pre-{task.task_id}")
                    # 1. 创建工作树 (Isolation)
                    worktree_path = self.worktree_manager.create(task.task_id)
                    # [Phase 6] 立即同步工作树 ID 到持久化状态，确保会话可恢复
                    self.state_manager.update_task(
                        task.task_id,
                        WorkflowStatus.RUNNING,
                        worktree_id=task.task_id
                    )
                    self.logger.info(
                        f"任务 {task.task_id} 已在隔离工作树中启动: {worktree_path}"
                    )
                except Exception as e:
                    self.logger.error(
                        f"无法创建隔离环境，任务 {task.task_id} 失败: {e}"
                    )
                    failed += 1
                    for idx, original_task in enumerate(tasks):
                        if original_task.task_id == task.task_id:
                            tasks[idx] = replace(
                                original_task,
                                status=WorkflowStatus.FAILED,
                                result=f"隔离环境创建失败: {e}",
                            )
                            break
                    self.state_manager.update_task(
                        task.task_id, WorkflowStatus.FAILED, f"隔离环境创建失败: {e}"
                    )
                    self._publish(
                        EventType.WORKFLOW_TASK_COMPLETED,
                        {
                            "task_id": task.task_id,
                            "category": WorkflowPhaseCategory.EXECUTE_STEP.value,
                            "result": f"隔离环境创建失败: {e}",
                        },
                    )
                    continue

            # 2. 执行任务 (使用工作树路径作为当前目录)
            original_dir = executor.workdir
            try:
                if worktree_path:
                    executor.workdir = worktree_path

                try:
                    res, status, _healed = await executor.execute_with_healing(task)
                    passed = await self.assurance_manager.run_scenarios_for_task(
                        task.task_id, worktree_path or self.workdir
                    )
                except ClawdError:
                    raise
                except Exception as e:
                    self.logger.error(
                        f"任务 {task.task_id} 执行期间发生未处理异常: {e}"
                    )
                    status = WorkflowStatus.FAILED
                    res = f"执行期间发生未处理异常: {e}"
                    failed += 1

                    for idx, original_task in enumerate(tasks):
                        if original_task.task_id == task.task_id:
                            tasks[idx] = replace(
                                original_task, status=status, result=res
                            )
                            break
                    self.state_manager.update_task(task.task_id, status, res)
                    continue

                assurance_artifact = (
                    worktree_path or self.workdir
                ) / f"assurance_verify-{task.task_id}.log"
                try:
                    evidence_path = str(assurance_artifact.relative_to(self.workdir))
                except ValueError:
                    evidence_path = str(assurance_artifact)

                # 3. 运行质保场景 (Assurance Proof)
                if not passed:
                    status = WorkflowStatus.FAILED
                    res += "\n[!] 验证场景未能全部通过。"

                # 4. 记录证据日志 (Evidence Log)
                self.state_manager.record_evidence_event(
                    scenario_id=f"verify-{task.task_id}",
                    harness_kind="pytest",  # 暂时写死
                    result={"status": status.value, "passed": passed},
                    artifacts=[evidence_path],
                )

                # 预算统计（简单 token 估算，避免长期运行无计量）
                estimated_tokens = max(1, len(res) // 4)
                self.budget_guard.record_usage(tokens=estimated_tokens)

                # [Phase 2] 记录证据到 Durable EvidenceLog
                if self.state_manager and hasattr(self.state_manager, "add_evidence_entry"):
                    try:
                        self.state_manager.add_evidence_entry(
                            evidence_id=f"exec-{task.task_id}",
                            evidence_type="test_result",
                            description=f"Task {task.task_id} execution: {status.value}",
                            obligation_id=task.task_id,
                            scenario_id=f"verify-{task.task_id}",
                            data={"status": status.value, "passed": passed},
                            artifacts=[evidence_path],
                            recorded_by="workflow_engine",
                        )
                    except Exception as e:
                        self.logger.debug(f"记录 Durable 证据失败: {e}")

                # 5. 整合更改 (Integrate)
                if worktree_path and status == WorkflowStatus.COMPLETED:
                    success, detail = self.worktree_manager.integrate(task.task_id)
                    if success:
                        self.logger.info(
                            f"任务 {task.task_id} 更改已成功整合回主分支。"
                        )
                    else:
                        status = WorkflowStatus.FAILED
                        res += f"\n[!] 更改整合失败: {detail}"
                        self.intervention_logger.record(
                            kind="integration_failure",
                            source="guard",
                            message=f"任务 {task.task_id} 整合冲突",
                            task_id=task.task_id,
                            conflict_detail=detail,
                        )

                # 同步内存任务状态，防止 all_tasks 与持久化状态不一致
                evidence_paths = [evidence_path]
                for idx, original_task in enumerate(tasks):
                    if original_task.task_id == task.task_id:
                        evidence_paths = list(
                            set([*original_task.evidence_paths, evidence_path])
                        )
                        tasks[idx] = replace(
                            original_task,
                            status=status,
                            result=res,
                            evidence_paths=evidence_paths,
                        )
                        break

                if status == WorkflowStatus.COMPLETED:
                    completed += 1
                else:
                    failed += 1

                # 更新任务状态
                self.state_manager.update_task(
                    task.task_id, status, res, evidence=evidence_paths
                )

            finally:
                executor.workdir = original_dir
                if worktree_path:
                    try:
                        # 汲取 GoalX: 增加清理重试机制
                        for retry in range(3):
                            try:
                                self.worktree_manager.remove(task.task_id)
                                break
                            except Exception as e:
                                if retry == 2:
                                    self.logger.error(
                                        f"工作树清理失败 (task_id: {task.task_id}): {e}"
                                    )
                                    # 记录严重异常，但不抛出防止中断后续任务，由 Discovery 阶段发现残留
                                await asyncio.sleep(0.5 * (retry + 1))
                    except Exception:
                        pass

        return f"{completed}/{len(tasks)} completed, {failed} failed"

    def _sync_state(
        self,
        goal: str,
        iteration: int,
        all_tasks: list[WorkflowTask],
        points: list[str],
    ):
        """同步当前状态到持久化层"""
        if self.state_manager:
            # 记录到 Notepad 优先级上下文
            self._memory_manager.notepad.add_priority(
                f"Sync State: Iteration {iteration}, Tasks: {len(all_tasks)}",
                {"goal": goal[:50]}
            )

            self.state_manager.sync(
                {
                    "goal": goal,
                    "intent": self.intent.value,
                    "iteration": iteration,
                    "tasks": [t.to_dict() for t in all_tasks],
                    "optimization_points": points,
                }
            )

            # [Phase 2] 同步到 Durable Surfaces
            self._update_status_summary(
                phase="executing" if all_tasks else "planning",
                progress_percentage=self._calculate_progress(all_tasks),
                tasks=all_tasks,
            )

            # [Project B] 同步更新 ControlState
            if self.state_manager.surface_manager:
                try:
                    from ..core.durable.surfaces.control_state import ControlState
                    from ..core.durable.surfaces.control_state import RunPhase as DurableRunPhase
                    control = self.state_manager.surface_manager.load_surface("control_state", ControlState)
                    control.phase = DurableRunPhase.EXECUTE if all_tasks else DurableRunPhase.PLAN
                    control.active_session_count = len([t for t in all_tasks if t.status == WorkflowStatus.RUNNING])
                    self.state_manager.surface_manager.save_surface("control_state", control)
                except Exception as e:
                    self.logger.debug(f"Update ControlState failed: {e}")

    async def _promote_evidence_to_memory(
        self, all_tasks: list[WorkflowTask], goal: str
    ) -> int:
        """[Phase 5] 将任务证据提升为情景记忆 (EpisodicMemory)

        从已完成的任务中提取证据路径，将其汇总并存储为情景记忆。
        这实现了 Evidence-Gated Memory 模式。

        Returns:
            提升的记忆数量
        """
        promoted_count = 0
        from ..memory.models import EpisodicMemory

        # 收集所有有证据的任务
        for task in all_tasks:
            if not task.evidence_paths:
                continue

            # 构建情况描述
            situation = f"任务: {task.title} | 状态: {task.status.value}"
            if task.result:
                # 截取结果的前200字符作为概要
                result_summary = task.result[:200] if len(task.result) > 200 else task.result
            else:
                result_summary = ""

            # 构建解决方案/证据
            solution = "\n".join(task.evidence_paths) if task.evidence_paths else ""

            # 教训：从任务执行结果中提取
            lesson = ""
            if task.status == WorkflowStatus.COMPLETED:
                lesson = "任务成功完成，证据已记录"
            elif task.status == WorkflowStatus.FAILED:
                lesson = f"任务失败: {result_summary[:100]}"

            # 创建情景记忆
            episodic = EpisodicMemory(
                skill_used=f"workflow:{self.intent.value}",
                situation=situation,
                solution=solution,
                lesson=lesson,
            )

            try:
                await self._memory_manager.add_episodic(episodic)
                promoted_count += 1
            except Exception as e:
                self.logger.debug(f"提升情景记忆失败 (task_id: {task.task_id}): {e}")

        self.logger.info(f"已提升 {promoted_count} 条情景记忆")
        return promoted_count

    def _finalize_run(
        self, goal, phase_summaries, all_tasks, optimization_points, error: str = ""
    ):
        """完成运行并发布结果"""
        self._is_running = False
        completed = sum(1 for t in all_tasks if t.status == WorkflowStatus.COMPLETED)
        status = WorkflowStatus.FAILED if error else WorkflowStatus.COMPLETED
        report = self._build_report(
            goal, phase_summaries, all_tasks, optimization_points
        )
        if error:
            report = f"{report}\n\n中断原因: {error}"

        # [Phase 5] 提升证据到情景记忆 (同步包装)
        # 注意: _finalize_run 是同步方法，在工作流完成时同步调用
        # 为了避免阻塞，我们记录一个待处理的提升任务
        if all_tasks:
            self._memory_manager.working_set(
                "_pending_episodic_promotion",
                {
                    "tasks": [t.to_dict() for t in all_tasks],
                    "goal": goal,
                    "timestamp": __import__("time").time()
                }
            )

        self._publish(
            EventType.WORKFLOW_COMPLETED,
            {
                "goal": goal,
                "status": status.value,
                "error": error,
                "total_tasks": len(all_tasks),
                "completed_tasks": completed,
            },
        )

        return WorkflowResult(
            status=status,
            phase_summary=phase_summaries,
            total_tasks=len(all_tasks),
            completed_tasks=completed,
            optimization_points=optimization_points,
            report=report,
        )

    # ===== Phase 委托 =====

    async def _phase_identify(self, goal: str) -> dict[str, Any]:
        """Phase 1: 扫描代码库，发现优化点"""
        self._publish(
            EventType.WORKFLOW_PHASE_STARTED, {"phase": WorkflowPhase.IDENTIFY.value}
        )
        await self._memory_manager.add_journal(
            JournalEntry(
                agent_id="WorkflowEngine",
                intent="explore",
                task_id="INIT",
                action="identify_issues",
                thought=f"开始识别与目标 '{goal}' 相关的潜在问题和优化点",
                confidence=0.9,
            )
        )

        scanner = self._get_code_scanner()
        result = scanner.scan_codebase(goal)

        # 汲取 GoalX: 增加认知事实 (Cognition Facts)
        if self._code_graph is None:
            self._code_graph = CodeGraph(self.workdir)
            self._code_graph.build()

        issues = result.get("issues", [])
        for issue in issues:
            impact = self._code_graph.impact_analysis(issue.file)
            # 将影响分析结果注入到 issue 中，供 Planner 参考
            issue.impact_files = impact["impacted_files"]
            issue.risk_level = impact["risk_level"]

        issues_count = len(issues)
        await self._memory_manager.add_journal(
            JournalEntry(
                agent_id="WorkflowEngine",
                intent="explore",
                task_id="INIT",
                action="identify_issues_completed",
                status="success",
                result_summary=f"识别完成，共发现 {issues_count} 个潜在问题",
            )
        )

        self._publish(
            EventType.WORKFLOW_PHASE_COMPLETED,
            {"phase": WorkflowPhase.IDENTIFY.value, "issues": issues_count},
        )
        return result

    async def _phase_plan(self, issues: list[CodeIssue]) -> list[WorkflowTask]:
        """Phase 2: 生成 TODO 列表"""
        self._publish(
            EventType.WORKFLOW_PHASE_STARTED, {"phase": WorkflowPhase.PLAN.value}
        )
        await self._memory_manager.add_journal(
            JournalEntry(
                agent_id="WorkflowEngine",
                intent=self.intent.value,
                task_id="PLANNING",
                action="plan_tasks",
                thought=f"根据收集到的 {len(issues)} 个问题生成执行任务列表。当前意图: {self.intent.value}",
                confidence=0.85,
            )
        )

        planner = self._get_task_planner()
        tasks = planner.plan_tasks(issues, intent=self.intent)

        # 挂载目标合约
        for task in tasks:
            self.goal_state.required.append(
                GoalItem(
                    id=task.task_id, text=task.description, role=GoalItemRole.OUTCOME
                )
            )

        # 辩论触发：如果是架构风险或复杂修复
        high_risk_issues = [
            i
            for i in issues
            if i.severity.lower() == "critical" or "architecture" in i.category.lower()
        ]
        if high_risk_issues:
            self.logger.info(
                f"检测到 {len(high_risk_issues)} 个高风险问题，启动多 Agent 辩论模式..."
            )
            if not self._debate_engine:
                # 初始化编排器所需的依赖
                bus = MessageBus()
                world = RepositoryWorldModel(self.workdir)
                orchestrator = OrchestratorAgent(
                    agent_id="Orchestrator-001", message_bus=bus, world_model=world
                )
                self._debate_engine = DebateEngine(orchestrator=orchestrator)

            for issue in high_risk_issues:
                try:
                    summary = await self._debate_engine.conduct_debate(
                        context=f"文件: {issue.file}, 类别: {issue.category}",
                        proposal=issue.description,
                    )
                    self.logger.info(f"辩论共识总结: {summary}")
                except Exception as e:
                    self.logger.warning(f"辩论模式执行失败: {e}，跳过该项辩论。")

        for task in tasks:
            self._publish(
                EventType.WORKFLOW_TASK_STARTED,
                {
                    "task_id": task.task_id,
                    "category": WorkflowPhaseCategory.PLAN_TODO.value,
                },
            )

        self._publish(
            EventType.WORKFLOW_PHASE_COMPLETED,
            {"phase": WorkflowPhase.PLAN.value, "tasks_planned": len(tasks)},
        )
        return tasks

    async def _phase_execute(self, tasks: list[WorkflowTask]) -> str:
        """Phase 3: 执行任务（带自愈逻辑）"""
        self._publish(
            EventType.WORKFLOW_PHASE_STARTED, {"phase": WorkflowPhase.EXECUTE.value}
        )
        self._slogger.info(
            "PHASE_STARTED", phase=WorkflowPhase.EXECUTE.value, task_count=len(tasks)
        )
        await self._memory_manager.add_journal(
            JournalEntry(
                agent_id="WorkflowEngine",
                intent=self.intent.value,
                task_id="EXECUTION",
                action="execute_tasks",
                thought=f"开始并发执行 {len(tasks)} 个任务，启用自愈和拓扑排序。",
                confidence=0.9,
            )
        )

        completed = 0
        failed = 0
        processed_task_ids: set[str] = set()
        task_states: dict[str, WorkflowTask] = {t.task_id: t for t in tasks}
        executor = self._get_executor()

        # 基于 depends_on 的拓扑排序执行
        while len(processed_task_ids) < len(tasks):
            ready_tasks: list[WorkflowTask] = []
            blocked: list[str] = []
            for t_id, t in task_states.items():
                if t_id in processed_task_ids:
                    continue
                deps = getattr(t, "depends_on", []) or []
                if all(d in processed_task_ids for d in deps):
                    ready_tasks.append(t)
                else:
                    blocked.append(t_id)

            if not ready_tasks:
                self.logger.warning(
                    f"工作流死锁，阻塞的任务: {blocked}，标记剩余任务为 CANCELLED"
                )
                for t_id in blocked:
                    self.state_manager.update_task(
                        t_id, WorkflowStatus.CANCELLED, "Detected deadlock"
                    )
                    self._publish(
                        EventType.WORKFLOW_TASK_COMPLETED,
                        {
                            "task_id": t_id,
                            "category": WorkflowPhaseCategory.EXECUTE_STEP.value,
                            "result": "Detected deadlock",
                            "status": WorkflowStatus.CANCELLED.value,
                        },
                    )
                break

            self.logger.debug(f"本轮并发执行 {len(ready_tasks)} 个就绪任务")

            async def execute_task_wrapper(t):
                self._publish(
                    EventType.WORKFLOW_TASK_STARTED,
                    {
                        "task_id": t.task_id,
                        "category": WorkflowPhaseCategory.EXECUTE_STEP.value,
                    },
                )
                try:
                    res, status, healed = await executor.execute_with_healing(t)
                    return t.task_id, res, status, healed, None
                except Exception as e:
                    return t.task_id, str(e), WorkflowStatus.FAILED, False, e

            results = await asyncio.gather(
                *(execute_task_wrapper(t) for t in ready_tasks)
            )

            for t_id, res, status, _healed, _exc in results:
                if t_id not in processed_task_ids:
                    processed_task_ids.add(t_id)
                    if t_id in task_states:
                        t = task_states[t_id]
                        # 尝试从结果文本中提取证据路径 (如果 executor 没直接返回对象的话)
                        evidence_paths = []
                        evidence_match = re.search(
                            r"\[🔍 执行证据链\]:\n(.*?)(?:\n\n|\Z)", res, re.DOTALL
                        )
                        if evidence_match:
                            evidence_paths = [
                                line.strip().lstrip("- ").strip()
                                for line in evidence_match.group(1).split("\n")
                                if line.strip()
                            ]

                        new_t = replace(
                            t,
                            status=status,
                            result=res,
                            evidence_paths=list(set(t.evidence_paths + evidence_paths)),
                        )
                        task_states[t_id] = new_t

                        if status == WorkflowStatus.COMPLETED:
                            completed += 1
                            self.state_manager.update_task(
                                t_id, status, res, evidence=evidence_paths
                            )
                            self._publish(
                                EventType.WORKFLOW_TASK_COMPLETED,
                                {
                                    "task_id": t_id,
                                    "category": WorkflowPhaseCategory.EXECUTE_VERIFY.value,
                                    "result": res,
                                    "evidence": evidence_paths,
                                },
                            )
                        else:
                            self.state_manager.update_task(t_id, status, res)
                            failed += 1
                            self.logger.warning(f"任务 {t_id} 失败: {res}")

        # Full validation
        self._publish(
            EventType.WORKFLOW_TASK_STARTED,
            {"category": WorkflowPhaseCategory.EXECUTE_VALIDATE.value},
        )
        validation = self._full_validation(list(task_states.values()))
        self._publish(
            EventType.WORKFLOW_TASK_COMPLETED,
            {
                "category": WorkflowPhaseCategory.EXECUTE_VALIDATE.value,
                "valid": validation,
                "failed": failed,
            },
        )

        self._publish(
            EventType.WORKFLOW_PHASE_COMPLETED, {"phase": WorkflowPhase.EXECUTE.value}
        )

        return f"{completed}/{len(tasks)} completed, {failed} failed"

    async def _phase_review(self, tasks: list[WorkflowTask]) -> str:
        """Phase 4: 全局审查"""
        reviewer = self._get_reviewer()

        # 集成 QualityDebtCollector
        changed_files = []
        for task in tasks:
            if task.status == WorkflowStatus.COMPLETED:
                loc = self._parse_file_location(task.description)
                if loc and "file" in loc:
                    changed_files.append(loc["file"])

        debt = self.debt_collector.collect(changed_files)
        if not debt.is_zero():
            from .tech_debt import TechDebtManager

            td_mgr = TechDebtManager(self.workdir)
            td_mgr.add_record(
                issue_id="QUALITY_DEBT_AUTO",
                description=f"质量债务检测: TestGap={debt.test_gap}, DocGap={debt.documentation_gap}",
                affected_files=changed_files,
            )

        return await reviewer.phase_review(tasks)

    async def _phase_discover(self, goal: str, tasks: list[WorkflowTask]) -> list[str]:
        """Phase 5: 发现新优化点"""
        reviewer = self._get_reviewer()
        return await reviewer.phase_discover(goal, tasks)

    # ===== 辅助方法 =====

    def _full_validation(self, task_states: list[WorkflowTask]) -> bool:
        """全量验证：检查语法错误"""
        syntax_ok = True
        src_dir = self.workdir / "src"
        if not src_dir.exists():
            return True

        for py_file in src_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
                ast.parse(source)
            except SyntaxError as e:
                self.logger.error(f"语法错误 in {py_file}: {e}")
                syntax_ok = False

        return syntax_ok

    def _build_report(
        self,
        goal: str,
        phase_summaries: dict[WorkflowPhase, str],
        tasks: list[WorkflowTask],
        optimization_points: list[str],
    ) -> str:
        """构建完成报告"""
        lines = [
            f"工作流完成报告: {goal}",
            "=" * 60,
            f"总任务数: {len(tasks)}",
            f"完成任务: {sum(1 for t in tasks if t.status == WorkflowStatus.COMPLETED)}",
            f"失败任务: {sum(1 for t in tasks if t.status == WorkflowStatus.FAILED)}",
            "",
            "阶段摘要:",
        ]
        for phase, summary in phase_summaries.items():
            lines.append(f"  {phase.value}: {summary}")

        if optimization_points:
            lines.extend(["", "优化点:", *[f"  - {p}" for p in optimization_points]])

        return "\n".join(lines)

    def _publish(
        self, event_type: EventType, data: dict[str, Any] | None = None
    ) -> None:
        """封装事件发布"""
        self._event_bus.publish(
            Event(
                type=event_type,
                data=data or {},
                source="workflow_engine",
            )
        )

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._is_running

    def stop(self) -> None:
        """停止工作流"""
        self._is_running = False
        if self.runtime_host:
            asyncio.create_task(self.runtime_host.stop())

    # ===== [Phase 2] Durable Surfaces 辅助方法 =====

    def _update_status_summary(
        self,
        phase: str,
        progress_percentage: float = 0.0,
        tasks: list[WorkflowTask] | None = None,
    ) -> None:
        """更新 StatusSummary (Durable Surface)"""
        if not self.state_manager or not hasattr(self.state_manager, "update_status_summary"):
            return

        tasks = tasks or []
        completed = sum(1 for t in tasks if t.status == WorkflowStatus.COMPLETED)
        failed = sum(1 for t in tasks if t.status == WorkflowStatus.FAILED)

        try:
            self.state_manager.update_status_summary(
                phase=phase,
                current_activity=f"Processing {len(tasks)} tasks",
                active_sessions=len([t for t in tasks if t.status == WorkflowStatus.RUNNING]),
                blocked_sessions=failed,
                progress_percentage=progress_percentage,
                obligations_satisfied=completed,
                obligations_total=len(tasks),
                summary=f"{completed}/{len(tasks)} tasks completed",
            )
        except Exception as e:
            self.logger.debug(f"更新 StatusSummary 失败: {e}")

    def _calculate_progress(self, tasks: list[WorkflowTask]) -> float:
        """计算任务完成进度百分比"""
        if not tasks:
            return 0.0
        completed = sum(1 for t in tasks if t.status == WorkflowStatus.COMPLETED)
        return (completed / len(tasks)) * 100

"""Swarm Engine — 多 Agent 协作主引擎

核心流程:
1. Orchestrator 分解任务
2. Worker 执行子任务 (复用 AgentEngine)
3. Auditor 审计代码
4. Reviewer 审查代码
5. Integrator 集成结果

性能优化 (v0.37.0):
- 预编译正则表达式，避免重复编译
- 添加并发度控制，避免 API 限流
- 优化内存使用，结果截断
- 就绪队列优化，任务调度 O(1)
"""
from __future__ import annotations

import json
import logging
import os
import time
from asyncio import Semaphore
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ...core.metrics_exporter import get_metrics_collector as EnterpriseMetricsCollector
from ...llm import LLMConfig
from ...memory.enterprise_ltm import EnterpriseLTM, PatternType
from ..engine import AgentEngine
from ..factory import create_agent_engine
from .auditor import AuditorAgent, AuditReport
from .base_agent import BaseAgent
from .config import SwarmConfig
from .integrator import AtomicIntegrator
from .message_bus import MessageType
from .orchestrator import OrchestratorAgent
from .quality_gate import GateResult, QualityGate
from .task_registry import TaskRegistry

logger = logging.getLogger(__name__)

# 延迟导入避免循环依赖 (放在使用它的函数/模块顶部)


@dataclass
class SwarmResult:
    """Swarm 执行结果"""
    success: bool
    goal: str
    final_result: str = ""
    code_changes: dict[str, str] = field(default_factory=dict)
    audit_report: AuditReport | None = None
    gate_results: list[GateResult] = field(default_factory=list)
    task_stats: dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class SwarmEngine:
    """多 Agent 协作引擎

    用法:
        engine = SwarmEngine(config=SwarmConfig(), workdir=Path.cwd())
        result = await engine.run("实现用户认证功能")
    """

    def __init__(
        self,
        config: SwarmConfig | None = None,
        workdir: Path | None = None,
        llm_config: LLMConfig | None = None,
        on_progress: Callable[[str, str], None] | None = None,
        intent: str = "implement", # 默认意图
    ) -> None:
        self.config = config or SwarmConfig()
        self.workdir = workdir or Path.cwd()
        self.llm_config = llm_config
        self.on_progress = on_progress
        self.intent = intent

        # 基础设施
        from ...brain.world_model import RepositoryWorldModel
        self.world_model = RepositoryWorldModel(root_dir=self.workdir)

        # [汲取 GoalX] 使用持久化消息总线
        from .persistent_message_bus import PersistentMessageBus
        self.message_bus = PersistentMessageBus(
            storage_dir=self.workdir / ".clawd" / "control"
        )

        self.task_registry = TaskRegistry()
        self.quality_gate = QualityGate(
            workdir=self.workdir,
            lint_strict=self.config.lint_strict,
            require_tests=self.config.require_tests,
        )
        self.integrator = AtomicIntegrator(
            workdir=self.workdir,
            message_bus=self.message_bus
        )
        self.ltm = EnterpriseLTM()

        # [汲取 OMX] 初始化意图澄清和脱水器
        from ...workflow.clarify import ClarifyGate
        from ...llm.model_manager import ModelManager
        from ..factory import create_model_manager
        from ...self_healing.cleaner import SlopCleaner
        self.clarify_gate = ClarifyGate(create_model_manager())
        self.slop_cleaner = SlopCleaner()

        # GoalX 基础设施集成
        from ...core.git.worktree import WorktreeManager
        self.worktree_manager = WorktreeManager(self.workdir)
        # [汲取 GoalX] 增加预算守卫
        from ...core.budget_guard import BudgetGuard, parse_budget_string
        # 尝试从配置或环境变量获取预算字符串
        budget_str = getattr(self.config, 'budget', None) or os.environ.get('CLAWD_BUDGET')
        self.budget_guard = BudgetGuard(parse_budget_string(budget_str))

        # [NEW Phase 4] 运行时与协作管理
        self.runtime_host: RuntimeHost | None = None
        self.surface_manager: SurfaceManager | None = None
        self.coordination_state: CoordinationState | None = None

        if self.config.enable_runtime_host:
            from ...core.resource_monitor import ResourceMonitor
            from ...core.runtime.host import RuntimeHost
            # 自动生成 session_id (如果是重连模式，可能需要传入)
            session_id = f"swarm-{int(time.time())}"
            self.runtime_host = RuntimeHost(
                run_dir=self.workdir / ".clawd",
                session_id=session_id,
                resource_monitor=ResourceMonitor(
                    memory_threshold_mb=self.config.resource_memory_threshold_mb,
                    cpu_threshold=self.config.resource_cpu_threshold
                )
            )

        if self.config.enable_coordination_state:
            from ...core.durable.surface_manager import SurfaceManager
            from ...core.durable.surfaces.coordination_state import CoordinationState
            self.surface_manager = SurfaceManager(run_dir=self.workdir / ".clawd")
            # 初始化或加载现有状态
            self.coordination_state = self.surface_manager.load_surface(
                "coordination_state",
                CoordinationState
            )

        # Agents
        self.orchestrator: OrchestratorAgent | None = None
        self.auditor: AuditorAgent | None = None
        self._worker_engine: AgentEngine | None = None

        # [性能优化 v0.37.0] 并发控制信号量
        self._task_semaphore: Semaphore | None = None

    def _get_worker_engine(self) -> AgentEngine:
        """获取 Worker 使用的 AgentEngine"""
        if self._worker_engine is None:
            self._worker_engine = create_agent_engine(
                provider_type=self.llm_config.provider.value if self.llm_config else 'openai',
                api_key=self.llm_config.api_key if self.llm_config else '',
                model=(self.config.worker_model or self.llm_config.model or 'gpt-4o') if self.llm_config else 'gpt-4o',
                workdir=self.workdir,
                intent=self.intent,  # 传递意图
            )
        return self._worker_engine

    def _init_agents(self) -> None:
        """初始化 Agents"""
        if self.orchestrator is None:
            self.orchestrator = OrchestratorAgent(
                agent_id='orchestrator-1',
                message_bus=self.message_bus,
                llm_config=self.llm_config,
                world_model=self.world_model,
            )

        if self.config.enable_auditor and self.auditor is None:
            self.auditor = AuditorAgent(
                agent_id='auditor-1',
                message_bus=self.message_bus,
                workdir=self.workdir,
                llm_config=self.llm_config,
                lint_strict=self.config.lint_strict,
                require_tests=self.config.require_tests,
                llm_review_batch_size=self.config.auditor_llm_review_batch_size,
                max_line_length=self.config.auditor_max_line_length,
            )

    async def run(self, goal: str) -> SwarmResult:
        """执行 Swarm 协作流程"""
        from ...utils.tracing import TracingContext

        # 启动运行时托管
        if self.runtime_host:
            await self.runtime_host.start()

        # 启动预算守卫
        if self.budget_guard:
            self.budget_guard.start()

        with TracingContext.start_request():
            rid = TracingContext.get_request_id()
            logger.info(f"开启新的 Swarm 请求 [Goal: {goal[:50]}]")
            return await self._run_core(goal, rid)

    async def _run_core(self, goal: str, request_id: str) -> SwarmResult:
        """核心执行逻辑"""

        EnterpriseMetricsCollector.record_start()
        start_time = time.time()

        # [NEW Phase 4] 恢复持久化状态
        recovered = False
        if self.config.enable_coordination_state and self.surface_manager and (
            self.coordination_state and self.coordination_state.sessions
        ):
            self._progress('swarm', '检测到现有协作状态，尝试恢复会话...')
            recovered = True

        self._init_agents()

        self._progress('swarm', f'开始 Swarm 协作: {goal[:50]}...')

        # Step 0: 语义分析与自裂变 (可选)
        specialized_agents: list[BaseAgent] = []
        if self.config.enable_self_fission and not recovered:
            specialized_agents = await self._self_fission(goal)
            if specialized_agents:
                self._progress('self-fission', f'合成 {len(specialized_agents)} 个专项 Agent')

        # Step 0b: 经验检索 (内联优化)
        experience_hints: list[str] = []
        if self.config.enable_experience_retrieval and not recovered:
            experience_hints = await self._retrieve_experience_hints(goal)
            if experience_hints:
                self._progress('rl-exp', f'检索到 {len(experience_hints)} 条历史经验')

        # Step 0c: 世界模型感知
        if not self.world_model._is_initialized:
            await self.world_model.initialize()

        self._progress('world-model', f'代码库感知中: {self.world_model.stats()["node_count"]} 个节点')

        # 执行前校验预算
        if self.budget_guard:
            self.budget_guard.validate()

        # 开启全局集成事务
        if self.config.enable_integrator:
            await self.integrator.start_transaction()

        # [汲取 GoalX] 订阅审计失败事件进行自愈尝试
        self.message_bus.subscribe(MessageType.AUDIT_FAIL, self._on_audit_fail)

        # [NEW] 订阅 Worker 的状态同步消息，并启用 catch_up 模式进行灾难恢复
        # 注意: PersistentMessageBus.subscribe(catch_up=True) 会回放历史 SYNC_STATE 消息
        # 从而自动填充 task_registry
        self.message_bus.subscribe(
            MessageType.SYNC_STATE,
            self._on_worker_sync,
            catch_up=True,
            recipient_id=self.orchestrator.agent_id
        )

        # 记录会话开始
        if not recovered:
            await self.ltm.record_session_start(request_id, goal)

        # [汲取 OMX] 意图澄清阶段
        if self.config.enable_clarify_gate and not recovered:
            analysis = await self.clarify_gate.analyze_intent(goal)
            self._progress('clarify', f"意图清晰度得分: {analysis.get('clarity_score', 0)}")
            if self.clarify_gate.should_ask_user(analysis):
                self._progress('clarify', "检测到模糊点，建议进行深层对话...")

            # 注入 Non-goals 和 Constraints 到目标描述中 (临时增强)
            draft = analysis.get('draft_contract', {})
            non_goals = draft.get('non_goals', [])
            if non_goals:
                goal += "\n[NON-GOALS]:\n" + "\n".join(f"- {ng}" for ng in non_goals)

        try:
            # Step 1: Orchestrator 分解任务
            if not recovered or not self.task_registry.get_all_tasks():
                decomposition = await self.orchestrator.decompose_task(goal)
                self._progress('orchestrator', f'任务分解为 {len(decomposition.sub_tasks)} 个子任务')
            else:
                self._progress('orchestrator', '从持久化状态恢复任务分解')
                from .orchestrator import TaskDAG, TaskDecomposition
                # 从 registry 重建 decomposition
                tasks_data = []
                for t in self.task_registry.get_all_tasks():
                    tasks_data.append({
                        'task_id': t.task_id,
                        'title': t.title,
                        'description': t.description,
                        'depends_on': t.metadata.get('depends_on', ''),
                        'assigned_to': t.metadata.get('assigned_to', 'worker')
                    })
                decomposition = TaskDecomposition(
                    sub_tasks=tasks_data,
                    dag=TaskDAG(tasks_data)
                )

            if len(decomposition.sub_tasks) == 1 and not self.config.fallback_to_single_agent:
                return await self._fallback_single_agent(goal, start_time)

            # Step 2-3: 使用管道执行
            from .pipeline import SwarmPipeline
            pipeline = SwarmPipeline(
                config=self.config,
                workdir=self.workdir,
                llm_config=self.llm_config,
                orchestrator=self.orchestrator,
                auditor=self.auditor,
                task_registry=self.task_registry,
                quality_gate=self.quality_gate,
                integrator=self.integrator,
                ltm=self.ltm,
                get_worker_engine=self._get_worker_engine,
                progress_callback=self._progress,
                worktree_manager=self.worktree_manager, # 注入工作树管理器
            )

            code_changes, audit_report, gate_results = await pipeline.execute(
                goal=goal,
                request_id=request_id,
                decomposition=decomposition,
                budget_guard=self.budget_guard, # 传递预算守卫
            )

            elapsed = time.time() - start_time
            all_gates_passed = all(g.passed for g in gate_results) if gate_results else True

            # 提交或回滚
            if self.config.enable_integrator:
                if all_gates_passed:
                    await self.integrator.commit()
                    if code_changes:
                        await self.ltm.learn_pattern(
                            goal=goal,
                            implementation=code_changes,
                            pattern_type=PatternType.SUCCESS
                        )
                else:
                    self._progress('swarm', '质量门禁未通过，回滚')
                    await self.integrator.rollback()
                    if audit_report and not audit_report.passed:
                        await self.ltm.learn_pattern(
                            goal=goal,
                            rejection_reason=str(audit_report.issues),
                            pattern_type=PatternType.FAILURE_PREVENTION
                        )

            EnterpriseMetricsCollector.record_completion(elapsed)

            # 停止运行时托管
            if self.runtime_host:
                await self.runtime_host.stop()

            summary = await self.orchestrator.summarize_results(
                {t.task_id: self.task_registry.get_task(t.task_id).result
                 for t in decomposition.sub_tasks if self.task_registry.get_task(t.task_id)}
            )
            metrics_report = EnterpriseMetricsCollector.get_report()
            logger.info(f"[ENTERPRISE_STATS] {json.dumps(metrics_report)}")

            return SwarmResult(
                success=all_gates_passed,
                goal=goal,
                final_result=summary,
                code_changes=code_changes,
                audit_report=audit_report,
                gate_results=gate_results,
                task_stats={**self.task_registry.get_stats(), "enterprise_metrics": metrics_report},
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            logger.error(f'Swarm 执行失败: {e}')
            elapsed = time.time() - start_time

            # 停止运行时托管
            if self.runtime_host:
                await self.runtime_host.stop()

            if self.config.enable_integrator:
                await self.integrator.rollback()

            if self.config.fallback_to_single_agent:
                self._progress('swarm', 'Swarm 失败，回退到单 Agent')
                return await self._fallback_single_agent(goal, start_time)

            await self.ltm.record_session_failure(request_id, str(e))

            return SwarmResult(
                success=False,
                goal=goal,
                final_result=f'Swarm 执行失败: {e}',
                elapsed_seconds=elapsed,
                errors=[str(e)],
            )

    async def _fallback_single_agent(self, goal: str, start_time: float) -> SwarmResult:
        """回退到单 Agent 模式"""
        import time

        engine = self._get_worker_engine()

        try:
            session = await engine.run(goal)
            elapsed = time.time() - start_time

            return SwarmResult(
                success=True,
                goal=goal,
                final_result=session.final_result,
                elapsed_seconds=elapsed,
                task_stats={'mode': 'single_agent_fallback'},
            )
        except Exception as e:
            elapsed = time.time() - start_time
            return SwarmResult(
                success=False,
                goal=goal,
                final_result=f'执行失败: {e}',
                elapsed_seconds=elapsed,
                errors=[str(e)],
            )

    async def _self_fission(self, goal: str) -> list[BaseAgent]:
        """执行语义分析与专项 Agent 合成（自裂变）"""
        try:
            from .self_fission import AgentSynthesisFactory, SemanticCodeAnalyzer

            analyzer = SemanticCodeAnalyzer(threshold=self.config.detection_threshold)
            result = await analyzer.analyze(goal, self.workdir)

            if not result.features:
                self._progress('self-fission', '未检测到语义特征')
                return []

            self._progress('self-fission', f'检测到特征: {", ".join(result.tags)}')

            factory = AgentSynthesisFactory(llm_config=self.llm_config)
            agents = factory.synthesize(
                features=result.features,
                message_bus=self.message_bus,
                workdir=self.workdir,
                max_agents=self.config.max_specialized_agents,
            )

            for agent in agents:
                self._progress('self-fission', f'注册专项 Agent: {agent.agent_id}')

            return agents

        except ImportError as e:
            self._progress('self-fission', f'自裂变模块未安装: {e}')
            return []
        except Exception as e:
            self._progress('self-fission', f'自裂变失败: {e}')
            logger.warning(f'自裂变异常: {e}')
            return []

    def _progress(self, agent: str, message: str) -> None:
        """进度回调"""
        logger.info(f'[{agent}] {message}')
        if self.on_progress:
            self.on_progress(agent, message)

    async def _retrieve_experience_hints(self, goal: str) -> list[str]:
        """[内联优化] 检索历史经验并返回提示"""
        try:
            from .self_fission.rl_experience import RLExperienceHub
            hub = RLExperienceHub()
            best_practices = hub.find_best_practices(goal, top_k=3)
            failure_warnings = hub.get_failure_warnings(goal)

            hints: list[str] = []
            if best_practices:
                for i, exp in enumerate(best_practices, 1):
                    hints.append(
                        f"历史方案 {i}: {exp.task_description} -> {exp.solution} "
                        f"(成功率: {exp.success_rate:.0%}, 尝试: {exp.total_attempts})"
                    )
            if failure_warnings:
                for warn in failure_warnings[:2]:
                    hints.append(f"⚠️ 失败预警: {warn.pattern} (出现 {warn.frequency} 次)")
            return hints
        except Exception as e:
            logger.debug(f"经验检索异常: {e}")
            return []

    async def _on_audit_fail(self, message: Any) -> None:
        """处理审计失败事件 (汲取 GoalX 自愈模式)"""
        task_id = message.metadata.get('task_id')
        report = message.metadata.get('report', '')

        if not task_id:
            return

        self._progress('swarm', f'⚠️ 检测到任务 {task_id} 审计失败，启动自愈分析...')

        # 记录到 LTM 失败模式
        await self.ltm.learn_pattern(
            goal=f"任务 {task_id} 审计失败",
            rejection_reason=report,
            pattern_type=PatternType.FAILURE_PREVENTION
        )

    async def _on_worker_sync(self, message: Any) -> None:
        """处理 Worker 状态同步消息 (Master-Worker 状态恢复)"""
        task_id = message.metadata.get('task_id')
        status = message.metadata.get('status')
        sender = message.sender

        if not task_id or not status:
            return

        # [NEW Phase 4] 更新协作状态 (CoordinationState)
        if self.coordination_state and self.surface_manager:
            from ...core.durable.surfaces.coordination_state import SessionInfo, SessionState
            from .task_registry import TaskStatus as TStatus

            # 获取或创建会话信息
            if sender not in self.coordination_state.sessions:
                self.coordination_state.add_session(SessionInfo(
                    session_id=sender,
                    state=SessionState.EXECUTING,
                    created_at=datetime.utcnow().isoformat()
                ))

            # 更新会话绑定的义务 (Obligations)
            self.coordination_state.assign_obligation(sender, task_id)

            # 将 TaskStatus 映射到 SessionState
            try:
                target_tstatus = TStatus(status)
                s_state = SessionState.EXECUTING
                if target_tstatus == TStatus.COMPLETED:
                    s_state = SessionState.COMPLETED
                elif target_tstatus == TStatus.FAILED:
                    s_state = SessionState.FAILED
                elif target_tstatus == TStatus.IN_PROGRESS:
                    s_state = SessionState.EXECUTING

                self.coordination_state.update_session(sender, state=s_state)
            except Exception:
                pass

            # 持久化状态
            self.surface_manager.save_surface("coordination_state", self.coordination_state)

        try:
            from .task_registry import TaskStatus
            target_status = TaskStatus(status)

            if task_id in [t.task_id for t in self.task_registry.get_all_tasks()]:
                # 如果任务已存在，更新状态
                self.task_registry.update_status(task_id, target_status)

                # [NEW] 如果是完成状态，注入结果摘要
                if target_status in (TaskStatus.COMPLETED, TaskStatus.SUBMITTED):
                    result = message.metadata.get('result_summary')
                    if result:
                        self.task_registry.update_result(task_id, result)
                    evidence = message.metadata.get('evidence_paths')
                    if evidence:
                        task = self.task_registry.get_task(task_id)
                        if task:
                            task.evidence_paths = list(set(task.evidence_paths + evidence))
            else:
                # [NEW] 如果任务不存在（例如 Orchestrator 状态丢失时从磁盘恢复），注册一个新任务
                self._progress('sync', f'从持久化总线恢复任务: {task_id}')
                self.task_registry.register(
                    title=f"Recovered: {task_id}",
                    description=f"Recovered from persistent state: {status}",
                    task_id=task_id
                )
                self.task_registry.update_status(task_id, target_status)
        except Exception as e:
            self.logger.debug(f"Worker 状态同步异常: {task_id} -> {status}, error: {e}")


# 向后兼容: 从 pipeline 导出

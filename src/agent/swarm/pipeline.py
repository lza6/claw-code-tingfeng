"""Swarm 执行流水线 — 核心执行逻辑

封装 Swarm 引擎的核心执行管道逻辑，提供可独立调用的执行单元。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...llm import LLMConfig
from ...memory.enterprise_ltm import EnterpriseLTM
from .auditor import AuditorAgent, AuditReport
from .code_extractor import extract_file_changes
from .config import SwarmConfig
from .integrator import AtomicIntegrator
from .orchestrator import OrchestratorAgent
from .quality_gate import GateResult, QualityGate
from .task_registry import SubTask, TaskRegistry, TaskStatus

logger = logging.getLogger(__name__)


class SwarmPipeline:
    """Swarm 核心执行流水线

    封装任务分解、并行执行、审计和质量门禁的核心逻辑。
    """

    def __init__(
        self,
        config: SwarmConfig,
        workdir: Path,
        llm_config: LLMConfig | None,
        orchestrator: OrchestratorAgent,
        auditor: AuditorAgent | None,
        task_registry: TaskRegistry,
        quality_gate: QualityGate,
        integrator: AtomicIntegrator,
        ltm: EnterpriseLTM,
        get_worker_engine: Callable,
        progress_callback: Callable[[str, str], None] | None = None,
        worktree_manager: Any | None = None,
    ) -> None:
        self.config = config
        self.workdir = workdir
        self.llm_config = llm_config
        self.orchestrator = orchestrator
        self.auditor = auditor
        self.task_registry = task_registry
        self.quality_gate = quality_gate
        self.integrator = integrator
        self.ltm = ltm
        self._get_worker_engine = get_worker_engine
        self._progress = progress_callback or (lambda a, m: None)
        self.worktree_manager = worktree_manager
        self._use_isolation = True  # 默认开启隔离模式

    async def execute(
        self,
        goal: str,
        request_id: str,
        decomposition: Any,
        budget_guard: Any | None = None,
    ) -> tuple[dict[str, str], AuditReport | None, list[GateResult]]:
        """执行核心流水线

        参数:
            goal: 任务目标
            request_id: 请求 ID
            decomposition: 任务分解结果
            budget_guard: 预算守卫实例

        返回:
            (code_changes, audit_report, gate_results)
        """
        dag = decomposition.dag
        completed_task_ids: set[str] = set()
        running_tasks: dict[asyncio.Task, str] = {}
        task_results: dict[str, str] = {}
        code_changes: dict[str, str] = {}

        self._progress('swarm', '启动流式执行流水线 (Fluid Pipeline)...')

        # [可靠性增强] 开启集成事务
        await self.integrator.start_transaction()

        try:
            while not dag.is_complete(completed_task_ids) or running_tasks:
                # 3a. 找出新就绪的任务
                ready_ids = dag.get_ready_tasks(completed_task_ids)
                new_ready_ids = [
                    tid for tid in ready_ids
                    if tid not in completed_task_ids and tid not in running_tasks.values()
                ]

                # 3b. 启动新就绪的任务
                for t_id in new_ready_ids:
                    # 每次启动新任务前校验预算
                    if budget_guard:
                        budget_guard.validate()

                    t_data = dag.tasks[t_id]
                    task = self.task_registry.get_task(t_id) or self.task_registry.register_subtask(t_data)

                    # 注入依赖上下文
                    dep_results = self.task_registry.get_dependency_results(t_id)
                    if dep_results:
                        task.metadata['dependency_context'] = dep_results
                        self._progress('swarm', f'任务 {t_id} 已注入 {len(dep_results)} 个依赖上下文')

                    # 启动后台任务
                    fut = asyncio.create_task(self._execute_task_fn(task))
                    running_tasks[fut] = t_id

                if not running_tasks:
                    if not dag.is_complete(completed_task_ids):
                        logger.error("检测到任务循环依赖或执行卡死")
                        break
                    break

                # 3c. 等待任意一个任务完成
                done, _ = await asyncio.wait(running_tasks.keys(), return_when=asyncio.FIRST_COMPLETED)

                for fut in done:
                    t_id = running_tasks.pop(fut)
                    try:
                        result = await fut
                        task_results[t_id] = result
                        completed_task_ids.add(t_id)
                        dag.mark_task_completed(t_id)

                        # 3d. 收集代码变更
                        new_changes = extract_file_changes(result, task.metadata if task else None)
                        if new_changes:
                            code_changes.update(new_changes)
                            if self.config.enable_integrator:
                                self._progress('integrator', f'文件就绪: {list(new_changes.keys())}')
                                # 注意: 已经在事务中，apply_patch 会自动处理原子性
                                await self.integrator.integrate_batch(new_changes)

                                # [NEW Phase 4] 记录证据到 EvidenceLog
                                if hasattr(self.orchestrator, 'surface_manager') and self.orchestrator.surface_manager:
                                    try:
                                        from ...core.persistence.run_state import RunStateManager
                                        state_mgr = RunStateManager(self.workdir)
                                        for file_path in new_changes.keys():
                                            state_mgr.add_evidence_entry(
                                                evidence_id=f"ev-{t_id}-{int(asyncio.get_event_loop().time())}",
                                                evidence_type="code_integration",
                                                description=f"Task {t_id} integrated changes to {file_path}",
                                                obligation_id=t_id,
                                                recorded_by=f"worker-{t_id}"
                                            )
                                    except Exception as e:
                                        logger.warning(f"记录证据日志失败: {e}")

                        # [可靠性增强] 记录成功任务到经验回传中心
                        try:
                            from .self_fission.rl_experience import RLExperienceHub
                            hub = RLExperienceHub()
                            hub.record_task_experience(
                                task_description=dag.tasks[t_id].get('description', ''),
                                solution=result[:500],
                                success=True,
                                tags=dag.tasks[t_id].get('tags', [])
                            )
                        except Exception as rl_err:
                            logger.warning(f"记录成功经验失败: {rl_err}")

                        self._progress('swarm', f'任务 {t_id} 已完成')

                    except Exception as e:
                        logger.error(f'子任务 {t_id} 运行时异常: {e}')
                        # [可靠性增强] 记录任务失败到经验回传中心
                        try:
                            from .self_fission.rl_experience import RLExperienceHub
                            hub = RLExperienceHub()
                            hub.record_task_experience(
                                task_description=dag.tasks[t_id].get('description', ''),
                                solution="",
                                success=False,
                                error_pattern=str(e),
                                tags=dag.tasks[t_id].get('tags', [])
                            )
                        except Exception as rl_err:
                            logger.warning(f"记录失败经验失败: {rl_err}")

                        # [重要] 记录失败但继续，或者根据策略决定是否回滚
                        completed_task_ids.add(t_id)
                        dag.mark_task_completed(t_id)

            # Step 4: Auditor 审计
            audit_report: AuditReport | None = None
            if self.config.enable_auditor and self.auditor and code_changes:
                audit_report = await self.auditor.audit(code_changes)
                self._progress('auditor', f'审计{"通过" if audit_report.passed else "驳回"}')

                if not audit_report.passed:
                    # [可靠性增强] 审计失败且开启自愈逻辑
                    from .message_bus import AgentMessage, MessageType
                    await self.orchestrator.message_bus.publish(AgentMessage(
                        sender='auditor',
                        recipient='orchestrator-1',
                        message_type=MessageType.AUDIT_FAIL,
                        content=f"Audit failed for multiple files. Requesting self-healing.",
                        metadata={'report': audit_report.to_markdown(), 'is_fatal': True}
                    ))

                    for task in self.task_registry.get_tasks_by_status(TaskStatus.AUDIT_FAILED):
                        if task.retry_count < self.config.max_audit_retries:
                            self._progress('auditor', f'任务 {task.task_id} 触发自愈重试')
                            task.retry_count += 1
                            # 重新注入审计报告作为反馈
                            task.metadata['audit_feedback'] = audit_report.to_markdown()
                            result = await self._execute_task_fn(task)
                            task_results[task.task_id] = result
                        else:
                            raise RuntimeError(f"审计失败且超过重试限制: {task.task_id}")

            # Step 5: 质量门禁
            gate_results = self.quality_gate.run_all_gates(
                audit_report=audit_report,
                code_changes=code_changes if code_changes else None,
            )

            # 检查关键质量门禁
            critical_failure = any(not r.passed and r.severity == 'critical' for r in gate_results)
            if critical_failure:
                raise RuntimeError("未通过关键质量门禁，正在撤销所有变更。")

            # [所有检查通过] 提交事务
            await self.integrator.commit()
            return code_changes, audit_report, gate_results

        except Exception as e:
            logger.error(f"SwarmPipeline 执行失败，正在回滚: {e}")
            await self.integrator.rollback()
            self._progress('swarm', f"⚠️ 执行失败并已安全回滚: {str(e)[:100]}...")
            raise e

    async def _execute_task_fn(self, task: SubTask) -> str:
        """执行单个子任务的内部实现 (集成隔离环境与证据校验)"""
        import os
        import re

        from .roles import ROLE_SYSTEM_PROMPTS, AgentRole
        from .message_bus import AgentMessage, MessageType

        self.task_registry.update_status(task.task_id, TaskStatus.IN_PROGRESS)
        self._progress('worker', f'执行任务 {task.task_id}: {task.title}')

        # [NEW] 广播初始进度，以便持久化回溯
        if hasattr(self.orchestrator, 'message_bus'):
            await self.orchestrator.message_bus.publish(AgentMessage(
                sender='worker-logic',
                recipient=self.orchestrator.agent_id,
                message_type=MessageType.SYNC_STATE,
                content=f"Task {task.task_id} started",
                metadata={'task_id': task.task_id, 'status': TaskStatus.IN_PROGRESS.value}
            ))

        # 隔离环境准备
        exec_workdir = self.workdir
        if self._use_isolation and self.worktree_manager:
            try:
                exec_workdir = self.worktree_manager.create(task.task_id)
                task.worktree_id = task.task_id
                self._progress('worker', f'任务 {task.task_id} 已隔离至 Worktree: {exec_workdir}')
            except Exception as e:
                self._progress('worker', f'警告: 隔离环境创建失败，回退到主目录: {e}')

        engine = self._get_worker_engine()
        # 更新引擎工作目录
        if hasattr(engine, 'workdir'):
            engine.workdir = exec_workdir

        # 启用执行-审计配对机制
        if self.config.enable_auditor and self.auditor:
            engine.audit_mode = True
            engine.auditor = self.auditor
            engine.max_audit_retries = self.config.max_audit_retries

        role = task.metadata.get('role', AgentRole.WORKER)
        role_prompt = ROLE_SYSTEM_PROMPTS.get(role, ROLE_SYSTEM_PROMPTS[AgentRole.WORKER])

        # 动态角色指令合成 (v0.50.0)
        if role == AgentRole.SYNTHESIZED:
            dynamic_instruction = task.metadata.get('dynamic_instruction', '根据任务描述自主定义专家行为。')
            # [安全加固] 限制指令长度并过滤高危关键词，防止 Prompt 注入
            dynamic_instruction = dynamic_instruction[:500]
            BANNED_KEYWORDS = {'rm -rf', 'sudo', 'eval(', 'exec(', '__import__'}
            if any(kw in dynamic_instruction.lower() for kw in BANNED_KEYWORDS):
                self._progress('worker', f'错误: 任务 {task.task_id} 的动态指令包含禁止项')
                return "执行失败: 动态指令安全校验未通过"

            role_prompt = role_prompt.format(dynamic_instruction=dynamic_instruction)

        prompt = f"""作为 {role.value.upper()}，请执行以下子任务:

[角色系统提示]:
{role_prompt}

标题: {task.title}
描述: {task.description}
验证标准 (Outcome Proof): {task.verification_criteria or "实现功能并确保正确"}

要求:
1. 请完成代码实现，确保功能正确。
2. 输出代码时请使用 ```python 代码块格式。
3. 请在代码块的第一行显式注明目标文件路径，格式为: # file: 路径/文件名.py

执行建议:
- 优先选择最优雅的算法和模式
- 确保符合企业级性能标准

[相关依赖任务结果]:
{task.metadata.get('dependency_context', {})}

[审计反馈 (如有)]:
{task.metadata.get('audit_feedback', '无')}
"""

        try:
            session = await engine.run(prompt)
            result = session.final_result
            self.task_registry.update_result(task.task_id, result)

            # --- 证据发现逻辑 (借鉴 GoalX) ---
            evidence_paths = []
            paths = re.findall(r'([a-zA-Z0-9_/.-]+\.(?:log|txt|xml|html|py))', result)
            for p in paths:
                full_p = os.path.join(exec_workdir, p)
                if os.path.exists(full_p):
                    evidence_paths.append(p)
            task.evidence_paths = evidence_paths

            # 验证标准校验 (初步实现：若有显式标准且包含文件要求，检查文件是否存在)
            if "文件" in task.verification_criteria and task.metadata.get('file_path'):
                target_file = task.metadata['file_path']
                # [安全加固] 在文件校验前进行路径合法性检查
                is_safe = False
                try:
                    full_p = (Path(exec_workdir) / target_file).resolve()
                    if full_p.is_relative_to(Path(exec_workdir).resolve()):
                        is_safe = True
                except Exception:
                    pass

                if not is_safe:
                    self._progress('worker', f'错误: 任务 {task.task_id} 涉及非法路径 {target_file}')
                    return "执行失败: 路径越界校验失败"

                if not os.path.exists(os.path.join(exec_workdir, target_file)):
                    self._progress('worker', f'错误: 任务 {task.task_id} 未能生成预期文件 {target_file}')
                    # 此处可触发自愈或标记失败

            # 隔离环境整合
            if self._use_isolation and self.worktree_manager and task.worktree_id:
                self.worktree_manager.integrate(task.task_id)
                self.worktree_manager.remove(task.task_id)

            final_status = TaskStatus.COMPLETED
            if self.config.enable_auditor:
                final_status = TaskStatus.SUBMITTED

            # [NEW] 广播完成进度和证据，以便 Master 重启后恢复
            if hasattr(self.orchestrator, 'message_bus'):
                await self.orchestrator.message_bus.publish(AgentMessage(
                    sender='worker-logic',
                    recipient=self.orchestrator.agent_id,
                    message_type=MessageType.SYNC_STATE,
                    content=f"Task {task.task_id} finished",
                    metadata={
                        'task_id': task.task_id,
                        'status': final_status.value,
                        'evidence_paths': task.evidence_paths,
                        'result_summary': result[:200]
                    }
                ))

            self.task_registry.update_status(task.task_id, final_status)
            return result
        except Exception as e:
            if self._use_isolation and self.worktree_manager and task.worktree_id:
                self.worktree_manager.remove(task.task_id, force=True)

            self.task_registry.update_status(task.task_id, TaskStatus.FAILED)
            self._progress('worker', f'任务 {task.task_id} 执行失败: {e}')
            return f'执行失败: {e}'

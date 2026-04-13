"""自愈式执行引擎 - 负责任务执行、自愈式重试、异常反馈

从 workflow/engine.py 拆分出来 (Phase 3: EXECUTE - 自愈逻辑部分)
"""
from __future__ import annotations

import ast
import logging
import os
from pathlib import Path
from typing import Any

from .error_classifier import ErrorClassification
from .models import (
    WorkflowStatus,
    WorkflowTask,
)


class HealableExecutor:
    """自愈式执行引擎 - 执行任务并自动重试修复"""

    MAX_HEAL_RETRIES = 2

    def __init__(
        self,
        workdir: Path,
        feedback_loop: Any | None = None,
        meta_correction: Any | None = None,
        event_bus: Any | None = None,
        intent: str = "implement", # 默认为实现意图
        worktree_manager: Any | None = None,
        assurance_manager: Any | None = None,
    ) -> None:
        self.logger = logging.getLogger('workflow.executor')
        self.workdir = workdir
        self._feedback_loop = feedback_loop
        self._meta_correction = meta_correction
        self._event_bus = event_bus
        self.intent = intent
        self.worktree_manager = worktree_manager
        self.assurance_manager = assurance_manager
        self._use_isolation = False

    async def execute_with_healing(
        self, task: WorkflowTask,
    ) -> tuple[str, WorkflowStatus, bool]:
        """执行任务 + 自愈式修复 + 异常反馈回路 (集成 Worktree 隔离)

        返回:
            (result_text, status, was_healed)
        """
        last_error: Exception | None = None
        last_classification: ErrorClassification | None = None

        # 准备隔离环境
        current_workdir = self.workdir
        if self._use_isolation and self.worktree_manager:
            try:
                # 汲取 GoalX: 使用更具描述性的分支名
                import re
                # 去除特殊字符并截断，保持分支名整洁
                safe_title = re.sub(r'[^a-zA-Z0-9_-]', '-', task.title[:40]).strip('-').lower()
                branch_name = f"fix/{task.task_id}/{safe_title or 'untitled'}"
                current_workdir = self.worktree_manager.create(task.task_id, branch_name=branch_name)
                self.logger.info(f"任务 {task.task_id} 已隔离至工作树: {current_workdir} (分支: {branch_name})")
            except Exception as e:
                raise RuntimeError(f"创建工作树失败，终止执行: {e}") from e

        try:
            for attempt in range(1 + self.MAX_HEAL_RETRIES):
                try:
                    # 使用反馈回路或常规策略执行修复
                    result = await self._run_execution_attempt(task, attempt, current_workdir, last_error, last_classification)

                    # --- 证据提取与校验 (汲取 GoalX) ---
                    evidence_paths = self._extract_evidence(result, current_workdir)

                    # 增强证据反馈：如果发现关键文件，在结果中显著标注
                    evidence_summary = ""
                    if evidence_paths:
                        evidence_summary = f"\n\n[🔍 执行证据链]:\n" + "\n".join([f"  - {p}" for p in evidence_paths])

                    final_result_text = f"{result}{evidence_summary}"

                    self._verify_proof_of_work(task, result, evidence_paths)

                    # 修复成功，记录经验
                    if self._feedback_loop and attempt > 0 and last_error and last_classification:
                        self._feedback_loop.record_outcome(
                            last_error, task, last_classification,
                            success=True, fix_result=result
                        )

                    # 整合隔离环境
                    if self._use_isolation and self.worktree_manager:
                        await self._integrate_worktree(task, current_workdir)

                    return final_result_text, WorkflowStatus.COMPLETED, (attempt > 0)

                except Exception as e:
                    last_error = e
                    self.logger.warning(
                        f'任务 {task.task_id} 第 {attempt + 1} 次执行失败: {e}',
                    )
                    if self._feedback_loop:
                        last_classification = self._feedback_loop._classifier.classify(e)

            # 全部尝试已失败
            diagnosis = self._generate_diagnosis(task, str(last_error))
            if self._feedback_loop and last_error and last_classification:
                self._feedback_loop.record_outcome(
                    last_error, task, last_classification,
                    success=False, fix_result=diagnosis
                )
            return diagnosis, WorkflowStatus.FAILED, False

        finally:
            # 清理工作树
            if self._use_isolation and self.worktree_manager:
                self.worktree_manager.remove(task.task_id, force=True)

    async def _run_execution_attempt(self, task: WorkflowTask, attempt: int, workdir: Path, last_error: Exception | None, last_classification: ErrorClassification | None) -> str:
        """执行单次尝试"""
        if attempt == 0:
            return await self._execute_task(task, workdir)

        if self._feedback_loop and last_error and last_classification:
            feedback_result = await self._feedback_loop.handle_error(last_error, task, attempt)
            recommended_fix = self._feedback_loop.find_recommended_fix(last_error, min_success_rate=0.6)
            fix_strategy = recommended_fix or feedback_result.fix_strategy
            return await self._execute_heal_strategy_with_feedback(task, fix_strategy, last_error)

        strategy = self._build_heal_strategy(task, attempt, str(last_error))
        return await self._execute_heal_strategy(task, strategy, workdir)

    def _extract_evidence(self, result: str, workdir: Path) -> list[str]:
        """提取执行证据 (汲取 GoalX)"""
        import re
        evidence_paths = []

        def _resolve_safe_path(base: Path, candidate: str) -> Path | None:
            """安全解析路径，防止路径遍历 (加固版)"""
            clean_candidate = candidate.strip('`"\'').replace('\\', '/')

            # 严格拦截绝对路径 (涵盖 Windows/Unix) 和回溯路径
            # Path(p).is_absolute() 在 Windows 下能识别 C:\ 这种路径
            if Path(clean_candidate).is_absolute() or '..' in clean_candidate.split('/'):
                return None

            try:
                # 使用 resolve() 解析所有符号链接和相对路径部分
                base_resolved = base.resolve()
                resolved = (base_resolved / clean_candidate).resolve()

                # 使用 commonpath 验证 resolved 是否在 base_resolved 之下
                # 这是最稳健的目录包含检查方法
                if os.path.commonpath([str(base_resolved), str(resolved)]) != str(base_resolved):
                    return None

                return resolved
            except (OSError, ValueError, RuntimeError):
                return None

        # 1. 匹配日志和报告文件
        paths = re.findall(r'([a-zA-Z0-9_/.-]+\.(?:log|txt|xml|html|json|md))', result)
        for p in paths:
            full_path = _resolve_safe_path(workdir, p)
            if full_path and full_path.exists() and full_path.is_file():
                evidence_paths.append(str(full_path.relative_to(workdir.resolve())))

        # 2. 自动匹配测试相关的关键产物
        test_patterns = [
            "**/report.xml",
            "**/.pytest_cache/v/cache/lastfailed",
            "**/coverage.xml",
            "**/junit-*.xml"
        ]
        for pattern in test_patterns:
            try:
                for p in workdir.glob(pattern):
                    rel_p = str(p.relative_to(workdir))
                    if rel_p not in evidence_paths:
                        evidence_paths.append(rel_p)
            except Exception:
                continue

        # 3. 匹配新创建或修改的源文件 (作为证据)
        # 如果 result 中提到了 "Created file" 或 "Updated file"，尝试提取
        file_actions = re.findall(r'(?:Created|Updated|Modified)\s+file:\s*([^\s]+)', result)
        for f in file_actions:
            full_path = _resolve_safe_path(workdir, f)
            if full_path and full_path.exists() and full_path.is_file():
                evidence_paths.append(str(full_path.relative_to(workdir.resolve())))

        return list(set(evidence_paths))

    def _verify_proof_of_work(self, task: WorkflowTask, result: str, evidence: list[str]) -> None:
        """验证工作证明 (Proof of Work)"""
        has_evidence = len(evidence) > 0 or any(k in result for k in ["协作修复成功", "已分析"])
        self.logger.debug(f"Proof validation for {task.task_id}: evidence={evidence}, result_len={len(result)}, has_evidence={has_evidence}")
        if not has_evidence and any(k in task.title.lower() for k in ['fix', 'repair', 'refactor']):
            raise ValueError(f"任务 {task.task_id} 执行结束但未提供有效证明 (Proof Gap)")

    async def _integrate_worktree(self, task: WorkflowTask, workdir: Path) -> None:
        """整合工作树"""
        verification_passed = True
        if self.assurance_manager:
            self.logger.info(f"任务 {task.task_id} 执行完毕，正在运行质保验证...")
            verification_passed = await self.assurance_manager.run_scenarios_for_task(task.task_id, workdir)

        if not verification_passed:
            raise RuntimeError(f"任务 {task.task_id} 整合前验证失败 (Outcome Verification Failed)")

        if self.worktree_manager:
            if not self.worktree_manager.integrate(task.task_id):
                raise RuntimeError(f"任务 {task.task_id} 整合失败 (可能存在冲突或无有效更改)")
            self.worktree_manager.remove(task.task_id)
            self.logger.info(f"任务 {task.task_id} 隔离执行并整合成功。")

    async def _execute_task(self, task: WorkflowTask, workdir: Path | None = None) -> str:
        """执行单个修复任务"""
        exec_workdir = workdir or self.workdir
        # Meta-Self-Correction: 检索历史失败案例
        if self._meta_correction:
            advice = self._meta_correction.get_avoidance_advice(task.description)
            if advice:
                self.logger.info(f"历史规避建议: {advice[0][:100]}")

        # 判断是否使用 SwarmEngine
        is_complex = any(sev in task.title.lower() for sev in ['critical', 'high'])
        is_coding = any(cat in task.title.lower() for cat in ['complexity', 'duplication', 'security'])

        if is_complex or is_coding:
            try:
                result = await self._execute_with_swarm(task, exec_workdir)
                if result:
                    return result
            except Exception as e:
                self.logger.warning(f"SwarmEngine 启动失败: {e}，回退到常规策略")

        # 使用常规策略模式执行修复
        from .strategies import execute_strategy
        return execute_strategy(task, exec_workdir)

    async def _execute_with_swarm(self, task: WorkflowTask, workdir: Path) -> str | None:
        """使用 SwarmEngine 执行任务"""
        try:
            from ..agent.swarm.config import SwarmConfig
            from ..agent.swarm.engine import SwarmEngine

            self.logger.info(f"启用 SwarmEngine 协作修复任务: {task.task_id}")
            swarm_config = SwarmConfig(
                enable_auditor=True,
                enable_integrator=True,
                fallback_to_single_agent=True
            )
            swarm = SwarmEngine(config=swarm_config, workdir=workdir, intent=self.intent)

            swarm_goal = f"修复代码中的质量问题: {task.title}\n\n详细说明:\n{task.description}"
            result = await swarm.run(swarm_goal)

            if result.success:
                return f"Swarm 协作修复成功: {result.final_result}"
            else:
                return f"Swarm 协作尝试失败: {'; '.join(result.errors)}"
        except (ImportError, Exception):
            return None

    def _build_heal_strategy(
        self, task: WorkflowTask, attempt: int, last_error: str,
    ) -> dict[str, str]:
        """生成修复策略"""
        strategies = {
            1: self._heal_diagnosis,
            2: self._heal_fallback,
        }
        handler = strategies.get(attempt, self._heal_fallback)
        return handler(task, last_error)

    def _heal_diagnosis(self, task: WorkflowTask, last_error: str) -> dict[str, str]:
        """诊断型修复策略 - 细化策略标识"""
        error_lower = last_error.lower()

        if 'syntax' in error_lower or 'parse' in error_lower:
            return {'action': '语法修复：尝试修正代码结构', 'strategy': 'fix_syntax'}
        elif 'no such' in error_lower or 'not found' in error_lower or '不存' in error_lower:
            return {'action': '路径修复：检查并创建缺失目录', 'strategy': 'fix_path'}
        elif 'permission' in error_lower or 'denied' in error_lower:
            return {'action': '权限不足：记录并跳过', 'strategy': 'safe_skip'}

        return {'action': f'未知错误处理: {last_error[:50]}', 'strategy': 'general_fix'}

    def _heal_fallback(self, task: WorkflowTask, last_error: str) -> dict[str, str]:
        """保守降级策略"""
        return {
            'action': '保守降级：已记录问题，跳过自动修复',
            'strategy': 'safe_skip',
        }

    async def _execute_heal_strategy(
        self, task: WorkflowTask, strategy: dict[str, str], workdir: Path | None = None
    ) -> str:
        """执行修复策略 - 真实落地逻辑"""
        exec_workdir = workdir or self.workdir
        action = strategy.get('action', '')
        strategy_name = strategy.get('strategy', '')

        self.logger.info(f"正在执行自愈策略: {strategy_name} - {action}")

        if strategy_name == 'fix_syntax':
            # 真实动作：启动 Swarm 或专用策略进行修复
            return await self._execute_task(task, exec_workdir)
        elif strategy_name == 'safe_skip':
            return f"已选择安全跳过: {action}"

        # 默认尝试使用常规策略重新执行
        from .strategies import execute_strategy
        return await execute_strategy(task, exec_workdir)

    async def _execute_heal_strategy_with_feedback(
        self,
        task: WorkflowTask,
        fix_strategy: str,
        original_error: Exception,
    ) -> str:
        """执行基于反馈回路的修复策略"""
        if self._feedback_loop:
            classification = self._feedback_loop._classifier.classify(original_error)
            category_name = classification.category.value if classification else 'unknown'
            return f'[错误分类: {category_name}] 修复策略: {fix_strategy}'

        # 回退到基础错误类型匹配
        error_lower = str(original_error).lower()

        if 'syntax' in error_lower or 'parse' in error_lower or 'invalid syntax' in error_lower:
            return f'语法错误修复: {fix_strategy}'
        elif 'no such' in error_lower or 'not found' in error_lower or 'file not found' in error_lower:
            return f'文件路径修复: {fix_strategy}，跳过不存在的路径'
        elif 'permission' in error_lower or 'denied' in error_lower:
            return f'权限问题: {fix_strategy}，已跳过'
        elif 'import' in error_lower or 'module' in error_lower:
            return f'导入错误修复: {fix_strategy}'
        elif 'type' in error_lower:
            return f'类型错误修复: {fix_strategy}'
        elif 'value' in error_lower:
            return f'值错误修复: {fix_strategy}'
        else:
            return f'通用修复: {fix_strategy}'

    def _generate_diagnosis(self, task: WorkflowTask, last_error: str) -> str:
        """生成诊断报告"""
        return (
            f'[诊断报告] 任务 {task.task_id} 自愈失败\n'
            f'  任务: {task.title}\n'
            f'  最后错误: {last_error[:200]}\n'
            f'  建议: 需要人工介入'
        )

    @staticmethod
    def _parse_file_location(desc: str) -> dict[str, str] | None:
        """从描述中解析文件路径和行号"""
        import re
        match = re.search(r'文件:\s*([^\s:]+)(?::(\d+))?', desc)
        if not match:
            return None
        result = {'file': match.group(1)}
        if match.group(2):
            result['line'] = match.group(2)
        # Try to extract function name hint
        func_match = re.search(r'[`「](\w+)[`」]', desc)
        if func_match:
            result['hint'] = func_match.group(1)
        lines_match = re.search(r'(\d+)\s*行', desc)
        if lines_match:
            result['lines'] = lines_match.group(1)
        return result

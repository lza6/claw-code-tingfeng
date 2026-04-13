"""异常反馈回路 — 工作流错误自动感知与修复"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.events import Event, EventBus, EventType, get_event_bus
from .error_classifier import ErrorCategory, ErrorClassification, ErrorClassifier
from .experience_bank import ExperienceBank
from .models import TechDebtPriority, WorkflowTask
from .tech_debt import TechDebtManager


@dataclass
class FeedbackResult:
    """反馈回路结果"""
    success: bool                        # 是否修复成功
    classification: ErrorClassification  # 错误分类
    fix_strategy: str                    # 使用的修复策略
    fix_result: str                      # 修复结果描述
    experience_updated: bool = False     # 经验库是否更新
    tech_debt_recorded: bool = False     # 是否记录到技术债务


class ErrorAnalyzer:
    """问题分析子 Agent — 分析错误根因并生成修复计划"""

    def __init__(self, workdir: Path | None = None) -> None:
        self.workdir = workdir or Path.cwd()
        self.logger = logging.getLogger('workflow.error_analyzer')

    def analyze(
        self,
        error: Exception,
        task: WorkflowTask,
        classification: ErrorClassification,
    ) -> dict[str, Any]:
        """分析错误并生成诊断报告

        参数:
            error: 原始异常
            task: 失败的任务
            classification: 错误分类结果

        返回:
            诊断报告字典
        """
        diagnosis = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'category': classification.category.value,
            'task_id': task.task_id,
            'task_title': task.title,
            'root_cause': self._guess_root_cause(classification),
            'fix_plan': self._generate_fix_plan(classification, task),
            'preventive_measures': self._get_preventive_measures(classification),
        }
        return diagnosis

    def _guess_root_cause(self, classification: ErrorClassification) -> str:
        """猜测错误根因"""
        category = classification.category
        error_msg = classification.original_error[:100]

        root_causes = {
            ErrorCategory.SYNTAX: f'代码语法不正确: {error_msg}',
            ErrorCategory.FILE_NOT_FOUND: f'文件路径不存在: {error_msg}',
            ErrorCategory.PERMISSION: f'权限不足无法操作: {error_msg}',
            ErrorCategory.IMPORT: f'模块未安装或路径错误: {error_msg}',
            ErrorCategory.RUNTIME: f'运行时数据异常: {error_msg}',
            ErrorCategory.NETWORK: f'网络连接异常: {error_msg}',
            ErrorCategory.TIMEOUT: f'操作超时: {error_msg}',
            ErrorCategory.RESOURCE: f'系统资源不足: {error_msg}',
            ErrorCategory.UNKNOWN: f'未知错误: {error_msg}',
        }
        return root_causes.get(category, error_msg)

    def _generate_fix_plan(
        self,
        classification: ErrorClassification,
        task: WorkflowTask,
    ) -> str:
        """生成修复计划"""
        category = classification.category
        fix_plans = {
            ErrorCategory.SYNTAX: '注释掉问题代码行，重新验证语法',
            ErrorCategory.FILE_NOT_FOUND: '检查路径是否正确，或跳过该任务',
            ErrorCategory.PERMISSION: '跳过该任务并记录，需要人工授权',
            ErrorCategory.IMPORT: '安装缺失的依赖模块',
            ErrorCategory.RUNTIME: '检查输入数据，添加异常处理',
            ErrorCategory.NETWORK: '检查网络连接，稍后重试',
            ErrorCategory.TIMEOUT: '增加超时时间或优化代码',
            ErrorCategory.RESOURCE: '释放系统资源或增加配置',
            ErrorCategory.UNKNOWN: classification.suggested_fix,
        }
        return fix_plans.get(category, '需要人工介入')

    @staticmethod
    def _get_preventive_measures(classification: ErrorClassification) -> list[str]:
        """获取预防措施"""
        category = classification.category
        measures = {
            ErrorCategory.SYNTAX: ['使用 linter 检查代码', '添加语法验证'],
            ErrorCategory.FILE_NOT_FOUND: ['添加路径存在性检查', '使用绝对路径'],
            ErrorCategory.PERMISSION: ['提前检查权限', '使用 sudo 或授权'],
            ErrorCategory.IMPORT: ['添加依赖检查脚本', '使用 requirements.txt'],
            ErrorCategory.RUNTIME: ['添加输入验证', '使用类型检查'],
            ErrorCategory.NETWORK: ['添加重试机制', '使用连接池'],
            ErrorCategory.TIMEOUT: ['优化算法复杂度', '增加超时配置'],
            ErrorCategory.RESOURCE: ['监控资源使用', '优化内存使用'],
            ErrorCategory.UNKNOWN: ['添加详细日志', '人工审查代码'],
        }
        return measures.get(category, ['人工审查'])


class ExceptionFeedbackLoop:
    """异常反馈回路 — 工作流错误自动感知与修复"""

    def __init__(
        self,
        workdir: Path | None = None,
        event_bus: EventBus | None = None,
        experience_storage: Path | None = None,
    ) -> None:
        self.workdir = workdir or Path.cwd()
        self.logger = logging.getLogger('workflow.feedback_loop')
        self._event_bus = event_bus or get_event_bus()
        self._classifier = ErrorClassifier()
        self._analyzer = ErrorAnalyzer(self.workdir)
        self._experience_bank = ExperienceBank(experience_storage)
        self._tech_debt_manager = TechDebtManager(self.workdir)

    async def handle_error(
        self,
        error: Exception,
        task: WorkflowTask,
        attempt: int,
    ) -> FeedbackResult:
        """处理错误并生成反馈 — 集成 EnterpriseLTM 经验

        流程:
        1. 分类错误
        2. 查询企业级 LTM (EnterpriseLTM)
        3. 如果 LTM 无果，查询基础经验库 (ExperienceBank)
        4. 分析错误（子 Agent）
        5. 生成修复计划
        6. 发布错误事件
        """
        # Step 1: 分类错误
        classification = self._classifier.classify(error)
        self.logger.info(
            f'错误分类: {classification.category.value} '
            f'(置信度: {classification.confidence:.2f})'
        )

        # Step 2: 查询企业级 LTM (v3 核心: 跨项目经验复用)
        from ..memory.enterprise_ltm import EnterpriseLTM, PatternType
        ltm = EnterpriseLTM()

        # 尝试寻找失败预防模式 (Failure Prevention)
        ltm_patterns = await ltm.find_similar_patterns(str(error))
        ltm_fix = None
        if ltm_patterns:
            # 优先选择失败预防模式
            prevention = next((p for p in ltm_patterns if p.pattern_type == PatternType.FAILURE_PREVENTION), None)
            if prevention:
                ltm_fix = f"参考企业级失败预防方案: {prevention.description}\n代码: {prevention.solution_code[:100]}..."
                self.logger.info(f"匹配到企业级失败预防模式: {prevention.pattern_id}")
            else:
                # 否则选择最相关的成功模式
                ltm_fix = f"参考企业级成功模式: {ltm_patterns[0].description}"
                self.logger.info(f"匹配到企业级成功模式: {ltm_patterns[0].pattern_id}")

        # Step 3: 回退到基础经验库
        similar_exp = self._experience_bank.find_similar_fix(
            classification.original_error,
            classification.category.value,
        )
        experience_fix = ltm_fix or (similar_exp.fix_strategy if similar_exp else None)

        # Step 4: 分析错误
        diagnosis = self._analyzer.analyze(error, task, classification)

        # Step 5: 生成修复策略
        fix_strategy = experience_fix or classification.suggested_fix

        # Step 6: 发布错误事件
        self._event_bus.publish(Event(
            type=EventType.WORKFLOW_TASK_ERROR,
            data={
                'task_id': task.task_id,
                'error_type': classification.category.value,
                'error_message': str(error),
                'attempt': attempt,
                'fix_strategy': fix_strategy,
                'diagnosis': diagnosis,
                'ltm_hit': ltm_fix is not None
            },
            source='feedback_loop',
        ))

        # Step 7: 执行修复
        fix_result = f'修复策略: {fix_strategy}\n诊断: {diagnosis["root_cause"]}'

        return FeedbackResult(
            success=False,
            classification=classification,
            fix_strategy=fix_strategy,
            fix_result=fix_result,
        )

    def record_outcome(
        self,
        error: Exception,
        task: WorkflowTask,
        classification: ErrorClassification,
        success: bool,
        fix_result: str,
    ) -> FeedbackResult:
        """记录修复结果并更新经验库

        参数:
            error: 原始异常
            task: 失败的任务
            classification: 错误分类
            success: 修复是否成功
            fix_result: 修复结果描述

        返回:
            更新后的 FeedbackResult
        """
        # 更新经验库
        exp_record = self._experience_bank.record_experience(
            error_pattern=classification.original_error,
            error_category=classification.category.value,
            fix_strategy=classification.suggested_fix,
            success=success,
            task_description=task.description,
            fix_details=fix_result,
        )

        # 如果失败，记录到 TECH_DEBT.md
        tech_debt_recorded = False
        if not success:
            self._tech_debt_manager.initialize()
            self._tech_debt_manager.add_record(
                issue_id=f'heal-{task.task_id}',
                description=f'自愈失败: {task.title}\n错误: {str(error)[:200]}',
                affected_files=[],
                priority=TechDebtPriority.HIGH,
            )
            tech_debt_recorded = True

        # 发布结果事件
        self._event_bus.publish(Event(
            type=EventType.WORKFLOW_HEAL_COMPLETED if success else EventType.WORKFLOW_HEAL_FAILED,
            data={
                'task_id': task.task_id,
                'success': success,
                'experience_id': exp_record.error_pattern,
                'tech_debt_recorded': tech_debt_recorded,
            },
            source='feedback_loop',
        ))

        return FeedbackResult(
            success=success,
            classification=classification,
            fix_strategy=classification.suggested_fix,
            fix_result=fix_result,
            experience_updated=True,
            tech_debt_recorded=tech_debt_recorded,
        )

    def get_experience_stats(self) -> dict[str, Any]:
        """获取经验统计"""
        return {
            'classifier': self._classifier.get_stats(),
            'experience_bank': self._experience_bank.get_stats(),
        }

    def find_recommended_fix(
        self,
        error: Exception,
        min_success_rate: float = 0.5,
    ) -> str | None:
        """查找推荐的修复方案"""
        classification = self._classifier.classify(error)
        similar = self._experience_bank.find_similar_fix(
            classification.original_error,
            classification.category.value,
            min_success_rate,
        )
        return similar.fix_strategy if similar else None

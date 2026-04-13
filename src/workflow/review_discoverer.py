"""审查与发现模块 - 负责全局审查、清理、文档、发现新优化点

从 workflow/engine.py 拆分出来 (Phase 4: REVIEW & Phase 5: DISCOVER)
"""
from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any

from .models import (
    TechDebtPriority,
    WorkflowPhase,
    WorkflowPhaseCategory,
    WorkflowStatus,
    WorkflowTask,
)


class ReviewDiscoverer:
    """审查与发现器 - 全局审查、清理、文档、发现新优化点"""

    def __init__(self, workdir: Path, event_bus: Any | None = None) -> None:
        self.logger = logging.getLogger('workflow.review')
        self.workdir = workdir
        self._event_bus = event_bus

    async def phase_review(self, tasks: list[WorkflowTask]) -> str:
        """全局审查、清理、文档、完成报告"""
        self._publish_event('WORKFLOW_PHASE_STARTED', {'phase': WorkflowPhase.REVIEW.value})

        review_items: dict[str, str] = {}

        # 1) Global review: check for leftover temp files, backup files
        self._publish_event('WORKFLOW_TASK_STARTED',
                           {'category': WorkflowPhaseCategory.REVIEW_GLOBAL.value})
        leftovers = self._find_leftovers()
        review_items['leftovers'] = f'{len(leftovers)} temp/backup files'
        self._publish_event('WORKFLOW_TASK_COMPLETED',
                           {'category': WorkflowPhaseCategory.REVIEW_GLOBAL.value,
                            'leftovers': len(leftovers)})

        # 2) Cleanup
        self._publish_event('WORKFLOW_TASK_STARTED',
                           {'category': WorkflowPhaseCategory.REVIEW_CLEANUP.value})
        cleaned = self._cleanup(leftovers)
        review_items['cleaned'] = f'{cleaned} files removed'
        self._publish_event('WORKFLOW_TASK_COMPLETED',
                           {'category': WorkflowPhaseCategory.REVIEW_CLEANUP.value,
                            'cleaned': cleaned})

        # 3) Documentation: update TECH_DEBT.md for failed tasks or quality debt
        # 3.1) Handle Failed Tasks
        self._publish_event('WORKFLOW_TASK_STARTED',
                           {'category': WorkflowPhaseCategory.REVIEW_DOCUMENT.value})
        failed_tasks = [t for t in tasks if t.status == WorkflowStatus.FAILED]
        from .tech_debt import TechDebtManager
        td_mgr = TechDebtManager(self.workdir)

        if failed_tasks:
            for ft in failed_tasks:
                td_mgr.add_record(
                    issue_id='workflow-auto-failure',
                    description=f'未完成的修复: {ft.title}',
                    affected_files=[],
                )

        # 3.2) Handle Quality Debt (v0.50.0 Auto-Healing)
        from .quality_debt import QualityDebtCollector
        collector = QualityDebtCollector(str(self.workdir))
        changed_files = []
        for t in tasks:
            if t.status == WorkflowStatus.COMPLETED:
                # 简单解析描述中的文件路径
                import re
                matches = re.findall(r'文件: ([\w/.-]+\.py)', t.description)
                changed_files.extend(matches)

        if changed_files:
            debt = collector.collect(list(set(changed_files)))
            if not debt.is_zero():
                self.logger.info(f"检测到质量债务: {debt}")
                if debt.test_gap:
                    td_mgr.add_record(
                        issue_id='quality-debt-test',
                        description='检测到测试缺口：新修改的源文件缺少对应的测试用例。',
                        affected_files=changed_files,
                        priority=TechDebtPriority.MEDIUM
                    )
                if debt.documentation_gap:
                    td_mgr.add_record(
                        issue_id='quality-debt-doc',
                        description='检测到文档缺口：核心逻辑变动未同步更新文档。',
                        affected_files=changed_files,
                        priority=TechDebtPriority.LOW
                    )
                for complex_fn in debt.complex_functions:
                    td_mgr.add_record(
                        issue_id='quality-debt-complexity',
                        description=f'函数复杂度过高: {complex_fn}',
                        affected_files=changed_files,
                        priority=TechDebtPriority.HIGH
                    )

        review_items['tech_debt_added'] = f'{len(failed_tasks)} failure records'
        self._publish_event('WORKFLOW_TASK_COMPLETED',
                           {'category': WorkflowPhaseCategory.REVIEW_DOCUMENT.value,
                            'failed_tasks_recorded': len(failed_tasks)})

        # 4) Report
        self._publish_event('WORKFLOW_TASK_STARTED',
                           {'category': WorkflowPhaseCategory.REVIEW_REPORT.value})
        completed = sum(1 for t in tasks if t.status == WorkflowStatus.COMPLETED)
        review_items['success_rate'] = (
            f'{completed}/{len(tasks)} ({completed/max(1,len(tasks))*100:.0f}%)'
        )
        self._publish_event('WORKFLOW_TASK_COMPLETED',
                           {'category': WorkflowPhaseCategory.REVIEW_REPORT.value})

        self._publish_event('WORKFLOW_PHASE_COMPLETED',
                           {'phase': WorkflowPhase.REVIEW.value})

        return '; '.join(f'{k}: {v}' for k, v in review_items.items())

    async def phase_discover(
        self, goal: str, tasks: list[WorkflowTask]
    ) -> list[str]:
        """发现新优化点"""
        self._publish_event('WORKFLOW_PHASE_STARTED',
                           {'phase': WorkflowPhase.DISCOVER.value})

        new_points: list[str] = []

        # Analyze failed tasks for cascading issues
        failed = [t for t in tasks if t.status == WorkflowStatus.FAILED]
        if failed:
            failure_categories = Counter()
            for t in failed:
                cat = t.title.split('.')[0] if '.' in t.title else 'unknown'
                failure_categories[cat] += 1
            for cat, count in failure_categories.items():
                new_points.append(f'[{cat}] {count} 个任务执行失败，需人工介入')

        # Check for architectural improvements after changes
        structural_points = self._check_architecture()
        new_points.extend(structural_points)

        self._publish_event('WORKFLOW_TASK_STARTED',
                           {'category': WorkflowPhaseCategory.DISCOVER_OPTIMIZE.value})
        self._publish_event('WORKFLOW_TASK_COMPLETED',
                           {'category': WorkflowPhaseCategory.DISCOVER_OPTIMIZE.value,
                            'new_points': len(new_points)})

        self._publish_event('WORKFLOW_PHASE_COMPLETED',
                           {'phase': WorkflowPhase.DISCOVER.value})
        return new_points

    def _find_leftovers(self) -> list[Path]:
        """查找临时文件、备份文件、swap 文件"""
        extensions = {'.bak', '.tmp', '.orig', '.rej', '.swp', '.swo',
                      '.pyc', '.pyo', '~'}
        results: list[Path] = []

        try:
            for item in self.workdir.rglob('*'):
                if not item.is_file():
                    continue
                if item.suffix in extensions or item.name.endswith('~'):
                    if '__pycache__' in str(item) or '/.git/' in str(item):
                        continue
                    results.append(item)
        except (OSError, PermissionError):
            self.logger.warning('残留文件扫描被权限错误中断')

        return results

    def _cleanup(self, files: list[Path]) -> int:
        """清理临时文件"""
        removed = 0
        for f in files:
            try:
                f.unlink()
                removed += 1
                self.logger.debug(f'已清理临时文件: {f}')
            except (OSError, PermissionError):
                self.logger.warning(f'无法清理文件 {f}，跳过')
        return removed

    def _check_architecture(self) -> list[str]:
        """架构级优化建议"""
        points: list[str] = []
        src_dir = self.workdir / 'src'
        if not src_dir.exists():
            return points

        # Check for circular imports hint
        init_files = list(src_dir.rglob('__init__.py'))
        init_with_imports = []
        for init in init_files:
            try:
                content = init.read_text(encoding='utf-8')
                if 'import' in content:
                    init_with_imports.append(str(init.relative_to(self.workdir)))
            except (OSError, PermissionError):
                pass

        if len(init_with_imports) > 10:
            points.append(
                f'{len(init_with_imports)} 个 __init__.py 有导入，'
                '可能需要简化或消除循环依赖'
            )

        # Large modules (> 500 lines in a single file)
        large_modules = []
        for py_file in src_dir.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue
            try:
                content = py_file.read_text(encoding='utf-8', errors='replace')
                if content.count('\n') > 500:
                    large_modules.append(str(py_file.relative_to(self.workdir)))
            except (OSError, PermissionError):
                pass

        if large_modules:
            points.append(f'{len(large_modules)} 个模块超过 500 行，建议拆分')

        return points

    def _publish_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """封装事件发布"""
        if self._event_bus:
            from ..core.events import Event, EventType
            try:
                et = getattr(EventType, event_type)
                self._event_bus.publish(Event(type=et, data=data or {}, source='workflow_review'))
            except AttributeError:
                pass  # Event type doesn't exist

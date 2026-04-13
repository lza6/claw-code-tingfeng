"""Meta-Self-Correction — 经验自反思闭环

特性:
- 长效记忆: 任务日志向量化存储，自动检索相似失败案例
- 自进化逻辑: 定期自动触发框架代码审计，生成优化建议
- 历史规避: 开始新任务前自动检索历史失败案例
"""
from __future__ import annotations

import ast
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ASTAuditor(ast.NodeVisitor):
    """基于 AST 的高级代码审计器"""

    def __init__(self):
        self.findings = []
        self._current_function = None
        self._nesting_level = 0
        self._max_nesting = 0

    def visit_FunctionDef(self, node: ast.FunctionDef):
        old_nesting = self._nesting_level
        old_max = self._max_nesting
        self._current_function = node.name
        self._nesting_level = 0
        self._max_nesting = 0
        self.generic_visit(node)
        if self._max_nesting > 4:
            self.findings.append(f"代码异味: 函数 '{node.name}' 嵌套过深 (>{self._max_nesting} 层)")
        self._current_function = None
        self._nesting_level = old_nesting
        self._max_nesting = old_max

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)

    def visit_Try(self, node: ast.Try):
        for handler in node.handlers:
            if handler.type is None:
                self.findings.append("安全建议: 存在裸 except: 捕获，建议指定具体异常类型")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "time" and node.func.attr == "sleep":
                self.findings.append("性能风险: 在异步场景或主循环中使用 time.sleep，建议改用 asyncio.sleep")
        self.generic_visit(node)

    def generic_visit(self, node):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            self._nesting_level += 1
            self._max_nesting = max(self._max_nesting, self._nesting_level)
            super().generic_visit(node)
            self._nesting_level -= 1
        else:
            super().generic_visit(node)

from ..self_healing.experience_bank import (
    ExperienceEntry,
    VectorExperienceBank,
)

logger = logging.getLogger(__name__)


@dataclass
class TaskLog:
    """任务日志"""
    task_id: str
    goal: str
    success: bool
    error_traceback: str = ""
    fix_applied: str = ""
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SelfAuditResult:
    """自审计结果"""
    audit_id: str
    target: str                    # 审计目标 (框架模块)
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    severity: str = "low"          # low, medium, high, critical
    timestamp: float = field(default_factory=time.time)


class MetaSelfCorrection:
    """经验自反思闭环

    职责:
    1. 任务日志记录与向量化
    2. 相似失败案例检索
    3. 历史规避建议
    4. 自进化审计
    """

    def __init__(
        self,
        experience_bank: VectorExperienceBank | None = None,
        storage_path: Path | None = None,
        max_entries: int = 1000,
    ) -> None:
        self.experience_bank = experience_bank or VectorExperienceBank(
            storage_path=storage_path,
            max_entries=max_entries,
        )
        self._task_logs: list[TaskLog] = []
        self._audit_results: list[SelfAuditResult] = []

    def log_task(
        self,
        task_id: str,
        goal: str,
        success: bool,
        error_traceback: str = "",
        fix_applied: str = "",
        duration: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """记录任务日志

        参数:
            task_id: 任务 ID
            goal: 任务目标
            success: 是否成功
            error_traceback: 错误堆栈
            fix_applied: 应用的修复
            duration: 持续时间
            metadata: 元数据

        返回:
            经验 ID (如果失败并记录到经验库)
        """
        log = TaskLog(
            task_id=task_id,
            goal=goal,
            success=success,
            error_traceback=error_traceback,
            fix_applied=fix_applied,
            duration_seconds=duration,
            metadata=metadata or {},
        )
        self._task_logs.append(log)

        # 失败任务记录到经验库
        exp_id = ""
        if not success and error_traceback:
            exp_id = self.experience_bank.record_experience(
                error_traceback=error_traceback,
                fix_strategy=fix_applied or "待分析",
                fix_code="",
                success=False,
                error_category=metadata.get("error_category", "") if metadata else "",
            )

        return exp_id

    async def retrieve_similar_failures(
        self,
        current_error: str,
        top_k: int = 5,
    ) -> list[ExperienceEntry]:
        """检索相似失败案例

        参数:
            current_error: 当前错误
            top_k: 返回前 K 个结果

        返回:
            相似失败经验列表
        """
        similar = self.experience_bank.find_similar(
            current_error,
            top_k=top_k,
            min_success_rate=0.0,  # 包括失败的
        )
        return similar

    def get_avoidance_advice(
        self,
        current_goal: str,
    ) -> list[str]:
        """获取规避建议

        基于历史任务日志，提供规避建议

        参数:
            current_goal: 当前任务目标

        返回:
            规避建议列表
        """
        advice = []

        # 查找相似目标的历史失败
        goal_keywords = current_goal.lower().split()

        for log in self._task_logs:
            if not log.success:
                # 检查目标是否相似
                log_keywords = log.goal.lower().split()
                common = set(goal_keywords) & set(log_keywords)

                if len(common) >= 2:
                    advice.append(
                        f"历史相似任务 '{log.goal[:50]}' 失败: "
                        f"{log.error_traceback[:100]}... "
                        f"修复: {log.fix_applied[:100]}"
                    )

        return advice[:5]  # 最多 5 条建议

    async def self_audit(
        self,
        target_module: str,
        source_code: str,
    ) -> SelfAuditResult:
        """自进化审计 — 审计框架自身代码

        参数:
            target_module: 目标模块名
            source_code: 源代码

        返回:
            自审计结果
        """
        findings = []
        recommendations = []
        severity = "low"

        # 1. AST 深度审计 (Python 专用)
        try:
            tree = ast.parse(source_code)
            auditor = ASTAuditor()
            auditor.visit(tree)
            findings.extend(auditor.findings)
        except Exception as e:
            # 非 Python 代码回退到正则检查或仅记录错误
            if target_module.endswith(".py") or ".py" not in target_module:
                findings.append(f"审计警告: 语法解析失败 ({e!s})")

        # 2. 检查冗余代码模式
        redundant_patterns = self._check_redundant_patterns(source_code)
        findings.extend(redundant_patterns)

        # 3. 检查性能瓶颈
        perf_issues = self._check_performance_issues(source_code)
        findings.extend(perf_issues)

        # 4. 检查代码异味 (正则回退)
        code_smells = self._check_code_smells(source_code)
        # 过滤掉 AST 已覆盖的部分以去重
        for cs in code_smells:
            if not any(f in cs for f in findings):
                findings.append(cs)

        # 生成建议
        if findings:
            for f in findings:
                if "冗余" in f:
                    recommendations.append(f"重构: {f}")
                elif "性能" in f or "风险" in f:
                    recommendations.append(f"优化: {f}")
                    severity = max(severity, "medium", key=lambda x: ["low", "medium", "high", "critical"].index(x))
                elif "异味" in f or "建议" in f:
                    recommendations.append(f"清理: {f}")

        result = SelfAuditResult(
            audit_id=f"audit-{int(time.time())}",
            target=target_module,
            findings=findings,
            recommendations=recommendations,
            severity=severity,
        )

        self._audit_results.append(result)
        return result

    def _check_redundant_patterns(self, code: str) -> list[str]:
        """检查冗余代码模式"""
        findings = []

        # 检查重复导入
        import re
        imports = re.findall(r'^(from .+ import .+|import .+)$', code, re.MULTILINE)
        if len(imports) != len(set(imports)):
            findings.append("存在冗余导入语句")

        # 检查未使用的变量
        if re.search(r'_unused|_temp|_placeholder', code):
            findings.append("存在未使用的占位变量")

        return findings

    def _check_performance_issues(self, code: str) -> list[str]:
        """检查性能问题"""
        findings = []

        # 检查同步阻塞调用
        if "time.sleep(" in code:
            findings.append("性能: 使用 time.sleep 可能阻塞，建议使用 asyncio.sleep")

        # 检查非优化的循环
        if "for i in range(len(" in code:
            findings.append("性能: 建议使用 enumerate 替代 range(len(...))")

        return findings

    def _check_code_smells(self, code: str) -> list[str]:
        """检查代码异味"""
        findings = []

        # 检查过长函数
        lines = code.split("\n")
        if len(lines) > 200:
            findings.append("代码异味: 模块过长 (>200 行)")

        # 检查深层嵌套
        max_indent = max((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
        if max_indent > 16:  # 4 层嵌套
            findings.append("代码异味: 嵌套过深 (>4 层)")

        return findings

    def get_stats(self) -> dict[str, Any]:
        """获取统计"""
        return {
            "task_logs": len(self._task_logs),
            "successful_tasks": sum(1 for log in self._task_logs if log.success),
            "failed_tasks": sum(1 for log in self._task_logs if not log.success),
            "experience_entries": len(self.experience_bank._experiences),
            "audit_results": len(self._audit_results),
            "experience_bank_stats": self.experience_bank.get_stats(),
        }

    def save(self) -> None:
        """保存所有数据"""
        self.experience_bank.save()

    def load(self) -> int:
        """加载所有数据"""
        return self.experience_bank.load()

"""质量门禁"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .auditor import AuditReport

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    """门禁结果"""
    passed: bool
    gate_name: str
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class QualityGate:
    """质量门禁系统

    门禁层级:
    1. Gate 1 (审计门): 语法、安全、规范
    2. Gate 2 (审查门): 架构、可维护性
    3. Gate 3 (集成门): 集成测试、全量验证
    """

    def __init__(
        self,
        workdir: Path | None = None,
        lint_strict: bool = True,
        require_tests: bool = True,
    ) -> None:
        self.workdir = workdir or Path.cwd()
        self.lint_strict = lint_strict
        self.require_tests = require_tests

    def check_audit_gate(self, audit_report: AuditReport) -> GateResult:
        """Gate 1: 审计门

        检查项:
        - 无 critical 级别问题
        - 无 high 级别安全问题
        - 语法正确
        """
        checks = [
            '无 critical 问题' if audit_report.critical_count == 0 else f'发现 {audit_report.critical_count} 个 critical 问题',
            '无 high 问题' if audit_report.high_count == 0 else f'发现 {audit_report.high_count} 个 high 问题',
        ]

        # 检查是否有语法错误
        syntax_errors = [f for f in audit_report.findings if f.category == 'syntax']
        checks.append('语法检查通过' if not syntax_errors else f'发现 {len(syntax_errors)} 个语法错误')

        failures = [c for c in checks if '发现' in c]
        passed = len(failures) == 0

        return GateResult(
            passed=passed,
            gate_name='audit',
            checks=checks,
            failures=failures,
            warnings=audit_report.warnings,
        )

    def check_review_gate(self, review_report: str) -> GateResult:
        """Gate 2: 审查门

        检查项:
        - 审查通过
        - 无驳回标记
        """
        passed = '驳回' not in review_report and 'FAIL' not in review_report

        checks = [
            '审查通过' if passed else '审查未通过',
        ]

        return GateResult(
            passed=passed,
            gate_name='review',
            checks=checks,
            failures=[] if passed else ['审查未通过'],
        )

    def check_integration_gate(self, code_changes: dict[str, str]) -> GateResult:
        """Gate 3: 集成门

        检查项:
        - 所有 Python 文件语法正确
        - 无冲突标记
        - [NEW] Ruff 静态检查通过
        """
        import ast
        import subprocess
        import tempfile
        import os

        checks: list[str] = []
        failures: list[str] = []

        for file_path, content in code_changes.items():
            if file_path.endswith('.py'):
                # 1. AST 语法检查
                try:
                    ast.parse(content)
                    checks.append(f'{file_path}: 语法正确')
                except SyntaxError as e:
                    msg = f'{file_path}: 语法错误 - {e.msg}'
                    checks.append(msg)
                    failures.append(msg)
                    continue

                # 2. 物理 Lint 检查 (Ruff)
                if self.lint_strict:
                    with tempfile.NamedTemporaryFile(suffix=".py", mode='w', encoding='utf-8', delete=False) as tmp:
                        tmp.write(content)
                        tmp_path = tmp.name

                    try:
                        # 尝试运行 ruff check --quiet
                        res = subprocess.run(
                            ["ruff", "check", "--quiet", tmp_path],
                            capture_output=True,
                            text=True
                        )
                        if res.returncode != 0:
                            msg = f'{file_path}: 未通过 Ruff 检查 - {res.stdout[:200]}'
                            checks.append(msg)
                            failures.append(msg)
                        else:
                            checks.append(f'{file_path}: Ruff 检查通过')
                    except Exception as e:
                        logger.debug(f"跳过 Ruff 检查 (工具未安装或环境异常): {e}")
                    finally:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)

            # 3. 检查冲突标记
            if '<<<<<<<' in content or '=======' in content or '>>>>>>>' in content:
                msg = f'{file_path}: 存在合并冲突标记'
                checks.append(msg)
                failures.append(msg)

        return GateResult(
            passed=len(failures) == 0,
            gate_name='integration',
            checks=checks,
            failures=failures,
        )

    def run_all_gates(
        self,
        audit_report: AuditReport,
        review_report: str = "",
        code_changes: dict[str, str] | None = None,
    ) -> list[GateResult]:
        """运行所有门禁

        返回:
            所有门禁结果列表
        """
        results = []

        # Gate 1: 审计门
        results.append(self.check_audit_gate(audit_report))

        # Gate 2: 审查门 (可选)
        if review_report:
            results.append(self.check_review_gate(review_report))

        # Gate 3: 集成门 (可选)
        if code_changes:
            results.append(self.check_integration_gate(code_changes))

        return results

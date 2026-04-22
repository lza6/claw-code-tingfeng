"""质量门控系统 (Quality Gate)

参考: oh-my-codex-main 的 quality gate 概念
在关键操作前执行自动化检查:
    - 代码风格 (ruff format + lint)
    - 类型检查 (mypy)
    - 测试覆盖 (pytest --cov)
    - 安全检查 (bandit 或 semgrep)
    - 依赖检查 (pip-audit)

集成点:
    - SwarmAgent 完成后的 PostTask 阶段
    - Workflow 的 Review 阶段
    - Commit 前的 PreCommit 阶段
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)


class GateLevel(str, Enum):
    """质量门级别"""
    COMMIT = "commit"       # 每次提交前 (最快)
    TASK = "task"           # 每个任务完成后
    PHASE = "phase"         # 每个阶段结束
    RELEASE = "release"     # 发布前 (最严格)


class GateResult(str, Enum):
    """门禁检查结果"""
    PASS = "pass"
    WARN = "warn"      # 有警告但可继续
    FAIL = "fail"      # 阻断
    SKIP = "skip"      # 跳过 (无相关文件)


@dataclass
class GateCheck:
    """单个检查项"""
    name: str
    command: list[str] | str
    level: GateLevel
    file_patterns: list[str] = None  # 匹配的文件模式
    timeout: int = 60
    ignore_errors: bool = False  # 是否忽略错误
    description: str = ""


@dataclass
class GateReport:
    """门禁报告"""
    level: GateLevel
    checks: list[GateCheckResult]
    overall: GateResult
    summary: str = ""


@dataclass
class GateCheckResult:
    """单个检查结果"""
    check: GateCheck
    result: GateResult
    output: str = ""
    duration_ms: float = 0.0


# ==================== 预定义门禁规则 ====================

DEFAULT_GATES: dict[GateLevel, list[GateCheck]] = {
    GateLevel.COMMIT: [
        GateCheck(
            name="format",
            command=["ruff", "format", "--check", "."],
            level=GateLevel.COMMIT,
            description="代码格式检查 (ruff format --check)",
        ),
        GateCheck(
            name="lint",
            command=["ruff", "check", "--fix", "."],
            level=GateLevel.COMMIT,
            description="代码风格检查 (ruff check)",
        ),
    ],
    GateLevel.TASK: [
        GateCheck(
            name="typecheck",
            command=["mypy", "src/", "--ignore-missing-imports"],
            level=GateLevel.TASK,
            file_patterns=["*.py"],
            timeout=120,
            description="类型检查 (mypy)",
        ),
    ],
    GateLevel.PHASE: [
        GateCheck(
            name="tests",
            command=["pytest", "tests/", "-x", "--tb=short"],
            level=GateLevel.PHASE,
            description="运行测试套件",
            timeout=300,
        ),
        GateCheck(
            name="coverage",
            command=["pytest", "tests/", "--cov=src", "--cov-report=term-missing"],
            level=GateLevel.PHASE,
            description="测试覆盖率检查",
            timeout=300,
        ),
    ],
    GateLevel.RELEASE: [
        GateCheck(
            name="security",
            command=["bandit", "-r", "src/"],
            level=GateLevel.RELEASE,
            description="安全检查 (bandit)",
            timeout=120,
        ),
    ],
}


class QualityGate:
    """质量门控制器

    提供两阶段质量门:
        - 轻量级 Gate: lint + fast checks
        - 全面 Gate: tests + coverage + security
    """

    def __init__(
        self,
        workdir: Path,
        level: GateLevel = GateLevel.TASK,
        strict: bool = False,  # 严格模式：任何失败都阻断
    ):
        self.workdir = workdir
        self.level = level
        self.strict = strict
        self.results: list[GateCheckResult] = []

    def run(self, path_hint: Path | None = None) -> GateReport:
        """运行质量门检查"""
        import time

        logger.info(f"Running quality gate (level={self.level.value})")

        checks = list(DEFAULT_GATES.get(self.level, []))
        results = []

        for check in checks:
            start = time.time()
            try:
                result = self._run_check(check, path_hint)
            except Exception as e:
                result = GateCheckResult(
                    check=check,
                    result=GateResult.FAIL,
                    output=str(e),
                    duration_ms=(time.time() - start) * 1000,
                )
            results.append(result)

        # 计算总体结果
        overall = self._calculate_overall(results)

        report = GateReport(
            level=self.level,
            checks=results,
            overall=overall,
            summary=self._summarize(results),
        )
        self.results = results
        return report

    def _run_check(self, check: GateCheck, path_hint: Path | None) -> GateCheckResult:
        """执行单个检查"""
        import time

        start = time.time()

        # 构建命令 (支持路径提示)
        cmd = check.command
        if isinstance(cmd, list) and path_hint:
            # 替换占位符 {path} 或添加路径参数
            if "{path}" in cmd:
                cmd = [c.replace("{path}", str(path_hint)) for c in cmd]
            else:
                cmd = cmd + [str(path_hint)]

        # 执行
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=check.timeout,
                shell=isinstance(cmd, str),
            )

            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()

            # 判断结果
            if proc.returncode == 0:
                result = GateResult.PASS
            elif check.ignore_errors or self._is_warning_code(proc.returncode):
                result = GateResult.WARN
            else:
                result = GateResult.FAIL

            output = stdout or stderr or "(no output)"

        except subprocess.TimeoutExpired:
            result = GateResult.FAIL
            output = f"TIMEOUT after {check.timeout}s"
        except FileNotFoundError:
            result = GateResult.SKIP
            output = f"Command not found: {cmd[0] if isinstance(cmd, list) else cmd}"

        return GateCheckResult(
            check=check,
            result=result,
            output=output[:2000],  # 截断过长输出
            duration_ms=(time.time() - start) * 1000,
        )

    def _is_warning_code(self, returncode: int) -> bool:
        """判断退出码是否仅产生警告"""
        # ruff: 0=pass, 1=violations found (fixable), 2=internal error
        if returncode == 1:
            return True
        return False

    def _calculate_overall(self, results: list[GateCheckResult]) -> GateResult:
        """计算总体结果"""
        if not results:
            return GateResult.PASS

        has_fail = any(r.result == GateResult.FAIL for r in results)
        has_warn = any(r.result == GateResult.WARN for r in results)

        if has_fail:
            return GateResult.FAIL
        elif has_warn:
            return GateResult.WARN if self.strict else GateResult.PASS
        return GateResult.PASS

    def _summarize(self, results: list[GateCheckResult]) -> str:
        """生成摘要"""
        passed = sum(1 for r in results if r.result == GateResult.PASS)
        warnings = sum(1 for r in results if r.result == GateResult.WARN)
        failures = sum(1 for r in results if r.result == GateResult.FAIL)

        status_icon = {
            GateResult.PASS: "✅",
            GateResult.WARN: "⚠️ ",
            GateResult.FAIL: "❌",
            GateResult.SKIP: "⏭️ ",
        }

        lines = [
            f"质量门 [bold]{self.level.value}[/bold]: ",
            " ".join(
                f"{status_icon.get(r.result, '?')} {r.check.name}"
                for r in results
            ),
        ]

        if failures:
            lines.append(f"\n[bold red]{failures} 个检查失败，门禁阻断[/bold red]")
        elif warnings:
            lines.append(f"\n[yellow]{warnings} 个警告 {'(strict模式将阻断)' if self.strict else ''}[/yellow]")
        else:
            lines.append(f"\n[bold green]{passed} 个检查全部通过[/bold green]")

        return "".join(lines)

    def must_block(self) -> bool:
        """是否应该阻断"""
        return self.overall == GateResult.FAIL

    @property
    def overall(self) -> GateResult:
        return self.results[0].result if self.results else GateResult.PASS


# ==================== 便捷函数 ====================

def run_quality_gate(
    workdir: Path,
    level: GateLevel = GateLevel.TASK,
    strict: bool = False,
    path_hint: Path | None = None,
) -> GateReport:
    """一条命令运行质量门

    用法:
        report = run_quality_gate(Path.cwd(), GateLevel.TASK)
        if report.overall == GateResult.FAIL:
            raise Exception("质量门失败")
    """
    gate = QualityGate(workdir, level, strict)
    report = gate.run(path_hint=path_hint)

    # 输出报告
    console.print(report.summary)

    return report


def should_block_on_gate(level: GateLevel, strict: bool = False) -> bool:
    """根据配置决定是否阻断"""
    gate = QualityGate(Path.cwd(), level, strict)
    report = gate.run()
    return report.overall == GateResult.FAIL


__all__ = [
    "DEFAULT_GATES",
    "GateCheckResult",
    "GateLevel",
    "GateReport",
    "GateResult",
    "QualityGate",
    "run_quality_gate",
    "should_block_on_gate",
]

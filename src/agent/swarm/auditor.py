"""Auditor Agent — 代码审计师（核心质量保障）

职责:
- 语法正确性（AST 解析）
- 代码规范（Ruff/Black 标准）
- 安全风险扫描
- 测试覆盖检查
- 性能影响评估
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ...llm import LLMConfig
from ..engine import AgentEngine
from .base_agent import BaseAgent
from .message_bus import AgentMessage, MessageBus, MessageType
from .roles import AgentRole

logger = logging.getLogger(__name__)


@dataclass
class AuditFinding:
    """审计发现"""
    severity: str           # critical | high | medium | low | info
    category: str           # syntax | security | convention | performance | test_coverage
    file: str
    line: int
    description: str
    suggestion: str = ""
    code_snippet: str = ""


@dataclass
class AuditReport:
    """审计报告"""
    passed: bool
    findings: list[AuditFinding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == 'critical')

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == 'high')

    def to_markdown(self) -> str:
        lines = [
            '# 审计报告',
            '',
            f'**结果**: {"通过" if self.passed else "驳回"}',
            f'**严重问题**: {self.critical_count}',
            f'**高优先级**: {self.high_count}',
            f'**警告**: {len(self.warnings)}',
            '',
        ]

        if self.findings:
            lines.append('## 问题列表')
            lines.append('')
            for f in self.findings:
                lines.append(f'- **[{f.severity.upper()}]** `{f.file}:{f.line}` - {f.description}')
                if f.suggestion:
                    lines.append(f'  - 建议: {f.suggestion}')
            lines.append('')

        if self.warnings:
            lines.append('## 警告')
            for w in self.warnings:
                lines.append(f'- {w}')
            lines.append('')

        if self.summary:
            lines.append(f'## 摘要\n{self.summary}')

        return '\n'.join(lines)


class AuditorAgent(BaseAgent):
    """审计师 Agent — 核心质量保障

    审计维度:
    1. 语法正确性 (AST 解析)
    2. 安全风险 (eval/exec, SQL 注入, 硬编码密钥)
    3. 代码规范 (bare except, import *, 长行)
    4. 性能影响 (循环字符串拼接, 列表推导 vs 生成器)
    5. 测试覆盖 (新增代码是否有测试)
    """

    # 默认配置常量
    DEFAULT_LLM_REVIEW_BATCH_SIZE = 3
    DEFAULT_MAX_LINE_LENGTH = 120

    def __init__(
        self,
        agent_id: str,
        message_bus: MessageBus,
        workdir: Path | None = None,
        llm_config: LLMConfig | None = None,
        lint_strict: bool = True,
        require_tests: bool = True,
        llm_review_batch_size: int = DEFAULT_LLM_REVIEW_BATCH_SIZE,
        max_line_length: int = DEFAULT_MAX_LINE_LENGTH,
    ) -> None:
        super().__init__(agent_id, AgentRole.AUDITOR, message_bus)
        self.workdir = workdir or Path.cwd()
        self._llm_config = llm_config
        self._engine: AgentEngine | None = None
        self.lint_strict = lint_strict
        self.require_tests = require_tests
        self.llm_review_batch_size = llm_review_batch_size
        self.max_line_length = max_line_length

    def _get_engine(self) -> AgentEngine:
        if self._engine is None:
            from ..factory import create_agent_engine
            if self._llm_config:
                self._engine = create_agent_engine(
                    provider_type=self._llm_config.provider.value,
                    api_key=self._llm_config.api_key,
                    model=self._llm_config.model or 'gpt-4o',
                )
            else:
                self._engine = create_agent_engine()
        return self._engine

    async def audit(self, code_changes: dict[str, str]) -> AuditReport:
        """审计代码变更

        参数:
            code_changes: {file_path: new_content}

        返回:
            AuditReport 对象
        """
        findings: list[AuditFinding] = []
        warnings: list[str] = []

        for file_path, content in code_changes.items():
            # 1. 语法检查
            findings.extend(self._check_syntax(file_path, content))

            # 2. 安全检查
            findings.extend(self._check_security(file_path, content))

            # 3. 规范检查
            findings.extend(self._check_conventions(file_path, content))

            # 4. 性能检查
            findings.extend(self._check_performance(file_path, content))

        # 5. 测试覆盖
        if self.require_tests:
            warnings.extend(self._check_test_coverage(code_changes))

        # 6. LLM 辅助审查（可选，用于发现更深层问题）
        llm_findings = await self._llm_assist(code_changes)
        findings.extend(llm_findings)

        # 判断是否通过
        critical_or_high = sum(1 for f in findings if f.severity in ('critical', 'high'))
        passed = critical_or_high == 0

        summary = self._build_summary(findings, warnings)

        return AuditReport(
            passed=passed,
            findings=findings,
            warnings=warnings,
            summary=summary,
        )

    def _check_syntax(self, file_path: str, content: str) -> list[AuditFinding]:
        """检查语法正确性"""
        findings: list[AuditFinding] = []

        if not file_path.endswith('.py'):
            return findings

        try:
            ast.parse(content)
        except SyntaxError as e:
            findings.append(AuditFinding(
                severity='critical',
                category='syntax',
                file=file_path,
                line=e.lineno or 0,
                description=f'语法错误: {e.msg}',
                suggestion='修复语法错误后再提交',
            ))

        return findings

    def _check_security(self, file_path: str, content: str) -> list[AuditFinding]:
        """检查安全风险"""
        findings: list[AuditFinding] = []
        lines = content.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue

            # eval/exec 使用
            if re.search(r'\beval\s*\(', stripped) or re.search(r'\bexec\s*\(', stripped):
                # 排除注释和检查代码本身
                if 're.search' not in stripped and 'description=' not in stripped:
                    findings.append(AuditFinding(
                        severity='critical',
                        category='security',
                        file=file_path,
                        line=i,
                        description='使用了不安全的 eval/exec',
                        suggestion='使用 ast.literal_eval 或其他安全替代方案',
                        code_snippet=stripped,
                    ))

            # 硬编码密钥/密码
            secret_patterns = [
                r'(password|secret|api_key|token)\s*=\s*["\'][^"\']{8,}["\']',
                r'AWS_SECRET_ACCESS_KEY\s*=',
                r'PRIVATE KEY',
            ]
            for pattern in secret_patterns:
                if re.search(pattern, stripped, re.IGNORECASE):
                    if 'example' not in stripped.lower() and 'placeholder' not in stripped.lower():
                        findings.append(AuditFinding(
                            severity='high',
                            category='security',
                            file=file_path,
                            line=i,
                            description='疑似硬编码密钥/密码',
                            suggestion='使用环境变量或密钥管理服务',
                            code_snippet=stripped,
                        ))

            # SQL 注入风险
            if re.search(r'(execute|cursor\.execute)\s*\(\s*["\'].*%s', stripped):
                findings.append(AuditFinding(
                    severity='high',
                    category='security',
                    file=file_path,
                    line=i,
                    description='疑似 SQL 拼接，存在注入风险',
                    suggestion='使用参数化查询',
                    code_snippet=stripped,
                ))

        return findings

    def _check_conventions(self, file_path: str, content: str) -> list[AuditFinding]:
        """检查代码规范"""
        findings: list[AuditFinding] = []
        lines = content.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.rstrip()

            # 行长度
            if self.lint_strict and len(stripped) > self.max_line_length:
                findings.append(AuditFinding(
                    severity='low',
                    category='convention',
                    file=file_path,
                    line=i,
                    description=f'行过长 ({len(stripped)} 字符，上限 {self.max_line_length})',
                    suggestion='拆分为多行',
                ))

        # bare except
        if re.search(r'except\s*:', content):
            # 排除测试文件和本文件
            if 'test_audit' not in file_path:
                findings.append(AuditFinding(
                    severity='medium',
                    category='convention',
                    file=file_path,
                    line=0,
                    description='使用了 bare except',
                    suggestion='改为 except Exception:',
                ))

        # import *
        if re.search(r'from\s+\S+\s+import\s+\*', content) and '__init__.py' not in file_path:
            findings.append(AuditFinding(
                severity='medium',
                category='convention',
                file=file_path,
                line=0,
                description='使用了 import *',
                suggestion='显式导入需要的名称',
            ))

        return findings

    def _check_performance(self, file_path: str, content: str) -> list[AuditFinding]:
        """检查性能反模式"""
        findings: list[AuditFinding] = []

        # 循环中字符串拼接
        if re.search(r'(for|while)\s.*\+.*str\(', content):
            findings.append(AuditFinding(
                severity='medium',
                category='performance',
                file=file_path,
                line=0,
                description='疑似循环中字符串拼接',
                suggestion='使用 list + join 或 f-string',
            ))

        # 列表推导 vs 生成器
        if re.search(r'(sum|min|max)\(\[.*for.*\]\)', content):
            findings.append(AuditFinding(
                severity='low',
                category='performance',
                file=file_path,
                line=0,
                description='sum/min/max 中使用了列表推导而非生成器',
                suggestion='去掉方括号改为生成器表达式',
            ))

        return findings

    def _check_test_coverage(self, code_changes: dict[str, str]) -> list[str]:
        """检查测试覆盖"""
        warnings: list[str] = []

        # 检查是否有新增的 Python 文件
        new_py_files = [f for f in code_changes if f.endswith('.py') and 'test' not in f.lower()]

        if new_py_files:
            # 简单检查 tests 目录是否有对应测试
            tests_dir = self.workdir / 'tests'
            if not tests_dir.exists():
                warnings.append('无 tests 目录，建议添加测试文件')
                return warnings

            test_files = list(tests_dir.rglob('*.py'))
            if not test_files:
                warnings.append('无测试文件，新增代码缺乏测试覆盖')

        return warnings

    async def _llm_assist(self, code_changes: dict[str, str]) -> list[AuditFinding]:
        """使用 LLM 辅助审查（并行优化）"""
        findings: list[AuditFinding] = []

        if not code_changes:
            return findings

        engine = self._get_engine()
        import asyncio

        # 将文件分批并行审查，批次大小可配置
        file_list = list(code_changes.items())
        batch_size = self.llm_review_batch_size
        batches = [file_list[i:i + batch_size] for i in range(0, len(file_list), batch_size)]

        async def review_batch(batch):
            batch_findings = []
            changes_summary = '\n\n'.join(
                f'### {fp}\n```python\n{content[:1000]}\n```'
                for fp, content in batch
            )

            prompt = f"""请审查以下代码变更，指出任何潜在问题:

    {changes_summary}

    关注点:
    1. 逻辑错误
    2. 边界条件
    3. 可维护性问题
    4. 潜在 Bug

    如果有问题，请简要描述。如果没有问题，回复"无问题"。"""

            try:
                session = await engine.run(prompt)
                result = session.final_result.lower()
                if '无问题' not in result and 'no issue' not in result and 'no problem' not in result:
                    batch_findings.append(AuditFinding(
                        severity='medium',
                        category='review',
                        file=f'(LLM Review: {", ".join(f[0] for f in batch)})',
                        line=0,
                        description='LLM 审查发现潜在问题',
                        suggestion=session.final_result[:500],
                    ))
            except Exception as e:
                logger.warning(f'LLM 辅助审查批次失败: {e}')
            return batch_findings

        # 并行执行所有批次
        results = await asyncio.gather(*(review_batch(b) for b in batches))
        for batch_res in results:
            findings.extend(batch_res)

        return findings

    def _build_summary(self, findings: list[AuditFinding], warnings: list[str]) -> str:
        """构建摘要"""
        if not findings and not warnings:
            return '代码质量良好，未发现明显问题'

        parts = []
        if findings:
            by_severity = {}
            for f in findings:
                by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
            parts.append(f'发现 {len(findings)} 个问题: ' +
                        ', '.join(f'{v} {k}' for k, v in by_severity.items()))
        if warnings:
            parts.append(f'{len(warnings)} 个警告')

        return '; '.join(parts)

    async def process(self, message: AgentMessage) -> str:
        """处理消息"""
        if message.message_type == MessageType.AUDIT_REQUEST:
            try:
                code_changes = message.metadata.get('code_changes', {})
                report = await self.audit(code_changes)

                if report.passed:
                    reply = message.reply(
                        MessageType.AUDIT_PASS,
                        '审计通过',
                        metadata={'report': report.to_markdown()},
                    )
                else:
                    reply = message.reply(
                        MessageType.AUDIT_FAIL,
                        '审计驳回',
                        metadata={'report': report.to_markdown()},
                    )

                await self.message_bus.publish(reply)
                return report.to_markdown()
            except Exception as e:
                logger.error(f'审计失败: {e}')
                return f'审计失败: {e}'

        return f'未知操作: {message.message_type.value}'

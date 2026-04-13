"""验证协议 — 汲取 oh-my-codex evidence-backed 验证模式

功能:
- 结构化验证结果（passed, evidence, summary, confidence）
- 任务大小分级（small/standard/large）
- 验证指令生成（按任务大小自动调整检查项）
- 修复循环指令生成
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskSize(Enum):
    """任务大小分级"""
    SMALL = 'small'
    STANDARD = 'standard'
    LARGE = 'large'


class EvidenceType(Enum):
    """验证证据类型"""
    TEST = 'test'
    TYPECHECK = 'typecheck'
    LINT = 'lint'
    BUILD = 'build'
    MANUAL = 'manual'
    RUNTIME = 'runtime'
    SECURITY = 'security'


class Confidence(Enum):
    """验证置信度"""
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'


@dataclass
class VerificationEvidence:
    """单条验证证据"""
    type: EvidenceType
    passed: bool
    command: str = ''
    output: str = ''
    details: str = ''

    def as_text(self) -> str:
        status = '✓ PASS' if self.passed else '✗ FAIL'
        parts = [f'[{status}] {self.type.value}']
        if self.command:
            parts.append(f'  命令: {self.command}')
        if self.details:
            parts.append(f'  详情: {self.details}')
        if self.output and not self.passed:
            # 截取输出前 500 字符
            truncated = self.output[:500]
            parts.append(f'  输出: {truncated}')
        return '\n'.join(parts)


@dataclass
class VerificationResult:
    """验证结果"""
    passed: bool
    evidence: list[VerificationEvidence] = field(default_factory=list)
    summary: str = ''
    confidence: Confidence = Confidence.MEDIUM

    def as_text(self) -> str:
        status = '✓ 验证通过' if self.passed else '✗ 验证失败'
        parts = [
            f'## 验证结果: {status}',
            f'置信度: {self.confidence.value}',
            '',
        ]
        if self.summary:
            parts.append(f'摘要: {self.summary}')
            parts.append('')

        if self.evidence:
            parts.append('### 验证证据:')
            for ev in self.evidence:
                parts.append(ev.as_text())
                parts.append('')

        return '\n'.join(parts)

    def to_reflected_message(self) -> str | None:
        """转换为反思消息 (Aider 风格)"""
        if self.passed:
            return None

        failures = [ev.as_text() for ev in self.evidence if not ev.passed]
        if not failures:
            return f"验证未通过，但未找到明确失败条目。摘要: {self.summary}"

        return "发现以下验证失败项，请修复：\n\n" + "\n\n".join(failures)


def determine_task_size(file_count: int, line_changes: int) -> TaskSize:
    """根据文件数和行数变化判定任务大小

    参数:
        file_count: 影响的文件数
        line_changes: 代码行变更数

    返回:
        任务大小分级
    """
    if file_count <= 3 and line_changes < 100:
        return TaskSize.SMALL
    if file_count <= 15 and line_changes < 500:
        return TaskSize.STANDARD
    return TaskSize.LARGE


def get_verification_instructions(task_size: TaskSize, task_description: str) -> str:
    """生成验证指令（按任务大小分级）

    参数:
        task_size: 任务大小
        task_description: 任务描述

    返回:
        验证指令文本
    """
    base = f'## 验证协议\n\n验证以下任务已完成: {task_description}\n\n### 必须提供的证据:\n'

    instructions = {
        TaskSize.SMALL: base + (
            '1. 对修改文件运行语法/类型检查\n'
            '2. 运行相关测试\n'
            '3. 确认变更按预期工作\n\n'
            '报告: 每项检查的 PASS/FAIL 结果。\n'
        ),
        TaskSize.STANDARD: base + (
            '1. 运行完整类型检查（如适用）\n'
            '2. 运行测试套件（聚焦变更区域）\n'
            '3. 对修改文件运行 linter\n'
            '4. 端到端验证功能/修复\n'
            '5. 检查相关功能的回归\n\n'
            '报告: 每项检查的 PASS/FAIL 结果及命令输出。\n'
        ),
        TaskSize.LARGE: base + (
            '1. 运行项目级完整类型检查\n'
            '2. 运行完整测试套件\n'
            '3. 对修改文件运行 linter\n'
            '4. 安全审计（OWASP Top 10 检查）\n'
            '5. 性能影响评估\n'
            '6. API 兼容性检查（如适用）\n'
            '7. 所有受影响功能的端到端验证\n'
            '8. 相邻功能的回归测试\n\n'
            '报告: 每项检查的详细 PASS/FAIL 结果。\n'
            '包含置信度（high/medium/low）及理由。\n'
        ),
    }

    return instructions[task_size]


def get_fix_loop_instructions(max_retries: int = 3) -> str:
    """生成修复-验证循环指令

    参数:
        max_retries: 最大重试次数

    返回:
        修复循环指令文本
    """
    return (
        f'## 修复-验证循环\n\n'
        f'如验证失败:\n'
        f'1. 定位每个失败的根因\n'
        f'2. 用最小变更修复问题\n'
        f'3. 重新运行验证\n'
        f'4. 最多重试 {max_retries} 次\n'
        f'5. 若 {max_retries} 次后仍失败，输出:\n'
        f'   - 已尝试的方案\n'
        f'   - 失败原因分析\n'
        f'   - 建议的后续步骤\n'
    )


def has_structured_verification_evidence(summary: str | None) -> bool:
    """启发式检查任务完成摘要中是否包含结构化验证证据

    用于运行时完成门控（尽力检测，向后兼容）。

    参数:
        summary: 任务完成摘要文本

    返回:
        是否包含结构化验证证据
    """
    if not isinstance(summary, str):
        return False
    text = summary.strip()
    if not text:
        return False

    # 检查是否有验证段
    import re
    has_section = bool(re.search(r'验证(?:\s*证据)?\s*:', text)) or \
                  bool(re.search(r'##\s*验证', text)) or \
                  bool(re.search(r'verification(?:\s+evidence)?\s*:', text, re.I)) or \
                  bool(re.search(r'##\s*verification', text, re.I))

    if not has_section:
        return False

    # 检查是否有证据信号
    has_signal = bool(re.search(r'\b(pass|passed|fail|failed|通过|失败)\b', text, re.I)) or \
                 bool(re.search(r'`[^`]+`', text)) or \
                 bool(re.search(r'\b(command|test|build|typecheck|lint|命令|测试|构建)\b', text, re.I))

    return has_signal

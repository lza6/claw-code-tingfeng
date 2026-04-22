"""Workflow Verifier — 结构化验证协议

汲取 oh-my-codex-main/src/verification/verifier.ts

提供:
- VerificationResult: 验证结果结构
- VerificationEvidence: 证据结构
- 任务大小判断 (determine_task_size)
- 验证指令生成 (get_verification_instructions)
- 修复循环指令 (get_fix_loop_instructions)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class ConfidenceLevel(Enum):
    """置信度级别"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class VerificationEvidence:
    """单条验证证据"""

    type: Literal["test", "typecheck", "lint", "build", "manual", "runtime"]
    passed: bool
    command: str | None = None
    output: str | None = None
    details: str | None = None

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "type": self.type,
            "passed": self.passed,
            "command": self.command,
            "output": self.output,
            "details": self.details,
        }


@dataclass
class VerificationResult:
    """完整的验证结果"""

    passed: bool
    evidence: list[VerificationEvidence] = field(default_factory=list)
    summary: str = ""
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM

    @property
    def evidence_dicts(self) -> list[dict]:
        """证据列表（字典格式）"""
        return [e.to_dict() for e in self.evidence]

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "passed": self.passed,
            "evidence": self.evidence_dicts,
            "summary": self.summary,
            "confidence": self.confidence.value,
        }

    def add_evidence(
        self,
        evidence_type: Literal["test", "typecheck", "lint", "build", "manual", "runtime"],
        passed: bool,
        command: str | None = None,
        output: str | None = None,
        details: str | None = None,
    ) -> None:
        """添加一条验证证据"""
        self.evidence.append(
            VerificationEvidence(
                type=evidence_type,
                passed=passed,
                command=command,
                output=output,
                details=details,
            )
        )

    def is_fully_passed(self) -> bool:
        """所有证据是否都通过"""
        return all(e.passed for e in self.evidence)


def has_structured_verification_evidence(summary: str | None) -> bool:
    """检查摘要中是否包含结构化验证证据

    参考: oh-my-codex-main/src/verification/verifier.ts
    """
    if not summary or not isinstance(summary, str):
        return False

    text = summary.strip()
    if not text:
        return False

    # 检查是否有验证部分
    has_verification_section = (
        "verification" in text.lower() or "## verification" in text.lower()
    )
    if not has_verification_section:
        return False

    # 检查是否有证据信号
    has_evidence_signal = any(
        keyword in text.lower()
        for keyword in ["pass", "fail", "test", "build", "typecheck", "lint", "command"]
    )

    return has_evidence_signal


def determine_task_size(
    file_count: int,
    line_changes: int | None = None,
) -> Literal["small", "standard", "large"]:
    """根据文件数和代码变更行数判断任务大小

    参考: oh-my-codex-main/src/verification/verifier.ts::determineTaskSize

    标准:
    - small: ≤3个文件, <100行变更
    - standard: ≤15个文件, <500行变更
    - large: 其他情况
    """
    if file_count <= 3 and (line_changes is None or line_changes < 100):
        return "small"
    if file_count <= 15 and (line_changes is None or line_changes < 500):
        return "standard"
    return "large"


def get_verification_instructions(
    task_size: Literal["small", "standard", "large"],
    task_description: str,
) -> str:
    """获取验证指令模板

    参考: oh-my-codex-main/src/verification/verifier.ts::getVerificationInstructions
    """
    base_instructions = f"""
## Verification Protocol

Verify the following task is complete: {task_description}

### Required Evidence:
"""

    if task_size == "small":
        return base_instructions + """
1. Run type checker on modified files (if TypeScript/typed language)
2. Run tests related to the change
3. Confirm the change works as described

Report: PASS/FAIL with evidence for each check.
"""

    elif task_size == "standard":
        return base_instructions + """
1. Run full type check (tsc --noEmit or equivalent)
2. Run test suite (focus on changed areas)
3. Run linter on modified files
4. Verify the feature/fix works end-to-end
5. Check for regressions in related functionality

Report: PASS/FAIL with command output for each check.
"""

    else:  # large
        return base_instructions + """
1. Run full type check across the project
2. Run complete test suite
3. Run linter across modified files
4. Security review of changes (OWASP top 10)
5. Performance impact assessment
6. API compatibility check (if applicable)
7. End-to-end verification of all affected features
8. Regression testing of adjacent functionality

Report: PASS/FAIL with detailed evidence for each check.
Include confidence level (high/medium/low) with justification.
"""


def get_fix_loop_instructions(max_retries: int = 3) -> str:
    """获取修复循环指令

    参考: oh-my-codex-main/src/verification/verifier.ts::getFixLoopInstructions
    """
    return f"""
## Fix-Verify Loop

If verification fails:
1. Identify the root cause of each failure
2. Fix the issue (prefer minimal changes)
3. Re-run verification
4. Repeat up to {max_retries} times
5. If still failing after {max_retries} attempts, escalate with:
   - What was attempted
   - What failed and why
   - Recommended next steps
"""


def create_verification_result_from_evidence(
    evidence: list[tuple[Literal["test", "typecheck", "lint", "build", "manual", "runtime"], bool, str | None]],
    summary: str = "",
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM,
) -> VerificationResult:
    """从证据列表创建验证结果"""
    result = VerificationResult(passed=True, summary=summary, confidence=confidence)

    for ev_type, passed, command in evidence:
        result.add_evidence(ev_type, passed, command=command)

    result.passed = result.is_fully_passed()
    return result

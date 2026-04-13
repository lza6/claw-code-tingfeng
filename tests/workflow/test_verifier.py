"""验证器测试 - 覆盖 src/workflow/verifier.py"""

import pytest
from src.workflow.verifier import (
    TaskSize,
    EvidenceType,
    Confidence,
    VerificationEvidence,
    VerificationResult,
    determine_task_size,
    get_verification_instructions,
    get_fix_loop_instructions,
)


class TestEnums:
    def test_task_size(self):
        assert TaskSize.SMALL.value == 'small'
        assert TaskSize.STANDARD.value == 'standard'
        assert TaskSize.LARGE.value == 'large'

    def test_evidence_type(self):
        assert EvidenceType.TEST.value == 'test'

    def test_confidence(self):
        assert Confidence.HIGH.value == 'high'


class TestVerificationEvidence:
    def test_create_passed(self):
        evidence = VerificationEvidence(type=EvidenceType.TEST, passed=True)
        assert evidence.passed is True

    def test_create_failed(self):
        evidence = VerificationEvidence(type=EvidenceType.TEST, passed=False)
        assert evidence.passed is False

    def test_as_text_passed(self):
        evidence = VerificationEvidence(type=EvidenceType.TEST, passed=True)
        assert 'PASS' in evidence.as_text()


class TestVerificationResult:
    def test_create_passed(self):
        result = VerificationResult(passed=True, evidence=[])
        assert result.passed is True


class TestFunctions:
    def test_determine_task_size_small(self):
        size = determine_task_size(1, 10)
        assert size == TaskSize.SMALL

    def test_determine_task_size_large(self):
        size = determine_task_size(5, 1000)
        assert size == TaskSize.LARGE

    def test_get_verification_instructions(self):
        instructions = get_verification_instructions(TaskSize.SMALL, "test")
        assert isinstance(instructions, str)

    def test_get_fix_loop_instructions(self):
        instructions = get_fix_loop_instructions(1)
        assert isinstance(instructions, str)
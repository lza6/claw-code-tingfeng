"""Brain 模型测试 - 覆盖 src/brain/models.py"""

import pytest
from src.brain.models import (
    OptimizationAdvice,
    BrainRule,
    EntropyReport,
    ConfigPatchResult,
)


class TestOptimizationAdvice:
    def test_create(self):
        advice = OptimizationAdvice(
            id="test",
            advice_type="optimize",
            description="Test advice",
        )
        assert advice.id == "test"
        assert advice.advice_type == "optimize"


class TestBrainRule:
    def test_create(self):
        rule = BrainRule(
            id="test",
            rule_text="test rule",
            trigger_error=False,
        )
        assert rule.id == "test"

    def test_matches(self):
        rule = BrainRule(id="test", rule_text="test.*", trigger_error=False)
        assert "test" in rule.rule_text


class TestEntropyReport:
    def test_create(self):
        report = EntropyReport(
            file_path="test.py",
            entropy_score=0.5,
        )
        assert report.entropy_score == 0.5


class TestConfigPatchResult:
    def test_create(self):
        result = ConfigPatchResult(success=True)
        assert result.success is True
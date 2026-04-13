"""Tests for self_healing engine"""
import pytest
import asyncio
from pathlib import Path
from src.self_healing.engine import SelfHealingEngine, SelfHealingConfig
from src.self_healing.models import ErrorCategory, HealingStrategyType, VerificationLevel


class TestSelfHealingConfig:
    def test_defaults(self):
        config = SelfHealingConfig()
        assert config.enabled is True
        assert config.max_attempts == 3
        assert config.enable_ai_diagnosis is True
        assert config.enable_learning is True
        assert config.verification_level == VerificationLevel.L3_UNIT_TEST

    def test_custom_config(self):
        config = SelfHealingConfig(
            max_attempts=5,
            enable_ai_diagnosis=False,
            verification_level=VerificationLevel.L1_SYNTAX,
        )
        assert config.max_attempts == 5
        assert config.enable_ai_diagnosis is False
        assert config.verification_level == VerificationLevel.L1_SYNTAX


class TestSelfHealingEngine:
    @pytest.fixture
    def engine(self, tmp_path):
        return SelfHealingEngine(
            config=SelfHealingConfig(enable_ai_diagnosis=False, max_attempts=1),
            workdir=tmp_path,
        )

    def test_init(self, tmp_path):
        engine = SelfHealingEngine(workdir=tmp_path)
        assert engine.classifier is not None
        assert engine.diagnoser is not None
        assert engine.verifier is not None
        assert engine.experience_bank is not None

    def test_stats_initialization(self, tmp_path):
        engine = SelfHealingEngine(workdir=tmp_path)
        assert engine.stats.total_errors_detected == 0
        assert engine.stats.successful_healings == 0
        assert engine.stats.failed_healings == 0

    async def test_heal_returns_result(self, tmp_path):
        """Heal should return a HealingResult even when all attempts fail"""
        engine = SelfHealingEngine(
            config=SelfHealingConfig(
                enable_ai_diagnosis=False,
                max_attempts=1,
            ),
            workdir=tmp_path,
        )
        result = await engine.heal("unknown error message xyz", context={"code": "x = 1"})
        # Result depends on classifier matching - check it returns a HealingResult
        assert result is not None
        assert hasattr(result, 'success')

    def test_get_stats_summary(self, tmp_path):
        engine = SelfHealingEngine(workdir=tmp_path)
        summary = engine.get_stats_summary()
        assert "自愈统计" in summary
        assert "错误检测" in summary
        assert "修复尝试" in summary

    def test_update_stats(self, tmp_path):
        engine = SelfHealingEngine(workdir=tmp_path)
        engine.stats.successful_healings = 1
        engine._update_stats(attempts=1, elapsed=1.5, category=ErrorCategory.SYNTAX)
        assert engine.stats.avg_attempts == 1
        assert engine.stats.avg_elapsed_seconds == 1.5
        assert "syntax" in engine.stats.error_categories

    async def test_heal_increments_error_count(self, tmp_path):
        engine = SelfHealingEngine(workdir=tmp_path)
        before = engine.stats.total_errors_detected
        await engine.heal("test error")
        assert engine.stats.total_errors_detected == before + 1

    async def test_heal_with_syntax_error(self, tmp_path):
        """Test with a syntax error that should match a known pattern"""
        engine = SelfHealingEngine(
            config=SelfHealingConfig(max_attempts=1),
            workdir=tmp_path,
        )
        result = await engine.heal("invalid syntax at line 5", context={"code": "def foo("})
        assert result is not None

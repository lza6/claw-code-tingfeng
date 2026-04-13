"""Regression tests for SelfHealingEngine"""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from src.self_healing.engine import SelfHealingEngine, SelfHealingConfig
from src.self_healing.models import ErrorCategory, HealingStrategyType, VerificationLevel, HealingResult

class TestSelfHealingRegression:
    @pytest.fixture
    def mock_llm_engine(self):
        with patch("src.agent.factory.create_agent_engine") as mock_factory:
            mock_engine = MagicMock()
            mock_session = MagicMock()
            mock_session.final_result = "def fixed_function():\n    return True"
            mock_engine.run = AsyncMock(return_value=mock_session)
            mock_factory.return_value = mock_engine
            yield mock_engine

    @pytest.fixture
    def engine(self, tmp_path):
        config = SelfHealingConfig(
            max_attempts=2,
            enable_ai_diagnosis=True,
            verification_level=VerificationLevel.L1_SYNTAX
        )
        return SelfHealingEngine(config=config, workdir=tmp_path)

    @pytest.mark.asyncio
    async def test_heal_syntax_error_workflow(self, engine, mock_llm_engine):
        """Regression: Verify that syntax errors trigger the CODE_PATCH strategy and LLM repair."""
        error_msg = "SyntaxError: invalid syntax (line 1)"
        context = {"code": "def faulty_function("}

        result = await engine.heal(error_msg, context, use_experience=False)

        assert result.success is True
        assert result.error_category == ErrorCategory.SYNTAX
        assert result.strategy_used == HealingStrategyType.CODE_PATCH
        assert "fixed_function" in result.fix_applied
        assert result.verification_passed is True
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_heal_runtime_error_classification(self, engine, mock_llm_engine):
        """Regression: Verify that runtime errors are correctly classified."""
        error_msg = "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
        context = {"code": "x = 1 + 'hello'"}

        result = await engine.heal(error_msg, context, use_experience=False)

        assert result.success is True
        assert result.error_category == ErrorCategory.RUNTIME

    @pytest.mark.asyncio
    async def test_heal_retry_on_verification_failure(self, engine, mock_llm_engine):
        """Regression: Verify that the engine retries if the first fix fails verification."""
        error_msg = "RuntimeError: something went wrong"
        context = {"code": "result = 1/0"}

        # First attempt returns invalid syntax
        first_fix = MagicMock()
        first_fix.final_result = "def invalid_syntax(:" # Syntax error

        # Second attempt returns valid code
        second_fix = MagicMock()
        second_fix.final_result = "def valid_fix():\n    return 1"

        mock_llm_engine.run.side_effect = [first_fix, second_fix]

        result = await engine.heal(error_msg, context, use_experience=False)

        assert result.success is True
        assert result.attempts == 2
        assert "valid_fix" in result.fix_applied
        assert result.verification_passed is True

    @pytest.mark.asyncio
    async def test_heal_max_attempts_exhausted(self, engine, mock_llm_engine):
        """Regression: Verify that heal returns failure after max_attempts are exhausted."""
        error_msg = "RuntimeError: persistent error"
        context = {"code": "raise RuntimeError()"}

        # All attempts return invalid syntax
        bad_fix = MagicMock()
        bad_fix.final_result = "def invalid(:"
        mock_llm_engine.run.return_value = bad_fix

        result = await engine.heal(error_msg, context, use_experience=False)

        assert result.success is False
        assert result.attempts == 2  # max_attempts=2

    @pytest.mark.asyncio
    async def test_skip_and_log_strategy(self, engine, mock_llm_engine):
        """Regression: Verify that unknown errors with AI diagnosis disabled use SKIP_AND_LOG."""
        engine.config.enable_ai_diagnosis = False
        error_msg = "SomeWeirdError: something happened"
        context = {"code": ""}

        result = await engine.heal(error_msg, context, use_experience=False)

        assert result.success is True
        assert result.strategy_used == HealingStrategyType.SKIP_AND_LOG
        assert result.fix_applied == '跳过并记录'

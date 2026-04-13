"""Tests for self_healing classifier"""
import pytest
from src.self_healing.classifier import ErrorClassifier
from src.self_healing.models import ErrorCategory, HealingStrategyType


class TestErrorCategory:
    def test_values(self):
        assert ErrorCategory.SYNTAX.value == "syntax"
        assert ErrorCategory.IMPORT.value == "import"
        assert ErrorCategory.RUNTIME.value == "runtime"
        assert ErrorCategory.LLM.value == "llm"
        assert ErrorCategory.UNKNOWN.value == "unknown"
        assert ErrorCategory.TIMEOUT.value == "timeout"


class TestErrorClassifier:
    @pytest.fixture
    def classifier(self):
        return ErrorClassifier()

    def test_has_builtin_patterns(self, classifier):
        assert len(classifier.patterns) > 0

    def test_classify_syntax(self, classifier):
        cat = classifier.classify("SyntaxError: invalid syntax at line 10")
        assert cat == ErrorCategory.SYNTAX

    def test_classify_indentation(self, classifier):
        cat = classifier.classify("IndentationError: expected an indented block")
        assert cat == ErrorCategory.SYNTAX

    def test_classify_import_error(self, classifier):
        cat = classifier.classify("ModuleNotFoundError: No module named 'numpy'")
        assert cat == ErrorCategory.IMPORT

    def test_classify_file_not_found(self, classifier):
        cat = classifier.classify("FileNotFoundError: No such file or directory")
        assert cat == ErrorCategory.RUNTIME

    def test_classify_permission(self, classifier):
        cat = classifier.classify("PermissionError: Permission denied")
        assert cat == ErrorCategory.RUNTIME

    def test_classify_timeout(self, classifier):
        cat = classifier.classify("asyncio.TimeoutError")
        assert cat == ErrorCategory.TIMEOUT

    def test_classify_unknown(self, classifier):
        cat = classifier.classify("some random xyz error")
        assert cat == ErrorCategory.UNKNOWN

    def test_match_pattern_known_error(self, classifier):
        pattern = classifier.match_pattern("SyntaxError: invalid syntax")
        assert pattern is not None
        assert pattern.category == ErrorCategory.SYNTAX

    def test_match_pattern_no_match(self, classifier):
        pattern = classifier.match_pattern("zqxj_random12345")
        assert pattern is None


class TestErrorPattern:
    def test_create_pattern(self):
        from src.self_healing.models import ErrorPattern
        pattern = ErrorPattern(
            id="test-001",
            category=ErrorCategory.SYNTAX,
            signature="test regex",
            description="Test pattern",
            strategy=HealingStrategyType.CODE_PATCH,
            fix_prompt="Fix this: {code}",
        )
        assert pattern.id == "test-001"
        assert pattern.success_count == 0
        assert pattern.failure_count == 0

    def test_success_rate_empty(self):
        from src.self_healing.models import ErrorPattern
        pattern = ErrorPattern(
            id="t", category=ErrorCategory.SYNTAX, signature="x",
            description="t", strategy=HealingStrategyType.CODE_PATCH,
        )
        total = pattern.success_count + pattern.failure_count
        rate = pattern.success_count / total if total > 0 else 0.0
        assert rate == 0.0

    def test_success_rate_computed(self):
        from src.self_healing.models import ErrorPattern
        pattern = ErrorPattern(
            id="t", category=ErrorCategory.SYNTAX, signature="x",
            description="t", strategy=HealingStrategyType.CODE_PATCH,
            success_count=3, failure_count=1,
        )
        total = pattern.success_count + pattern.failure_count
        rate = pattern.success_count / total if total > 0 else 0.0
        assert abs(rate - 0.75) < 0.01


class TestHealingResult:
    def test_success_result(self):
        from src.self_healing.models import HealingResult
        result = HealingResult(
            success=True,
            error="",
            error_category=ErrorCategory.SYNTAX,
            root_cause="missing colon",
            strategy_used=HealingStrategyType.CODE_PATCH,
            fix_applied="x: int = 1",
            verification_passed=True,
            attempts=1,
            elapsed_seconds=0.5,
            messages=["Fixed successfully"],
        )
        assert result.success is True
        assert result.verification_passed is True

    def test_failure_result(self):
        from src.self_healing.models import HealingResult
        result = HealingResult(
            success=False,
            error="error",
            error_category=ErrorCategory.RUNTIME,
            root_cause="unknown",
            strategy_used=HealingStrategyType.SKIP_AND_LOG,
            fix_applied="",
            verification_passed=False,
            attempts=3,
            elapsed_seconds=5.0,
            messages=["All attempts failed"],
        )
        assert result.success is False

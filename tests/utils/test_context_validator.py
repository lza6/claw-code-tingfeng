"""
上下文验证工具单元测试

测试 src/utils/context_validator.py 的所有功能
"""

import pytest

from src.utils.context_validator import (
    ContextValidator,
    ValidationResult,
    create_keyword_validator,
    create_regex_validator,
    create_structure_validator,
    validate_match_context,
)


@pytest.fixture
def validator():
    """创建验证器实例"""
    return ContextValidator(context_window=100)


@pytest.fixture
def sample_code():
    """示例代码"""
    return '''
def growthbook_init():
    """Initialize GrowthBook"""
    config = load_config()
    return config

def get_feature_value(key):
    if not growthbook_enabled():
        result = True
    return result

class FeatureManager:
    def __init__(self):
        self.growthBook = GrowthBook()
    
    def evaluate(self, context):
        return self.growthBook.evaluate(context)
'''


class TestValidationResult:
    """测试验证结果数据类"""

    def test_default_values(self):
        """测试默认值"""
        result = ValidationResult(is_valid=True)
        assert result.is_valid is True
        assert result.context == ""
        assert result.matched_keywords == []
        assert result.matched_patterns == []
        assert result.reason == ""

    def test_with_values(self):
        """测试带值初始化"""
        result = ValidationResult(
            is_valid=False,
            context="some context",
            matched_keywords=['keyword1'],
            matched_patterns=['pattern1'],
            reason="Test reason",
        )
        assert result.is_valid is False
        assert result.context == "some context"
        assert result.matched_keywords == ['keyword1']
        assert result.reason == "Test reason"


class TestContextValidator:
    """测试上下文验证器"""

    def test_get_context_basic(self, validator, sample_code):
        """测试基础上下文获取"""
        match_str = "get_feature_value"
        context = validator.get_context(sample_code, match_str)
        assert match_str in context
        assert len(context) > 0

    def test_get_context_not_found(self, validator, sample_code):
        """测试匹配字符串不存在时返回空"""
        context = validator.get_context(sample_code, "NONEXISTENT")
        assert context == ""

    def test_get_context_at(self, validator, sample_code):
        """测试按位置获取上下文"""
        pos = sample_code.find("growthbook_init")
        context = validator.get_context_at(sample_code, pos)
        assert "growthbook_init" in context

    def test_validate_by_keywords_success(self, validator, sample_code):
        """测试关键字验证成功"""
        match_str = "get_feature_value"
        result = validator.validate_by_keywords(
            sample_code, match_str, ['growthbook', 'GrowthBook']
        )
        assert result.is_valid is True
        assert len(result.matched_keywords) > 0

    def test_validate_by_keywords_fail(self, validator, sample_code):
        """测试关键字验证失败"""
        match_str = "some_function"
        result = validator.validate_by_keywords(
            sample_code, match_str, ['nonexistent_keyword']
        )
        assert result.is_valid is False

    def test_validate_by_keywords_require_all(self, validator, sample_code):
        """测试需要匹配所有关键字"""
        match_str = "growthBook"
        # 上下文中应同时存在 growthBook 和 GrowthBook
        result = validator.validate_by_keywords(
            sample_code, match_str, ['growthBook'], require_all=True
        )
        # 应该匹配成功
        assert result.is_valid is True

    def test_validate_by_regex_success(self, validator, sample_code):
        """测试正则验证成功"""
        match_str = "get_feature_value"
        result = validator.validate_by_regex(
            sample_code, match_str, r'growthbook|GrowthBook'
        )
        assert result.is_valid is True
        assert len(result.matched_patterns) > 0

    def test_validate_by_regex_fail(self, validator, sample_code):
        """测试正则验证失败"""
        match_str = "get_feature_value"
        result = validator.validate_by_regex(
            sample_code, match_str, r'NONEXISTENT_PATTERN'
        )
        assert result.is_valid is False

    def test_validate_by_structure_success(self, validator, sample_code):
        """测试结构验证成功"""
        match_str = "growthbook_enabled"
        result = validator.validate_by_structure(
            sample_code,
            match_str,
            expected_before="def get_feature_value",
            expected_after="return result",
        )
        assert result.is_valid is True

    def test_validate_by_structure_fail(self, validator, sample_code):
        """测试结构验证失败"""
        match_str = "get_feature_value"
        result = validator.validate_by_structure(
            sample_code,
            match_str,
            expected_before="NONEXISTENT_BEFORE",
        )
        assert result.is_valid is False

    def test_find_all_with_context(self, validator, sample_code):
        """测试查找所有匹配并返回上下文"""
        results = validator.find_all_with_context(
            sample_code, r'growthbook|GrowthBook', flags=0
        )
        assert len(results) > 0
        for match_str, context, pos in results:
            assert match_str in sample_code
            assert len(context) > 0
            assert pos >= 0


class TestCreateKeywordValidator:
    """测试关键字验证器创建函数"""

    def test_basic(self, sample_code):
        """测试基础创建"""
        validate = create_keyword_validator(['growthbook', 'GrowthBook'])
        match_str = "get_feature_value"
        assert validate(match_str, sample_code) is True

    def test_require_all(self, sample_code):
        """测试 require_all 参数"""
        validate = create_keyword_validator(['growthbook', 'GrowthBook'], require_all=True)
        match_str = "growthBook"
        assert validate(match_str, sample_code) is True

    def test_not_found(self):
        """测试匹配不存在"""
        validate = create_keyword_validator(['nonexistent'])
        assert validate("anything", "code without keywords") is False


class TestCreateRegexValidator:
    """测试正则验证器创建函数"""

    def test_basic(self, sample_code):
        """测试基础创建"""
        validate = create_regex_validator(r'growthbook|GrowthBook')
        match_str = "get_feature_value"
        assert validate(match_str, sample_code) is True

    def test_not_found(self):
        """测试匹配不存在"""
        validate = create_regex_validator(r'NONEXISTENT')
        assert validate("anything", "code without pattern") is False


class TestCreateStructureValidator:
    """测试结构验证器创建函数"""

    def test_basic(self, sample_code):
        """测试基础创建"""
        validate = create_structure_validator(
            expected_before="def get_feature_value",
            expected_after="return result",
        )
        match_str = "growthbook_enabled"
        assert validate(match_str, sample_code) is True

    def test_fail(self, sample_code):
        """测试失败"""
        validate = create_structure_validator(
            expected_before="NONEXISTENT",
        )
        match_str = "anything"
        assert validate(match_str, sample_code) is False


class TestValidateMatchContext:
    """测试一站式验证函数"""

    def test_keywords_only(self, sample_code):
        """测试仅关键字验证"""
        match_str = "get_feature_value"
        result = validate_match_context(
            code=sample_code,
            match_str=match_str,
            keywords=['growthbook'],
        )
        assert result.is_valid is True

    def test_regex_only(self, sample_code):
        """测试仅正则验证"""
        match_str = "get_feature_value"
        result = validate_match_context(
            code=sample_code,
            match_str=match_str,
            regex_pattern=r'growthbook|GrowthBook',
        )
        assert result.is_valid is True

    def test_structure_only(self, sample_code):
        """测试仅结构验证"""
        match_str = "growthbook_enabled"
        result = validate_match_context(
            code=sample_code,
            match_str=match_str,
            expected_before="def get_feature_value",
            expected_after="return result",
        )
        assert result.is_valid is True

    def test_combined(self, sample_code):
        """测试组合验证"""
        match_str = "growthbook_enabled"
        result = validate_match_context(
            code=sample_code,
            match_str=match_str,
            keywords=['growthbook'],
            regex_pattern=r'def \w+',
            expected_before="def get_feature_value",
        )
        assert result.is_valid is True

    def test_match_not_found(self):
        """测试匹配不存在"""
        result = validate_match_context(
            code="some code",
            match_str="NONEXISTENT",
            keywords=['keyword'],
        )
        assert result.is_valid is False
        assert "not found" in result.reason.lower()

    def test_keywords_not_found(self, sample_code):
        """测试关键字不存在"""
        match_str = "get_feature_value"
        result = validate_match_context(
            code=sample_code,
            match_str=match_str,
            keywords=['NONEXISTENT_KEYWORD'],
        )
        assert result.is_valid is False

    def test_regex_not_found(self, sample_code):
        """测试正则不匹配"""
        match_str = "get_feature_value"
        result = validate_match_context(
            code=sample_code,
            match_str=match_str,
            regex_pattern=r'NONEXISTENT_PATTERN',
        )
        assert result.is_valid is False

    def test_empty_keywords(self, sample_code):
        """测试空关键字列表"""
        match_str = "get_feature_value"
        result = validate_match_context(
            code=sample_code,
            match_str=match_str,
            keywords=[],
        )
        # 空列表应跳过关键字验证，但 match_str 必须存在于 code 中
        assert result.is_valid is True

    def test_no_validators(self, sample_code):
        """测试无任何验证器"""
        match_str = "get_feature_value"
        result = validate_match_context(
            code=sample_code,
            match_str=match_str,
        )
        # 无验证器时应返回成功
        assert result.is_valid is True


class TestContextValidatorEdgeCases:
    """测试边界情况"""

    def test_empty_code(self, validator):
        """测试空代码"""
        assert validator.get_context("", "test") == ""
        result = validator.validate_by_keywords("", "test", ['keyword'])
        assert result.is_valid is False

    def test_very_small_context_window(self):
        """测试极小上下文窗口"""
        validator = ContextValidator(context_window=5)
        code = "prefix MATCH_VALUE suffix"
        context = validator.get_context(code, "MATCH_VALUE")
        # 上下文应包含匹配值
        assert "MATCH_VALUE" in context

    def test_large_context_window(self):
        """测试大上下文窗口"""
        validator = ContextValidator(context_window=10000)
        code = "short code"
        context = validator.get_context(code, "short")
        # 上下文不应超过代码长度
        assert len(context) <= len(code)

    def test_match_at_beginning(self, validator):
        """测试匹配在开头"""
        code = "MATCH_VALUE rest of code"
        context = validator.get_context(code, "MATCH_VALUE")
        assert "MATCH_VALUE" in context

    def test_match_at_end(self, validator):
        """测试匹配在结尾"""
        code = "start of code MATCH_VALUE"
        context = validator.get_context(code, "MATCH_VALUE")
        assert "MATCH_VALUE" in context

    def test_validate_by_structure_not_found(self, validator):
        """测试结构验证匹配不存在"""
        code = "some code here"
        result = validator.validate_by_structure(
            code, "NONEXISTENT", "before", "after"
        )
        assert result.is_valid is False

"""LLM Exception Handler 模块单元测试"""
import pytest
from src.llm.exception_handler import (
    ExceptionInfo,
    LiteLLMExceptions,
    format_error_message,
    get_error_description,
    get_exception_handler,
    get_exception_info,
    is_retryable_error,
    EXCEPTIONS,
)


class TestExceptionInfo:
    """ExceptionInfo 数据类测试"""

    def test_create(self):
        info = ExceptionInfo("TestError", True, "Test description")
        assert info.name == "TestError"
        assert info.retry is True
        assert info.description == "Test description"

    def test_none_values(self):
        info = ExceptionInfo(None, None, None)
        assert info.name is None
        assert info.retry is None
        assert info.description is None


class TestExceptionList:
    """预定义异常列表测试"""

    def test_has_expected_count(self):
        assert len(EXCEPTIONS) > 20

    def test_has_api_connection_error(self):
        names = [ex.name for ex in EXCEPTIONS]
        assert "APIConnectionError" in names

    def test_has_authentication_error(self):
        names = [ex.name for ex in EXCEPTIONS]
        assert "AuthenticationError" in names

    def test_has_rate_limit_error(self):
        names = [ex.name for ex in EXCEPTIONS]
        assert "RateLimitError" in names

    def test_retryable_errors(self):
        retryable = [ex for ex in EXCEPTIONS if ex.retry is True]
        assert len(retryable) > 10

    def test_non_retryable_errors(self):
        non_retryable = [ex for ex in EXCEPTIONS if ex.retry is False]
        assert len(non_retryable) > 0

    def test_authentication_error_not_retryable(self):
        auth_ex = next(ex for ex in EXCEPTIONS if ex.name == "AuthenticationError")
        assert auth_ex.retry is False

    def test_context_window_exceeded_not_retryable(self):
        ctx_ex = next(ex for ex in EXCEPTIONS if ex.name == "ContextWindowExceededError")
        assert ctx_ex.retry is False


class TestLiteLLMExceptionsInit:
    """初始化测试"""

    def test_init(self):
        handler = LiteLLMExceptions()
        assert len(handler._exception_info) > 20

    def test_exception_info_dict(self):
        handler = LiteLLMExceptions()
        assert "APIConnectionError" in handler._exception_info
        assert "RateLimitError" in handler._exception_info


class TestLiteLLMExceptionsGetInfo:
    """获取异常信息测试"""

    def test_known_exception(self):
        handler = LiteLLMExceptions()
        handler._load()  # Load litellm exceptions

        # Create actual exception class to test
        class APIConnectionError(Exception):
            pass

        ex = APIConnectionError("test")
        # After _load, custom exceptions still won't match litellm classes
        # But the handler should handle gracefully (return defaults)
        info = handler.get_ex_info(ex)
        # Custom exception classes don't match litellm mappings
        assert info.name is None

    def test_boto3_error(self):
        handler = LiteLLMExceptions()
        ex = Exception("boto3 connection failed")
        info = handler.get_ex_info(ex)
        assert info.name == "APIConnectionError"
        assert info.retry is False
        assert "boto3" in info.description.lower()

    def test_openrouter_error(self):
        handler = LiteLLMExceptions()
        ex = Exception("openrouter error 'choices' missing")
        info = handler.get_ex_info(ex)
        assert info.retry is True
        assert "OpenRouter" in info.description

    def test_insufficient_credits_error(self):
        handler = LiteLLMExceptions()
        ex = Exception('{"code":402} insufficient credits')
        info = handler.get_ex_info(ex)
        assert info.retry is False
        assert "credits" in info.description.lower()

    def test_unknown_exception(self):
        handler = LiteLLMExceptions()
        ex = Exception("unknown error")
        info = handler.get_ex_info(ex)
        assert info.name is None
        assert info.retry is None
        assert info.description is None


class TestLiteLLMExceptionsIsRetryable:
    """可重试判断测试"""

    def test_api_connection_retryable(self):
        handler = LiteLLMExceptions()
        handler._load()  # Load litellm exceptions

        # Use actual litellm exception with required params
        import litellm
        ex = litellm.APIConnectionError(message="test", llm_provider="openai", model="gpt-4")
        assert handler.is_retryable(ex) is True

    def test_auth_error_not_retryable(self):
        handler = LiteLLMExceptions()
        handler._load()  # Load litellm exceptions

        # Use actual litellm exception with required params
        import litellm
        ex = litellm.AuthenticationError(message="test", llm_provider="openai", model="gpt-4")
        assert handler.is_retryable(ex) is False

    def test_unknown_error_defaults_retryable(self):
        """未知异常默认视为可重试"""
        handler = LiteLLMExceptions()
        ex = Exception("unknown")
        # 由于 retry is None, is_retryable 返回 None (truthy check)
        # 实际逻辑: return info.retry if info.retry is not None else True
        assert handler.is_retryable(ex) is True


class TestLiteLLMExceptionsGetDescription:
    """描述获取测试"""

    def test_known_description(self):
        handler = LiteLLMExceptions()
        handler._load()  # Load litellm exceptions

        # Use actual litellm exception with required params
        import litellm
        ex = litellm.RateLimitError(message="test", llm_provider="openai", model="gpt-4")
        desc = handler.get_description(ex)
        assert desc is not None
        assert "rate limit" in desc.lower()

    def test_no_description(self):
        handler = LiteLLMExceptions()
        handler._load()  # Load litellm exceptions

        # Use actual litellm exception with required params
        import litellm
        ex = litellm.APIError(status_code=500, message="test", llm_provider="openai", model="gpt-4")
        desc = handler.get_description(ex)
        # APIError 没有预定义描述
        assert desc is None


class TestConvenienceFunctions:
    """便捷函数测试"""

    def test_get_exception_handler_singleton(self):
        h1 = get_exception_handler()
        h2 = get_exception_handler()
        assert h1 is h2

    def test_is_retryable_error(self):
        handler = get_exception_handler()
        handler._load()  # Load litellm exceptions

        import litellm
        ex = litellm.APIConnectionError(message="test", llm_provider="openai", model="gpt-4")
        assert is_retryable_error(ex) is True

    def test_get_error_description(self):
        handler = get_exception_handler()
        handler._load()  # Load litellm exceptions

        import litellm
        ex = litellm.RateLimitError(message="test", llm_provider="openai", model="gpt-4")
        desc = get_error_description(ex)
        assert desc is not None

    def test_get_exception_info(self):
        handler = get_exception_handler()
        handler._load()  # Load litellm exceptions

        import litellm
        ex = litellm.APIError(status_code=500, message="test", llm_provider="openai", model="gpt-4")
        info = get_exception_info(ex)
        assert info.name == "APIError"


class TestFormatErrorMessage:
    """错误消息格式化测试"""

    def test_with_description(self):
        import litellm
        handler = get_exception_handler()
        handler._load()

        ex = litellm.RateLimitError(message="too many requests", llm_provider="openai", model="gpt-4")
        msg = format_error_message(ex)
        assert "RateLimitError" in msg
        assert "rate limit" in msg.lower()

    def test_without_description(self):
        import litellm
        ex = litellm.APIError(status_code=500, message="generic error", llm_provider="openai", model="gpt-4")
        msg = format_error_message(ex)
        assert "APIError" in msg

    def test_with_details(self):
        import litellm
        ex = litellm.APIError(status_code=500, message="very detailed error message here", llm_provider="openai", model="gpt-4")
        msg = format_error_message(ex)
        assert "Details:" in msg
        assert "very detailed error message here" in msg

    def test_unknown_exception_uses_class_name(self):
        class CustomError(Exception):
            pass

        msg = format_error_message(CustomError("something broke"))
        assert "CustomError" in msg

"""Retry 模块测试 - 重试策略"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, AsyncMock

import pytest

from src.utils.retry import (
    RetryPolicy,
    default_should_retry,
    get_error_status,
    with_retry,
)


class TestGetErrorStatus:
    """get_error_status 函数测试"""

    def test_get_status_from_attribute(self):
        """测试从属性获取状态码"""
        error = Exception("Error")
        error.status_code = 429
        assert get_error_status(error) == 429

    def test_get_status_from_status(self):
        """测试从 status 属性获取"""
        error = Exception("Error")
        error.status = 500
        assert get_error_status(error) == 500

    def test_get_status_from_code(self):
        """测试从 code 属性获取"""
        error = Exception("Error")
        error.code = 503
        assert get_error_status(error) == 503

    def test_get_status_none(self):
        """测试无法获取状态码"""
        error = Exception("Generic error")
        assert get_error_status(error) is None


class TestDefaultShouldRetry:
    """default_should_retry 函数测试"""

    def test_retry_on_429(self):
        """测试 429 应重试"""
        error = Exception("Rate limit")
        error.status_code = 429
        assert default_should_retry(error) is True

    def test_retry_on_5xx(self):
        """测试 5xx 应重试"""
        for status in [500, 502, 503, 504]:
            error = Exception("Server error")
            error.status_code = status
            assert default_should_retry(error) is True

    def test_no_retry_on_4xx(self):
        """测试 4xx 不重试"""
        for status in [400, 401, 403, 404]:
            error = Exception("Client error")
            error.status_code = status
            assert default_should_retry(error) is False

    def test_retry_on_timeout(self):
        """测试超时时应重试"""
        error = Exception("Connection timeout")
        assert default_should_retry(error) is True

    def test_no_retry_on_generic_error(self):
        """测试一般错误不重试"""
        error = Exception("ValueError: invalid literal")
        assert default_should_retry(error) is False


class TestRetryPolicyCreation:
    """RetryPolicy 创建测试"""

    def test_create_default(self):
        """测试默认创建"""
        policy = RetryPolicy()
        assert policy.max_retries == 3

    def test_create_custom(self):
        """测试自定义创建"""
        policy = RetryPolicy(max_retries=5, base_delay=1.0)
        assert policy.max_retries == 5
        assert policy.base_delay == 1.0


class TestRetryPolicyExecute:
    """RetryPolicy 执行测试"""

    @pytest.mark.asyncio
    async def test_execute_success_first_try(self):
        """测试首次成功"""
        policy = RetryPolicy(max_retries=3)
        mock_func = AsyncMock(return_value="result")
        
        result = await policy.execute(mock_func, "arg1")
        
        assert result == "result"
        mock_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_success_after_retry(self):
        """测试重试后成功"""
        policy = RetryPolicy(max_retries=3)
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Connection timeout")
            return "success"

        result = await policy.execute(flaky_func)

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_execute_failure_max_retries(self):
        """测试达到最大重试次数"""
        policy = RetryPolicy(max_retries=2)
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise Exception("Connection timeout")

        with pytest.raises(Exception):
            await policy.execute(always_fail)

        assert call_count == 3  # max_retries + 1


class TestRetryPolicyDelay:
    """延迟策略测试"""

    def test_calculate_delay(self):
        """测试延迟计算"""
        policy = RetryPolicy(base_delay=0.001, max_delay=0.01)
        # 不应抛出异常
        delay = policy._calculate_delay(0)
        assert delay > 0


class TestWithRetryDecorator:
    """装饰器测试"""

    @pytest.mark.asyncio
    async def test_decorator_success(self):
        """测试装饰器成功"""
        call_count = 0

        @with_retry(max_retries=3)
        async def flaky_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Connection timeout")
            return "success"

        result = await flaky_function()
        assert result == "success"
        assert call_count >= 1


class TestRetryPolicyEdgeCases:
    """边界条件测试"""

    @pytest.mark.asyncio
    async def test_zero_retries(self):
        """测试零重试"""
        policy = RetryPolicy(max_retries=0)
        mock_func = AsyncMock(side_effect=Exception("Fail"))
        
        with pytest.raises(Exception):
            await policy.execute(mock_func)
        
        assert mock_func.call_count == 1

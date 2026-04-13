"""统一异常处理中间件测试"""
from __future__ import annotations

import pytest

from src.core.exceptions import (
    AuthenticationError,
    ClawdError,
    CommandInjectionError,
    ConfigFileNotFoundError,
    ConfigMissingError,
    ConfigurationError,
    ErrorCode,
    IPBannedError,
    LLMContextTooLongError,
    LLMNotConfiguredError,
    LLMProviderError,
    LLMRateLimitError,
    PathTraversalError,
    SecurityError,
    ToolExecutionError,
    ToolInvalidArgsError,
    ToolNotFoundError,
    ToolTimeoutError,
    create_error,
    format_error,
)


class TestClawdError:
    """ClawdError 基础测试"""

    def test_basic_error_creation(self):
        """测试基础异常创建"""
        error = ClawdError(code=ErrorCode.UNKNOWN_ERROR, message='测试错误')
        assert error.code == ErrorCode.UNKNOWN_ERROR
        assert error.message == '测试错误'
        assert error.details == {}
        assert error.recoverable is True

    def test_error_with_details(self):
        """测试带详细信息的异常"""
        error = ClawdError(
            code=ErrorCode.VALIDATION_ERROR,
            message='验证失败',
            details={'field': 'name'},
            recoverable=False,
        )
        assert error.details == {'field': 'name'}
        assert error.recoverable is False

    def test_error_str_representation(self):
        """测试字符串表示"""
        error = ClawdError(code=ErrorCode.UNKNOWN_ERROR, message='未知错误')
        assert str(error) == '[E0001] 未知错误'

        error_with_details = ClawdError(
            code=ErrorCode.VALIDATION_ERROR,
            message='验证失败',
            details={'field': 'name'},
        )
        assert str(error_with_details) == "[E0003] 验证失败 | 详情: {'field': 'name'}"

    def test_error_to_dict(self):
        """测试转换为字典"""
        error = ClawdError(
            code=ErrorCode.UNKNOWN_ERROR,
            message='未知错误',
            details={'key': 'value'},
            recoverable=False,
        )
        result = error.to_dict()
        assert result == {
            'code': 'E0001',
            'message': '未知错误',
            'details': {'key': 'value'},
            'recoverable': False,
        }


class TestLLMErrors:
    """LLM 相关异常测试"""

    def test_llm_provider_error(self):
        """测试 LLM 提供商错误"""
        error = LLMProviderError(message='API 调用失败')
        assert error.code == ErrorCode.LLM_API_CALL_FAILED
        assert error.recoverable is True

    def test_llm_not_configured_error(self):
        """测试 LLM 未配置错误"""
        error = LLMNotConfiguredError()
        assert error.code == ErrorCode.LLM_PROVIDER_NOT_CONFIGURED
        assert error.recoverable is False
        assert 'API key' in error.message

    def test_llm_rate_limit_error(self):
        """测试 LLM 速率限制错误"""
        error = LLMRateLimitError()
        assert error.code == ErrorCode.LLM_RATE_LIMIT_EXCEEDED
        assert error.recoverable is True

    def test_llm_context_too_long_error(self):
        """测试 LLM 上下文过长错误"""
        error = LLMContextTooLongError()
        assert error.code == ErrorCode.LLM_CONTEXT_TOO_LONG
        assert error.recoverable is True


class TestToolErrors:
    """工具执行异常测试"""

    def test_tool_execution_error(self):
        """测试工具执行错误"""
        error = ToolExecutionError(message='执行失败')
        assert error.code == ErrorCode.TOOL_EXECUTION_FAILED
        assert error.recoverable is True

    def test_tool_not_found_error(self):
        """测试工具未找到错误"""
        error = ToolNotFoundError(tool_name='BashTool')
        assert error.code == ErrorCode.TOOL_NOT_FOUND
        assert error.recoverable is False
        assert 'BashTool' in error.message

    def test_tool_timeout_error(self):
        """测试工具超时错误"""
        error = ToolTimeoutError(tool_name='BashTool', timeout=30)
        assert error.code == ErrorCode.TOOL_TIMEOUT
        assert error.details['tool_name'] == 'BashTool'
        assert error.details['timeout'] == 30
        assert error.recoverable is True

    def test_tool_invalid_args_error(self):
        """测试工具参数无效错误"""
        error = ToolInvalidArgsError(tool_name='FileReadTool', reason='路径不存在')
        assert error.code == ErrorCode.TOOL_INVALID_ARGS
        assert error.details['tool_name'] == 'FileReadTool'
        assert '路径不存在' in error.message
        assert error.recoverable is False


class TestSecurityErrors:
    """安全相关异常测试"""

    def test_security_error(self):
        """测试基础安全错误"""
        error = SecurityError(message='安全违规')
        assert error.code == ErrorCode.SECURITY_COMMAND_INJECTION
        assert error.recoverable is False

    def test_command_injection_error(self):
        """测试命令注入错误"""
        error = CommandInjectionError(command='rm -rf /', reason='危险命令')
        assert error.code == ErrorCode.SECURITY_COMMAND_INJECTION
        assert error.details['command'] == 'rm -rf /'
        assert error.details['reason'] == '危险命令'

    def test_path_traversal_error(self):
        """测试路径遍历错误"""
        error = PathTraversalError(path='../../etc/passwd')
        assert error.code == ErrorCode.SECURITY_PATH_TRAVERSAL
        assert error.details['path'] == '../../etc/passwd'

    def test_authentication_error(self):
        """测试认证失败错误"""
        error = AuthenticationError(client_ip='192.168.1.1')
        assert error.code == ErrorCode.SECURITY_AUTH_FAILED
        assert error.details['client_ip'] == '192.168.1.1'

    def test_ip_banned_error(self):
        """测试 IP 封禁错误"""
        error = IPBannedError(client_ip='10.0.0.1', ban_duration=600)
        assert error.code == ErrorCode.SECURITY_IP_BANNED
        assert error.details['client_ip'] == '10.0.0.1'
        assert error.details['ban_duration'] == 600


class TestConfigurationErrors:
    """配置相关异常测试"""

    def test_configuration_error(self):
        """测试基础配置错误"""
        error = ConfigurationError(message='配置无效')
        assert error.code == ErrorCode.CONFIG_INVALID
        assert error.recoverable is False

    def test_config_missing_error(self):
        """测试配置缺失错误"""
        error = ConfigMissingError(key='API_KEY', hint='请在 .env 中设置')
        assert error.code == ErrorCode.CONFIG_MISSING
        assert error.details['key'] == 'API_KEY'
        assert error.details['hint'] == '请在 .env 中设置'

    def test_config_file_not_found_error(self):
        """测试配置文件未找到错误"""
        error = ConfigFileNotFoundError(file_path='/path/to/.env')
        assert error.code == ErrorCode.CONFIG_FILE_NOT_FOUND
        assert error.details['file_path'] == '/path/to/.env'


class TestUtilityFunctions:
    """便捷函数测试"""

    def test_format_error_clawd_error(self):
        """测试格式化 ClawdError"""
        error = ClawdError(
            code=ErrorCode.UNKNOWN_ERROR,
            message='未知错误',
            details={'key': 'value'},
        )
        result = format_error(error)
        assert result['code'] == 'E0001'
        assert result['message'] == '未知错误'
        assert result['details'] == {'key': 'value'}

    def test_format_error_standard_exception(self):
        """测试格式化标准异常"""
        error = ValueError('标准错误')
        result = format_error(error)
        assert result['code'] == 'E0001'
        assert result['message'] == '标准错误'
        assert result['type'] == 'ValueError'

    def test_format_error_with_traceback(self):
        """测试带堆栈的格式化"""
        error = ValueError('测试错误')
        result = format_error(error, include_traceback=True)
        assert 'traceback' in result
        # traceback 可能包含 NoneType，至少检查有内容
        assert result['traceback'] is not None
        assert len(result['traceback']) > 0

    def test_create_error_factory(self):
        """测试错误工厂函数"""
        error = create_error(
            code=ErrorCode.VALIDATION_ERROR,
            message='验证失败',
            details={'field': 'email'},
            recoverable=False,
        )
        assert isinstance(error, ClawdError)
        assert error.code == ErrorCode.VALIDATION_ERROR
        assert error.message == '验证失败'
        assert error.details == {'field': 'email'}
        assert error.recoverable is False


class TestErrorCodeCoverage:
    """错误码覆盖测试"""

    def test_all_error_codes_have_unique_values(self):
        """测试所有错误码值唯一"""
        codes = list(ErrorCode)
        values = [code.value for code in codes]
        assert len(values) == len(set(values)), '存在重复的错误码'

    def test_error_code_categories(self):
        """测试错误码分类"""
        # 通用 E0xxx
        assert ErrorCode.UNKNOWN_ERROR.value.startswith('E0')
        # LLM E1xxx
        assert ErrorCode.LLM_PROVIDER_NOT_CONFIGURED.value.startswith('E1')
        # 工具 E2xxx
        assert ErrorCode.TOOL_NOT_FOUND.value.startswith('E2')
        # 安全 E3xxx
        assert ErrorCode.SECURITY_COMMAND_INJECTION.value.startswith('E3')
        # 配置 E4xxx
        assert ErrorCode.CONFIG_MISSING.value.startswith('E4')
        # Workflow E5xxx
        assert ErrorCode.WORKFLOW_VERSION_MISMATCH.value.startswith('E5')

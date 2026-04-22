"""
错误码稳定性契约测试

确保核心错误码不会被意外修改，这些错误码是公共 API 的一部分。
任何变更都需要明确的版本升级和迁移指南。

来源: oh-my-codex dist/cli/__tests__/catalog-contract.test.ts
"""

import pytest


class TestErrorCodeStability:
    """验证 ErrorCode 枚举值的稳定性"""

    def test_general_error_codes_are_stable(self):
        """通用错误码不应变更"""
        from src.core.exceptions import ErrorCode

        # E0xxx: 通用错误
        assert ErrorCode.UNKNOWN_ERROR.value == 'E0001'
        assert ErrorCode.INTERNAL_ERROR.value == 'E0002'
        assert ErrorCode.VALIDATION_ERROR.value == 'E0003'

    def test_llm_error_codes_are_stable(self):
        """LLM 相关错误码不应变更"""
        from src.core.exceptions import ErrorCode

        # E1xxx: LLM 相关错误
        assert ErrorCode.LLM_API_CALL_FAILED.value == 'E1002'
        assert ErrorCode.LLM_RATE_LIMIT_EXCEEDED.value == 'E1003'
        assert ErrorCode.LLM_INVALID_RESPONSE.value == 'E1004'
        assert ErrorCode.LLM_CONTEXT_TOO_LONG.value == 'E1005'

    def test_tool_error_codes_are_stable(self):
        """工具执行错误码不应变更"""
        from src.core.exceptions import ErrorCode

        # E2xxx: 工具执行错误
        assert ErrorCode.TOOL_NOT_FOUND.value == 'E2001'
        assert ErrorCode.TOOL_EXECUTION_FAILED.value == 'E2002'
        assert ErrorCode.TOOL_TIMEOUT.value == 'E2003'

    def test_security_error_codes_are_stable(self):
        """安全相关错误码不应变更"""
        from src.core.exceptions import ErrorCode

        # E3xxx: 安全相关错误
        assert ErrorCode.SECURITY_COMMAND_INJECTION.value == 'E3001'
        assert ErrorCode.SECURITY_PATH_TRAVERSAL.value == 'E3002'
        assert ErrorCode.SECURITY_AUTH_FAILED.value == 'E3003'

    def test_config_error_codes_are_stable(self):
        """配置相关错误码不应变更"""
        from src.core.exceptions import ErrorCode

        # E4xxx: 配置相关错误
        assert ErrorCode.CONFIG_MISSING.value == 'E4001'
        assert ErrorCode.CONFIG_INVALID.value == 'E4002'
        assert ErrorCode.CONFIG_FILE_NOT_FOUND.value == 'E4003'

    def test_workflow_error_codes_are_stable(self):
        """工作流相关错误码不应变更"""
        from src.core.exceptions import ErrorCode

        # E5xxx: Workflow 工作流引擎
        assert ErrorCode.WORKFLOW_VERSION_MISMATCH.value == 'E5001'
        assert ErrorCode.WORKFLOW_FILE_NOT_FOUND.value == 'E5002'
        assert ErrorCode.TECH_DEBT_FILE_ERROR.value == 'E5003'
        assert ErrorCode.WORKFLOW_EXECUTION_ERROR.value == 'E5004'

    def test_error_code_format_consistency(self):
        """所有错误码应遵循统一的格式规范"""
        from src.core.exceptions import ErrorCode

        for error_code in ErrorCode:
            # 错误码应为 E + 4位数字
            assert error_code.value.startswith('E'), \
                f"Error code {error_code.name} should start with 'E'"
            assert len(error_code.value) == 5, \
                f"Error code {error_code.name} should be 5 characters (E + 4 digits)"
            assert error_code.value[1:].isdigit(), \
                f"Error code {error_code.name} should have numeric suffix"


class TestClawdErrorStructure:
    """验证 ClawdError 异常结构的稳定性"""

    def test_clawd_error_has_required_fields(self):
        """ClawdError 应包含必需的字段"""
        from src.core.exceptions import ClawdError, ErrorCode

        error = ClawdError(
            code=ErrorCode.UNKNOWN_ERROR,
            message="Test error",
            details={"key": "value"},
            recoverable=True
        )

        assert hasattr(error, 'code')
        assert hasattr(error, 'message')
        assert hasattr(error, 'details')
        assert hasattr(error, 'recoverable')

    def test_clawd_error_code_type(self):
        """code 字段应为 ErrorCode 枚举类型"""
        from src.core.exceptions import ClawdError, ErrorCode

        error = ClawdError(code=ErrorCode.UNKNOWN_ERROR, message="Test")
        assert isinstance(error.code, ErrorCode)

    def test_clawd_error_details_default_empty_dict(self):
        """details 字段默认为空字典"""
        from src.core.exceptions import ClawdError, ErrorCode

        error = ClawdError(code=ErrorCode.UNKNOWN_ERROR, message="Test")
        assert error.details == {}

    def test_clawd_error_recoverable_default_true(self):
        """recoverable 字段默认为 True"""
        from src.core.exceptions import ClawdError, ErrorCode

        error = ClawdError(code=ErrorCode.UNKNOWN_ERROR, message="Test")
        assert error.recoverable is True

    def test_clawd_error_string_representation(self):
        """ClawdError 的字符串表示应包含错误码"""
        from src.core.exceptions import ClawdError, ErrorCode

        error = ClawdError(code=ErrorCode.UNKNOWN_ERROR, message="Test error")
        error_str = str(error)

        assert 'E0001' in error_str or 'UNKNOWN_ERROR' in error_str
        assert 'Test error' in error_str

    def test_clawd_error_from_exception(self):
        """from_exception 方法应保持稳定的接口"""
        from src.core.exceptions import ClawdError, ErrorCode

        try:
            raise ValueError("Original error")
        except Exception as e:
            clawd_error = ClawdError.from_exception(e, ErrorCode.UNKNOWN_ERROR)

            assert isinstance(clawd_error, ClawdError)
            assert clawd_error.code == ErrorCode.UNKNOWN_ERROR
            assert "ValueError" in str(clawd_error) or "Original error" in str(clawd_error)

"""统一异常处理中间件

提供结构化的异常体系，避免散落在各处的异常处理逻辑。
所有异常继承自 ClawdError，支持错误码、恢复建议等元数据。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """错误码枚举

    分类:
    - E0xxx: 通用错误
    - E1xxx: LLM 相关错误
    - E2xxx: 工具执行错误
    - E3xxx: 安全相关错误
    - E4xxx: 配置相关错误
    - E5xxx: Workflow（工作流引擎）
    - E6xxx: 认证与授权
    - E7xxx: API Key 相关
    - E8xxx: 限流相关
    """
    # 通用
    UNKNOWN_ERROR = 'E0001'
    INTERNAL_ERROR = 'E0002'
    VALIDATION_ERROR = 'E0003'

    # LLM 相关
    LLM_PROVIDER_NOT_CONFIGURED = 'E1001'
    LLM_API_CALL_FAILED = 'E1002'
    LLM_RATE_LIMIT_EXCEEDED = 'E1003'
    LLM_INVALID_RESPONSE = 'E1004'
    LLM_CONTEXT_TOO_LONG = 'E1005'

    # 工具执行
    TOOL_NOT_FOUND = 'E2001'
    TOOL_EXECUTION_FAILED = 'E2002'
    TOOL_TIMEOUT = 'E2003'
    TOOL_INVALID_ARGS = 'E2004'
    TOOL_REGISTRATION_ERROR = 'E2005'       # 工具注册失败
    TOOL_CAPSULE_ISOLATION_FAILED = 'E2006'  # 工具胶囊隔离失败
    TOOL_OBSERVABILITY_HOOK_ERROR = 'E2007'  # 工具监控钩子错误
    TOOL_PARALLEL_LIMIT_EXCEEDED = 'E2008'   # 并行工具数超限

    # 安全
    SECURITY_COMMAND_INJECTION = 'E3001'
    SECURITY_PATH_TRAVERSAL = 'E3002'
    SECURITY_AUTH_FAILED = 'E3003'
    SECURITY_IP_BANNED = 'E3004'
    SECURITY_DANGEROUS_OPERATION = 'E3005'

    # 配置
    CONFIG_MISSING = 'E4001'
    CONFIG_INVALID = 'E4002'
    CONFIG_FILE_NOT_FOUND = 'E4003'

    # Workflow 工作流引擎
    WORKFLOW_VERSION_MISMATCH = 'E5001'
    WORKFLOW_FILE_NOT_FOUND = 'E5002'
    TECH_DEBT_FILE_ERROR = 'E5003'
    WORKFLOW_EXECUTION_ERROR = 'E5004'

    # 认证与授权
    AUTH_FAILED = 'E6001'
    AUTH_TOKEN_EXPIRED = 'E6002'
    AUTH_TOKEN_INVALID = 'E6003'
    AUTH_PERMISSION_DENIED = 'E6004'
    AUTH_USER_DISABLED = 'E6005'
    AUTH_TENANT_NOT_FOUND = 'E6006'

    # API Key 相关
    API_KEY_INVALID = 'E7001'
    API_KEY_DISABLED = 'E7002'
    API_KEY_RATE_LIMITED = 'E7003'
    API_KEY_NOT_FOUND = 'E7004'
    API_KEY_EXPIRED = 'E7005'

    # 限流相关
    RATE_LIMIT_EXCEEDED = 'E8001'
    TOKEN_LIMIT_EXCEEDED = 'E8002'
    TENANT_LIMIT_EXCEEDED = 'E8003'

    # 状态/运行时 (借鉴 omx-runtime-core)
    STATE_LEASE_NOT_HELD = 'E9001'  # 权限租约未持有
    STATE_LEASE_STALE = 'E9002'     # 权限租约过期
    STATE_LEASE_CONFLICT = 'E9003'  # 权限租约冲突
    STATE_DISPATCH_NOT_FOUND = 'E9004'       # 调度记录未找到
    STATE_INVALID_TRANSITION = 'E9005'       # 无效状态转换
    STATE_MAILBOX_NOT_FOUND = 'E9006'        # 邮箱消息未找到
    STATE_ALREADY_DELIVERED = 'E9007'        # 消息已交付
    STATE_RECOVERY_FAILED = 'E9008'          # 状态恢复失败
    STATE_PERSISTENCE_ERROR = 'E9009'        # 持久化错误
    STATE_INTEGRITY_CHECK_FAILED = 'E9010'   # 完整性检查失败


@dataclass
class ClawdError(Exception):
    """Clawd 基础异常（非 frozen 以支持错误链）

    属性:
        code: 错误码
        message: 人类可读的错误描述
        details: 额外上下文信息（用于调试）
        recoverable: 是否可恢复（True = 可重试，False = 需人工干预）
        __cause__: 原始异常（错误链支持，从 oh-my-codex Rust error handling 汲取）
    """
    code: ErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
        cause: Exception | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        self.recoverable = recoverable

        # 初始化 Exception 基类
        super().__init__(message)

        # 设置异常链（从 oh-my-codex Rust error handling 汲取）
        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        detail_str = ''
        if self.details:
            detail_str = f' | 详情: {self.details}'

        # 如果有原因异常，添加到消息中
        cause_str = ''
        if self.__cause__ is not None:
            cause_str = f' | 原因: {type(self.__cause__).__name__}: {self.__cause__}'

        return f'[{self.code.value}] {self.message}{detail_str}{cause_str}'

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式（用于日志/上报）"""
        result = {
            'code': self.code.value,
            'message': self.message,
            'details': self.details,
            'recoverable': self.recoverable,
        }

        # 如果有原因异常，包含其信息
        if self.__cause__ is not None:
            result['cause'] = {
                'type': type(self.__cause__).__name__,
                'message': str(self.__cause__),
            }

        return result

    @classmethod
    def from_exception(
        cls,
        ex: Exception,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        recoverable: bool | None = None,
    ) -> ClawdError:
        """从原生异常创建 ClawdError（保留错误链）

        从 oh-my-codex Rust error handling 汲取的错误链模式。

        参数:
            ex: 原始异常
            code: 错误码（默认 UNKNOWN_ERROR）
            message: 自定义消息（默认为原始异常消息）
            details: 额外上下文
            recoverable: 是否可恢复（默认为 True）

        返回:
            ClawdError 实例，保留原始异常作为 __cause__
        """
        return cls(
            code=code,
            message=message or str(ex),
            details=details or {},
            recoverable=recoverable if recoverable is not None else True,
            cause=ex,  # 保留错误链
        )


# ==================== LLM 异常 ====================

class LLMProviderError(ClawdError):
    """LLM 提供商错误"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.LLM_API_CALL_FAILED,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(code=code, message=message, details=details or {}, recoverable=recoverable)

    @classmethod
    def from_exception(cls, ex: Exception) -> LLMProviderError:
        """从原生异常自动转换

        结合 src.llm.exception_handler 的逻辑判断可重试性。
        """
        from src.llm.exception_handler import get_exception_info
        info = get_exception_info(ex)

        return cls(
            message=info.description or str(ex),
            code=ErrorCode.LLM_API_CALL_FAILED,
            details={
                "original_exception": type(ex).__name__,
                "raw_message": str(ex)
            },
            recoverable=info.retry if info.retry is not None else True
        )


class LLMNotConfiguredError(LLMProviderError):
    """LLM 未配置错误"""

    def __init__(self, message: str = 'LLM 提供商未配置，请先设置 API key') -> None:
        super().__init__(
            message=message,
            code=ErrorCode.LLM_PROVIDER_NOT_CONFIGURED,
            recoverable=False,
        )


class LLMRateLimitError(LLMProviderError):
    """LLM 速率限制错误"""

    def __init__(self, message: str = 'LLM API 调用频率超限，请稍后重试') -> None:
        super().__init__(message=message, code=ErrorCode.LLM_RATE_LIMIT_EXCEEDED, recoverable=True)


class LLMContextTooLongError(LLMProviderError):
    """LLM 上下文过长错误"""

    def __init__(self, message: str = '消息上下文过长，已自动截断') -> None:
        super().__init__(message=message, code=ErrorCode.LLM_CONTEXT_TOO_LONG, recoverable=True)


# ==================== 工具执行异常 ====================

class ToolExecutionError(ClawdError):
    """工具执行错误"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.TOOL_EXECUTION_FAILED,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(code=code, message=message, details=details or {}, recoverable=recoverable)


class ToolNotFoundError(ToolExecutionError):
    """工具未找到错误"""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            message=f'未找到工具: {tool_name}',
            code=ErrorCode.TOOL_NOT_FOUND,
            details={'tool_name': tool_name},
            recoverable=False,
        )


class ToolTimeoutError(ToolExecutionError):
    """工具执行超时错误"""

    def __init__(self, tool_name: str, timeout: int) -> None:
        super().__init__(
            message=f'工具 {tool_name} 执行超时（{timeout}s）',
            code=ErrorCode.TOOL_TIMEOUT,
            details={'tool_name': tool_name, 'timeout': timeout},
            recoverable=True,
        )


class ToolInvalidArgsError(ToolExecutionError):
    """工具参数无效错误"""

    def __init__(self, tool_name: str, reason: str) -> None:
        super().__init__(
            message=f'工具 {tool_name} 参数无效: {reason}',
            code=ErrorCode.TOOL_INVALID_ARGS,
            details={'tool_name': tool_name, 'reason': reason},
            recoverable=False,
        )


# ==================== 安全异常 ====================

class SecurityError(ClawdError):
    """安全相关错误"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.SECURITY_COMMAND_INJECTION,
        details: dict[str, Any] | None = None,
        recoverable: bool = False,
    ) -> None:
        super().__init__(code=code, message=message, details=details or {}, recoverable=recoverable)


class CommandInjectionError(SecurityError):
    """命令注入错误"""

    def __init__(self, command: str, reason: str) -> None:
        super().__init__(
            message=f'检测到命令注入: {reason}',
            code=ErrorCode.SECURITY_COMMAND_INJECTION,
            details={'command': command, 'reason': reason},
        )


class PathTraversalError(SecurityError):
    """路径遍历错误"""

    def __init__(self, path: str, reason: str = '路径遍历攻击被阻止') -> None:
        super().__init__(
            message=reason,
            code=ErrorCode.SECURITY_PATH_TRAVERSAL,
            details={'path': path},
        )


class AuthenticationError(SecurityError):
    """认证失败错误"""

    def __init__(self, client_ip: str = '') -> None:
        super().__init__(
            message='认证失败',
            code=ErrorCode.SECURITY_AUTH_FAILED,
            details={'client_ip': client_ip} if client_ip else {},
        )


class IPBannedError(SecurityError):
    """IP 被封禁错误"""

    def __init__(self, client_ip: str, ban_duration: int = 300) -> None:
        super().__init__(
            message=f'IP {client_ip} 已被封禁，请 {ban_duration} 秒后重试',
            code=ErrorCode.SECURITY_IP_BANNED,
            details={'client_ip': client_ip, 'ban_duration': ban_duration},
        )


# ==================== 配置异常 ====================

class ConfigurationError(ClawdError):
    """配置相关错误"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.CONFIG_INVALID,
        details: dict[str, Any] | None = None,
        recoverable: bool = False,
    ) -> None:
        super().__init__(code=code, message=message, details=details or {}, recoverable=recoverable)


class ConfigMissingError(ConfigurationError):
    """配置缺失错误"""

    def __init__(self, key: str, hint: str = '') -> None:
        details: dict[str, Any] = {'key': key}
        if hint:
            details['hint'] = hint
        super().__init__(
            message=f'缺少必要配置: {key}',
            code=ErrorCode.CONFIG_MISSING,
            details=details,
        )


class ConfigFileNotFoundError(ConfigurationError):
    """配置文件未找到错误"""

    def __init__(self, file_path: str) -> None:
        super().__init__(
            message=f'配置文件未找到: {file_path}',
            code=ErrorCode.CONFIG_FILE_NOT_FOUND,
            details={'file_path': file_path},
        )


# ==================== 状态/运行时异常（借鉴 omx-runtime-core）====================

class StateError(ClawdError):
    """状态/运行时错误基类"""
    pass


class AuthorityError(StateError):
    """权限/租约错误 - 对应 omx-runtime-core 的 AuthorityError"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.STATE_LEASE_NOT_HELD,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(code=code, message=message, details=details or {}, recoverable=recoverable)


class AlreadyHeldByOtherError(AuthorityError):
    """权限已被其他持有者占用"""

    def __init__(self, current_owner: str) -> None:
        super().__init__(
            message=f"权限已被 {current_owner} 持有",
            code=ErrorCode.STATE_LEASE_CONFLICT,
            details={"current_owner": current_owner},
            recoverable=False,
        )


class OwnerMismatchError(AuthorityError):
    """权限持有者不匹配"""

    def __init__(self, current_owner: str) -> None:
        super().__init__(
            message=f"权限持有者不匹配: 当前持有者为 {current_owner}",
            code=ErrorCode.STATE_LEASE_CONFLICT,
            details={"current_owner": current_owner},
            recoverable=False,
        )


class NotHeldError(AuthorityError):
    """未持有权限"""

    def __init__(self) -> None:
        super().__init__(message="未持有权限租约", code=ErrorCode.STATE_LEASE_NOT_HELD, recoverable=True)


class DispatchError(StateError):
    """调度错误 - 对应 omx-runtime-core 的 DispatchError"""

    def __init__(
        self,
        message: str,
        request_id: str,
        code: ErrorCode = ErrorCode.STATE_DISPATCH_NOT_FOUND,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        details = details or {}
        details["request_id"] = request_id
        super().__init__(message=message, code=code, details=details, recoverable=recoverable)


class DispatchNotFoundError(DispatchError):
    """调度记录未找到"""

    def __init__(self, request_id: str) -> None:
        super().__init__(
            message=f"调度记录未找到: {request_id}",
            code=ErrorCode.STATE_DISPATCH_NOT_FOUND,
            details={"request_id": request_id},
            recoverable=False,
        )


class InvalidTransitionError(DispatchError):
    """无效的状态转换"""

    def __init__(self, request_id: str, from_status: str, to_status: str) -> None:
        super().__init__(
            message=f"无效的状态转换: {request_id}: {from_status} -> {to_status}",
            code=ErrorCode.STATE_INVALID_TRANSITION,
            details={"request_id": request_id, "from": from_status, "to": to_status},
            recoverable=False,
        )


class MailboxError(StateError):
    """邮箱错误 - 对应 omx-runtime-core 的 MailboxError"""

    def __init__(
        self,
        message: str,
        message_id: str,
        code: ErrorCode = ErrorCode.STATE_MAILBOX_NOT_FOUND,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        details = details or {}
        details["message_id"] = message_id
        super().__init__(message=message, code=code, details=details, recoverable=recoverable)


class MailboxNotFoundError(MailboxError):
    """邮箱消息未找到"""

    def __init__(self, message_id: str) -> None:
        super().__init__(
            message=f"邮箱记录未找到: {message_id}",
            code=ErrorCode.STATE_MAILBOX_NOT_FOUND,
            details={"message_id": message_id},
            recoverable=False,
        )


class AlreadyDeliveredError(MailboxError):
    """消息已交付"""

    def __init__(self, message_id: str) -> None:
        super().__init__(
            message=f"邮箱消息已交付: {message_id}",
            code=ErrorCode.STATE_ALREADY_DELIVERED,
            details={"message_id": message_id},
            recoverable=False,
        )


class PersistenceError(StateError):
    """持久化错误"""

    def __init__(self, message: str, path: str | None = None, cause: Exception | None = None) -> None:
        details = {"path": path} if path else {}
        super().__init__(message=message, code=ErrorCode.STATE_PERSISTENCE_ERROR, details=details, recoverable=False)
        if cause:
            self.__cause__ = cause


class RecoveryError(StateError):
    """状态恢复错误"""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message=message, code=ErrorCode.STATE_RECOVERY_FAILED, recoverable=False)
        if cause:
            self.__cause__ = cause


# ==================== 状态/运行时异常（借鉴 omx-runtime-core）====================

class StateError(ClawdError):
    """状态/运行时错误基类"""
    pass


class AuthorityError(StateError):
    """权限/租约错误 - 对应 omx-runtime-core 的 AuthorityError"""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.STATE_LEASE_NOT_HELD,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(code=code, message=message, details=details or {}, recoverable=recoverable)


class AlreadyHeldByOtherError(AuthorityError):
    """权限已被其他持有者占用"""

    def __init__(self, current_owner: str) -> None:
        super().__init__(
            message=f"权限已被 {current_owner} 持有",
            code=ErrorCode.STATE_LEASE_CONFLICT,
            details={"current_owner": current_owner},
            recoverable=False,
        )


class OwnerMismatchError(AuthorityError):
    """权限持有者不匹配"""

    def __init__(self, current_owner: str) -> None:
        super().__init__(
            message=f"权限持有者不匹配: 当前持有者为 {current_owner}",
            code=ErrorCode.STATE_LEASE_CONFLICT,
            details={"current_owner": current_owner},
            recoverable=False,
        )


class NotHeldError(AuthorityError):
    """未持有权限"""

    def __init__(self) -> None:
        super().__init__(message="未持有权限租约", code=ErrorCode.STATE_LEASE_NOT_HELD, recoverable=True)


class DispatchError(StateError):
    """调度错误 - 对应 omx-runtime-core 的 DispatchError"""

    def __init__(
        self,
        message: str,
        request_id: str,
        code: ErrorCode = ErrorCode.STATE_DISPATCH_NOT_FOUND,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        details = details or {}
        details["request_id"] = request_id
        super().__init__(message=message, code=code, details=details, recoverable=recoverable)


class DispatchNotFoundError(DispatchError):
    """调度记录未找到"""

    def __init__(self, request_id: str) -> None:
        super().__init__(
            message=f"调度记录未找到: {request_id}",
            code=ErrorCode.STATE_DISPATCH_NOT_FOUND,
            details={"request_id": request_id},
            recoverable=False,
        )


class InvalidTransitionError(DispatchError):
    """无效的状态转换"""

    def __init__(self, request_id: str, from_status: str, to_status: str) -> None:
        super().__init__(
            message=f"无效的状态转换: {request_id}: {from_status} -> {to_status}",
            code=ErrorCode.STATE_INVALID_TRANSITION,
            details={"request_id": request_id, "from": from_status, "to": to_status},
            recoverable=False,
        )


class MailboxError(StateError):
    """邮箱错误 - 对应 omx-runtime-core 的 MailboxError"""

    def __init__(
        self,
        message: str,
        message_id: str,
        code: ErrorCode = ErrorCode.STATE_MAILBOX_NOT_FOUND,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        details = details or {}
        details["message_id"] = message_id
        super().__init__(message=message, code=code, details=details, recoverable=recoverable)


class MailboxNotFoundError(MailboxError):
    """邮箱消息未找到"""

    def __init__(self, message_id: str) -> None:
        super().__init__(
            message=f"邮箱记录未找到: {message_id}",
            code=ErrorCode.STATE_MAILBOX_NOT_FOUND,
            details={"message_id": message_id},
            recoverable=False,
        )


class AlreadyDeliveredError(MailboxError):
    """消息已交付"""

    def __init__(self, message_id: str) -> None:
        super().__init__(
            message=f"邮箱消息已交付: {message_id}",
            code=ErrorCode.STATE_ALREADY_DELIVERED,
            details={"message_id": message_id},
            recoverable=False,
        )


class PersistenceError(StateError):
    """持久化错误"""

    def __init__(self, message: str, path: str | None = None, cause: Exception | None = None) -> None:
        details = {"path": path} if path else {}
        super().__init__(message=message, code=ErrorCode.STATE_PERSISTENCE_ERROR, details=details, recoverable=False)
        if cause:
            self.__cause__ = cause


class RecoveryError(StateError):
    """状态恢复错误"""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message=message, code=ErrorCode.STATE_RECOVERY_FAILED, recoverable=False)
        if cause:
            self.__cause__ = cause


# ==================== 便捷函数 ====================

def format_error(error: Exception, include_traceback: bool = False) -> dict[str, Any]:
    """格式化异常为字典格式（用于日志/上报）

    参数:
        error: 异常对象
        include_traceback: 是否包含堆栈跟踪

    返回:
        格式化的错误字典
    """
    if isinstance(error, ClawdError):
        return error.to_dict()

    result = {
        'code': ErrorCode.UNKNOWN_ERROR.value,
        'message': str(error),
        'type': type(error).__name__,
        'recoverable': True,
    }

    if include_traceback:
        import traceback
        result['traceback'] = traceback.format_exc()

    return result


def create_error(
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
    recoverable: bool = True,
) -> ClawdError:
    """便捷创建 ClawdError 的工厂函数

    参数:
        code: 错误码
        message: 错误描述
        details: 额外上下文
        recoverable: 是否可恢复

    返回:
        ClawdError 实例
    """
    return ClawdError(
        code=code,
        message=message,
        details=details or {},
        recoverable=recoverable,
    )

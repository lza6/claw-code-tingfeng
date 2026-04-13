"""
中间件系统 - 整合自 Onyx
CORS、日志、错误处理、请求日志
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger


class MiddlewareType(str, Enum):
    """中间件类型"""
    CORS = "cors"
    LOGGING = "logging"
    ERROR_HANDLING = "error_handling"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    METRICS = "metrics"
    TRACING = "tracing"


@dataclass
class RequestContext:
    """请求上下文"""
    request_id: str
    path: str
    method: str
    ip: str
    user_agent: str
    start_time: float
    status_code: int | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CorsConfig:
    """CORS 配置"""
    allow_origins: list[str] = field(default_factory=lambda: ["*"])
    allow_methods: list[str] = field(
        default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )
    allow_headers: list[str] = field(default_factory=lambda: ["*"])
    allow_credentials: bool = False
    max_age: int = 3600


class CorsMiddleware:
    """
    CORS 中间件（整合自 Onyx 的 CORS 模式）
    """

    def __init__(self, config: CorsConfig | None = None):
        self.config = config or CorsConfig()

    def process_request(self, request: Any) -> dict[str, Any]:
        """处理请求 - 添加 CORS 头"""
        # 这个方法需要在响应时调用
        return {}

    def get_headers(self, origin: str | None = None) -> dict[str, str]:
        """获取 CORS 响应头"""
        headers = {}

        # 检查是否允许该 origin
        if "*" in self.config.allow_origins or origin in self.config.allow_origins:
            headers["Access-Control-Allow-Origin"] = origin or "*"

        if self.config.allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"

        headers["Access-Control-Allow-Methods"] = ", ".join(self.config.allow_methods)
        headers["Access-Control-Allow-Headers"] = ", ".join(self.config.allow_headers)
        headers["Access-Control-Max-Age"] = str(self.config.max_age)

        return headers

    def __call__(self, request: Any, call_next: Callable) -> Any:
        """处理请求"""
        # 获取 Origin
        origin = getattr(request.headers, "get", lambda k, d=None: d)("Origin")

        # 预检请求处理
        if getattr(request, "method", "") == "OPTIONS":
            return self._preflight_response(origin)

        # 处理实际请求
        response = call_next(request)

        # 添加 CORS 头
        self.get_headers(origin)
        # 注意: 这里假设 response 有 headers 属性
        # 实际实现需要适配具体的 web 框架

        return response

    def _preflight_response(self, origin: str | None) -> Any:
        """预检响应"""
        # 返回一个带有 CORS 头的预检响应
        # 具体实现需要适配 web 框架
        pass


class LoggingMiddleware:
    """
    请求日志中间件（整合自 Onyx 的日志模式）
    """

    def __init__(
        self,
        log_request: bool = True,
        log_response: bool = True,
        log_headers: bool = False,
    ):
        self.log_request = log_request
        self.log_response = log_response
        self.log_headers = log_headers

    def __call__(self, request: Any, call_next: Callable) -> Any:
        """处理请求"""
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # 记录请求
        if self.log_request:
            self._log_request(request, request_id)

        try:
            response = call_next(request)

            # 记录响应
            if self.log_response:
                duration = time.time() - start_time
                self._log_response(response, request_id, duration)

            return response

        except Exception as e:
            duration = time.time() - start_time
            self._log_error(e, request_id, duration)
            raise

    def _log_request(self, request: Any, request_id: str):
        """记录请求"""
        method = getattr(request, "method", "UNKNOWN")
        path = getattr(request, "url", getattr(request, "path", "UNKNOWN"))
        ip = self._get_client_ip(request)

        logger.info(
            f"[{request_id}] {method} {path} | IP: {ip}"
        )

    def _log_response(self, response: Any, request_id: str, duration: float):
        """记录响应"""
        status = getattr(response, "status_code", 200)
        logger.info(
            f"[{request_id}] Response: {status} | Duration: {duration:.3f}s"
        )

    def _log_error(self, error: Exception, request_id: str, duration: float):
        """记录错误"""
        logger.error(
            f"[{request_id}] Error: {type(error).__name__}: {error} | Duration: {duration:.3f}s"
        )

    def _get_client_ip(self, request: Any) -> str:
        """获取客户端 IP"""
        # 尝试从常见 header 获取
        for header in ["X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP"]:
            ip = getattr(request.headers, "get", lambda k, d=None: d)(header)
            if ip:
                return ip.split(",")[0].strip()
        return "unknown"


class ErrorHandlingMiddleware:
    """
    错误处理中间件（整合自 Onyx 的错误处理模式）
    """

    def __init__(
        self,
        debug: bool = False,
        error_callback: Callable[[Exception, Any], Any] | None = None,
    ):
        self.debug = debug
        self.error_callback = error_callback

    def __call__(self, request: Any, call_next: Callable) -> Any:
        """处理请求"""
        try:
            return call_next(request)

        except Exception as e:
            return self._handle_error(e, request)

    def _handle_error(self, error: Exception, request: Any) -> Any:
        """处理错误"""
        # 调用错误回调
        if self.error_callback:
            return self.error_callback(error, request)

        # 记录日志
        logger.error(f"请求处理错误: {type(error).__name__}: {error}")

        # 返回错误响应
        error_response = {
            "error": type(error).__name__,
            "message": str(error) if self.debug else "Internal server error",
        }

        if self.debug:
            error_response["traceback"] = self._get_traceback(error)

        return error_response

    def _get_traceback(self, error: Exception) -> str:
        """获取错误堆栈"""
        import traceback
        return "".join(traceback.format_exception(type(error), error, error.__traceback__))


class MetricsMiddleware:
    """
    指标中间件（整合自 Onyx 的遥测模式）
    """

    def __init__(self):
        self._request_count = 0
        self._error_count = 0
        self._total_duration = 0.0
        self._status_codes: dict[int, int] = {}

    def __call__(self, request: Any, call_next: Callable) -> Any:
        """处理请求"""
        start_time = time.time()

        try:
            response = call_next(request)
            status = getattr(response, "status_code", 200)

            # 更新统计
            self._request_count += 1
            if status >= 400:
                self._error_count += 1

            self._status_codes[status] = self._status_codes.get(status, 0) + 1

            return response

        except Exception:
            self._error_count += 1
            raise

        finally:
            self._total_duration += time.time() - start_time

    def get_metrics(self) -> dict[str, Any]:
        """获取指标"""
        return {
            "requests": {
                "total": self._request_count,
                "errors": self._error_count,
                "success_rate": (
                    (self._request_count - self._error_count) / self._request_count * 100
                    if self._request_count > 0 else 0
                ),
            },
            "duration": {
                "total": self._total_duration,
                "average": (
                    self._total_duration / self._request_count
                    if self._request_count > 0 else 0
                ),
            },
            "status_codes": self._status_codes,
        }

    def reset(self):
        """重置指标"""
        self._request_count = 0
        self._error_count = 0
        self._total_duration = 0.0
        self._status_codes = {}


class MiddlewareChain:
    """
    中间件链
    """

    def __init__(self):
        self._middlewares: list[tuple[str, Callable]] = []

    def add(self, name: str, middleware: Callable):
        """添加中间件"""
        self._middlewares.append((name, middleware))

    def __call__(self, request: Any, call_next: Callable) -> Any:
        """执行中间件链"""
        # 构建调用链
        def build_chain(index: int) -> Callable:
            if index >= len(self._middlewares):
                return call_next

            _name, middleware = self._middlewares[index]

            def wrapped(request: Any) -> Any:
                return middleware(request, build_chain(index + 1))

            return wrapped

        return build_chain(0)(request)


# ==================== 便捷函数 ====================

def create_cors_middleware(config: CorsConfig | None = None) -> CorsMiddleware:
    """创建 CORS 中间件"""
    return CorsMiddleware(config)


def create_logging_middleware(
    log_request: bool = True,
    log_response: bool = True
) -> LoggingMiddleware:
    """创建日志中间件"""
    return LoggingMiddleware(log_request, log_response)


def create_error_handling_middleware(
    debug: bool = False
) -> ErrorHandlingMiddleware:
    """创建错误处理中间件"""
    return ErrorHandlingMiddleware(debug)


def create_metrics_middleware() -> MetricsMiddleware:
    """创建指标中间件"""
    return MetricsMiddleware()

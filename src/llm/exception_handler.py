"""LLM Exception Handler — LLM 异常处理（从 Aider exceptions.py 移植）

提供 LLM API 异常的分类和处理建议。

用法:
    from src.llm.exception_handler import LiteLLMExceptions, get_exception_info

    handler = LiteLLMExceptions()
    info = handler.get_ex_info(exception)
    if info.retry:
        print("可以重试")
    if info.description:
        print(info.description)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExceptionInfo:
    """异常信息数据类"""
    name: str | None
    retry: bool | None
    description: str | None


# 预定义的异常列表
EXCEPTIONS: list[ExceptionInfo] = [
    ExceptionInfo("APIConnectionError", True, None),
    ExceptionInfo("APIError", True, None),
    ExceptionInfo("APIResponseValidationError", True, None),
    ExceptionInfo(
        "AuthenticationError",
        False,
        "The API provider is not able to authenticate you. Check your API key.",
    ),
    ExceptionInfo("AzureOpenAIError", True, None),
    ExceptionInfo("BadGatewayError", True, "The API provider's servers are down or overloaded."),
    ExceptionInfo("BadRequestError", False, None),
    ExceptionInfo("BudgetExceededError", True, None),
    ExceptionInfo(
        "ContentPolicyViolationError",
        True,
        "The API provider has refused the request due to a safety policy about the content.",
    ),
    ExceptionInfo("ContextWindowExceededError", False, None),
    ExceptionInfo("ImageFetchError", False, "The API provider was unable to fetch one or more images."),
    ExceptionInfo("InternalServerError", True, "The API provider's servers are down or overloaded."),
    ExceptionInfo("InvalidRequestError", True, None),
    ExceptionInfo("JSONSchemaValidationError", True, None),
    ExceptionInfo("NotFoundError", False, None),
    ExceptionInfo(
        "PermissionDeniedError",
        False,
        "Permission was denied. Check your API key and/or credentials.",
    ),
    ExceptionInfo("OpenAIError", True, None),
    ExceptionInfo(
        "RateLimitError",
        True,
        "The API provider has rate limited you. Try again later or check your quotas.",
    ),
    ExceptionInfo("RouterRateLimitError", True, None),
    ExceptionInfo("ServiceUnavailableError", True, "The API provider's servers are down or overloaded."),
    ExceptionInfo("UnprocessableEntityError", True, None),
    ExceptionInfo("UnsupportedParamsError", True, None),
    ExceptionInfo(
        "Timeout",
        True,
        "The API provider timed out without returning a response. They may be down or overloaded.",
    ),
]


class LiteLLMExceptions:
    """LiteLLM 异常处理器

    功能:
    - 异常分类（可重试/不可重试）
    - 异常描述信息
    - 特殊异常处理
    """

    def __init__(self) -> None:
        self._exception_info: dict[str, ExceptionInfo] = {
            ex.name: ex for ex in EXCEPTIONS
        }
        self._exceptions: dict[type, ExceptionInfo] = {}
        self._loaded = False

    def _load(self) -> None:
        """从 litellm 加载异常类"""
        if self._loaded:
            return

        try:
            import litellm

            for var in dir(litellm):
                if var.endswith("Error") and issubclass(getattr(litellm, var), BaseException):
                    ex_cls = getattr(litellm, var)
                    if var in self._exception_info:
                        self._exceptions[ex_cls] = self._exception_info[var]

            self._loaded = True
        except ImportError:
            pass

    def exceptions_tuple(self) -> tuple:
        """获取所有异常类元组（用于 except 语句）"""
        self._load()
        return tuple(self._exceptions.keys())

    def get_ex_info(self, ex: Exception) -> ExceptionInfo:
        """获取异常的详细信息

        参数:
            ex: 异常实例

        Returns:
            ExceptionInfo
        """
        self._load()

        # 特殊异常处理
        ex_str = str(ex).lower()

        # boto3 错误
        if "boto3" in ex_str:
            return ExceptionInfo(
                "APIConnectionError",
                False,
                "Missing dependency. Try: pip install boto3",
            )

        # OpenRouter 特殊错误
        if "openrouter" in ex_str and "'choices'" in ex_str:
            return ExceptionInfo(
                "APIConnectionError",
                True,
                "OpenRouter or the upstream API provider is down, overloaded or rate limiting your requests.",
            )

        # 余额不足错误
        if "insufficient credits" in ex_str and '"code":402' in ex_str:
            return ExceptionInfo(
                "APIError",
                False,
                "Insufficient credits with the API provider. Please add credits.",
            )

        # 尝试匹配异常类
        ex_class = ex.__class__
        return self._exceptions.get(ex_class, ExceptionInfo(None, None, None))

    def is_retryable(self, ex: Exception) -> bool:
        """判断异常是否可重试

        参数:
            ex: 异常实例

        Returns:
            是否可重试
        """
        info = self.get_ex_info(ex)
        return info.retry if info.retry is not None else True

    def get_description(self, ex: Exception) -> str | None:
        """获取异常的描述信息

        参数:
            ex: 异常实例

        Returns:
            描述字符串或 None
        """
        info = self.get_ex_info(ex)
        return info.description


# 全局实例
_exception_handler: LiteLLMExceptions | None = None


def get_exception_handler() -> LiteLLMExceptions:
    """获取全局异常处理器"""
    global _exception_handler
    if _exception_handler is None:
        _exception_handler = LiteLLMExceptions()
    return _exception_handler


def get_exception_info(ex: Exception) -> ExceptionInfo:
    """获取异常信息的便捷函数"""
    return get_exception_handler().get_ex_info(ex)


def is_retryable_error(ex: Exception) -> bool:
    """判断异常是否可重试的便捷函数"""
    return get_exception_handler().is_retryable(ex)


def get_error_description(ex: Exception) -> str | None:
    """获取异常描述的便捷函数"""
    return get_exception_handler().get_description(ex)


# ==================== 便捷函数 ====================

def format_error_message(ex: Exception) -> str:
    """格式化异常为用户友好的错误消息

    参数:
        ex: 异常实例

    Returns:
        格式化的错误消息
    """
    info = get_exception_info(ex)

    msg = f"Error: {info.name or ex.__class__.__name__}"

    if info.description:
        msg += f"\n{info.description}"

    # 添加原始错误信息
    ex_str = str(ex)
    if ex_str and ex_str != info.name:
        msg += f"\n\nDetails: {ex_str[:200]}"

    return msg


# 导出
__all__ = [
    "ExceptionInfo",
    "LiteLLMExceptions",
    "format_error_message",
    "get_error_description",
    "get_exception_handler",
    "get_exception_info",
    "is_retryable_error",
]

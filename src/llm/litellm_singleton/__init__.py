"""LiteLLM Singleton — LiteLLM 单例管理（参考 Onyx litellm_）"""
import logging
from typing import Any, Optional

import litellm
from litellm import acompletion, completion, embedding, image_generation

# 兼容新版 litellm - batch_completion 可能已被移除
try:
    from litellm.main import (
        batch_completion,
        get_model_list,
        get_ollama_response,
        mock_completion,
        validate_environment,
    )
except ImportError:
    # 新版 litellm 中这些函数可能已移除
    batch_completion = None
    get_ollama_response = None
    mock_completion = None
    get_model_list = None
    validate_environment = None

logger = logging.getLogger(__name__)


class LiteLLMSingleton:
    """LiteLLM 单例 - 统一管理所有 LLM 调用"""

    _instance: Optional["LiteLLMSingleton"] = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not LiteLLMSingleton._initialized:
            self._setup_litellm()
            LiteLLMSingleton._initialized = True

    def _setup_litellm(self):
        """配置 LiteLLM"""
        # 基础配置
        litellm.drop_params = True
        litellm.set_verbose = False
        litellm.max_parallel = 100
        litellm.request_timeout = 600

        # 回调
        litellm.callbacks = []

        # 关闭端点的 verbose 日志
        # 兼容性: litellm 在 1.6x 之后移除了 turn_off_verbose_logging()，
        # 新版本提供 turn_off_message_logging()。这里做版本无关的降级调用，
        # 因为 set_verbose=False 已能覆盖主要场景，缺失该方法不应导致启动失败。
        for _fn_name in ("turn_off_verbose_logging", "turn_off_message_logging"):
            _fn = getattr(litellm, _fn_name, None)
            if callable(_fn):
                try:
                    _fn()
                except Exception as exc:
                    logger.debug("litellm.%s() 调用失败: %s", _fn_name, exc)
                break

        # 自定义模型映射（如需要）
        litellm.custom_provider_map = []

        logger.info("LiteLLM initialized")

    def completion(
        self,
        model: str,
        messages: list[dict],
        **kwargs
    ) -> Any:
        """同步补全"""
        return completion(model=model, messages=messages, **kwargs)

    async def acompletion(
        self,
        model: str,
        messages: list[dict],
        **kwargs
    ) -> Any:
        """异步补全"""
        return await acompletion(model=model, messages=messages, **kwargs)

    def embedding(
        self,
        model: str,
        input: str | list[str],
        **kwargs
    ) -> Any:
        """文本嵌入"""
        return embedding(model=model, input=input, **kwargs)

    def image_generation(
        self,
        model: str,
        prompt: str,
        **kwargs
    ) -> Any:
        """图像生成"""
        return image_generation(model=model, prompt=prompt, **kwargs)

    def batch_complete(
        self,
        model: str,
        messages: list[list[dict]],
        **kwargs
    ) -> list[Any]:
        """批量补全"""
        if batch_completion is None:
            raise NotImplementedError("batch_completion not available in this litellm version")
        return batch_completion(model=model, messages=messages, **kwargs)

    def get_model_list(self) -> list[dict]:
        """获取可用模型列表"""
        if get_model_list is None:
            return []
        return get_model_list()

    def validate_environment(self) -> dict:
        """验证环境"""
        if validate_environment is None:
            return {"status": "unavailable"}
        return validate_environment()


# 全局实例
_litellm_singleton: LiteLLMSingleton | None = None


def get_litellm() -> LiteLLMSingleton:
    """获取 LiteLLM 单例"""
    global _litellm_singleton
    if _litellm_singleton is None:
        _litellm_singleton = LiteLLMSingleton()
    return _litellm_singleton


__all__ = [
    "LiteLLMSingleton",
    "acompletion",
    "batch_completion",
    "completion",  # re-export
    "embedding",
    "get_litellm",
    "get_model_list",
    "image_generation",
]

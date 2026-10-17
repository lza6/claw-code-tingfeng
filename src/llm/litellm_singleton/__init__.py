"""LiteLLM Singleton — LiteLLM 单例管理（参考 Onyx litellm_）

## 为什么这个模块必须"零导入期副作用"

`litellm` 是重依赖：本机实测**导入本身约 34 秒**（它会连带拉起
`openai` / `httpx` / `pydantic` 的大量子模块）。

此文件原先在**模块顶层** `import litellm`，而导入链是

    src.main → src.cli_handlers → src.workflow.cli_handler → src.workflow
      → src.workflow.experience_bank → src.core.experience_bank
      → src.memory.enterprise_ltm → src.llm.litellm_singleton

结果是：**运行 `clawd --version` 也要先等 50 秒**。

现在改为完全惰性：
- 模块顶层不 import litellm；
- `LiteLLMSingleton` 在**首次真正调用**时才加载并配置；
- 模块级 `completion` / `acompletion` 等名字通过 PEP 562 的 `__getattr__`
  按需解析，`from src.llm.litellm_singleton import completion` 仍然可用。
"""
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_litellm_module: Any = None
_litellm_initialized = False

#: 通过模块级 `__getattr__` 惰性解析的名字 → litellm 属性名
_LAZY_EXPORTS = {
    "completion": "completion",
    "acompletion": "acompletion",
    "embedding": "embedding",
    "image_generation": "image_generation",
}


def _import_litellm() -> Any:
    """加载（并缓存）litellm 模块。仅在此处发生真实导入。"""
    global _litellm_module
    if _litellm_module is None:
        try:
            import litellm as _ll
        except ImportError as exc:  # pragma: no cover - 环境问题
            raise ImportError("litellm 未安装。请运行: pip install litellm") from exc
        _ll.suppress_debug_info = True
        _litellm_module = _ll
    return _litellm_module


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
        """配置 LiteLLM（首次实例化时才触发真实导入）"""
        global _litellm_initialized
        litellm = _import_litellm()

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

        _litellm_initialized = True
        logger.info("LiteLLM initialized")

    # ---- 调用入口：每次都在实际调用时才解析具体函数 ----------------

    def completion(self, model: str, messages: list[dict], **kwargs) -> Any:
        """同步补全"""
        self._setup_litellm_if_needed()
        return _import_litellm().completion(model=model, messages=messages, **kwargs)

    async def acompletion(self, model: str, messages: list[dict], **kwargs) -> Any:
        """异步补全"""
        self._setup_litellm_if_needed()
        return await _import_litellm().acompletion(model=model, messages=messages, **kwargs)

    def embedding(self, model: str, input: str | list[str], **kwargs) -> Any:
        """文本嵌入"""
        self._setup_litellm_if_needed()
        return _import_litellm().embedding(model=model, input=input, **kwargs)

    def image_generation(self, model: str, prompt: str, **kwargs) -> Any:
        """图像生成"""
        self._setup_litellm_if_needed()
        return _import_litellm().image_generation(model=model, prompt=prompt, **kwargs)

    def batch_complete(self, model: str, messages: list[list[dict]], **kwargs) -> list[Any]:
        """批量补全"""
        self._setup_litellm_if_needed()
        fn = _litellm_main_attr("batch_completion")
        if fn is None:
            raise NotImplementedError("batch_completion not available in this litellm version")
        return fn(model=model, messages=messages, **kwargs)

    def get_model_list(self) -> list[dict]:
        """获取可用模型列表"""
        fn = _litellm_main_attr("get_model_list")
        if fn is None:
            return []
        return fn()

    def validate_environment(self) -> dict:
        """验证环境"""
        fn = _litellm_main_attr("validate_environment")
        if fn is None:
            return {"status": "unavailable"}
        return fn()

    @staticmethod
    def _setup_litellm_if_needed() -> None:
        if not LiteLLMSingleton._initialized:
            LiteLLMSingleton()


def _litellm_main_attr(name: str) -> Any:
    """取 `litellm.main.<name>`，不存在时返回 None（不同版本差异）。"""
    try:
        from litellm import main as _main
    except ImportError:
        return None
    return getattr(_main, name, None)


def get_litellm() -> LiteLLMSingleton:
    """获取 LiteLLM 单例"""
    global _litellm_singleton
    if _litellm_singleton is None:
        _litellm_singleton = LiteLLMSingleton()
    return _litellm_singleton


_litellm_singleton: LiteLLMSingleton | None = None


def __getattr__(name: str) -> Any:
    """PEP 562：模块级惰性属性。

    让 `from src.llm.litellm_singleton import completion` 这类历史写法
    仍然可用，同时不在导入期拉起 litellm。
    """
    if name in _LAZY_EXPORTS:
        return getattr(_import_litellm(), _LAZY_EXPORTS[name])
    if name == "batch_completion":
        return _litellm_main_attr("batch_completion")
    if name in ("get_model_list", "validate_environment", "get_ollama_response",
                "mock_completion"):
        return _litellm_main_attr(name)
    if name == "litellm":
        return _import_litellm()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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

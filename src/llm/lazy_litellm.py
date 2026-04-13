"""Lazy LiteLLM Loading — 从 Aider llm.py 移植

延迟导入 litellm 模块，将 ~1.5s 的启动时间推迟到首次使用。

用法:
    from src.llm.lazy_litellm import litellm

    # litellm 模块在首次访问时才真正导入
    response = litellm.completion(...)
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LazyLiteLLM:
    """LiteLLM 延迟加载包装器

    借鉴 Aider 的设计，将 litellm 的导入延迟到首次使用。
    这可以显著减少启动时间（约 1.5 秒）。

    属性:
        _lazy_module: 实际的 litellm 模块（首次访问时加载）
    """

    def __init__(self) -> None:
        self._lazy_module: Any = None

    def _load_litellm(self) -> Any:
        """加载 litellm 模块"""
        if self._lazy_module is None:
            logger.debug('首次使用 litellm，正在加载...')
            try:
                self._lazy_module = importlib.import_module('litellm')
                # 禁用 litellm 的调试信息
                self._lazy_module.suppress_debug_info = True
                logger.debug('litellm 已加载')
            except ImportError:
                raise ImportError(
                    'litellm 未安装。请运行: pip install litellm'
                ) from None
        return self._lazy_module

    def __getattr__(self, name: str) -> Any:
        """属性访问时触发加载"""
        module = self._load_litellm()
        return getattr(module, name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """调用时触发加载"""
        module = self._load_litellm()
        return module(*args, **kwargs)


# 全局延迟加载实例
litellm = LazyLiteLLM()


def get_litellm() -> Any:
    """获取 litellm 模块（延迟加载）

    Returns:
        litellm 模块对象
    """
    return litellm._load_litellm()


def completion_cost(completion_response: Any) -> float:
    """计算 completion 成本（延迟加载）

    Args:
        completion_response: LLM 响应对象

    Returns:
        成本（美元）
    """
    try:
        llm = get_litellm()
        return llm.completion_cost(completion_response=completion_response)
    except Exception:
        # 回退：手动估算
        return _estimate_cost_fallback(completion_response)


def _estimate_cost_fallback(completion_response: Any) -> float:
    """成本估算回退（当 litellm 不可用时）

    使用简单的 token 计算估算成本。
    """
    try:
        usage = getattr(completion_response, 'usage', None)
        if usage is None:
            return 0.0

        prompt_tokens = getattr(usage, 'prompt_tokens', 0) or 0
        completion_tokens = getattr(usage, 'completion_tokens', 0) or 0

        # 简单估算：GPT-4 价格参考
        # 输入: $0.03/1K tokens, 输出: $0.06/1K tokens
        cost = (prompt_tokens * 0.03 + completion_tokens * 0.06) / 1000
        return cost
    except Exception:
        return 0.0


__all__ = ['completion_cost', 'get_litellm', 'litellm']

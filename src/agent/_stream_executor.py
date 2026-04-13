"""Stream Executor — 组合模式替代 AgentStreamMixin

负责 LLM 结构化输出执行。
通过组合方式注入 llm_provider 和 run 方法引用。
"""
from __future__ import annotations

from typing import Any

from ..llm import BaseLLMProvider, LLMResponse


class StreamExecutor:
    """流式执行器 — 组合模式替代 AgentStreamMixin

    将原本通过 Mixin 访问的 self.llm_provider 和 self.run() 方法，
    现在通过构造函数显式注入。
    """

    def __init__(
        self,
        llm_provider: BaseLLMProvider | None,
        run_coroutine: Any,
    ) -> None:
        self._llm_provider = llm_provider
        self._run_coroutine = run_coroutine

    async def run_structured(
        self,
        goal: str,
        output_schema: dict[str, Any],
    ) -> LLMResponse:
        """运行 LLM 结构化输出

        参数:
            goal: 任务目标
            output_schema: 输出 JSON Schema

        返回:
            LLM 结构化响应
        """
        if self._llm_provider is None:
            return LLMResponse(
                content='{"error": "LLM 提供商未配置"}',
                model='none',
                usage={'total_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0},
            )

        # 检查 LLM 提供商是否支持结构化输出
        if hasattr(self._llm_provider, 'chat_structured'):
            return await self._llm_provider.chat_structured(
                messages=[{"role": "user", "content": goal}],
                response_schema=output_schema,
            )

        # 降级：使用普通 chat 方法
        return await self._llm_provider.chat(
            messages=[{"role": "user", "content": goal}]
        )

    def has_structured_support(self) -> bool:
        """检查是否支持结构化输出"""
        return (
            self._llm_provider is not None
            and hasattr(self._llm_provider, 'chat_structured')
        )

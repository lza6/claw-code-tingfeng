"""Stream Executor — 负责 LLM 结构化输出执行"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..llm import LLMResponse

if TYPE_CHECKING:
    from ..llm import BaseLLMProvider

class StreamExecutor:
    """流式执行器 — 负责结构化输出与流式相关操作"""

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
        if self._llm_provider is None:
            return LLMResponse(
                content='{"error": "LLM 提供商未配置"}',
                model='none',
                usage={'total_tokens': 0, 'prompt_tokens': 0, 'completion_tokens': 0},
            )

        if hasattr(self._llm_provider, 'chat_structured'):
            return await self._llm_provider.chat_structured(
                messages=[{"role": "user", "content": goal}],
                response_schema=output_schema,
            )

        return await self._llm_provider.chat(
            messages=[{"role": "user", "content": goal}]
        )

    def has_structured_support(self) -> bool:
        return (
            self._llm_provider is not None
            and hasattr(self._llm_provider, 'chat_structured')
        )

"""代理流式执行 Mixin — 保留 run_structured 方法

v0.27.x 重构: run_stream 已移至 Engine._run_agent_core (统一核心循环)。
此文件仅保留 run_structured，用于需要 LLM 结构化 JSON 输出的场景。
"""
from __future__ import annotations

import json
from typing import Any

from ..core.exceptions import LLMProviderError
from ..llm import LLMMessage
from ..llm.structured_output import JsonSchema, StructuredResponse
from ..utils import warn


class AgentStreamMixin:
    """代理流式执行 Mixin — 仅提供结构化输出支持。

    需要宿主类提供:
        - llm_provider: LLM 提供商实例
        - run: 基础代理执行方法
        - _llm_config: LLM 配置
    """

    async def run_structured(
        self,
        goal: str,
        output_schema: JsonSchema | dict[str, Any],
    ) -> StructuredResponse:
        """运行代理并返回结构化响应

        使用 LLM 的结构化输出能力，返回符合 schema 的 JSON 响应。

        参数:
            goal: 任务目标
            output_schema: 期望的 JSON Schema 输出格式

        返回:
            StructuredResponse 对象
        """
        if self.llm_provider is None:  # type: ignore[attr-defined]
            return StructuredResponse(
                data={}, raw_content='', success=False,
                error='未配置 LLM 提供商',
            )

        # 检查结构化输出支持
        if not hasattr(self.llm_provider, 'chat_structured'):  # type: ignore[attr-defined]
            try:
                session = await self.run(goal)  # type: ignore[attr-defined]
            except Exception as e:
                warn(f'run_structured 回退执行失败: {e}')
                return StructuredResponse(
                    data={}, raw_content='', success=False,
                    error=f'LLM 不支持结构化输出，回退执行失败: {e}',
                )
            try:
                data = json.loads(session.final_result)
                return StructuredResponse(data=data, raw_content=session.final_result, success=True)
            except json.JSONDecodeError:
                return StructuredResponse(
                    data={}, raw_content=session.final_result, success=False,
                    error='LLM 不支持结构化输出，且回复不是有效 JSON',
                )

        user_content = f'任务目标：{goal}\n\n请以 JSON 格式回复，符合指定的 schema。'
        messages = [
            LLMMessage(role='system', content='你是专业的 AI 助手，严格按 JSON schema 回复。'),
            LLMMessage(role='user', content=user_content),
        ]

        try:
            return await self.llm_provider.chat_structured(messages, output_schema)  # type: ignore[attr-defined]
        except LLMProviderError as e:
            return StructuredResponse(
                data={}, raw_content='', success=False,
                error=str(e),
            )


__all__ = ['AgentStreamMixin']

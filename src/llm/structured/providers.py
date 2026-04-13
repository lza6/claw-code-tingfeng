"""提供商特定的结构化输出实现"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import StructuredOutputMixin

if TYPE_CHECKING:
    from .. import LLMMessage, LLMResponse


class OpenAICompatibleStructuredMixin(StructuredOutputMixin):
    """OpenAI 兼容的结构化输出 Mixin"""

    async def _chat_with_format(
        self,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> LLMResponse:
        from .. import LLMResponse as Resp
        client = getattr(self, '_get_client', None)
        if client is None:
            raise RuntimeError('子类未实现 _get_client 方法')

        config = getattr(self, 'config', None)
        if config is None:
            raise RuntimeError('子类未设置 config 属性')

        response = await client().chat.completions.create(
            model=config.model or getattr(self, 'DEFAULT_MODEL', ''),
            messages=[{'role': m.role, 'content': m.content} for m in messages],
            max_tokens=config.max_tokens,
            temperature=0.1,
            response_format={'type': 'json_object'},
            **kwargs,
        )

        choice = response.choices[0]
        return Resp(
            content=choice.message.content or '',
            model=response.model,
            usage={
                'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                'completion_tokens': response.usage.completion_tokens if response.usage else 0,
                'total_tokens': response.usage.total_tokens if response.usage else 0,
            },
            finish_reason=choice.finish_reason or 'stop',
        )


class AnthropicStructuredMixin(StructuredOutputMixin):
    """Anthropic 结构化输出 Mixin"""

    async def _chat_with_format(
        self,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> LLMResponse:
        from .. import LLMResponse as Resp
        client = getattr(self, '_get_client', None)
        if client is None:
            raise RuntimeError('子类未实现 _get_client 方法')

        config = getattr(self, 'config', None)
        if config is None:
            raise RuntimeError('子类未设置 config 属性')

        system_msg = next((m.content for m in messages if m.role == 'system'), '')
        user_msgs = [m for m in messages if m.role != 'system']

        response = await client().messages.create(
            model=config.model or 'claude-3-5-sonnet-20241022',
            system=system_msg,
            messages=[{'role': m.role, 'content': m.content} for m in user_msgs],
            max_tokens=config.max_tokens,
            temperature=0.1,
            **kwargs,
        )

        return Resp(
            content=response.content[0].text if response.content else '',
            model=response.model,
            usage={
                'input_tokens': response.usage.input_tokens if response.usage else 0,
                'output_tokens': response.usage.output_tokens if response.usage else 0,
            },
            finish_reason=response.stop_reason or 'stop',
        )


class GoogleStructuredMixin(StructuredOutputMixin):
    """Google Gemini 结构化输出 Mixin"""

    async def _chat_with_format(
        self,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> LLMResponse:
        from .. import LLMResponse as Resp
        client = getattr(self, '_get_client', None)
        if client is None:
            raise RuntimeError('子类未实现 _get_client 方法')

        config = getattr(self, 'config', None)
        if config is None:
            raise RuntimeError('子类未设置 config 属性')

        response = await client().chat.completions.create(
            model=config.model or 'gemini-2.0-flash',
            messages=[{'role': m.role, 'content': m.content} for m in messages],
            max_tokens=config.max_tokens,
            temperature=0.1,
            response_format={'type': 'json_object'},
            **kwargs,
        )

        choice = response.choices[0]
        return Resp(
            content=choice.message.content or '',
            model=response.model,
            usage={
                'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                'completion_tokens': response.usage.completion_tokens if response.usage else 0,
                'total_tokens': response.usage.total_tokens if response.usage else 0,
            },
            finish_reason=choice.finish_reason or 'stop',
        )

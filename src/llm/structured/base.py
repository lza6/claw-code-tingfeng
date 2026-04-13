"""结构化输出 Mixin 基类"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from .models import JsonSchema, StructuredResponse

if TYPE_CHECKING:
    from .. import LLMMessage, LLMResponse

logger = logging.getLogger('llm.structured.base')


class StructuredOutputMixin:
    """结构化输出 Mixin 基类"""

    DEFAULT_MAX_RETRIES = 2

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        output_schema: JsonSchema | dict[str, Any],
        max_retries: int | None = None,
        validate_schema: bool = True,
        **kwargs: Any,
    ) -> StructuredResponse:
        """发送聊天消息并期望返回结构化 JSON 响应"""
        if isinstance(output_schema, JsonSchema):
            schema_dict = output_schema.to_dict()
            json_schema = output_schema
        else:
            schema_dict = output_schema
            json_schema = JsonSchema.from_dict(output_schema)

        max_retries = max_retries if max_retries is not None else self.DEFAULT_MAX_RETRIES

        constraint_message = self._build_constraint_message(schema_dict)

        enhanced_messages = list(messages)
        if enhanced_messages and enhanced_messages[0].role == 'system':
            enhanced_messages[0] = enhanced_messages[0].__class__(
                role='system',
                content=enhanced_messages[0].content + '\n\n' + constraint_message,
            )
        else:
            from .. import LLMMessage as Msg
            enhanced_messages.insert(0, Msg(role='system', content=constraint_message))

        last_error = ''
        for attempt in range(max_retries + 1):
            try:
                response = await self._chat_with_format(enhanced_messages, schema_dict, **kwargs)
                result = self._parse_json_response(response)
                result.retry_count = attempt

                if not result.success:
                    last_error = result.error
                    logger.warning(f'JSON 解析失败 (尝试 {attempt + 1}/{max_retries + 1}): {result.error}')
                    continue

                if validate_schema:
                    is_valid, validation_error = json_schema.validate(result.data)
                    if not is_valid:
                        result.validation_error = validation_error
                        last_error = validation_error
                        logger.warning(f'Schema 验证失败 (尝试 {attempt + 1}/{max_retries + 1}): {validation_error}')
                        continue
                    result.is_validated = True

                return result

            except Exception as e:
                last_error = str(e)
                logger.warning(f'结构化输出异常 (尝试 {attempt + 1}/{max_retries + 1}): {e}')

        return StructuredResponse(
            data={},
            raw_content='',
            success=False,
            error=f'结构化输出失败，已重试 {max_retries + 1} 次: {last_error}',
        )

    @staticmethod
    def _build_constraint_message(schema_dict: dict[str, Any]) -> str:
        return (
            '你必须以 JSON 格式回复。不要包含任何额外文本、解释或 Markdown 代码块标记。\n'
            '确保回复是有效的 JSON，并符合以下 schema：\n'
            f'{json.dumps(schema_dict, ensure_ascii=False, indent=2)}'
        )

    async def _chat_with_format(
        self,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> LLMResponse:
        raise NotImplementedError('子类必须实现 _chat_with_format 方法')

    def _parse_json_response(self, response: LLMResponse) -> StructuredResponse:
        content = response.content.strip()
        content = self._strip_markdown_code_blocks(content)

        try:
            data = json.loads(content)
            return StructuredResponse(
                data=data,
                raw_content=response.content,
                success=True,
            )
        except json.JSONDecodeError as e:
            logger.debug(f'首次 JSON 解析失败: {e}')
            json_str = self._extract_json(content)
            if json_str:
                try:
                    data = json.loads(json_str)
                    return StructuredResponse(
                        data=data,
                        raw_content=response.content,
                        success=True,
                    )
                except json.JSONDecodeError as e2:
                    logger.debug(f'提取后 JSON 解析失败: {e2}')

            return StructuredResponse(
                data={},
                raw_content=response.content,
                success=False,
                error=f'JSON 解析失败: {e}',
            )

    @staticmethod
    def _strip_markdown_code_blocks(content: str) -> str:
        pattern = r'^```(?:json|JSON)?\s*\n?(.*?)\n?```$'
        match = re.match(pattern, content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content

    @staticmethod
    def _extract_json(text: str) -> str | None:
        json_match = re.search(r'(\{.*\})', text, re.DOTALL)
        if json_match:
            candidate = json_match.group(1)
            if StructuredOutputMixin._is_balanced_json(candidate):
                return candidate

        json_match = re.search(r'(\[.*\])', text, re.DOTALL)
        if json_match:
            candidate = json_match.group(1)
            if StructuredOutputMixin._is_balanced_json(candidate):
                return candidate

        return StructuredOutputMixin._extract_json_manual(text)

    @staticmethod
    def _is_balanced_json(text: str) -> bool:
        try:
            json.loads(text)
            return True
        except json.JSONDecodeError:
            return False

    @staticmethod
    def _extract_json_manual(text: str) -> str | None:
        start = -1
        for i, char in enumerate(text):
            if char in ('{', '['):
                start = i
                break
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            char = text[i]
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char in ('{', '['):
                depth += 1
            elif char in ('}', ']'):
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return None

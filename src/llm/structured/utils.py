"""结构化输出快捷函数"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .models import JsonSchema, StructuredResponse

if TYPE_CHECKING:
    from .. import LLMConfig, LLMMessage


def get_structured_mixin(config: LLMConfig) -> type:
    """根据提供商类型获取对应的结构化输出 Mixin 类"""
    from .. import LLMProviderType
    from .providers import (
        AnthropicStructuredMixin,
        GoogleStructuredMixin,
        OpenAICompatibleStructuredMixin,
    )

    if config.provider == LLMProviderType.ANTHROPIC:
        return AnthropicStructuredMixin
    elif config.provider == LLMProviderType.GOOGLE:
        return GoogleStructuredMixin
    else:
        return OpenAICompatibleStructuredMixin


def create_structured_prompt(
    task_description: str,
    output_schema: JsonSchema | dict[str, Any],
    examples: list[dict[str, Any]] | None = None,
) -> list[LLMMessage]:
    """创建结构化输出的提示消息"""
    from .. import LLMMessage as Msg
    if isinstance(output_schema, JsonSchema):
        schema_dict = output_schema.to_dict()
    else:
        schema_dict = output_schema

    system_content = (
        f'任务: {task_description}\n\n'
        f'请以 JSON 格式回复，符合以下 schema：\n'
        f'{json.dumps(schema_dict, ensure_ascii=False, indent=2)}'
    )

    if examples:
        system_content += '\n\n示例输出：\n'
        for i, example in enumerate(examples, 1):
            system_content += f'示例 {i}:\n{json.dumps(example, ensure_ascii=False, indent=2)}\n\n'

    return [Msg(role='system', content=system_content)]


def validate_structured_response(
    response: StructuredResponse,
    schema: JsonSchema | dict[str, Any],
) -> tuple[bool, str]:
    """验证结构化响应是否符合 schema"""
    if not response.success:
        return False, f'响应解析失败: {response.error}'

    if isinstance(schema, JsonSchema):
        json_schema = schema
    else:
        json_schema = JsonSchema.from_dict(schema)

    return json_schema.validate(response.data)

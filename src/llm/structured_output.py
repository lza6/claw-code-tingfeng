"""结构化输出支持模块 - JSON mode / Function Calling 抽象"""
from __future__ import annotations

from .structured.base import StructuredOutputMixin
from .structured.models import JsonSchema, StructuredResponse
from .structured.providers import (
    AnthropicStructuredMixin,
    GoogleStructuredMixin,
    OpenAICompatibleStructuredMixin,
)
from .structured.schema import common as common_schema
from .structured.schema import models as model_schema
from .structured.utils import (
    create_structured_prompt,
    get_structured_mixin,
    validate_structured_response,
)

__all__ = [
    'AnthropicStructuredMixin',
    'GoogleStructuredMixin',
    'JsonSchema',
    'OpenAICompatibleStructuredMixin',
    'StructuredOutputMixin',
    'StructuredResponse',
    'common_schema',
    'create_structured_prompt',
    'get_structured_mixin',
    'model_schema',
    'validate_structured_response',
]

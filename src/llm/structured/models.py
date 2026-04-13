"""结构化输出模型定义"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class JsonSchema:
    """JSON Schema 定义（简化版）"""
    type: str = 'object'
    properties: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    additional_properties: bool = False
    description: str = ''
    enum: list[Any] = field(default_factory=list)
    items: dict[str, Any] | None = None
    default: Any = None

    def to_openai_format(self) -> dict[str, Any]:
        """转换为 OpenAI function calling schema 格式"""
        schema: dict[str, Any] = {
            'type': self.type,
            'properties': self.properties,
            'required': self.required,
            'additionalProperties': self.additional_properties,
        }
        if self.description:
            schema['description'] = self.description
        if self.enum:
            schema['enum'] = self.enum
        if self.items:
            schema['items'] = self.items
        return schema

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        schema: dict[str, Any] = {
            'type': self.type,
            'properties': self.properties,
            'required': self.required,
            'additionalProperties': self.additional_properties,
        }
        if self.description:
            schema['description'] = self.description
        if self.enum:
            schema['enum'] = self.enum
        if self.items:
            schema['items'] = self.items
        if self.default is not None:
            schema['default'] = self.default
        return schema

    def validate(self, data: dict[str, Any]) -> tuple[bool, str]:
        """验证数据是否符合 schema"""
        if self.type != 'object':
            return True, ''

        for required_field in self.required:
            if required_field not in data:
                return False, f'缺少必填字段: {required_field}'

        for prop_name, prop_schema in self.properties.items():
            if prop_name in data:
                expected_type = prop_schema.get('type')
                if expected_type and not self._check_type(data[prop_name], expected_type):
                    return False, f'字段 {prop_name} 类型不匹配，期望 {expected_type}'

        if not self.additional_properties:
            for key in data:
                if key not in self.properties:
                    return False, f'不允许的额外字段: {key}'

        return True, ''

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        type_map = {
            'string': str,
            'number': (int, float),
            'integer': int,
            'boolean': bool,
            'array': list,
            'object': dict,
            'null': type(None),
        }
        python_type = type_map.get(expected_type)
        if python_type is None:
            return True
        return isinstance(value, python_type)

    @classmethod
    def from_dict(cls, schema_dict: dict[str, Any]) -> JsonSchema:
        return cls(
            type=schema_dict.get('type', 'object'),
            properties=schema_dict.get('properties', {}),
            required=schema_dict.get('required', []),
            additional_properties=schema_dict.get('additionalProperties', False),
            description=schema_dict.get('description', ''),
            enum=schema_dict.get('enum', []),
            items=schema_dict.get('items'),
            default=schema_dict.get('default'),
        )


@dataclass
class StructuredResponse:
    """结构化响应结果"""
    data: dict[str, Any]
    raw_content: str
    success: bool
    error: str = ''
    validation_error: str = ''
    retry_count: int = 0
    is_validated: bool = False

    @property
    def is_valid(self) -> bool:
        return self.success and not self.validation_error

    def get_typed(self, key: str, default: Any = None) -> Any:
        if not self.success:
            return default
        return self.data.get(key, default)

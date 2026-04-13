"""结构化输出模型 Schema 定义"""
from __future__ import annotations

from ..models import JsonSchema


def create_model_info_schema() -> JsonSchema:
    """创建模型信息的 Schema"""
    return JsonSchema(
        description='模型详细信息',
        properties={
            'model_id': {'type': 'string'},
            'provider': {'type': 'string'},
            'context_window': {'type': 'integer'},
            'max_output_tokens': {'type': 'integer'},
            'pricing': {
                'type': 'object',
                'properties': {
                    'input_1m': {'type': 'number'},
                    'output_1m': {'type': 'number'},
                },
            },
            'capabilities': {
                'type': 'array',
                'items': {'type': 'string'},
            },
        },
        required=['model_id', 'provider'],
    )


def create_model_list_schema() -> JsonSchema:
    """创建模型列表的 Schema"""
    return JsonSchema(
        description='支持的模型列表',
        properties={
            'models': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'string'},
                        'alias': {'type': 'array', 'items': {'type': 'string'}},
                        'description': {'type': 'string'},
                    },
                    'required': ['id'],
                },
            },
        },
        required=['models'],
    )

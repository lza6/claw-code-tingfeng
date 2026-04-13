"""结构化输出通用 Schema 定义"""
from __future__ import annotations

from typing import Any

from ..models import JsonSchema


def create_error_schema(description: str = '错误响应') -> JsonSchema:
    """创建错误响应的 Schema"""
    return JsonSchema(
        description=description,
        properties={
            'error': {
                'type': 'string',
                'description': '错误消息内容',
            },
            'error_code': {
                'type': 'string',
                'description': '错误码',
            },
        },
        required=['error'],
    )


def create_list_schema(item_schema: dict[str, Any], description: str = '列表响应') -> JsonSchema:
    """创建列表响应的 Schema"""
    return JsonSchema(
        description=description,
        properties={
            'items': {
                'type': 'array',
                'items': item_schema,
            },
            'total': {
                'type': 'integer',
            },
        },
        required=['items'],
    )


def create_status_schema(description: str = '状态响应') -> JsonSchema:
    """创建状态响应的 Schema"""
    return JsonSchema(
        description=description,
        properties={
            'status': {
                'type': 'string',
                'enum': ['success', 'error', 'pending'],
            },
            'message': {
                'type': 'string',
            },
        },
        required=['status'],
    )

"""序列化工具 - 借鉴 omx-runtime-core 的 serde 设计

提供类型安全的序列化/反序列化工具。
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

logger = __import__("logging").getLogger(__name__)

T = TypeVar("T")


class SerializationError(Exception):
    """序列化错误"""
    pass


def to_json(obj: Any, indent: int = 2) -> str:
    """将对象序列化为 JSON 字符串

    支持 dataclass, Enum, datetime, date, Path, Decimal 等类型。
    """
    return json.dumps(obj, indent=indent, ensure_ascii=False, default=_json_default)


def from_json(json_str: str, cls: type[T]) -> T:
    """从 JSON 字符串反序列化

    Args:
        json_str: JSON 字符串
        cls: 目标类型

    Returns:
        反序列化的对象
    """
    data = json.loads(json_str)
    return from_dict(data, cls)


def to_dict(obj: Any) -> dict[str, Any]:
    """将对象转换为字典

    处理 dataclass, Enum, datetime, date, Path 等复杂类型。
    """
    if is_dataclass(obj):
        result = {}
        for f in fields(obj):
            value = getattr(obj, f.name)
            result[f.name] = to_dict(value)
        return result
    elif isinstance(obj, Enum):
        return obj.value if hasattr(obj, 'value') else obj.name
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, Path):
        return str(obj)
    elif isinstance(obj, (list, tuple)):
        return [to_dict(item) for item in obj]
    elif isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, (set, frozenset)):
        return list(to_dict(item) for item in obj)
    elif isinstance(obj, Decimal):
        return str(obj)
    else:
        return obj


def from_dict(data: Any, cls: type[T]) -> T:
    """从字典反序列化

    Args:
        data: 源字典
        cls: 目标类型

    Returns:
        反序列化的对象

    Raises:
        SerializationError: 反序列化失败
    """
    if data is None:
        return None

    # 处理 dataclass
    if is_dataclass(cls):
        type_hints = get_type_hints(cls) if cls != Any else {}
        init_values = {}

        for f in fields(cls):
            if f.name in data:
                value = data[f.name]
                field_type = type_hints.get(f.name, f.type)

                # 处理 Optional 类型
                origin = get_origin(field_type)
                if origin is type and origin is type(None):
                    # Optional[T]
                    field_type = get_args(field_type)[0] if get_args(field_type) else Any

                if value is not None:
                    init_values[f.name] = _convert_value(value, field_type)

        try:
            return cls(**init_values)
        except Exception as e:
            raise SerializationError(f"无法从字典创建 {cls.__name__}: {e}") from e

    # 处理 Enum
    if isinstance(cls, type) and issubclass(cls, Enum):
        if isinstance(data, str):
            try:
                return cls(data)
            except ValueError:
                # 尝试按名称查找
                try:
                    return cls[data]
                except KeyError:
                    pass
        raise SerializationError(f"无法将 '{data}' 转换为枚举 {cls.__name__}")

    # 处理简单类型
    if cls is Any:
        return data

    if cls is str:
        return str(data)
    elif cls is int:
        return int(data)
    elif cls is float:
        return float(data)
    elif cls is bool:
        return bool(data)
    elif cls is datetime:
        return datetime.fromisoformat(data)
    elif cls is date:
        return date.fromisoformat(data)
    elif cls is Path:
        return Path(data)
    elif cls is Decimal:
        return Decimal(str(data))
    elif cls is list or cls is tuple or cls is dict:
        return data
    elif cls is set:
        return set(data)

    raise SerializationError(f"不支持的类型: {cls}")


def _convert_value(value: Any, target_type: type) -> Any:
    """转换单个值到目标类型"""
    # List[T]
    origin = get_origin(target_type)
    if origin is list:
        item_type = get_args(target_type)[0] if get_args(target_type) else Any
        return [from_dict(item, item_type if is_dataclass(item_type) or (isinstance(item_type, type) and issubclass(item_type, Enum)) else Any) for item in value]

    # Dict[K, V]
    if origin is dict:
        key_type = get_args(target_type)[0] if get_args(target_type) else str
        value_type = get_args(target_type)[1] if get_args(target_type) else Any
        return {str(k): from_dict(v, value_type) for k, v in value.items()}

    # Optional[T]
    if origin is type:
        # Optional is Union[T, None], check for None
        args = get_args(target_type)
        if type(None) in args:
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                target_type = non_none[0]
                # 如果 value 是 None，返回 None
                if value is None:
                    return None

    return from_dict(value, target_type)


def _json_default(obj: Any) -> Any:
    """JSON 序列化默认处理器"""
    if is_dataclass(obj):
        return to_dict(obj)
    elif isinstance(obj, Enum):
        return obj.value if hasattr(obj, 'value') else obj.name
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, Path) or isinstance(obj, Decimal):
        return str(obj)
    elif isinstance(obj, (set, frozenset)):
        return list(obj)
    elif hasattr(obj, '__dict__'):
        return obj.__dict__
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class JSONSerializer:
    """JSON 序列化器 - 类型安全的序列化接口"""

    @staticmethod
    def serialize(obj: Any) -> str:
        """序列化对象为 JSON 字符串"""
        return to_json(obj)

    @staticmethod
    def deserialize(json_str: str, cls: type[T]) -> T:
        """从 JSON 字符串反序列化"""
        return from_json(json_str, cls)

    @staticmethod
    def save_to_file(obj: Any, filepath: Path) -> None:
        """保存到文件"""
        filepath.write_text(to_json(obj), encoding="utf-8")

    @staticmethod
    def load_from_file(filepath: Path, cls: type[T]) -> T:
        """从文件加载"""
        return from_json(filepath.read_text(encoding="utf-8"), cls)


class CompactSerializer:
    """紧凑序列化器 - 用于事件日志等需要高效存储的场景"""

    @staticmethod
    def serialize(obj: Any) -> str:
        """紧凑序列化（无缩进）"""
        return json.dumps(obj, ensure_ascii=False, default=_json_default)

    @staticmethod
    def serialize_events(events: list) -> str:
        """序列化事件列表（紧凑格式）"""
        return "[" + ",".join(to_json(e) for e in events) + "]"


__all__ = [
    "CompactSerializer",
    "JSONSerializer",
    "SerializationError",
    "from_dict",
    "from_json",
    "to_dict",
    "to_json",
]

"""模型数据类定义

包含 ModelSettings 和 ModelInfo 数据类。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ModelSettings:
    """模型设置

    每个模型可以有不同的行为配置。
    """
    name: str
    edit_format: str = 'diff'
    weak_model_name: str | None = None
    use_repo_map: bool = False
    send_undo_reply: bool = False
    lazy: bool = False
    overeager: bool = False
    reminder: str = 'user'
    examples_as_sys_msg: bool = False
    extra_params: dict | None = None
    cache_control: bool = False
    caches_by_default: bool = False
    use_system_prompt: bool = True
    use_temperature: Any = True
    streaming: bool = True
    editor_model_name: str | None = None
    editor_edit_format: str | None = None
    reasoning_tag: str | None = None
    system_prompt_prefix: str | None = None
    accepts_settings: list | None = None


@dataclass
class ModelInfo:
    """模型信息

    包含模型的能力和限制信息。
    """
    name: str
    max_input_tokens: int = 128000
    max_output_tokens: int = 4096
    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0
    cache_read_price_per_million: float = 0.0
    cache_write_price_per_million: float = 0.0
    supports_vision: bool = False
    supports_function_calling: bool = False
    supports_streaming: bool = True
    supports_prompt_cache: bool = False
    edit_format: str = 'diff'
    context_window: int = 128000
    reasoning_tag: str | None = None

    @property
    def total_context(self) -> int:
        """总上下文窗口"""
        return self.max_input_tokens


__all__ = ['ModelInfo', 'ModelSettings']

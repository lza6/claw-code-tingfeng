"""Base Coder — 代码编辑器基类

提供统一的编辑接口和结果类型。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MatchType(Enum):
    """匹配类型"""
    EXACT = "exact"  # 精确匹配
    WHITESPACE_FLEX = "whitespace_flex"  # 空白容错匹配
    DOTDOTDOT = "dotdotdot"  # ... 省略匹配
    FUZZY = "fuzzy"  # 模糊匹配
    NONE = "none"  # 未匹配


@dataclass
class EditResult:
    """编辑结果"""
    success: bool
    content: str | None = None  # 编辑后的内容
    match_type: MatchType = MatchType.NONE
    similarity: float = 0.0  # 相似度 (0.0 - 1.0)
    error_message: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_exact_match(self) -> bool:
        return self.match_type == MatchType.EXACT

    @property
    def is_fuzzy_match(self) -> bool:
        return self.match_type in (MatchType.FUZZY, MatchType.WHITESPACE_FLEX)


class BaseCoder:
    """代码编辑器基类

    所有编辑策略都继承此类，实现 apply() 方法。

    借鉴 Aider 的设计:
    - 多级匹配策略 (精确 -> 空白容错 -> 模糊)
    - ... 省略语法支持
    - 编辑距离相似度计算
    """

    edit_format: str = "base"
    supports_fuzzy: bool = True
    supports_dotdotdot: bool = True

    def apply(
        self,
        content: str,
        search_text: str,
        replace_text: str,
        fuzzy: bool = True,
    ) -> EditResult:
        """应用编辑

        Args:
            content: 原始内容
            search_text: 要搜索的文本 (SEARCH 块)
            replace_text: 替换文本 (REPLACE 块)
            fuzzy: 是否启用模糊匹配 (当精确匹配失败时)

        Returns:
            EditResult 对象
        """
        raise NotImplementedError("Subclasses must implement apply()")

    def parse_response(self, response: str) -> list[tuple[str, str, str]]:
        """解析 LLM 响应中的编辑块

        Args:
            response: LLM 响应文本

        Returns:
            List of (filename, search_text, replace_text)
        """
        raise NotImplementedError("Subclasses must implement parse_response()")

    def validate_edit(self, search_text: str, replace_text: str) -> tuple[bool, str]:
        """验证编辑块的有效性

        Args:
            search_text: SEARCH 文本
            replace_text: REPLACE 文本

        Returns:
            (is_valid, error_message)
        """
        # 基本验证
        if not search_text and not replace_text:
            return False, "Both search and replace text are empty"

        # 注意: 空 search_text 可能是创建新文件的意图
        return True, ""

    def get_error_hint(self, search_text: str, content: str) -> str:
        """生成错误提示，帮助用户理解为什么匹配失败

        借鉴 Aider 的 find_similar_lines() 函数。
        """
        from src.tools_runtime.code_edit.fuzzy_matcher import find_similar_lines

        similar = find_similar_lines(search_text, content)
        if similar:
            return f"Did you mean:\n{similar}"
        return ""

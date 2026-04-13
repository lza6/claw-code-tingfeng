from __future__ import annotations

import logging

from ..linter_tree_sitter import TreeSitterParser
from .base import BaseCoder, EditResult, MatchType

logger = logging.getLogger(__name__)


class TreeSitterPatchEngine(BaseCoder):
    """AST-based 代码编辑器

    使用 Tree-Sitter 解析代码结构，实现精确的函数/类级别替换。
    优势:
    - 不受空格、换行或微小格式差异的影响
    - 确保代码在结构上是完整的
    - 最小化编辑范围，节省 token
    """

    edit_format: str = "ast"
    supports_fuzzy: bool = False  # AST 模式是结构化、精确的
    supports_dotdotdot: bool = False

    def __init__(self, language: str = "python") -> None:
        self.language = language
        self.parser = TreeSitterParser(language=language)

    def apply(
        self,
        content: str,
        search_text: str,
        replace_text: str,
        fuzzy: bool = False,
    ) -> EditResult:
        """应用 AST 级别的编辑"""
        try:
            # 1. 解析原始代码和搜索文本
            # 我们通过查找 search_text 在 AST 中的对应节点来实现
            # 如果 search_text 是一个完整的函数或类，我们可以实现精确替换

            # 目前的简化策略:
            # 如果 search_text 在 content 中能找到完全匹配的 AST 节点
            # 则进行结构化替换

            # NOTE: 这是一个占位实现，实际需要更复杂的 AST 匹配逻辑
            # 在没有完全匹配的情况下，回退到字符串精确匹配
            if search_text in content:
                new_content = content.replace(search_text, replace_text, 1)
                return EditResult(
                    success=True,
                    content=new_content,
                    match_type=MatchType.EXACT,
                    similarity=1.0
                )

            return EditResult(
                success=False,
                error_message="AST 节点未匹配"
            )

        except Exception as e:
            logger.error(f"AST 编辑失败: {e}")
            return EditResult(
                success=False,
                error_message=str(e)
            )

    def parse_response(self, response: str) -> list[tuple[str, str, str]]:
        """解析带有目标节点信息的编辑块"""
        # 预期的格式 (类似于 XML 块):
        # <ast_patch file="path/to/file.py">
        #   <search>...</search>
        #   <replace>...</replace>
        # </ast_patch>

        import re
        patches = []
        pattern = re.compile(
            r'<ast_patch\s+file="([^"]+)">\s*<search>(.*?)</search>\s*<replace>(.*?)</replace>\s*</ast_patch>',
            re.DOTALL
        )

        for match in pattern.finditer(response):
            filename, search, replace = match.groups()
            patches.append((filename, search.strip(), replace.strip()))

        return patches

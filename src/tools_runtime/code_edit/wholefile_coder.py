"""WholeFile Coder — 整个文件替换编辑器

借鉴 Aider 的 WholeFileCoder，实现:
1. 整个文件内容替换
2. 文件创建功能
3. 安全备份机制

适合需要完全控制文件内容的场景。
"""
from __future__ import annotations

from pathlib import Path

from src.tools_runtime.code_edit.base_coder import BaseCoder, EditResult, MatchType


class WholeFileCoder(BaseCoder):
    """整个文件编辑器

    支持 LLM 输出整个文件内容进行替换:

        filename.py
        ```python
        # 完整的文件内容
        def main():
            pass
        ```

    特性:
    - 替换整个文件内容
    - 创建新文件
    - 自动备份原文件
    """

    edit_format = "wholefile"

    def apply(
        self,
        content: str,
        search_text: str,
        replace_text: str,
        fuzzy: bool = False,
    ) -> EditResult:
        """应用整个文件替换

        Args:
            content: 原始文件内容（通常为空表示创建新文件）
            search_text: 搜索文本（忽略，用于兼容）
            replace_text: 替换文本（新文件完整内容）

        Returns:
            EditResult 对象
        """
        if not replace_text.strip():
            return EditResult(
                success=False,
                content=None,
                match_type=MatchType.NONE,
                error_message="Replacement content cannot be empty",
            )

        # 整个文件替换
        return EditResult(
            success=True,
            content=replace_text,
            match_type=MatchType.EXACT,
            similarity=1.0,
            meta={"action": "replace_all"},
        )

    def parse_response(self, response: str) -> list[tuple[str, str, str]]:
        """解析 LLM 响应中的整个文件编辑

        支持格式:
        - 带文件名的 markdown 代码块
        - 纯文件内容（需要文件名提示）

        Returns:
            List of (filename, "", new_content)
        """
        import re

        edits = []

        # 模式 1: 带文件名的代码块
        # ```python filename.py
        # content
        # ```
        pattern1 = re.compile(
            r'```(\w+)\s+([^\s]+)\s*\n(.*?)```',
            re.DOTALL
        )

        for match in pattern1.finditer(response):
            filename = match.group(2)
            file_content = match.group(3).rstrip()
            if file_content:
                edits.append((filename, "", file_content))

        # 模式 2: filename\n```...content...```
        pattern2 = re.compile(
            r'^([^\n`]+)\n```(\w+)?\n(.*?)```',
            re.DOTALL | re.MULTILINE
        )

        for match in pattern2.finditer(response):
            filename = match.group(1).strip()
            file_content = match.group(3).rstrip()
            if file_content:
                edits.append((filename, "", file_content))

        # 模式 3: 简单文件名: 内容
        # file.py: |
        #   content
        pattern3 = re.compile(
            r'^([^\n:]+):\s*\|\s*\n((?:\s{2}.*\n)*)',
            re.MULTILINE
        )

        for match in pattern3.finditer(response):
            filename = match.group(1).strip()
            file_content = match.group(2)
            if file_content.strip():
                edits.append((filename, "", file_content))

        return edits

    def apply_edit(
        self,
        path: Path,
        new_content: str,
        create_backup: bool = True,
    ) -> EditResult:
        """应用文件编辑

        Args:
            path: 文件路径
            new_content: 新文件内容
            create_backup: 是否创建备份

        Returns:
            EditResult 对象
        """
        try:
            # 创建备份
            if create_backup and path.exists():
                backup_path = path.with_suffix(path.suffix + '.bak')
                backup_path.write_text(path.read_text(encoding='utf-8'))

            # 写入新内容
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_content, encoding='utf-8')

            return EditResult(
                success=True,
                content=new_content,
                match_type=MatchType.EXACT,
                similarity=1.0,
                meta={"action": "replace", "path": str(path)},
            )

        except PermissionError:
            return EditResult(
                success=False,
                content=None,
                match_type=MatchType.NONE,
                error_message=f"Permission denied: {path}",
            )
        except Exception as e:
            return EditResult(
                success=False,
                content=None,
                match_type=MatchType.NONE,
                error_message=f"Write error: {e}",
            )

    def get_error_hint(self, search: str, content: str) -> str | None:
        """生成错误提示"""
        # WholeFile 不需要 search 匹配，所以返回 None
        return None


class WholeFileFuncCoder(WholeFileCoder):
    """整个文件编辑器（函数级）

    适合代码需要以函数/类为单位进行修改的场景。
    """

    edit_format = "wholefile_func"

    def parse_response(self, response: str) -> list[tuple[str, str, str]]:
        """解析函数级编辑

        支持格式:
        - @ filename
        - content
        - @@
        """
        edits = []

        import re

        # 模式: @ filename\ncontent\n@@
        pattern = re.compile(
            r'^@\s*([^\n]+)\s*\n(.*?)\n?@@',
            re.DOTALL | re.MULTILINE
        )

        for match in pattern.finditer(response):
            filename = match.group(1).strip()
            file_content = match.group(2).rstrip()
            if file_content:
                edits.append((filename, "", file_content))

        return edits


class SingleWholeFileFuncCoder(WholeFileCoder):
    """单文件整个文件编辑器（函数级）

    一次只处理一个文件。
    """

    edit_format = "single_wholefile_func"

    def apply(
        self,
        content: str,
        search_text: str,
        replace_text: str,
        fuzzy: bool = False,
    ) -> EditResult:
        """应用单文件编辑"""
        # 验证内容不为空
        if not replace_text.strip():
            return EditResult(
                success=False,
                content=None,
                match_type=MatchType.NONE,
                error_message="File content cannot be empty",
            )

        # 整个文件替换
        return EditResult(
            success=True,
            content=replace_text,
            match_type=MatchType.EXACT,
            similarity=1.0,
            meta={"action": "replace_single"},
        )

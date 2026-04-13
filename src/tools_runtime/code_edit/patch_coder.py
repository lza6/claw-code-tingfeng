"""Patch Coder — Unified Diff 格式编辑器

借鉴 Aider 的 PatchCoder，实现:
1. 解析 Unified Diff 格式
2. 多文件 patch 应用
3. Fuzz 匹配支持

适合用于需要更精确控制的场景。
"""
from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from enum import Enum

from src.tools_runtime.code_edit.base_coder import BaseCoder, EditResult, MatchType


class ActionType(str, Enum):
    ADD = "Add"
    DELETE = "Delete"
    UPDATE = "Update"


@dataclass
class Chunk:
    """Patch 中的一个变更块"""
    orig_index: int = -1  # 原始文件的起始行号
    del_lines: list[str] = field(default_factory=list)  # 删除的行
    ins_lines: list[str] = field(default_factory=list)  # 插入的行


@dataclass
class PatchAction:
    """单个文件的 patch 操作"""
    type: ActionType
    path: str
    new_content: str | None = None  # 新建文件内容
    chunks: list[Chunk] = field(default_factory=list)  # 多个变更块
    move_path: str | None = None


@dataclass
class Patch:
    """完整的 patch 对象"""
    actions: dict[str, PatchAction] = field(default_factory=dict)
    fuzz: int = 0  # Fuzz 匹配级别


# Patch 格式标记
PATCH_START = "*** Update File:"
PATCH_DELETE = "*** Delete File:"
PATCH_ADD = "*** Add File:"
PATCH_END = "*** End Patch"
EOF_MARKER = "*** End of File"


class PatchCoder(BaseCoder):
    """Patch 格式代码编辑器

    支持 Unified Diff 风格的多文件修改:

        *** Update File: src/main.py
        ```python
        def old_function():
            pass
        ---
        def new_function():
            return True
        ***
        *** End of File
        *** End Patch
    """

    edit_format = "patch"
    supports_fuzzy = True

    def _norm(self, line: str) -> str:
        """标准化行尾以支持 LF 和 CRLF"""
        return line.rstrip("\r")

    def apply(
        self,
        content: str,
        search_text: str,
        replace_text: str,
        fuzzy: bool = True,
    ) -> EditResult:
        """应用 patch 风格编辑

        将 search/replace 转换为 patch 格式并应用
        """
        if not search_text.strip():
            # 创建新文件
            return EditResult(
                success=True,
                content=replace_text,
                match_type=MatchType.EXACT,
                similarity=1.0,
                meta={"action": "create"},
            )

        # 简单的行级替换
        search_lines = search_text.splitlines()
        replace_lines = replace_text.splitlines()

        content_lines = content.splitlines()
        result_lines = []

        i = 0
        matched = False

        while i < len(content_lines):
            # 检查是否匹配搜索块
            if self._match_block(content_lines, i, search_lines):
                # 应用替换
                result_lines.extend(replace_lines)
                i += len(search_lines)
                matched = True
            else:
                result_lines.append(content_lines[i])
                i += 1

        if matched:
            return EditResult(
                success=True,
                content='\n'.join(result_lines),
                match_type=MatchType.EXACT,
                similarity=1.0,
            )

        # 尝试模糊匹配
        if fuzzy:
            result = self._fuzzy_replace(content, search_lines, replace_lines)
            if result:
                return EditResult(
                    success=True,
                    content=result,
                    match_type=MatchType.FUZZY,
                    similarity=0.7,
                )

        # 匹配失败
        return EditResult(
            success=False,
            content=None,
            match_type=MatchType.NONE,
            error_message="Patch block failed to match",
        )

    def _match_block(self, content: list[str], start: int, search: list[str]) -> bool:
        """精确匹配块"""
        if start + len(search) > len(content):
            return False

        for i, search_line in enumerate(search):
            norm_search = self._norm(search_line)
            norm_content = self._norm(content[start + i])
            if norm_search != norm_content:
                return False
        return True

    def _fuzzy_replace(
        self,
        content: str,
        search: list[str],
        replace: list[str],
    ) -> str | None:
        """模糊替换"""
        # 简单的模糊匹配：忽略空白差异
        content_lines = content.splitlines()

        for i in range(len(content_lines) - len(search) + 1):
            matches = 0
            for j, search_line in enumerate(search):
                if search_line.strip() == content_lines[i + j].strip():
                    matches += 1

            if matches >= len(search) * 0.7:  # 70% 匹配
                result = content_lines[:i] + replace + content_lines[i + len(search):]
                return '\n'.join(result)

        return None

    def parse_response(self, response: str) -> list[tuple[str, str, str]]:
        """解析 patch 格式响应

        Returns:
            List of (filename, search_text, replace_text)
        """
        edits = []

        lines = response.splitlines()
        current_file = None
        current_search = []
        current_replace = []
        in_search = False
        in_replace = False

        for line in lines:
            norm = self._norm(line)

            if norm.startswith(PATCH_START):
                current_file = norm[len(PATCH_START):].strip()
                current_search = []
                current_replace = []
                in_search = True
                in_replace = False

            elif norm == "---" and in_search:
                in_search = False
                in_replace = True

            elif norm == "***" and in_replace:
                if current_file:
                    edits.append((
                        current_file,
                        '\n'.join(current_search),
                        '\n'.join(current_replace),
                    ))
                in_search = False
                in_replace = False
                current_file = None

            elif in_search:
                current_search.append(line)

            elif in_replace:
                current_replace.append(line)

        return edits

    def get_error_hint(self, search: str, content: str) -> str | None:
        """生成错误提示"""
        search_lines = search.splitlines()
        content_lines = content.splitlines()

        # 找到最相似的行
        similar = []
        for _i, search_line in enumerate(search_lines[:5]):
            for j, content_line in enumerate(content_lines):
                if search_line.strip() == content_line.strip():
                    similar.append(f"行 {j+1}: {content_line[:60]}")
                    break

        if similar:
            return "可能的匹配位置:\n" + "\n".join(similar[:3])
        return None


def find_patches(text: str) -> Generator[tuple[str, str, str], None, None]:
    """从文本中提取 patch 块"""
    lines = text.splitlines()

    current_file = None
    search_lines = []
    replace_lines = []
    mode = None  # 'search' or 'replace'

    for line in lines:
        norm = line.rstrip("\r")

        if norm.startswith(PATCH_START):
            if current_file and search_lines:
                yield current_file, '\n'.join(search_lines), '\n'.join(replace_lines)
            current_file = norm[len(PATCH_START):].strip()
            search_lines = []
            replace_lines = []
            mode = 'search'

        elif norm == "---" and mode == 'search':
            mode = 'replace'

        elif norm == "***":
            if current_file and search_lines:
                yield current_file, '\n'.join(search_lines), '\n'.join(replace_lines)
            current_file = None
            search_lines = []
            replace_lines = []
            mode = None

        elif mode == 'search':
            search_lines.append(line)

        elif mode == 'replace':
            replace_lines.append(line)

    # Yield last block
    if current_file and search_lines:
        yield current_file, '\n'.join(search_lines), '\n'.join(replace_lines)

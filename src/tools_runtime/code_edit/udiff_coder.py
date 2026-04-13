"""UDiff Coder — Unified Diff 格式编辑器

借鉴 Aider 的 UDiffCoder，实现:
1. 解析 Unified Diff 格式
2. @@ -start,len +start,len @@ 标记支持
3. 上下文行处理

适合需要与标准 diff 工具兼容的场景。
"""
from __future__ import annotations

import re
from collections.abc import Generator

from src.tools_runtime.code_edit.base_coder import BaseCoder, EditResult, MatchType


class UDiffCoder(BaseCoder):
    """Unified Diff 格式编辑器

    支持标准 Unified Diff 格式:

        diff --git a/file.py b/file.py
        --- a/file.py
        +++ b/file.py
        @@ -1,5 +1,6 @@
         def old_func():
        -    old_line
        +    new_line_1
        +    new_line_2

    特性:
    - 标准 Unified Diff 解析
    - 多文件 patch 支持
    - Hunk 级别编辑
    """

    edit_format = "udiff"
    supports_context = True

    def apply(
        self,
        content: str,
        search_text: str,
        replace_text: str,
        fuzzy: bool = True,
    ) -> EditResult:
        """应用 unified diff 风格编辑"""
        if not search_text.strip():
            return EditResult(
                success=False,
                content=None,
                match_type=MatchType.NONE,
                error_message="Search content required for diff",
            )

        # 解析 diff 格式
        search_lines = search_text.splitlines()
        replace_lines = replace_text.splitlines()

        content_lines = content.splitlines()
        result = self._apply_diff(content_lines, search_lines, replace_lines)

        if result:
            return EditResult(
                success=True,
                content='\n'.join(result),
                match_type=MatchType.EXACT,
                similarity=1.0,
            )

        # 模糊匹配
        if fuzzy:
            fuzzy_result = self._fuzzy_diff(content_lines, search_lines, replace_lines)
            if fuzzy_result:
                return EditResult(
                    success=True,
                    content='\n'.join(fuzzy_result),
                    match_type=MatchType.FUZZY,
                    similarity=0.7,
                )

        return EditResult(
            success=False,
            content=None,
            match_type=MatchType.NONE,
            error_message="Diff block failed to match",
        )

    def _apply_diff(
        self,
        content: list[str],
        search: list[str],
        replace: list[str],
    ) -> list[str] | None:
        """应用 diff 编辑"""
        # 提取被删除的行（以 - 开头但不是 ---）
        del_lines = [l[1:] for l in search if l.startswith('-') and not l.startswith('---')]
        # 提取新增的行（以 + 开头但不是 +++）
        ins_lines = [l[1:] for l in replace if l.startswith('+') and not l.startswith('+++')]

        if not del_lines:
            # 纯插入
            for i, line in enumerate(content):
                if line.strip() == '':
                    result = content[:i] + ins_lines + content[i:]
                    return result
            return content + ins_lines

        # 查找删除位置
        for i in range(len(content) - len(del_lines) + 1):
            matches = True
            for j, del_line in enumerate(del_lines):
                if content[i + j].strip() != del_line.strip():
                    matches = False
                    break

            if matches:
                result = content[:i] + ins_lines + content[i + len(del_lines):]
                return result

        return None

    def _fuzzy_diff(
        self,
        content: list[str],
        search: list[str],
        replace: list[str],
    ) -> list[str] | None:
        """模糊 diff 匹配"""
        # 忽略空白差异
        search_stripped = [l.strip() for l in search if l.strip() and not l.startswith('-')]

        for i in range(len(content) - len(search_stripped) + 1):
            matches = 0
            for j, search_line in enumerate(search_stripped):
                if content[i + j].strip() == search_line:
                    matches += 1

            if matches >= len(search_stripped) * 0.7:
                # 提取需要替换的内容
                ins_lines = [l for l in replace if l.startswith('+') and not l.startswith('+++')]
                result = content[:i] + ins_lines + content[i + len(search):]
                return result

        return None

    def parse_response(self, response: str) -> list[tuple[str, str, str]]:
        """解析 unified diff 格式响应

        Returns:
            List of (filename, search_text, replace_text)
        """
        edits = []

        # 标准 unified diff 格式
        lines = response.splitlines()
        current_file = None
        search_lines = []
        replace_lines = []
        in_hunk = False

        for line in lines:
            # 检测文件路径
            if line.startswith('diff --git'):
                if current_file and search_lines:
                    edits.append((current_file, '\n'.join(search_lines), '\n'.join(replace_lines)))
                # 提取文件名
                parts = line.split()
                if len(parts) >= 3:
                    current_file = parts[2].strip('a/')
                search_lines = []
                replace_lines = []
                in_hunk = False

            # 检测 hunk 开始
            elif line.startswith('@@'):
                in_hunk = True
                search_lines.append(line)
                replace_lines.append(line)

            # 检测文件结束
            elif line.startswith('diff ') or line.startswith('index '):
                if current_file and search_lines:
                    edits.append((current_file, '\n'.join(search_lines), '\n'.join(replace_lines)))
                current_file = None
                search_lines = []
                replace_lines = []
                in_hunk = False

            elif in_hunk:
                if line.startswith('-'):
                    search_lines.append(line)
                elif line.startswith('+'):
                    replace_lines.append(line)
                elif line.startswith(' ') or not line.strip():
                    search_lines.append(line)
                    replace_lines.append(line)

        # 添加最后一个
        if current_file and search_lines:
            edits.append((current_file, '\n'.join(search_lines), '\n'.join(replace_lines)))

        return edits

    def get_error_hint(self, search: str, content: str) -> str | None:
        """生成错误提示"""
        # 解析 @@ 行获取行号信息
        hunk_match = re.search(r'@@ -(\d+),?\d* \+(\d+),?\d* @@', search)
        if hunk_match:
            line_num = hunk_match.group(1)
            return f"Hunk starts at line {line_num}"

        return None


class UDiffSimpleCoder(UDiffCoder):
    """简化版 UDiff 编辑器

    不支持 hunk 级别的精确匹配，适合简单场景。
    """

    edit_format = "udiff_simple"

    def apply(
        self,
        content: str,
        search_text: str,
        replace_text: str,
        fuzzy: bool = True,
    ) -> EditResult:
        """应用简化 diff"""
        # 简化版：直接搜索替换
        search_lines = [l for l in search_text.splitlines() if l.strip()]
        replace_lines = replace_text.splitlines()

        content_lines = content.splitlines()
        result_lines = []

        i = 0
        matched = False

        while i < len(content_lines):
            # 简单匹配
            if i < len(content_lines) - len(search_lines) + 1:
                match = True
                for j, search_line in enumerate(search_lines):
                    if content_lines[i + j].strip() != search_line.strip():
                        match = False
                        break

                if match:
                    result_lines.extend(replace_lines)
                    i += len(search_lines)
                    matched = True
                    continue

            result_lines.append(content_lines[i])
            i += 1

        if matched:
            return EditResult(
                success=True,
                content='\n'.join(result_lines),
                match_type=MatchType.EXACT,
                similarity=1.0,
            )

        return EditResult(
            success=False,
            content=None,
            match_type=MatchType.NONE,
            error_message="Diff match failed",
        )


def extract_udiffs(text: str) -> Generator[tuple[str, str, str], None, None]:
    """从文本中提取 unified diff 块"""
    lines = text.splitlines()

    current_file = None
    search_lines = []
    replace_lines = []
    in_diff = False

    for line in lines:
        if line.startswith('diff --git'):
            if current_file and search_lines:
                yield current_file, '\n'.join(search_lines), '\n'.join(replace_lines)
            parts = line.split()
            if len(parts) >= 3:
                current_file = parts[2].strip('a/')
            search_lines = []
            replace_lines = []
            in_diff = True

        elif line.startswith('@@') and in_diff:
            search_lines.append(line)
            replace_lines.append(line)

        elif in_diff:
            if line.startswith('-'):
                search_lines.append(line)
            elif line.startswith('+'):
                replace_lines.append(line)
            elif line.startswith(' '):
                search_lines.append(line)
                replace_lines.append(line)

    if current_file and search_lines:
        yield current_file, '\n'.join(search_lines), '\n'.join(replace_lines)

"""EditBlock Coder — SEARCH/REPLACE 块编辑器

借鉴 Aider 的 EditBlockCoder，实现:
1. 解析 <<<<<<< SEARCH / ======= / >>>>>>> REPLACE 格式
2. 多级匹配策略
3. 错误提示生成

这是最常用的代码编辑格式，被 Claude、GPT-4 等模型广泛支持。
"""
from __future__ import annotations

import re
from collections.abc import Generator
from pathlib import Path

from src.tools_runtime.code_edit.base_coder import BaseCoder, EditResult, MatchType
from src.tools_runtime.code_edit.fuzzy_matcher import (
    replace_most_similar_chunk,
)

# 标记正则
HEAD = r"^<{5,9} SEARCH>?\s*$"
DIVIDER = r"^={5,9}\s*$"
UPDATED = r"^>{5,9} REPLACE\s*$"

HEAD_ERR = "<<<<<<< SEARCH"
DIVIDER_ERR = "======="
UPDATED_ERR = ">>>>>>> REPLACE"

DEFAULT_FENCE = ("`" * 3, "`" * 3)


class EditBlockCoder(BaseCoder):
    """SEARCH/REPLACE 块编辑器

    支持 LLM 输出的标准编辑格式:

        filename.py
        ```python
        <<<<<<< SEARCH
        def old_function():
            pass
        =======
        def new_function():
            return True
        >>>>>>> REPLACE
        ```

    特性:
    - 多级匹配策略 (精确 -> 空白容错 -> 模糊)
    - ... 省略语法支持
    - 创建新文件 (空 SEARCH 块)
    """

    edit_format = "editblock"
    supports_fuzzy = True
    supports_dotdotdot = True

    def apply(
        self,
        content: str,
        search_text: str,
        replace_text: str,
        fuzzy: bool = True,
    ) -> EditResult:
        """应用 SEARCH/REPLACE 编辑

        Args:
            content: 原始文件内容
            search_text: SEARCH 块内容
            replace_text: REPLACE 块内容
            fuzzy: 是否启用模糊匹配

        Returns:
            EditResult 对象
        """
        # 清理可能的外层包装
        search_text = self._strip_quoted_wrapping(search_text)
        replace_text = self._strip_quoted_wrapping(replace_text)

        # 处理创建新文件的情况
        if not search_text.strip():
            # 追加到现有文件或创建新文件
            new_content = (content or "") + replace_text
            return EditResult(
                success=True,
                content=new_content,
                match_type=MatchType.EXACT,
                similarity=1.0,
                meta={"action": "create_or_append"},
            )

        # 应用编辑
        result, match_type = replace_most_similar_chunk(content, search_text, replace_text)

        if result:
            return EditResult(
                success=True,
                content=result,
                match_type=MatchType(match_type),
                similarity=1.0 if match_type == "exact" else 0.8,
            )

        # 匹配失败
        error_hint = self.get_error_hint(search_text, content)
        error_message = f"SEARCH block failed to match.\n{error_hint}" if error_hint else "SEARCH block failed to match."

        return EditResult(
            success=False,
            content=None,
            match_type=MatchType.NONE,
            error_message=error_message,
        )

    def parse_response(self, response: str) -> list[tuple[str, str, str]]:
        """解析 LLM 响应中的所有编辑块

        Args:
            response: LLM 响应文本

        Returns:
            List of (filename, search_text, replace_text)

        Raises:
            ValueError: 格式错误
        """
        return list(find_original_update_blocks(response))

    def _strip_quoted_wrapping(self, text: str) -> str:
        """去除可能的外层包装

        LLM 有时会在编辑块外添加额外的引号或反引号。
        """
        if not text:
            return text

        lines = text.splitlines()

        # 移除开头的空行
        while lines and not lines[0].strip():
            lines.pop(0)

        # 移除结尾的空行
        while lines and not lines[-1].strip():
            lines.pop()

        # 检查是否有代码块包装
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
            lines = lines[1:-1]

        result = "\n".join(lines)
        if result and not result.endswith("\n"):
            result += "\n"

        return result


def find_original_update_blocks(
    content: str,
    fence: tuple[str, str] = DEFAULT_FENCE,
    valid_fnames: list[str] | None = None,
) -> Generator[tuple[str | None, str, str], None, None]:
    """从内容中提取所有 SEARCH/REPLACE 块

    借鉴 Aider 的 find_original_update_blocks() 函数。

    Yields:
        (filename, original_text, updated_text)
        filename 为 None 表示这是一个 shell 命令块
    """
    lines = content.splitlines(keepends=True)
    i = 0
    current_filename = None

    head_pattern = re.compile(HEAD)
    divider_pattern = re.compile(DIVIDER)
    updated_pattern = re.compile(UPDATED)

    while i < len(lines):
        line = lines[i]

        # 检查 shell 命令块
        shell_starts = [
            "```bash", "```sh", "```shell", "```cmd",
            "```batch", "```powershell", "```ps1",
            "```zsh", "```fish", "```ksh",
        ]

        next_is_editblock = (
            (i + 1 < len(lines) and head_pattern.match(lines[i + 1].strip()))
            or (i + 2 < len(lines) and head_pattern.match(lines[i + 2].strip()))
        )

        if any(line.strip().startswith(start) for start in shell_starts) and not next_is_editblock:
            shell_content = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                shell_content.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].strip().startswith("```"):
                i += 1

            yield None, "".join(shell_content), ""
            continue

        # 检查 SEARCH/REPLACE 块
        if head_pattern.match(line.strip()):
            try:
                # 查找文件名
                if i + 1 < len(lines) and divider_pattern.match(lines[i + 1].strip()):
                    filename = find_filename(lines[max(0, i - 3) : i], fence, None)
                else:
                    filename = find_filename(lines[max(0, i - 3) : i], fence, valid_fnames)

                if not filename:
                    if current_filename:
                        filename = current_filename
                    else:
                        raise ValueError(f"Missing filename. Expected before {HEAD_ERR}")

                current_filename = filename

                # 读取 SEARCH 部分
                original_text = []
                i += 1
                while i < len(lines) and not divider_pattern.match(lines[i].strip()):
                    original_text.append(lines[i])
                    i += 1

                if i >= len(lines) or not divider_pattern.match(lines[i].strip()):
                    raise ValueError(f"Expected `{DIVIDER_ERR}`")

                # 读取 REPLACE 部分
                updated_text = []
                i += 1
                while i < len(lines) and not (
                    updated_pattern.match(lines[i].strip())
                    or divider_pattern.match(lines[i].strip())
                ):
                    updated_text.append(lines[i])
                    i += 1

                if i >= len(lines) or not (
                    updated_pattern.match(lines[i].strip())
                    or divider_pattern.match(lines[i].strip())
                ):
                    raise ValueError(f"Expected `{UPDATED_ERR}` or `{DIVIDER_ERR}`")

                yield filename, "".join(original_text), "".join(updated_text)

            except ValueError as e:
                processed = "".join(lines[: i + 1])
                err = e.args[0]
                raise ValueError(f"{processed}\n^^^ {err}")

        i += 1


def find_filename(
    lines: list[str],
    fence: tuple[str, str] = DEFAULT_FENCE,
    valid_fnames: list[str] | None = None,
) -> str | None:
    """从最近的几行中查找文件名

    借鉴 Aider 的 find_filename() 函数。
    """
    import difflib

    if valid_fnames is None:
        valid_fnames = []

    lines = lines[::-1][:3]  # 最近 3 行

    filenames = []
    for line in lines:
        filename = strip_filename(line, fence)
        if filename:
            filenames.append(filename)

        if not line.startswith(fence[0]) and not line.startswith("`" * 3):
            break

    if not filenames:
        return None

    # 精确匹配
    for fname in filenames:
        if fname in valid_fnames:
            return fname

    # basename 匹配
    for fname in filenames:
        for vfn in valid_fnames:
            if fname == Path(vfn).name:
                return vfn

    # 模糊匹配
    for fname in filenames:
        close_matches = difflib.get_close_matches(fname, valid_fnames, n=1, cutoff=0.8)
        if close_matches:
            return close_matches[0]

    # 有扩展名的优先
    for fname in filenames:
        if "." in fname:
            return fname

    return filenames[0] if filenames else None


def strip_filename(filename: str, fence: tuple[str, str] = DEFAULT_FENCE) -> str | None:
    """清理文件名"""
    filename = filename.strip()

    if filename == "...":
        return None

    start_fence = fence[0]
    if filename.startswith(start_fence):
        candidate = filename[len(start_fence):]
        if candidate and ("." in candidate or "/" in candidate):
            return candidate
        return None

    # 处理三引号
    if filename.startswith("`" * 3):
        candidate = filename[len("`" * 3):]
        if candidate and ("." in candidate or "/" in candidate):
            return candidate
        return None

    filename = filename.rstrip(":")
    filename = filename.lstrip("#")
    filename = filename.strip()
    filename = filename.strip("`")
    filename = filename.strip("*")

    return filename

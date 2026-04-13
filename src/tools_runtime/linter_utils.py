"""Linter 辅助函数模块

包含 LintResult 合并、格式化等辅助函数。
"""
from __future__ import annotations

import re

from .linter_types import LintResult


def _merge_lint_results(a: LintResult, b: LintResult) -> LintResult:
    """合并两个 LintResult"""
    if not a:
        return b
    if not b:
        return a

    text = a.text
    if b.text:
        if text:
            text += '\n' + b.text
        else:
            text = b.text

    lines = list(dict.fromkeys(a.lines + b.lines))  # 去重保序
    return LintResult(text=text, lines=lines)


def _merge_multiple_results(results: list[LintResult]) -> LintResult:
    """合并多个 LintResult"""
    merged = LintResult()
    for r in results:
        merged = _merge_lint_results(merged, r)
    return merged


def _find_linenums_in_output(text: str, fnames: list[str]) -> list[int]:
    """从 lint 输出中提取行号（从 Aider 移植增强版）

    参数:
        text: lint 输出文本
        fnames: 文件名列表

    返回:
        0-indexed 行号列表
    """
    if not fnames:
        return []

    # 尝试使用 grep_ast.TreeContext 进行更精确的解析
    try:
        from grep_ast import TreeContext  # noqa: F401
        filenames_linenums = find_filenames_and_linenums(text, fnames)
        if filenames_linenums:
            # 返回第一个文件的行号（转为 0-indexed）
            return [ln - 1 for ln in next(iter(filenames_linenums.values()))]
    except ImportError:
        pass

    # 回退到简单正则匹配
    pattern = re.compile(
        r'(\b(?:' + '|'.join(re.escape(f) for f in fnames) + r'):\d+\b)'
    )
    matches = pattern.findall(text)
    result: dict[str, set[int]] = {}

    for match in matches:
        fname, linenum = match.rsplit(':', 1)
        if fname not in result:
            result[fname] = set()
        result[fname].add(int(linenum))

    if result:
        return list(next(iter(result.values())))
    return []


def find_filenames_and_linenums(
    text: str,
    fnames: list[str],
) -> dict[str, list[int]]:
    """从 lint 输出中提取文件名和行号（从 Aider 移植）

    支持多种常见的 linter 输出格式:
    - file.py:42: error
    - file.py:42:5: error
    - file.py(42): error
    - Error in file.py line 42

    参数:
        text: lint 输出文本
        fnames: 可能出现的文件名列表

    返回:
        {文件名: [行号列表]} 字典，行号为 1-indexed
    """
    result: dict[str, list[int]] = {}

    # 对每个文件名进行匹配
    for fname in fnames:
        # 转义文件名中的特殊字符
        escaped = re.escape(fname)

        # 多种行号模式
        patterns = [
            rf'{escaped}:(\d+)',           # file.py:42
            rf'{escaped}:(\d+):\d+',       # file.py:42:5
            rf'{escaped}\((\d+)\)',        # file.py(42)
            rf'{escaped}\s+line\s+(\d+)',  # file.py line 42
            rf'{escaped}\[(\d+)\]',        # file.py[42]
        ]

        linenums: set[int] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                linenum = int(match.group(1))
                if linenum > 0:
                    linenums.add(linenum)

        if linenums:
            result[fname] = sorted(linenums)

    return result


def format_lint_result(
    result: LintResult,
    fname: str,
    code: str,
    context_lines: int = 3,
) -> str:
    """格式化代码检查结果

    生成包含错误消息和代码上下文的可读输出，
    在错误行前标记 `>>` 符号。

    参数:
        result: LintResult 对象
        fname: 文件名（用于显示）
        code: 源代码内容
        context_lines: 每个错误行周围显示的上下文行数

    返回:
        格式化后的错误报告字符串

    示例输出:
        语法错误: invalid syntax
        File: example.py

        >>   5 |     def broken(
            6 |         pass
            7 |     )
    """
    if not result.text:
        return ''

    output_lines: list[str] = []
    output_lines.append(f'语法错误: {result.text}')
    output_lines.append(f'文件: {fname}')
    output_lines.append('')

    # 如果没有行号，仅显示错误消息
    if not result.lines:
        return '\n'.join(output_lines)

    # 分割代码为行列表
    code_lines = code.splitlines()

    # 计算需要显示的行号范围
    lines_to_show: set[int] = set()
    for error_line in result.lines:
        if 0 <= error_line < len(code_lines):
            # 添加错误行及其上下文
            for offset in range(-context_lines, context_lines + 1):
                context_line = error_line + offset
                if 0 <= context_line < len(code_lines):
                    lines_to_show.add(context_line)

    # 按行号排序并分组连续行
    sorted_lines = sorted(lines_to_show)
    if not sorted_lines:
        return '\n'.join(output_lines)

    # 找出连续行组之间的断点，添加分隔符
    prev_line = -1
    for line_idx in sorted_lines:
        if prev_line >= 0 and line_idx > prev_line + 1:
            output_lines.append('...')
        prev_line = line_idx

        # 格式化行（1-indexed 显示）
        display_line_num = line_idx + 1
        is_error_line = line_idx in result.lines
        prefix = '>> ' if is_error_line else '   '
        line_content = code_lines[line_idx]

        output_lines.append(f'{prefix}{display_line_num:4d} | {line_content}')

    return '\n'.join(output_lines)

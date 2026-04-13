"""Unified Diff 解析器 — 从 Aider udiff_coder.py 移植

解析标准 unified diff 格式（```diff / --- a/ / +++ b/ / @@ @@），支持:
- 标准 git diff 文件头
- 多文件多 hunk
- 智能上下文裁剪（progressive context dropping）
- SEARCH/REPLACE 回退策略
"""
from __future__ import annotations

import difflib
import logging
from collections.abc import Iterator

logger = logging.getLogger(__name__)


# ==================== 解析 ====================

def find_diffs(content: str) -> Iterator[tuple[str | None, list[str]]]:
    """从 LLM 输出中提取 diff 块

    查找 ```diff ... ``` 围栏块，解析出 (文件名, hunk行列表)。

    参数:
        content: LLM 响应文本

    生成:
        (文件名, hunk) 元组
    """
    if not content.endswith('\n'):
        content = content + '\n'

    lines = content.splitlines(keepends=True)
    line_num = 0

    while line_num < len(lines):
        while line_num < len(lines):
            line = lines[line_num]
            if line.startswith('```diff'):
                line_num, these_edits = _process_fenced_block(lines, line_num + 1)
                yield from these_edits
                break
            line_num += 1


def _process_fenced_block(
    lines: list[str],
    start_line_num: int,
) -> tuple[int, list[tuple[str | None, list[str]]]]:
    """处理 ```diff 围栏块"""
    end_line_num = start_line_num
    for line_num in range(start_line_num, len(lines)):
        line = lines[line_num]
        if line.startswith('```'):
            end_line_num = line_num
            break

    block = lines[start_line_num:end_line_num]
    block.append('@@ @@\n')

    if block[0].startswith('--- ') and block[1].startswith('+++ '):
        a_fname = block[0][4:].strip()
        b_fname = block[1][4:].strip()

        # 去除 git diff 前缀 (a/ 或 b/)
        if (a_fname.startswith('a/') or a_fname == '/dev/null') and b_fname.startswith('b/'):
            fname = b_fname[2:]
        else:
            fname = b_fname

        block = block[2:]
    else:
        fname = None

    edits: list[tuple[str | None, list[str]]] = []
    keeper = False
    hunk: list[str] = []

    for line in block:
        hunk.append(line)
        if len(line) < 2:
            continue

        if line.startswith('+++ ') and len(hunk) >= 2 and hunk[-2].startswith('--- '):
            if len(hunk) >= 3 and hunk[-3] == '\n':
                hunk = hunk[:-3]
            else:
                hunk = hunk[:-2]

            edits.append((fname, hunk))
            hunk = []
            keeper = False

            fname = line[4:].strip()
            continue

        op = line[0]
        if op in '-+':
            keeper = True
            continue
        if op != '@':
            continue
        if not keeper:
            hunk = []
            continue

        hunk = hunk[:-1]
        edits.append((fname, hunk))
        hunk = []
        keeper = False

    return end_line_num + 1, edits


# ==================== Hunk 操作 ====================

class SearchTextNotUnique(ValueError):
    """搜索文本在文件中出现多次"""
    pass


def hunk_to_before_after(
    hunk: list[str],
    lines: bool = False,
) -> tuple[list[str] | str, list[str] | str]:
    """将 hunk 拆分为 before/after 文本

    参数:
        hunk: diff hunk 行列表
        lines: 是否返回行列表（否则返回拼接字符串）

    返回:
        (before, after) — 删除前和添加后的内容
    """
    before: list[str] = []
    after: list[str] = []
    op = ' '

    for line in hunk:
        if len(line) < 2:
            op = ' '
            line_text = line
        else:
            op = line[0]
            line_text = line[1:]

        if op == ' ':
            before.append(line_text)
            after.append(line_text)
        elif op == '-':
            before.append(line_text)
        elif op == '+':
            after.append(line_text)

    if lines:
        return before, after

    return ''.join(before), ''.join(after)


def normalize_hunk(hunk: list[str]) -> list[str]:
    """规范化 hunk — 清理纯空白行并重新生成 diff"""
    before, after = hunk_to_before_after(hunk, lines=True)

    before = _cleanup_pure_whitespace_lines(before)
    after = _cleanup_pure_whitespace_lines(after)

    diff = difflib.unified_diff(before, after, n=max(len(before), len(after)))
    return list(diff)[3:]


def _cleanup_pure_whitespace_lines(lines: list[str]) -> list[str]:
    """清理纯空白行为仅保留换行符"""
    return [
        line if line.strip() else line[-(len(line) - len(line.rstrip('\r\n')))]
        for line in lines
    ]


# ==================== Hunk 应用 ====================

def apply_hunks(
    content: str,
    hunks: list[tuple[str, list[str]]],
    fname: str = '',
) -> str:
    """对文件内容应用多个 hunk

    参数:
        content: 原始文件内容
        hunks: [(文件名, hunk)] 列表
        fname: 当前文件名（用于错误信息）

    返回:
        修改后的文件内容

    异常:
        ValueError: hunk 应用失败
    """
    errors: list[str] = []

    seen = set()
    for path, hunk in hunks:
        hunk = normalize_hunk(hunk)
        if not hunk:
            continue

        hunk_key = ''.join(hunk)
        if hunk_key in seen:
            continue
        seen.add(hunk_key)

        try:
            result = _apply_single_hunk(content, hunk, path or fname)
            if result:
                content = result
            else:
                original, _ = hunk_to_before_after(hunk)
                errors.append(
                    f'UnifiedDiffNoMatch: hunk failed to apply for {path or fname}!\n'
                    f'{path or fname} does not contain these {len(original.splitlines())} lines:\n'
                    f'```\n{original}```\n'
                )
        except SearchTextNotUnique:
            original, _ = hunk_to_before_after(hunk)
            errors.append(
                f'UnifiedDiffNotUnique: hunk not unique in {path or fname}!\n'
                f'Use additional context lines to uniquely identify the code.\n'
                f'{path or fname} contains multiple copies of:\n'
                f'```\n{original}```\n'
            )

    if errors:
        msg = '\n\n'.join(errors)
        if len(errors) < len(hunks):
            msg += '\nNote: some hunks did apply successfully.\n'
        raise ValueError(msg)

    return content


def _apply_single_hunk(
    content: str,
    hunk: list[str],
    fname: str = '',
) -> str | None:
    """应用单个 hunk

    策略:
    1. 直接应用 (flexi search-and-replace)
    2. 逐步裁剪上下文后应用 (progressive context dropping)

    返回:
        修改后的内容，或 None（失败）
    """
    before_text, after_text = hunk_to_before_after(hunk)

    # 新文件 / 追加
    if not before_text.strip():
        return content + after_text

    # 策略1: 直接应用
    res = _directly_apply_hunk(content, hunk)
    if res:
        return res

    # 策略2: 逐步裁剪上下文
    hunk = _make_new_lines_explicit(content, hunk)

    # 将 hunk 按 context/change 分段
    ops = ''.join([line[0] for line in hunk])
    ops = ops.replace('-', 'x')
    ops = ops.replace('+', 'x')
    ops = ops.replace('\n', ' ')

    cur_op = ' '
    section: list[str] = []
    sections: list[list[str]] = []

    for i in range(len(ops)):
        op = ops[i]
        if op != cur_op:
            sections.append(section)
            section = []
            cur_op = op
        section.append(hunk[i])

    sections.append(section)
    if cur_op != ' ':
        sections.append([])

    # 逐步应用每个 change 段
    all_done = True
    for i in range(2, len(sections), 2):
        preceding_context = sections[i - 2]
        changes = sections[i - 1]
        following_context = sections[i]

        res = _apply_partial_hunk(content, preceding_context, changes, following_context)
        if res:
            content = res
        else:
            all_done = False
            break

    if all_done:
        return content

    return None


def _directly_apply_hunk(content: str, hunk: list[str]) -> str | None:
    """直接使用 flexi search-and-replace 应用 hunk"""
    from .search_replace import SearchTextNotUnique, flexible_search_and_replace

    before, after = hunk_to_before_after(hunk)

    if not before:
        return None

    before_lines, _ = hunk_to_before_after(hunk, lines=True)
    before_lines_stripped = ''.join([line.strip() for line in before_lines])

    # 拒绝对极小上下文进行重复替换
    if len(before_lines_stripped) < 10 and content.count(before) > 1:
        return None

    try:
        return flexible_search_and_replace(content, before, after)
    except SearchTextNotUnique:
        return None
    except ValueError:
        return None


def _make_new_lines_explicit(content: str, hunk: list[str]) -> list[str]:
    """将新增行显式化（在原始文件中找到对应位置）"""
    before, after = hunk_to_before_after(hunk)

    diff = _diff_lines(before, content)

    back_diff = []
    for line in diff:
        if line[0] == '+':
            continue
        back_diff.append(line)

    new_before = _directly_apply_hunk(before, back_diff)
    if not new_before:
        return hunk

    if len(new_before.strip()) < 10:
        return hunk

    before_lines = before.splitlines(keepends=True)
    new_before_lines = new_before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)

    if len(new_before_lines) < len(before_lines) * 0.66:
        return hunk

    new_hunk = difflib.unified_diff(
        new_before_lines, after_lines,
        n=max(len(new_before_lines), len(after_lines)),
    )
    return list(new_hunk)[3:]


def _apply_partial_hunk(
    content: str,
    preceding_context: list[str],
    changes: list[str],
    following_context: list[str],
) -> str | None:
    """逐步裁剪上下文并尝试应用 hunk 片段"""
    len_prec = len(preceding_context)
    len_foll = len(following_context)
    use_all = len_prec + len_foll

    for drop in range(use_all + 1):
        use = use_all - drop

        for use_prec in range(len_prec, -1, -1):
            if use_prec > use:
                continue

            use_foll = use - use_prec
            if use_foll > len_foll:
                continue

            if use_prec:
                this_prec = preceding_context[-use_prec:]
            else:
                this_prec = []

            this_foll = following_context[:use_foll]

            res = _directly_apply_hunk(content, this_prec + changes + this_foll)
            if res:
                return res

    return None


def _diff_lines(search_text: str, replace_text: str) -> list[str]:
    """生成 unified diff 行列表"""
    try:
        from diff_match_patch import diff_match_patch
    except ImportError:
        return list(difflib.unified_diff(
            search_text.splitlines(keepends=True),
            replace_text.splitlines(keepends=True),
        ))

    dmp = diff_match_patch()
    dmp.Diff_Timeout = 5

    search_lines, replace_lines, mapping = dmp.diff_linesToChars(search_text, replace_text)
    diff_result = dmp.diff_main(search_lines, replace_lines, None)
    dmp.diff_cleanupSemantic(diff_result)
    dmp.diff_cleanupEfficiency(diff_result)

    diff = list(diff_result)
    dmp.diff_charsToLines(diff, mapping)

    udiff: list[str] = []
    for d, lines in diff:
        if d < 0:
            prefix = '-'
        elif d > 0:
            prefix = '+'
        else:
            prefix = ' '
        for line in lines.splitlines(keepends=True):
            udiff.append(prefix + line)

    return udiff

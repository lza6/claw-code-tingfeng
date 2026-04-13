"""SEARCH/REPLACE 编辑块解析器 — 从 aider editblock_coder.py 移植

解析 LLM 输出中的 SEARCH/REPLACE 块，支持:
- <<<<<<< SEARCH / ======= / >>>>>>> REPLACE 格式
- 模糊文件名匹配
- 多种代码围栏格式（```, `````, ```python 等）
- Shell 命令块提取
- 级联容错匹配（精确 → 缩进归一化 → ...省略 → 模糊匹配）
"""
from __future__ import annotations

import difflib
import logging
import re
from collections.abc import Iterator

logger = logging.getLogger(__name__)

# ==================== 正则常量 ====================

# SEARCH/REPLACE 分隔符（5-9个连续字符）
HEAD = r'^<{5,9} SEARCH>?\s*$'
DIVIDER = r'^={5,9}\s*$'
UPDATED = r'^>{5,9} REPLACE\s*$'

# 组合为分割正则
split_re = re.compile(
    r'(' + HEAD + r')|(' + DIVIDER + r')|(' + UPDATED + r')',
    re.MULTILINE | re.DOTALL,
)

# Shell 代码块标记
SHELL_FENCE_RE = re.compile(
    r'^(?:```\s*(?:bash|sh|zsh|fish|shell|cmd|powershell)\s*\n'
    r'|```\s*\n)',
    re.MULTILINE,
)

# 代码围栏（3-4个反引号）
FENCE_RE = re.compile(r'^(`{3,4})\s*(\S*)\s*\n?', re.MULTILINE)

# 文件名模式（常见格式）
FILENAME_RE = re.compile(r'^(.+?\.(?:\w{1,10}))\s*$')


# ==================== 核心解析 ====================

def find_original_update_blocks(
    text: str,
) -> Iterator[tuple[str | None, str, str] | tuple[None, str]]:
    """解析 LLM 输出中的 SEARCH/REPLACE 块

    遍历响应文本，提取 (文件名, 搜索内容, 替换内容) 三元组。
    也检测 shell 命令块，返回 (None, shell_content) 元组。

    参数:
        text: LLM 的完整响应文本

    生成:
        - (文件名, 搜索文本, 替换文本) 三元组
        - (None, shell命令内容) 二元组（shell 块）
    """
    # 不去除围栏包装（保留 shell 块的围栏以便检测）
    lines = text.splitlines(keepends=True)
    length = len(lines)

    i = 0
    while i < length:
        line = lines[i]
        stripped = line.rstrip()

        # 检查 shell 命令块（```bash / ```sh 等）
        shell_match = re.match(r'^(`{3,4})\s*(?:bash|sh|zsh|fish|shell|cmd|powershell)\s*$', stripped)
        if shell_match:
            shell_match.group(1)
            shell_lines = []
            i += 1
            while i < length:
                close_line = lines[i].rstrip()
                # 检查结束围栏：仅包含反引号
                if re.match(r'^`{3,4}\s*$', close_line):
                    break
                shell_lines.append(lines[i])
                i += 1
            yield (None, ''.join(shell_lines))
            if i < length:
                i += 1  # 跳过结束围栏
            continue

        # 检查 SEARCH 标记
        if re.match(HEAD, stripped):
            # 回溯查找文件名（最多3行）
            fname = None
            for j in range(max(0, i - 3), i):
                candidate = lines[j].rstrip()
                # 跳过空行和标记行
                if not candidate or re.match(HEAD, candidate) or re.match(DIVIDER, candidate) or re.match(UPDATED, candidate):
                    continue
                # 跳过围栏行
                if re.match(r'^`{3,4}', candidate):
                    continue
                fname = candidate
                break

            # 收集 SEARCH 内容（直到 DIVIDER）
            search_lines = []
            i += 1
            while i < length and not re.match(DIVIDER, lines[i].rstrip()):
                search_lines.append(lines[i])
                i += 1

            # 跳过 DIVIDER
            found_divider = False
            if i < length and re.match(DIVIDER, lines[i].rstrip()):
                found_divider = True
                i += 1

            # 收集 REPLACE 内容（直到 UPDATED 或第二个 DIVIDER）
            replace_lines = []
            while i < length and not re.match(UPDATED, lines[i].rstrip()) and not re.match(DIVIDER, lines[i].rstrip()):
                replace_lines.append(lines[i])
                i += 1

            # 检查是否找到了 UPDATED（必须找到才算是有效的块）
            found_updated = False
            if i < length and re.match(UPDATED, lines[i].rstrip()):
                found_updated = True
                i += 1

            # 只有找到 DIVIDER 和 UPDATED 才算有效块
            if not found_divider or not found_updated:
                # 未闭合块，跳过不 yield
                continue

            search_text = ''.join(search_lines)
            replace_text = ''.join(replace_lines)

            # 清理文件名
            if fname:
                fname = strip_filename(fname)

            yield (fname, search_text, replace_text)
            continue

        i += 1


def strip_filename(fname: str) -> str:
    """清理文件名，去除围栏、路径前缀等

    参数:
        fname: 原始文件名字符串

    返回:
        清理后的文件名
    """
    fname = fname.strip()
    # 去除围栏标记
    if fname.startswith('`'):
        fname = fname.strip('`')
    # 去除路径前缀（如 path/to/file.py → file.py）
    fname = fname.split('/')[-1]
    fname = fname.split('\\')[-1]
    return fname.strip()


def find_filename(
    fname: str,
    fnames: list[str] | None = None,
) -> str | None:
    """模糊文件名匹配

    匹配策略:
    1. 精确匹配
    2. 基本名匹配
    3. difflib.get_close_matches (cutoff=0.8)
    4. 任何扩展名匹配的文件

    参数:
        fname: 要查找的文件名
        fnames: 候选文件名列表

    返回:
        匹配到的文件名，或 None
    """
    if not fnames:
        return fname or None
    if not fname:
        return None

    # 1. 精确匹配
    if fname in fnames:
        return fname

    # 2. 基本名匹配
    from pathlib import PurePosixPath
    fname_base = PurePosixPath(fname).name
    for f in fnames:
        if PurePosixPath(f).name == fname_base:
            return f

    # 3. 模糊匹配
    matches = difflib.get_close_matches(fname, fnames, n=1, cutoff=0.8)
    if matches:
        return matches[0]

    # 4. 基本名模糊匹配
    matches = difflib.get_close_matches(fname_base, [PurePosixPath(f).name for f in fnames], n=1, cutoff=0.8)
    if matches:
        for f in fnames:
            if PurePosixPath(f).name == matches[0]:
                return f

    return None


def strip_quoted_wrapping(
    res: str,
    fname: str | None = None,
) -> str:
    """去除文本中的代码围栏和文件名头

    处理常见格式:
    - ```python\\n<content>\\n```
    - `````python\\n<content>\\n`````
    - <filename>\\n```\\n<content>\\n```

    参数:
        res: 包含围栏的文本
        fname: 可选的预期文件名

    返回:
        去除围栏后的文本
    """
    if not res:
        return res

    lines = res.splitlines(keepends=True)
    if not lines:
        return res

    # 检测围栏
    stripped_lines = [l.rstrip() for l in lines]

    # 找到开头围栏
    start_fence = None
    start_idx = 0
    for idx, line in enumerate(stripped_lines):
        fence_match = re.match(r'^(`{3,4})\s*(\S*)\s*$', line)
        if fence_match:
            start_fence = fence_match.group(1)
            start_idx = idx + 1
            break
        # 文件名行（后跟围栏）
        if fname and line.strip() == fname and idx + 1 < len(stripped_lines):
            next_match = re.match(r'^(`{3,4})\s*(\S*)\s*$', stripped_lines[idx + 1])
            if next_match:
                start_fence = next_match.group(1)
                start_idx = idx + 2
                break

    if start_fence is None:
        return res

    # 找到结尾围栏
    end_idx = len(lines)
    for idx in range(len(stripped_lines) - 1, start_idx - 1, -1):
        if stripped_lines[idx].startswith(start_fence):
            end_idx = idx
            break

    return ''.join(lines[start_idx:end_idx])


# ==================== 匹配与替换 ====================

def replace_most_similar_chunk(
    search_text: str,
    content: str,
    min_match_ratio: float = 0.6,
) -> str:
    """在 content 中查找与 search_text 最相似的代码块并替换

    匹配策略（级联容错）:
    1. 精确行匹配
    2. 前导空白归一化
    3. 跳过前导空行
    4. ... 省略号处理

    参数:
        search_text: 要搜索的文本
        content: 原始文件内容
        min_match_ratio: 最小匹配比率（用于错误提示）

    返回:
        去除匹配部分后的剩余内容

    异常:
        ValueError: 未找到匹配时抛出，包含相似行建议
    """
    search_lines = search_text.splitlines(keepends=True)
    content_lines = content.splitlines(keepends=True)

    if not search_lines:
        return content

    # 1. 精确匹配
    result = perfect_replace(search_lines, content_lines)
    if result is not None:
        return result

    # 2. 前导空白归一化
    result = replace_part_with_missing_leading_whitespace(search_lines, content_lines)
    if result is not None:
        return result

    # 3. 跳过前导空行
    stripped_search = [l for l in search_lines if l.strip()]
    if stripped_search != search_lines:
        result = perfect_replace(stripped_search, content_lines)
        if result is not None:
            return result

    # 4. ... 省略号处理
    if '...\n' in search_text or '...\r\n' in search_text:
        result = try_dotdotdots(search_lines, content_lines)
        if result is not None:
            return result

    # 未找到匹配 — 生成错误信息
    similar = find_similar_lines(search_text, content)
    if similar:
        hint = f'\n\nDid you mean to match:\n{similar}'
    else:
        hint = ''

    raise ValueError(
        f'No matching chunk found in content for the provided search text.{hint}'
    )


def perfect_replace(
    chunks: list[str],
    content_lines: list[str],
) -> str | None:
    """精确行匹配替换

    使用滑动窗口在 content_lines 中查找与 chunks 完全匹配的子序列。

    参数:
        chunks: 要搜索的行列表
        content_lines: 文件内容行列表

    返回:
        替换后的内容，或 None（未找到匹配）
    """
    if not chunks:
        return None

    chunk_count = len(chunks)
    for i in range(len(content_lines) - chunk_count + 1):
        if content_lines[i:i + chunk_count] == chunks:
            # 找到匹配，去除这些行
            remaining = content_lines[:i] + content_lines[i + chunk_count:]
            return ''.join(remaining)

    return None


def replace_part_with_missing_leading_whitespace(
    chunks: list[str],
    content_lines: list[str],
) -> str | None:
    """处理 LLM 去除公共前导空白的情况

    当 LLM 生成的搜索文本缺少原始代码的缩进时，
    通过比较 lstrip() 后的内容来匹配。

    参数:
        chunks: 要搜索的行列表
        content_lines: 文件内容行列表

    返回:
        替换后的内容，或 None（未找到匹配）
    """
    if not chunks:
        return None

    # 计算 chunks 的最小前导空白
    leading = []
    for line in chunks:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped:  # 跳过空行
            leading.append(indent)

    if not leading:
        return None

    # 检查所有缩进是否一致（允许 0 缩进的空行）
    min_leading = min(leading)
    has_inconsistent = False
    for line in chunks:
        stripped = line.lstrip()
        if stripped:
            indent = len(line) - len(stripped)
            if indent != min_leading:
                has_inconsistent = True
                break

    # 只有当所有非空行的缩进一致时才使用此策略
    if has_inconsistent:
        return None

    # 去除公共前导空白后匹配
    stripped_chunks = [line[min_leading:] if line.strip() else line for line in chunks]

    # 在 content 中查找 lstrip 后匹配的子序列
    chunk_count = len(stripped_chunks)
    for i in range(len(content_lines) - chunk_count + 1):
        window = content_lines[i:i + chunk_count]
        match = True
        for _j, (sc, wl) in enumerate(zip(stripped_chunks, window, strict=False)):
            if not sc.strip() and not wl.strip():
                continue  # 空行匹配空行
            wl_stripped = wl.lstrip()
            sc_stripped = sc.lstrip()
            if wl_stripped != sc_stripped:
                match = False
                break
        if match:
            remaining = content_lines[:i] + content_lines[i + chunk_count:]
            return ''.join(remaining)

    return None


def try_dotdotdots(
    chunks: list[str],
    content_lines: list[str],
) -> str | None:
    """处理包含 ... 省略号的搜索块

    ... 行作为通配符，匹配任意数量的行。

    参数:
        chunks: 可能包含 ... 的搜索行列表
        content_lines: 文件内容行列表

    返回:
        替换后的内容，或 None（未找到匹配）
    """
    if not chunks:
        return None

    # 将 chunks 按 ... 分割为子块
    sub_blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in chunks:
        if line.strip() == '...':
            if current_block:
                sub_blocks.append(current_block)
                current_block = []
            sub_blocks.append(None)  # None 表示通配符
        else:
            current_block.append(line)

    if current_block:
        sub_blocks.append(current_block)

    # 在 content_lines 中顺序匹配每个子块
    def _match_from(pos: int, block_idx: int) -> int | None:
        if block_idx >= len(sub_blocks):
            return pos

        block = sub_blocks[block_idx]
        if block is None:
            # 通配符 — 尝试跳过 0 到所有剩余行
            for skip in range(len(content_lines) - pos + 1):
                result = _match_from(pos + skip, block_idx + 1)
                if result is not None:
                    return result
            return None

        # 精确匹配子块
        block_len = len(block)
        if pos + block_len > len(content_lines):
            return None

        if content_lines[pos:pos + block_len] == block:
            return _match_from(pos + block_len, block_idx + 1)

        return None

    # 尝试从每个位置开始匹配
    for start in range(len(content_lines) + 1):
        end = _match_from(start, 0)
        if end is not None:
            # 计算匹配的总行数（包括通配符匹配的行）
            remaining = content_lines[:start] + content_lines[end:]
            return ''.join(remaining)

    return None


def find_similar_lines(
    search_text: str,
    content: str,
    threshold: float = 0.6,
) -> str:
    """查找与搜索文本最相似的代码行（用于错误提示）

    参数:
        search_text: 搜索文本
        content: 文件内容
        threshold: 最小相似度阈值

    返回:
        格式化的相似行建议
    """
    search_lines = [l.strip() for l in search_text.splitlines() if l.strip()]
    content_lines = [l.strip() for l in content.splitlines() if l.strip()]

    if not search_lines or not content_lines:
        return ''

    # 对每个搜索行找最相似的内容行
    suggestions: list[str] = []
    for sl in search_lines[:3]:  # 最多检查前3行
        best_ratio = 0
        best_line = ''
        for cl in content_lines:
            ratio = difflib.SequenceMatcher(None, sl, cl).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_line = cl

        if best_ratio >= threshold:
            suggestions.append(f'  ~ {best_line} (similarity: {best_ratio:.0%})')

    if suggestions:
        return '\n'.join(suggestions)

    return ''


# ==================== 工具函数 ====================

def count_edit_blocks(text: str) -> int:
    """统计文本中 SEARCH/REPLACE 块的数量

    参数:
        text: LLM 响应文本

    返回:
        SEARCH 标记的数量
    """
    return len(re.findall(HEAD, text, re.MULTILINE))


def extract_shell_commands(text: str) -> list[str]:
    """从文本中提取 shell 命令块

    参数:
        text: LLM 响应文本

    返回:
        shell 命令列表
    """
    commands: list[str] = []
    for item in find_original_update_blocks(text):
        if item[0] is None and len(item) == 2:
            commands.append(item[1].strip())
    return commands


def validate_edit_blocks(text: str) -> tuple[bool, str]:
    """验证 SEARCH/REPLACE 块的完整性

    参数:
        text: LLM 响应文本

    返回:
        (是否有效, 错误描述)
    """
    search_count = len(re.findall(HEAD, text, re.MULTILINE))
    divider_count = len(re.findall(DIVIDER, text, re.MULTILINE))
    updated_count = len(re.findall(UPDATED, text, re.MULTILINE))

    if search_count == 0:
        return True, ''

    if divider_count < search_count:
        return False, f'缺少 {search_count - divider_count} 个 ======= 分隔符'

    if updated_count < search_count:
        return False, f'缺少 {search_count - updated_count} 个 >>>>>>> REPLACE 结束标记'

    return True, ''

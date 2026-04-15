"""Fuzzy Matcher — 多级模糊匹配引擎

借鉴 Aider 的 editblock_coder.py，实现:
1. perfect_replace() - 精确匹配
2. replace_part_with_missing_leading_whitespace() - 空白容错
3. try_dotdotdots() - ... 省略语法
4. replace_closest_edit_distance() - 编辑距离模糊匹配

这是代码编辑成功率的关键模块，处理 LLM 输出的格式偏差。
"""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher


def prep(content: str) -> tuple[str, list[str]]:
    """预处理内容

    确保内容以换行结尾，并分割为行列表。
    """
    if content and not content.endswith("\n"):
        content += "\n"
    lines = content.splitlines(keepends=True)
    return content, lines


def perfect_replace(
    whole_lines: list[str],
    part_lines: list[str],
    replace_lines: list[str],
) -> str | None:
    """精确匹配替换

    在 whole_lines 中精确查找 part_lines，替换为 replace_lines。

    Returns:
        替换后的完整内容，如果未找到则返回 None
    """
    part_tup = tuple(part_lines)
    part_len = len(part_lines)

    for i in range(len(whole_lines) - part_len + 1):
        whole_tup = tuple(whole_lines[i : i + part_len])
        if part_tup == whole_tup:
            res = whole_lines[:i] + replace_lines + whole_lines[i + part_len :]
            return "".join(res)
    return None


def perfect_or_whitespace(
    whole_lines: list[str],
    part_lines: list[str],
    replace_lines: list[str],
) -> tuple[str | None, str]:
    """尝试精确匹配，失败后尝试空白容错匹配

    Returns:
        (result, match_type) - result 为替换后内容，match_type 为匹配类型
    """
    # 尝试精确匹配
    res = perfect_replace(whole_lines, part_lines, replace_lines)
    if res:
        return res, "exact"

    # 尝试空白容错匹配
    res = replace_part_with_missing_leading_whitespace(
        whole_lines, part_lines, replace_lines
    )
    if res:
        return res, "whitespace_flex"

    return None, "none"


def replace_most_similar_chunk(
    whole: str,
    part: str,
    replace: str,
) -> tuple[str | None, str]:
    """最佳努力匹配替换

    按优先级尝试多种匹配策略:
    1. 精确匹配
    2. 空白容错匹配
    3. 跳过开头的空行
    4. ... 省略语法
    5. 编辑距离模糊匹配

    借鉴 Aider 的 replace_most_similar_chunk() 函数。

    Args:
        whole: 完整文件内容
        part: 要查找的内容 (SEARCH)
        replace: 替换内容 (REPLACE)

    Returns:
        (result, match_type) - result 为替换后内容，match_type 为匹配类型
    """
    whole, whole_lines = prep(whole)
    part, part_lines = prep(part)
    replace, replace_lines = prep(replace)

    # 1. 尝试精确或空白容错匹配
    res, match_type = perfect_or_whitespace(whole_lines, part_lines, replace_lines)
    if res:
        return res, match_type

    # 2. 跳过开头的空行 (LLM 有时会多输出空行)
    if len(part_lines) > 2 and not part_lines[0].strip():
        skip_blank_part_lines = part_lines[1:]
        res, match_type = perfect_or_whitespace(
            whole_lines, skip_blank_part_lines, replace_lines
        )
        if res:
            return res, match_type

    # 3. 尝试 ... 省略语法
    try:
        res = try_dotdotdots(whole, part, replace)
        if res:
            return res, "dotdotdot"
    except ValueError:
        pass

    # 4. 尝试编辑距离模糊匹配
    res = replace_closest_edit_distance(whole_lines, part, part_lines, replace_lines)
    if res:
        return res, "fuzzy"

    return None, "none"


def try_dotdotdots(whole: str, part: str, replace: str) -> str | None:
    """处理 ... 省略语法

    当 SEARCH/REPLACE 块包含 ... 时，只匹配前后部分。
    """
    if "..." not in part:
        return None


    # 1. 将 part 分割
    parts = part.split("...")
    if len(parts) < 2:
        return None

    # 2. 构建非贪婪匹配正则
    # 处理每一部分的转义，并去除两端空白以增加匹配成功率
    escaped_parts = []
    for p in parts:
        stripped = p.strip()
        if stripped:
            escaped_parts.append(re.escape(stripped))
        else:
            # 如果是空字符串（... 在开头或结尾，或者连续 ...），匹配空白
            escaped_parts.append(r"")

    # 构建正则：part1[\s\S]*?part2...
    # 我们使用 \s* 来容忍换行和缩进
    pattern_str = r"[\s\S]*?".join(escaped_parts)

    # 查找所有匹配
    matches = list(re.finditer(pattern_str, whole))
    if len(matches) != 1:
        # 如果没有匹配或多个匹配，为了安全返回 None
        return None

    match = matches[0]

    # 3. 执行替换
    # 如果 replace 包含 ...，目前暂不支持复杂填充
    if "..." in replace:
        return None

    return whole[:match.start()] + replace + whole[match.end():]


def replace_part_with_missing_leading_whitespace(
    whole_lines: list[str],
    part_lines: list[str],
    replace_lines: list[str],
) -> str | None:
    """空白容错匹配

    GPT 经常搞错缩进。这个函数尝试找到内容相同但缩进不同的匹配。

    借鉴 Aider 的 replace_part_with_missing_leading_whitespace() 函数。
    """
    # 计算最小缩进
    leading = [
        len(p) - len(p.lstrip()) for p in part_lines if p.strip()
    ] + [
        len(p) - len(p.lstrip()) for p in replace_lines if p.strip()
    ]

    if leading and min(leading):
        num_leading = min(leading)
        part_lines = [p[num_leading:] if p.strip() else p for p in part_lines]
        replace_lines = [p[num_leading:] if p.strip() else p for p in replace_lines]

    # 尝试找到忽略缩进的匹配
    num_part_lines = len(part_lines)

    for i in range(len(whole_lines) - num_part_lines + 1):
        add_leading = match_but_for_leading_whitespace(
            whole_lines[i : i + num_part_lines], part_lines
        )

        if add_leading is None:
            continue

        # 添加正确的缩进到替换内容
        replace_lines = [
            add_leading + rline if rline.strip() else rline
            for rline in replace_lines
        ]
        whole_lines = whole_lines[:i] + replace_lines + whole_lines[i + num_part_lines :]
        return "".join(whole_lines)

    return None


def match_but_for_leading_whitespace(
    whole_lines: list[str],
    part_lines: list[str],
) -> str | None:
    """检查去除缩进后是否匹配

    Returns:
        需要添加的前导空白，如果不匹配则返回 None
    """
    num = len(whole_lines)

    # 检查去除空白后的内容是否相同
    if not all(
        whole_lines[i].lstrip() == part_lines[i].lstrip() for i in range(num)
    ):
        return None

    # 检查所有行的缩进差异是否一致
    add = set(
        whole_lines[i][: len(whole_lines[i]) - len(part_lines[i])]
        for i in range(num)
        if whole_lines[i].strip()
    )

    if len(add) != 1:
        return None

    return add.pop()


def replace_closest_edit_distance(
    whole_lines: list[str],
    part: str,
    part_lines: list[str],
    replace_lines: list[str],
    similarity_thresh: float = 0.8,
) -> str | None:
    """基于编辑距离的模糊匹配

    使用 SequenceMatcher 计算相似度，找到最接近的块。

    借鉴 Aider 的 replace_closest_edit_distance() 函数。
    """
    max_similarity = 0
    most_similar_chunk_start = -1
    most_similar_chunk_end = -1

    # 允许 ±10% 的长度差异
    scale = 0.1
    min_len = math.floor(len(part_lines) * (1 - scale))
    max_len = math.ceil(len(part_lines) * (1 + scale))

    for length in range(min_len, max_len + 1):
        for i in range(len(whole_lines) - length + 1):
            chunk = whole_lines[i : i + length]
            chunk = "".join(chunk)

            similarity = SequenceMatcher(None, chunk, part).ratio()

            if similarity > max_similarity:
                max_similarity = similarity
                most_similar_chunk_start = i
                most_similar_chunk_end = i + length

    if max_similarity < similarity_thresh:
        return None

    modified_whole = (
        whole_lines[:most_similar_chunk_start]
        + replace_lines
        + whole_lines[most_similar_chunk_end:]
    )
    return "".join(modified_whole)


def find_similar_lines(
    search_lines: str,
    content_lines: str,
    threshold: float = 0.6,
) -> str:
    """查找相似行，用于错误提示

    当匹配失败时，找到最相似的代码块，帮助用户理解问题。

    借鉴 Aider 的 find_similar_lines() 函数。
    """
    search_lines_list = search_lines.splitlines()
    content_lines_list = content_lines.splitlines()

    best_ratio = 0
    best_match = None
    best_match_i = 0

    for i in range(len(content_lines_list) - len(search_lines_list) + 1):
        chunk = content_lines_list[i : i + len(search_lines_list)]
        ratio = SequenceMatcher(None, search_lines_list, chunk).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = chunk
            best_match_i = i

    if best_ratio < threshold:
        return ""

    # 如果首尾行匹配，直接返回
    if best_match[0] == search_lines_list[0] and best_match[-1] == search_lines_list[-1]:
        return "\n".join(best_match)

    # 返回匹配块及其上下文
    N = 5
    best_match_end = min(len(content_lines_list), best_match_i + len(search_lines_list) + N)
    best_match_i = max(0, best_match_i - N)

    best = content_lines_list[best_match_i:best_match_end]
    return "\n".join(best)


def compute_similarity(text1: str, text2: str) -> float:
    """计算两段文本的相似度"""
    return SequenceMatcher(None, text1, text2).ratio()

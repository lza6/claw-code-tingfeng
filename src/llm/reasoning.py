"""Reasoning Tags - 思维链标签处理 — 从 Aider reasoning_tags.py 移植

支持处理 LLM 的思维链（thinking/reasoning）内容标签。

用法:
    from src.llm.reasoning import (
        remove_reasoning_content,
        replace_reasoning_tags,
        format_reasoning_content,
        REASONING_TAG,
    )

    # 移除思维链内容
    clean_text = remove_reasoning_content(response, REASONING_TAG)

    # 替换标签为标准格式
    formatted = replace_reasoning_tags(text, REASONING_TAG)

    # 格式化思维链内容
    tagged = format_reasoning_content(thinking, REASONING_TAG)
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 标准标签标识符
REASONING_TAG = "thinking-content-" + "7bbeb8e1441453ad999a0bbba8a46d4b"

# 输出格式
REASONING_START = "--------------\n► **THINKING**"
REASONING_END = "------------\n► **ANSWER**"

# 常见的思维链标签别名
REASONING_TAG_ALIASES = [
    REASONING_TAG,
    "thinking",
    "thought",
    "reasoning",
    "chain-of-thought",
    "cot",
    "think",
]


def remove_reasoning_content(text: str, reasoning_tag: str | None = None) -> str:
    """从文本中移除思维链内容

    参数:
        text: 要处理的文本
        reasoning_tag: 要移除的标签名称，如果为 None 则尝试所有已知标签

    返回:
        移除思维链内容后的文本
    """
    if not text:
        return text

    if reasoning_tag:
        return _remove_tag(text, reasoning_tag)

    # 尝试移除所有已知的思维链标签
    result = text
    for tag in REASONING_TAG_ALIASES:
        result = _remove_tag(result, tag)

    return result


def _remove_tag(text: str, tag: str) -> str:
    """移除特定标签的内容"""
    if not tag:
        return text

    # 尝试匹配完整的标签模式
    pattern = f"<{tag}>.*?</{tag}>"
    result = re.sub(pattern, "", text, flags=re.DOTALL).strip()

    # 如果存在闭合标签但可能缺少开始标签，移除闭合标签之前的内容
    closing_tag = f"</{tag}>"
    if closing_tag in result:
        parts = result.split(closing_tag, 1)
        result = parts[1].strip() if len(parts) > 1 else result

    return result


def replace_reasoning_tags(text: str, tag_name: str) -> str:
    """将思维链标签替换为标准格式

    确保在 START 和 END 标记前恰好有一个空行。

    参数:
        text: 包含标签的文本
        tag_name: 要替换的标签名称

    返回:
        替换为标准格式后的文本
    """
    if not text:
        return text

    # 替换开始标签，确保正确的间距
    text = re.sub(f"\\s*<{tag_name}>\\s*", f"\n{REASONING_START}\n\n", text)

    # 替换结束标签，确保正确的间距
    text = re.sub(f"\\s*</{tag_name}>\\s*", f"\n\n{REASONING_END}\n\n", text)

    return text


def format_reasoning_content(reasoning_content: str, tag_name: str) -> str:
    """用适当的标签格式化思维链内容

    参数:
        reasoning_content: 要格式化的内容
        tag_name: 要使用的标签名称

    返回:
        带有标签的格式化思维链内容
    """
    if not reasoning_content:
        return ""

    formatted = f"<{tag_name}>\n\n{reasoning_content}\n\n</{tag_name}>"
    return formatted


def extract_reasoning_content(text: str, tag_name: str | None = None) -> str:
    """从文本中提取思维链内容

    参数:
        text: 包含思维链标签的文本
        tag_name: 要提取的标签名称，如果为 None 则尝试所有已知标签

    返回:
        提取的思维链内容，如果没有找到则返回空字符串
    """
    if not text:
        return ""

    if tag_name:
        return _extract_tag_content(text, tag_name)

    # 尝试提取所有已知的思维链标签
    for tag in REASONING_TAG_ALIASES:
        content = _extract_tag_content(text, tag)
        if content:
            return content

    return ""


def _extract_tag_content(text: str, tag: str) -> str:
    """提取特定标签的内容"""
    if not tag:
        return ""

    pattern = f"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, flags=re.DOTALL)

    if match:
        return match.group(1).strip()

    return ""


def has_reasoning_content(text: str) -> bool:
    """检查文本是否包含思维链内容

    参数:
        text: 要检查的文本

    返回:
        如果包含任何思维链标签则返回 True
    """
    if not text:
        return False

    return any(f"<{tag}>" in text or f"</{tag}>" in text for tag in REASONING_TAG_ALIASES)


def split_reasoning_and_answer(text: str) -> tuple[str, str]:
    """将文本分割为思维链和答案部分

    参数:
        text: 包含思维链标签的文本

    返回:
        (思维链内容, 答案内容) 的元组
    """
    reasoning = extract_reasoning_content(text)
    answer = remove_reasoning_content(text)

    return reasoning, answer


def normalize_reasoning_tags(text: str) -> str:
    """规范化文本中的思维链标签

    将所有已知的思维链标签别名替换为标准标签。

    参数:
        text: 要规范化的文本

    返回:
        规范化后的文本
    """
    if not text:
        return text

    result = text

    # 替换所有已知的标签别名为标准标签
    for tag in REASONING_TAG_ALIASES:
        if tag != REASONING_TAG:
            result = result.replace(f"<{tag}>", f"<{REASONING_TAG}>")
            result = result.replace(f"</{tag}>", f"</{REASONING_TAG}>")

    return result


def get_reasoning_stats(text: str) -> dict[str, int]:
    """获取思维链内容的统计信息

    参数:
        text: 要分析的文本

    返回:
        包含统计信息的字典:
        - has_reasoning: 是否包含思维链
        - reasoning_length: 思维链内容长度
        - answer_length: 答案内容长度
        - total_length: 总长度
    """
    reasoning, answer = split_reasoning_and_answer(text)

    return {
        'has_reasoning': bool(reasoning),
        'reasoning_length': len(reasoning),
        'answer_length': len(answer),
        'total_length': len(text),
    }

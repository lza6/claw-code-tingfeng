"""Prompt 模板集合 — 从 Aider prompts.py 移植增强

提供各类任务的专业提示词模板：
- Commit message 生成
- Chat 历史摘要
- Diff 分析
- 代码审查
"""
from __future__ import annotations

# ==================== Commit Message Prompt ====================

COMMIT_SYSTEM_PROMPT = """你是一个 commit message 生成专家。
根据 git diff 生成符合 conventional commits 规范的简洁 commit message。"""

COMMIT_USER_TEMPLATE = """请为以下 diff 生成 commit message：

要求：
1. 使用 conventional commit 格式: type(scope): description
2. type 可选: feat, fix, refactor, docs, test, chore, style, perf, ci, build
3. 第一行不超过 72 个字符
4. 不要包含 diff 统计信息（如 "3 files changed"）
5. 用英文编写
6. 如果有 breaking changes，使用 "!" 标记

{diff_content}

如果 diff 很大，只关注最重要的变更。"""


def make_commit_prompt(diff_text: str, max_length: int = 3000) -> list[dict[str, str]]:
    """生成 commit message 的 prompt"""
    truncated = diff_text[:max_length] if len(diff_text) > max_length else diff_text
    return [
        {"role": "system", "content": COMMIT_SYSTEM_PROMPT},
        {"role": "user", "content": COMMIT_USER_TEMPLATE.format(diff_content=truncated)},
    ]


# ==================== Summarize Prompt ====================

SUMMARIZE_SYSTEM_PROMPT = """你是一个对话摘要专家。
将以下对话历史压缩为精炼的摘要，保留关键信息。"""

SUMMARIZE_USER_TEMPLATE = """请将以下对话历史压缩为摘要：

保留：
- 任务进度和目标
- 关键发现和结论
- 文件路径和重要参数
- 决策和后续步骤

丢弃：
- 冗余的工具输出
- 中间推理过程
- 重复的确认信息

对话历史：
{history_text}

输出格式：
<summary>
[压缩后的摘要]
</summary>"""


def make_summarize_prompt(history_text: str, max_length: int = 4000) -> list[dict[str, str]]:
    """生成摘要的 prompt"""
    truncated = history_text[:max_length] if len(history_text) > max_length else history_text
    return [
        {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
        {"role": "user", "content": SUMMARIZE_USER_TEMPLATE.format(history_text=truncated)},
    ]


# ==================== Diff Analysis Prompt ====================

DIFF_ANALYSIS_SYSTEM_PROMPT = """你是一个代码审查专家。
分析 git diff，识别潜在的代码问题和改进点。"""

DIFF_ANALYSIS_USER_TEMPLATE = """请分析以下 diff，识别：

1. 语法或逻辑错误
2. 潜在的安全问题
3. 性能问题
4. 代码风格不一致
5. 缺失的错误处理
6. 可能的边界问题

{diff_content}

输出格式（如果没问题返回 "No issues found"）：
## Issues Found

### [问题类型]
- **位置**: [文件:行号]
- **描述**: [问题描述]
- **建议**: [修复建议]"""


def make_diff_analysis_prompt(diff_text: str, max_length: int = 5000) -> list[dict[str, str]]:
    """生成 diff 分析的 prompt"""
    truncated = diff_text[:max_length] if len(diff_text) > max_length else diff_text
    return [
        {"role": "system", "content": DIFF_ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": DIFF_ANALYSIS_USER_TEMPLATE.format(diff_content=truncated)},
    ]


# ==================== Error Classification Prompt ====================

ERROR_CLASSIFY_SYSTEM_PROMPT = """你是一个错误分类专家。
分析错误信息并分类，提供修复建议。"""

ERROR_CLASSIFY_USER_TEMPLATE = """请分析以下错误信息：

{error_text}

返回 JSON 格式：
{{
    "category": "syntax|runtime|import|type|config|network|permission|unknown",
    "severity": "low|medium|high|critical",
    "suggestion": "修复建议（一句话）",
    "root_cause": "可能的原因（一句话）"
}}"""

# ==================== Code Review Prompt ====================

CODE_REVIEW_SYSTEM_PROMPT = """你是一个高级代码审查专家。
审查代码变更，提供建设性的反馈。"""

CODE_REVIEW_USER_TEMPLATE = """请审查以下代码变更：

Files changed: {files}

{diff_content}

请从以下角度审查：
1. **正确性**: 代码逻辑是否正确？
2. **可读性**: 代码是否易于理解？
3. **安全性**: 是否有安全漏洞？
4. **性能**: 是否有性能问题？
5. **测试**: 是否有适当的测试覆盖？

输出格式：
## Review Summary

### Strengths
- [优点列表]

### Issues
- [问题列表，按严重程度排序]

### Suggestions
- [改进建议]"""


def make_code_review_prompt(files: list[str], diff_text: str) -> list[dict[str, str]]:
    """生成代码审查的 prompt"""
    files_str = "\n".join(f"- {f}" for f in files)
    return [
        {"role": "system", "content": CODE_REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": CODE_REVIEW_USER_TEMPLATE.format(
            files=files_str,
            diff_content=diff_text[:5000],
        )},
    ]


# ==================== File Rename Prompt ====================

FILE_RENAME_SYSTEM_PROMPT = """你是一个文件命名专家。
根据文件内容建议合适的文件名。"""

FILE_RENAME_USER_TEMPLATE = """根据以下文件内容，建议一个合适的文件名：

文件名应该：
1. 反映文件的主要功能
2. 使用 snake_case 命名
3. 简洁明了（不超过 50 字符）
4. 使用英文

文件内容摘要：
{content_summary}

输出：仅返回文件名（不含路径和扩展名）"""


def make_file_rename_prompt(content_summary: str) -> list[dict[str, str]]:
    """生成文件重命名的 prompt"""
    return [
        {"role": "system", "content": FILE_RENAME_SYSTEM_PROMPT},
        {"role": "user", "content": FILE_RENAME_USER_TEMPLATE.format(content_summary=content_summary[:500])},
    ]


# ==================== Tag Extract Prompt ====================

TAG_EXTRACT_SYSTEM_PROMPT = """你是一个标签提取专家。
从文本中提取关键标签。"""

TAG_EXTRACT_USER_TEMPLATE = """从以下文本中提取关键标签（最多 5 个）：

{text}

标签应该：
1. 反映文本的核心主题
2. 使用英文
3. 简洁（单词或短短语）

输出格式：tag1, tag2, tag3"""


def make_tag_extract_prompt(text: str, max_length: int = 1000) -> list[dict[str, str]]:
    """生成标签提取的 prompt"""
    truncated = text[:max_length] if len(text) > max_length else text
    return [
        {"role": "system", "content": TAG_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": TAG_EXTRACT_USER_TEMPLATE.format(text=truncated)},
    ]


# ==================== 便捷函数 ====================

def get_prompt_for_task(task_type: str, **kwargs) -> list[dict[str, str]]:
    """根据任务类型获取对应的 prompt

    Args:
        task_type: 任务类型
        **kwargs: 任务相关参数

    Returns:
        prompt 消息列表
    """
    prompts_map = {
        "commit_message": lambda: make_commit_prompt(kwargs.get("diff_text", "")),
        "chat_summarize": lambda: make_summarize_prompt(kwargs.get("history_text", "")),
        "diff_analysis": lambda: make_diff_analysis_prompt(kwargs.get("diff_text", "")),
        "error_classify": lambda: [
            {"role": "system", "content": ERROR_CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": ERROR_CLASSIFY_USER_TEMPLATE.format(error_text=kwargs.get("error_text", ""))},
        ],
        "code_review": lambda: make_code_review_prompt(
            kwargs.get("files", []),
            kwargs.get("diff_text", ""),
        ),
        "file_rename": lambda: make_file_rename_prompt(kwargs.get("content_summary", "")),
        "tag_extract": lambda: make_tag_extract_prompt(kwargs.get("text", "")),
    }

    prompt_fn = prompts_map.get(task_type)
    if prompt_fn:
        return prompt_fn()

    return []


__all__ = [
    "CODE_REVIEW_SYSTEM_PROMPT",
    "CODE_REVIEW_USER_TEMPLATE",
    "COMMIT_SYSTEM_PROMPT",
    "COMMIT_USER_TEMPLATE",
    "DIFF_ANALYSIS_SYSTEM_PROMPT",
    "DIFF_ANALYSIS_USER_TEMPLATE",
    # Error Classify
    "ERROR_CLASSIFY_SYSTEM_PROMPT",
    "ERROR_CLASSIFY_USER_TEMPLATE",
    "FILE_RENAME_SYSTEM_PROMPT",
    "FILE_RENAME_USER_TEMPLATE",
    "SUMMARIZE_SYSTEM_PROMPT",
    "SUMMARIZE_USER_TEMPLATE",
    "TAG_EXTRACT_SYSTEM_PROMPT",
    "TAG_EXTRACT_USER_TEMPLATE",
    # Utility
    "get_prompt_for_task",
    # Code Review
    "make_code_review_prompt",
    # Commit
    "make_commit_prompt",
    # Diff Analysis
    "make_diff_analysis_prompt",
    # File Rename
    "make_file_rename_prompt",
    # Summarize
    "make_summarize_prompt",
    # Tag Extract
    "make_tag_extract_prompt",
]

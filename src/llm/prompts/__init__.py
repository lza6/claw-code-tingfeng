"""LLM Prompts — 集中式提示词管理

借鉴 Aider 的 *_prompts.py 模式，提供:
- 统一的提示词基类
- 可复用的示例对话
- 模型特定的提示词适配
- 任务专用提示词模板

使用:
    from src.llm.prompts import EditPrompts

    prompts = EditPrompts()
    system_message = prompts.get_system_message()
    example_messages = prompts.get_example_messages()

或使用任务提示词:
    from src.llm.prompts import make_commit_prompt, get_prompt_for_task

    prompt = make_commit_prompt(diff_text)
"""
from src.llm.prompts.base_prompts import BasePrompts, PromptSection
from src.llm.prompts.edit_prompts import EditPrompts
from src.llm.prompts.task_prompts import (
    get_prompt_for_task,
    make_code_review_prompt,
    make_commit_prompt,
    make_diff_analysis_prompt,
    make_file_rename_prompt,
    make_summarize_prompt,
    make_tag_extract_prompt,
)

__all__ = [
    "BasePrompts",
    "EditPrompts",
    "PromptSection",
    "get_prompt_for_task",
    "get_prompts_for_model",
    "make_code_review_prompt",
    # Task prompts
    "make_commit_prompt",
    "make_diff_analysis_prompt",
    "make_file_rename_prompt",
    "make_summarize_prompt",
    "make_tag_extract_prompt",
]


def get_prompts_for_model(model_name: str, edit_format: str = "editblock") -> BasePrompts:
    """根据模型和编辑格式获取对应的提示词

    Args:
        model_name: 模型名称
        edit_format: 编辑格式

    Returns:
        对应的 Prompts 实例
    """
    # 目前只有 EditPrompts
    return EditPrompts()

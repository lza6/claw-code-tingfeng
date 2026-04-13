"""Base Prompts — 提示词基类

提供统一的提示词结构和常用模板。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromptSection:
    """提示词片段"""
    content: str
    role: str = "system"
    priority: int = 0  # 用于排序
    optional: bool = False  # 是否可省略

    def to_message(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class BasePrompts:
    """提示词基类

    借鉴 Aider 的 CoderPrompts 结构:
    - main_system: 主系统提示
    - system_reminder: 系统提醒
    - example_messages: 示例对话
    - lazy_prompt: 防止懒惰生成的提示
    - overeager_prompt: 防止过度修改的提示
    """

    # 子类必须定义
    main_system: str = ""
    system_reminder: str = ""
    files_content_prefix: str = ""

    # 可选提示词
    lazy_prompt: str = """
Don't skip code! Always show the complete code for each edit, never use placeholders like `# rest of code remains the same` or `# ... existing code ...`.
"""

    overeager_prompt: str = """
Don't make changes beyond what was explicitly requested. Only modify the specific code that needs to change.
"""

    # 示例对话
    example_messages: list[dict[str, str]] = field(default_factory=list)

    def get_system_message(self) -> str:
        """获取完整的系统消息"""
        parts = [self.main_system]

        if self.system_reminder:
            parts.append("\n\n" + self.system_reminder)

        return "".join(parts)

    def get_example_messages(self) -> list[dict[str, str]]:
        """获取示例对话"""
        return self.example_messages

    def get_files_content_prefix(self, rel_fname: str) -> str:
        """获取文件内容前缀"""
        if self.files_content_prefix:
            return self.files_content_prefix.format(rel_fname=rel_fname)
        return f"Here is the current content of {rel_fname}:\n"

    def format_example_as_message(self) -> dict[str, str]:
        """将示例格式化为消息 (用于支持 examples_as_sys_msg 的模型)"""
        if not self.example_messages:
            return {}

        # 将示例合并为一个系统消息
        content = "Here are examples of the expected format:\n\n"
        for msg in self.example_messages:
            role = msg.get("role", "")
            text = msg.get("content", "")
            if role == "user":
                content += f"USER: {text}\n\n"
            elif role == "assistant":
                content += f"ASSISTANT: {text}\n\n"

        return {"role": "system", "content": content}


def format_code_block(code: str, language: str = "") -> str:
    """格式化代码块"""
    return f"```{language}\n{code}\n```\n"


def format_search_replace_block(
    filename: str,
    search_text: str,
    replace_text: str,
    language: str = "",
) -> str:
    """格式化 SEARCH/REPLACE 块"""
    return f"""{filename}
```{language}
<<<<<<< SEARCH
{search_text}=======
{replace_text}>>>>>>> REPLACE
```"""


# 常用提示词模板
CODING_PRINCIPLES = """
Follow these coding principles:
1. Write clean, readable, and maintainable code
2. Follow the existing code style and conventions
3. Add appropriate comments for complex logic
4. Handle errors gracefully
5. Consider edge cases
"""

THINKING_PROMPT = """
Before making any changes, think through:
1. What is the current state of the code?
2. What specifically needs to change?
3. What could go wrong?
4. How will this affect other parts of the codebase?
"""


# ==================== 从 Aider prompts.py 移植 ====================

# COMMIT - 提交消息提示词
COMMIT_SYSTEM_PROMPT = """You are an expert software engineer that generates concise, \
one-line Git commit messages based on the provided diffs.
Review the provided context and diffs which are about to be committed to a git repo.
Review the diffs carefully.
Generate a one-line commit message for those changes.
The commit message should be structured as follows: <type>: <description>
Use these for <type>: fix, feat, build, chore, ci, docs, style, refactor, perf, test

Ensure the commit message:
- Starts with the appropriate prefix.
- Is in the imperative mood (e.g., "add feature" not "added feature" or "adding feature").
- Does not exceed 72 characters.

Reply only with the one-line commit message, without any additional text, explanations, or line breaks.
"""

# UNDO - 撤销命令回复
UNDO_COMMAND_REPLY = (
    "I did `git reset --hard HEAD~1` to discard the last edits. Please wait for further "
    "instructions before attempting that change again. Feel free to ask relevant questions about "
    "why the changes were reverted."
)

# ADDED FILES - 添加文件通知
ADDED_FILES_REPLY = (
    "I added these files to the chat: {fnames}\nLet me know if there are others we should add."
)

# RUN OUTPUT - 命令输出展示
RUN_OUTPUT_TEMPLATE = """I ran this command:

{command}

And got this output:

{output}
"""

# SUMMARIZE - 聊天历史摘要
SUMMARIZE_PROMPT = """*Briefly* summarize this partial conversation about programming.
Include less detail about older parts and more detail about the most recent messages.
Start a new paragraph every time the topic changes!

This is only part of a longer conversation so *DO NOT* conclude the summary with language like "Finally, ...". Because the conversation continues after the summary.
The summary *MUST* include the function names, libraries, packages that are being discussed.
The summary *MUST* include the filenames that are being referenced by the assistant inside the ```...``` fenced code blocks!
The summaries *MUST NOT* include ```...``` fenced code blocks!

Phrase the summary with the USER in first person, telling the ASSISTANT about the conversation.
Write *as* the user.
The user should refer to the assistant as *you*.
Start the summary with "I asked you...".
"""

# Summary prefix
SUMMARY_PREFIX = "I spoke to you previously about a number of things.\n"


def format_commit_prompt(language: str = "English") -> str:
    """格式化提交消息提示词"""
    if language.lower() != "english":
        instruction = f"Write the commit message in {language}.\n"
    else:
        instruction = ""
    return COMMIT_SYSTEM_PROMPT.replace("{language_instruction}", instruction)


def format_run_output(command: str, output: str) -> str:
    """格式化命令输出"""
    return RUN_OUTPUT_TEMPLATE.format(command=command, output=output)


def format_added_files(fnames: list[str]) -> str:
    """格式化添加文件消息"""
    return ADDED_FILES_REPLY.format(fnames=", ".join(fnames))

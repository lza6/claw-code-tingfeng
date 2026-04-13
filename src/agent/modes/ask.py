"""Ask Mode — 纯问答模式（移植自 Aider ask_coder.py）

只回答问题不编辑代码，适合:
- 代码理解/解释
- 架构咨询
- 技术方案讨论

使用场景:
- 用户只想了解代码而不修改
- 培训/学习场景
- 代码审查讨论
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


ASK_SYSTEM_PROMPT = """你是一个专业的编程助手。用户会向你提问关于代码的问题。

**重要规则**:
- 只回答问题，不要执行任何文件修改操作
- 如果需要查看文件来回答问题，请说明需要哪些文件
- 给出清晰、准确、有深度的回答
- 如果不确定，明确说明"""


class AskMode:
    """纯问答模式 — 禁止文件修改

    用法:
        mode = AskMode(engine)
        answer = await mode.ask("这个项目的架构是怎样的?")
    """

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    async def ask(self, question: str, *, context: str = "") -> str:
        """提出问题并获取回答

        参数:
            question: 用户问题
            context: 可选的额外上下文

        返回:
            LLM 的回答文本
        """
        messages = [
            {"role": "system", "content": ASK_SYSTEM_PROMPT},
        ]

        if context:
            messages.append({"role": "user", "content": f"上下文:\n{context}\n\n问题: {question}"})
        else:
            messages.append({"role": "user", "content": question})

        response = await self.engine.llm_provider.chat(
            messages,
            max_tokens=4096,
        )

        return response.content

    async def ask_with_files(self, question: str, file_paths: list[str]) -> str:
        """携带文件内容提问

        参数:
            question: 用户问题
            file_paths: 相关文件路径列表

        返回:
            LLM 的回答文本
        """
        from pathlib import Path

        context_parts: list[str] = []
        for path in file_paths:
            file_path = Path(path)
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding='utf-8', errors='replace')[:20000]
                    context_parts.append(f"### {path}\n```\n{content}\n```")
                except Exception as e:
                    context_parts.append(f"### {path}\n(无法读取: {e})")
            else:
                context_parts.append(f"### {path}\n(文件不存在)")

        context = "\n\n".join(context_parts)
        return await self.ask(question, context=context)

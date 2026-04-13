"""ChatChunks — 结构化消息管理（从 Aider chat_chunks.py 移植）

将 LLM 消息按功能分组，便于:
- Token 计算和管理
- 消息优先级排序
- 压缩和摘要策略

消息分组:
- system: 系统提示
- examples: few-shot 示例
- done: 已完成的对话历史
- repo: 代码库上下文
- readonly_files: 只读文件内容
- chat_files: 可编辑文件内容
- cur: 当前轮次消息
- reminder: 提醒消息

使用:
chunks = ChatChunks()
chunks.system = [system_message]
chunks.repo = repo_messages
all_messages = chunks.all_messages()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatChunks:
    """结构化消息分组（从 Aider 移植）

    将消息按功能分组，支持灵活的 Token 管理和消息处理。

    属性:
        system: 系统提示消息
        examples: Few-shot 示例
        done: 已完成的历史对话（已压缩）
        repo: 代码库映射上下文
        readonly_files: 只读文件内容
        chat_files: 可编辑文件内容
        cur: 当前轮次消息
        reminder: 提醒/约束消息
    """

    system: list[Any] = field(default_factory=list)
    examples: list[Any] = field(default_factory=list)
    done: list[Any] = field(default_factory=list)
    repo: list[Any] = field(default_factory=list)
    readonly_files: list[Any] = field(default_factory=list)
    chat_files: list[Any] = field(default_factory=list)
    cur: list[Any] = field(default_factory=list)
    reminder: list[Any] = field(default_factory=list)

    def all_messages(self) -> list[Any]:
        """按顺序返回所有消息

        顺序: system → examples → done → repo → readonly_files → chat_files → cur → reminder

        返回:
            所有消息的扁平列表
        """
        messages: list[Any] = []
        messages.extend(self.system)
        messages.extend(self.examples)
        messages.extend(self.done)
        messages.extend(self.repo)
        messages.extend(self.readonly_files)
        messages.extend(self.chat_files)
        messages.extend(self.cur)
        messages.extend(self.reminder)
        return messages

    def messages_before_cur(self) -> list[Any]:
        """返回当前轮次之前的所有消息

        用于计算可用 Token 预算。

        返回:
            当前轮次之前的消息列表
        """
        messages: list[Any] = []
        messages.extend(self.system)
        messages.extend(self.examples)
        messages.extend(self.done)
        messages.extend(self.repo)
        messages.extend(self.readonly_files)
        messages.extend(self.chat_files)
        return messages

    def context_messages(self) -> list[Any]:
        """返回上下文消息（不含系统提示）

        用于 Token 计算和压缩决策。

        返回:
            上下文消息列表
        """
        messages: list[Any] = []
        messages.extend(self.repo)
        messages.extend(self.readonly_files)
        messages.extend(self.chat_files)
        return messages

    def clear_cur(self) -> None:
        """清空当前轮次消息"""
        self.cur = []

    def clear_reminder(self) -> None:
        """清空提醒消息"""
        self.reminder = []

    def add_user_message(self, content: str) -> None:
        """添加用户消息到当前轮次

        参数:
            content: 消息内容
        """
        self.cur.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        """添加助手消息到当前轮次

        参数:
            content: 消息内容
        """
        self.cur.append({"role": "assistant", "content": content})

    def move_cur_to_done(self) -> None:
        """将当前轮次消息移动到已完成历史

        在对话轮次完成后调用，将 cur 移动到 done。
        """
        self.done.extend(self.cur)
        self.cur = []

    def token_count(self, estimator: Any) -> int:
        """估算所有消息的 Token 数量

        参数:
            estimator: Token 计算器，需支持 count_tokens(messages) 方法

        返回:
            Token 数量估算值
        """
        total = 0
        messages = self.all_messages()

        if hasattr(estimator, 'count_tokens'):
            return estimator.count_tokens(messages)

        # 简单估算: 每条消息约 4 tokens + 内容长度 / 4
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    total += len(content) // 4 + 4
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and "text" in part:
                            total += len(part["text"]) // 4 + 2

        return total

    def summary(self) -> dict[str, int]:
        """返回各分组消息数量摘要

        返回:
            {分组名: 消息数量} 字典
        """
        return {
            "system": len(self.system),
            "examples": len(self.examples),
            "done": len(self.done),
            "repo": len(self.repo),
            "readonly_files": len(self.readonly_files),
            "chat_files": len(self.chat_files),
            "cur": len(self.cur),
            "reminder": len(self.reminder),
            "total": len(self.all_messages()),
        }

    def __repr__(self) -> str:
        summary = self.summary()
        return (
            f"ChatChunks("
            f"system={summary['system']}, "
            f"done={summary['done']}, "
            f"repo={summary['repo']}, "
            f"cur={summary['cur']}, "
            f"total={summary['total']})"
        )

    # ===== Aider 风格缓存控制 =====

    def add_cache_control_headers(self) -> None:
        """添加缓存控制头（借鉴 Aider）

        根据消息分组添加不同的缓存策略：
        - system/examples: 首次出现时标记
        - repo/readonly_files: 一起标记
        - chat_files: 总是标记
        """
        if self.examples:
            self._add_cache_control(self.examples)
        else:
            self._add_cache_control(self.system)

        if self.repo:
            # 同时标记 readonly_files 和 repo map
            self._add_cache_control(self.repo)
        else:
            # 否则只缓存 readonly_files
            self._add_cache_control(self.readonly_files)

        self._add_cache_control(self.chat_files)

    def _add_cache_control(self, messages: list[Any]) -> None:
        """为消息列表的最后一条添加缓存控制

        参数:
            messages: 消息列表
        """
        if not messages:
            return

        last_msg = messages[-1]
        content = last_msg.get("content")

        # 转换为标准格式
        if isinstance(content, str):
            content = {"type": "text", "text": content}

        # 添加缓存控制
        if isinstance(content, dict):
            content["cache_control"] = {"type": "ephemeral"}
            last_msg["content"] = [content]

    def cacheable_messages(self) -> list[Any]:
        """返回可缓存的消息（借鉴 Aider）

        从末尾向前查找，返回到第一个带缓存控制的消息为止的消息。
        用于计算上下文窗口优化。

        返回:
            可缓存的消息列表
        """
        messages = self.all_messages()
        for i, msg in enumerate(reversed(messages)):
            content = msg.get("content")
            if isinstance(content, list) and content[0].get("cache_control"):
                # 返回到这个位置之前的所有消息
                return messages[:len(messages) - i]
        return messages

    # ===== 分组 Token 统计 =====

    def token_count_by_group(self, estimator: Any) -> dict[str, int]:
        """按分组统计 Token 数量

        参数:
            estimator: Token 计算器，需支持 count_tokens(text) 方法

        返回:
            {分组名: token数量} 字典
        """
        result = {}

        if hasattr(estimator, 'count_tokens'):
            for group_name in ['system', 'examples', 'done', 'repo',
                               'readonly_files', 'chat_files', 'cur', 'reminder']:
                group_messages = getattr(self, group_name, [])
                if group_messages:
                    result[group_name] = estimator.count_tokens(group_messages)
        else:
            # 简单估算
            for group_name in ['system', 'examples', 'done', 'repo',
                               'readonly_files', 'chat_files', 'cur', 'reminder']:
                group_messages = getattr(self, group_name, [])
                total = 0
                for msg in group_messages:
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        total += len(content) // 4 + 4
                result[group_name] = total

        return result

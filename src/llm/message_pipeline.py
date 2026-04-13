"""LLM Message Pipeline — 消息预处理管道（借鉴 Onyx multi_llm.py）

设计目标:
    1. 工具调用内容转纯文本（避免格式错误）
    2. 修复 user/assistant 消息交替顺序（Bedrock/Mistral 要求）
    3. 统一内容序列化（字符串/list/None 处理）
    4. 检测工具调用历史（Anthropic thinking 兼容）

参考 Onyx 的以下函数:
    - _strip_tool_content_from_messages()
    - _fix_tool_user_message_ordering()
    - _prompt_contains_tool_call_history()
    - _normalize_content()

用法:
    from src.llm.message_pipeline import MessagePipeline

    pipeline = MessagePipeline()
    cleaned_messages = pipeline.clean(messages)
    messages = pipeline.fix_message_ordering(messages)
"""
from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


class MessagePipeline:
    """LLM 消息预处理管道

    处理消息中的各种边缘情况，确保符合各提供商的 API 要求。
    """

    # ------------------------------------------------------------------
    # 内容规范化（参考 Onyx _normalize_content）
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_content(raw: Any) -> str:
        """规范化消息内容字段为纯字符串

        Content 可以是:
        - 字符串
        - None
        - 内容块列表 [{"type": "text", "text": "..."}]
        - Pydantic 模型

        参考 Onyx _normalize_content()
        """
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, list):
            return "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in raw
            )
        # Pydantic 模型或其他对象
        if hasattr(raw, "model_dump"):
            return str(raw.model_dump().get("content", ""))
        return str(raw)

    # ------------------------------------------------------------------
    # 工具内容转纯文本（参考 Onyx _strip_tool_content_from_messages）
    # ------------------------------------------------------------------

    @staticmethod
    def strip_tool_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将工具相关消息转换为纯文本

        某些 API（如 Bedrock Converse）在有 toolUse/toolResult 内容块时
        必须提供 toolConfig。当请求不使用工具时，需要将工具相关历史
        转换为纯文本以避免 "toolConfig field must be defined" 错误。

        参考 Onyx _strip_tool_content_from_messages()
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            tool_calls = msg.get("tool_calls")

            if role == "assistant" and tool_calls:
                # 将结构化工具调用转换为文本表示
                tool_call_lines = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "unknown")
                    args = func.get("arguments", "{}")
                    tc_id = tc.get("id", "")
                    tool_call_lines.append(
                        f"[Tool Call] name={name} id={tc_id} args={args}"
                    )

                existing_content = MessagePipeline.normalize_content(msg.get("content"))
                parts = (
                    [existing_content, *tool_call_lines]
                    if existing_content
                    else tool_call_lines
                )
                new_msg = {
                    "role": "assistant",
                    "content": "\n".join(parts),
                }
                result.append(new_msg)

            elif role == "tool":
                # 将工具响应转换为用户消息（带文本内容）
                tool_call_id = msg.get("tool_call_id", "")
                content = MessagePipeline.normalize_content(msg.get("content"))
                tool_result_text = f"[Tool Result] id={tool_call_id}\n{content}"

                # 如果前一条消息也是转换的工具结果，合并以避免连续 user 消息
                if (
                    result
                    and result[-1]["role"] == "user"
                    and "[Tool Result]" in result[-1].get("content", "")
                ):
                    result[-1]["content"] += "\n\n" + tool_result_text
                else:
                    result.append({"role": "user", "content": tool_result_text})

            else:
                result.append(msg)

        return result

    # ------------------------------------------------------------------
    # 修复消息交替顺序（参考 Onyx _fix_tool_user_message_ordering）
    # ------------------------------------------------------------------

    @staticmethod
    def fix_message_ordering(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """在 tool 和 user 消息之间插入合成 assistant 消息

        某些模型（如 Azure 上的 Mistral）要求严格的消息交替顺序，
        user 消息不能紧跟在 tool 消息后面。此函数插入最小
        assistant 消息来桥接。

        参考 Onyx _fix_tool_user_message_ordering()
        """
        if len(messages) < 2:
            return messages

        result: list[dict[str, Any]] = [messages[0]]
        for msg in messages[1:]:
            prev_role = result[-1].get("role")
            curr_role = msg.get("role")

            # tool -> user 之间需要插入 assistant 消息
            if prev_role == "tool" and curr_role == "user":
                result.append({"role": "assistant", "content": "Noted. Continuing."})
            result.append(msg)

        return result

    # ------------------------------------------------------------------
    # 检测工具调用历史（参考 Onyx _prompt_contains_tool_call_history）
    # ------------------------------------------------------------------

    @staticmethod
    def contains_tool_history(messages: list[dict[str, Any]]) -> bool:
        """检查消息中是否包含工具调用历史

        当 Anthropic 的 extended thinking 启用时，API 要求每个
        assistant 消息以 thinking 块开始。由于我们不保存 thinking_blocks
        （它们带有无法重建的加密签名），当历史包含 prior tool-calling
        turns 时必须跳过 thinking 参数。

        参考 Onyx _prompt_contains_tool_call_history()
        """
        for msg in messages:
            if msg.get("role") == "tool":
                return True
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                return True
        return False

    # ------------------------------------------------------------------
    # 消息转字典（参考 Onyx _prompt_to_dicts）
    # ------------------------------------------------------------------

    @staticmethod
    def to_dicts(messages: list[Any]) -> list[dict[str, Any]]:
        """将 Pydantic 消息模型序列化为字典

        LiteLLM 期望消息是字典（带 .get() 方法），而不是 Pydantic 模型。

        参考 Onyx _prompt_to_dicts()
        """
        result = []
        for msg in messages:
            if hasattr(msg, "model_dump"):
                result.append(msg.model_dump(exclude_none=True))
            elif isinstance(msg, dict):
                result.append(msg)
            else:
                # 假设是字符串内容
                result.append({"role": "user", "content": str(msg)})
        return result

    # ------------------------------------------------------------------
    # 完整清洗管道
    # ------------------------------------------------------------------

    @staticmethod
    def clean(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """执行完整的消息清洗管道

        顺序:
        1. 工具内容转纯文本
        2. 修复消息交替顺序

        Args:
            messages: 原始消息列表

        Returns:
            清洗后的消息列表
        """
        if not messages:
            return messages

        result = MessagePipeline.strip_tool_content(messages)
        result = MessagePipeline.fix_message_ordering(result)
        return result


# ---------------------------------------------------------------------------
# 便捷函数（模块级 API）
# ---------------------------------------------------------------------------

def normalize_content(raw: Any) -> str:
    """便捷函数: 规范化内容"""
    return MessagePipeline.normalize_content(raw)


def strip_tool_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """便捷函数: 工具内容转纯文本"""
    return MessagePipeline.strip_tool_content(messages)


def fix_message_ordering(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """便捷函数: 修复消息交替顺序"""
    return MessagePipeline.fix_message_ordering(messages)


def contains_tool_history(messages: list[dict[str, Any]]) -> bool:
    """便捷函数: 检测工具调用历史"""
    return MessagePipeline.contains_tool_history(messages)


def clean_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """便捷函数: 完整清洗管道"""
    return MessagePipeline.clean(messages)


__all__ = [
    "MessagePipeline",
    "clean_messages",
    "contains_tool_history",
    "fix_message_ordering",
    "normalize_content",
    "strip_tool_content",
]

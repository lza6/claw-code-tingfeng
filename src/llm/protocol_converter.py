"""
协议转换层 - 整合自 New-API
支持 OpenAI/Claude/Gemini 等格式互相转换
"""

from typing import Any

from loguru import logger


class ProtocolConverter:
    """
    协议转换器（整合自 New-API 的协议转换层）

    支持格式:
    - OpenAI (Chat Completions)
    - Anthropic (Claude Messages API)
    - Google Gemini
    """

    @staticmethod
    def openai_to_claude(
        openai_request: dict[str, Any]
    ) -> dict[str, Any]:
        """
        OpenAI 格式转 Claude 格式 (支持 Tool Calls 和多模态)
        """
        messages = openai_request.get("messages", [])
        system_message = None
        claude_messages = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls")

            if role == "system":
                system_message = content
            elif role == "user":
                claude_messages.append({"role": "user", "content": content})
            elif role == "assistant":
                if tool_calls:
                    content_blocks = []
                    if content:
                        content_blocks.append({"type": "text", "text": content})
                    for tc in tool_calls:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id"),
                            "name": tc.get("function", {}).get("name"),
                            "input": __import__('json').loads(tc.get("function", {}).get("arguments", "{}"))
                        })
                    claude_messages.append({"role": "assistant", "content": content_blocks})
                else:
                    claude_messages.append({"role": "assistant", "content": content})
            elif role == "tool":
                claude_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id"),
                        "content": content
                    }]
                })

        claude_request = {
            "messages": claude_messages,
            "max_tokens": openai_request.get("max_tokens", 4096),
        }
        if system_message:
            claude_request["system"] = system_message

        # 映射其他参数
        for param in ["temperature", "top_p", "stream"]:
            if param in openai_request:
                claude_request[param] = openai_request[param]

        return claude_request

    @staticmethod
    def claude_to_openai(
        claude_response: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Claude 响应转 OpenAI 响应格式 (支持 Tool Use)
        """
        content = ""
        tool_calls = []

        if "content" in claude_response:
            for item in claude_response["content"]:
                if item.get("type") == "text":
                    content += item.get("text", "")
                elif item.get("type") == "tool_use":
                    tool_calls.append({
                        "id": item.get("id"),
                        "type": "function",
                        "function": {
                            "name": item.get("name"),
                            "arguments": __import__('json').dumps(item.get("input"))
                        }
                    })

        openai_response = {
            "id": claude_response.get("id", "claude-msg"),
            "object": "chat.completion",
            "created": int(__import__('time').time()),
            "model": claude_response.get("model", "claude-3"),
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content or None,
                },
                "finish_reason": "tool_calls" if tool_calls else "stop"
            }],
            "usage": {
                "prompt_tokens": claude_response.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": claude_response.get("usage", {}).get("output_tokens", 0),
                "total_tokens": claude_response.get("usage", {}).get("input_tokens", 0) + claude_response.get("usage", {}).get("output_tokens", 0)
            }
        }

        if tool_calls:
            openai_response["choices"][0]["message"]["tool_calls"] = tool_calls

        return openai_response

    @staticmethod
    def openai_to_gemini(
        openai_request: dict[str, Any]
    ) -> dict[str, Any]:
        """
        OpenAI 格式转 Gemini 格式

        Args:
            openai_request: OpenAI 格式请求

        Returns:
            Dict: Gemini 格式请求
        """
        messages = openai_request.get("messages", [])

        # 转换为 Gemini 格式
        contents = []
        system_instruction = None

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                system_instruction = {"parts": [{"text": content}]}
            elif role == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": content}]
                })
            elif role == "assistant":
                contents.append({
                    "role": "model",
                    "parts": [{"text": content}]
                })

        gemini_request = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": openai_request.get("max_tokens", 4096),
            }
        }

        if system_instruction:
            gemini_request["system_instruction"] = system_instruction

        if "temperature" in openai_request:
            gemini_request["generationConfig"]["temperature"] = openai_request["temperature"]

        if "top_p" in openai_request:
            gemini_request["generationConfig"]["topP"] = openai_request["top_p"]

        return gemini_request

    @staticmethod
    def gemini_to_openai(
        gemini_response: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Gemini 响应转 OpenAI 响应格式

        Args:
            gemini_response: Gemini 格式响应

        Returns:
            Dict: OpenAI 格式响应
        """
        content = ""
        if gemini_response.get("candidates"):
            candidate = gemini_response["candidates"][0]
            if candidate.get("content", {}).get("parts"):
                content = candidate["content"]["parts"][0].get("text", "")

        # 构建 OpenAI 响应
        openai_response = {
            "id": "gemini-xxx",
            "object": "chat.completion",
            "created": int(__import__('time').time()),
            "model": "gemini-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": gemini_response.get("candidates", [{}])[0].get("finishReason", "stop"),
                }
            ],
            "usage": {
                "prompt_tokens": gemini_response.get("usageMetadata", {}).get("promptTokenCount", 0),
                "completion_tokens": gemini_response.get("usageMetadata", {}).get("candidatesTokenCount", 0),
                "total_tokens": gemini_response.get("usageMetadata", {}).get("totalTokenCount", 0),
            },
        }

        return openai_response

    @staticmethod
    def normalize_request(
        request: dict[str, Any],
        target_provider: str
    ) -> dict[str, Any]:
        """
        标准化请求到目标提供商格式

        Args:
            request: 原始请求（假设是 OpenAI 格式）
            target_provider: 目标提供商 (openai/claude/gemini)

        Returns:
            Dict: 转换后的请求
        """
        provider = target_provider.lower()

        if provider == "openai":
            return request  # 已经是 OpenAI 格式
        elif provider == "claude" or "claude" in provider:
            return ProtocolConverter.openai_to_claude(request)
        elif provider == "gemini" or "gemini" in provider:
            return ProtocolConverter.openai_to_gemini(request)
        else:
            logger.warning(f"未知提供商: {target_provider}，使用原始格式")
            return request

    @staticmethod
    def normalize_response(
        response: dict[str, Any],
        source_provider: str
    ) -> dict[str, Any]:
        """
        标准化响应到 OpenAI 格式

        Args:
            response: 原始响应
            source_provider: 源提供商 (openai/claude/gemini)

        Returns:
            Dict: OpenAI 格式响应
        """
        provider = source_provider.lower()

        if provider == "openai":
            return response  # 已经是 OpenAI 格式
        elif provider == "claude" or "claude" in provider:
            return ProtocolConverter.claude_to_openai(response)
        elif provider == "gemini" or "gemini" in provider:
            return ProtocolConverter.gemini_to_openai(response)
        else:
            logger.warning(f"未知提供商: {source_provider}，返回原始响应")
            return response


# 便捷函数
def convert_request(request: dict[str, Any], target: str) -> dict[str, Any]:
    """转换请求格式"""
    return ProtocolConverter.normalize_request(request, target)


def convert_response(response: dict[str, Any], source: str) -> dict[str, Any]:
    """转换响应格式"""
    return ProtocolConverter.normalize_response(response, source)

"""LLM 请求优化组件 - 用于拦截并模拟琐碎请求以节省 Quota"""
from typing import Any


def extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join([c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"])
    return ""

def is_quota_check_request(messages: list) -> bool:
    if len(messages) == 1 and messages[0].role == "user":
        text = extract_text_from_content(messages[0].content).lower()
        return "quota" in text
    return False

def is_title_generation_request(messages: list, system: str = "") -> bool:
    system_text = system.lower()
    return "new conversation topic" in system_text and "title" in system_text

def is_suggestion_mode_request(messages: list) -> bool:
    for msg in messages:
        if msg.role == "user":
            text = extract_text_from_content(msg.content)
            if "[SUGGESTION MODE:" in text:
                return True
    return False

def try_optimizations(messages: list, system: str = "", model: str = "") -> dict | None:
    """尝试进行请求优化拦截"""

    # 1. Quota 模拟
    if is_quota_check_request(messages):
        return {
            "content": "Quota check passed.",
            "model": model,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        }

    # 2. 标题生成跳过
    if is_title_generation_request(messages, system):
        return {
            "content": "Conversation",
            "model": model,
            "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}
        }

    # 3. 建议模式跳过
    if is_suggestion_mode_request(messages):
        return {
            "content": "",
            "model": model,
            "usage": {"prompt_tokens": 100, "completion_tokens": 1, "total_tokens": 101}
        }

    return None

"""Reasoning Model Adapter — 推理模型参数适配器（借鉴 Onyx multi_llm.py）

设计目标:
    1. 自动检测推理模型（o1/o3/Claude/DeepSeek-R1）
    2. 为不同提供商构建正确的推理参数
    3. 自动调整温度（推理模型强制 temperature=1）
    4. 处理 Anthropic thinking budget_tokens 规则

参考 Onyx 的 reasoning_effort 处理逻辑。

用法:
    from src.llm.reasoning_adapter import (
        is_reasoning_model,
        build_reasoning_kwargs,
        ReasoningEffort,
    )

    kwargs = build_reasoning_kwargs(
        model="claude-sonnet-4-5",
        provider="anthropic",
        reasoning_effort=ReasoningEffort.HIGH,
        max_tokens=4096,
    )
    # kwargs 包含正确的 thinking/reasoning/reasoning_effort 参数
"""
from __future__ import annotations

from typing import Any

from src.llm.interfaces import ReasoningEffort
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 推理模型预算配置（参考 Onyx ANTHROPIC_REASONING_EFFORT_BUDGET）
# ---------------------------------------------------------------------------

# Anthropic thinking budget tokens（推理努力等级 -> 预算 token 数）
ANTHROPIC_REASONING_EFFORT_BUDGET: dict[ReasoningEffort, int | None] = {
    ReasoningEffort.LOW: 1024,
    ReasoningEffort.MEDIUM: 4096,
    ReasoningEffort.HIGH: 16384,
    ReasoningEffort.AUTO: 4096,
    ReasoningEffort.OFF: None,
}

# OpenAI reasoning effort 映射
OPENAI_REASONING_EFFORT: dict[ReasoningEffort, str] = {
    ReasoningEffort.LOW: "low",
    ReasoningEffort.MEDIUM: "medium",
    ReasoningEffort.HIGH: "high",
    ReasoningEffort.AUTO: "medium",
}


# ---------------------------------------------------------------------------
# 提供商常量
# ---------------------------------------------------------------------------

class LlmProviderNames:
    """LLM 提供商名称常量"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA_CHAT = "ollama_chat"
    MISTRAL = "mistral"
    VERTEX_AI = "vertex_ai"
    BIFROST = "bifrost"
    OPENAI_COMPATIBLE = "openai_compatible"
    DEEPSEEK = "deepseek"


# Claude 模型标识符
_CLAUDE_IDENTIFIERS = ("claude",)

# OpenAI 推理模型前缀
_OPENAI_REASONING_PREFIXES = ("o1", "o3", "o4")

# 需要特殊处理的提供商
_PROVIDERS_NEEDING_TOOL_CHOICE_FIX = (
    LlmProviderNames.OPENAI,
    LlmProviderNames.BIFROST,
    LlmProviderNames.OPENAI_COMPATIBLE,
)
_PROVIDERS_BREAKING_TOOL_CHOICE = (
    LlmProviderNames.ANTHROPIC,
    LlmProviderNames.MISTRAL,
)


# ---------------------------------------------------------------------------
# 检测函数
# ---------------------------------------------------------------------------

def is_claude_model(model_name: str) -> bool:
    """检测是否是 Claude 模型"""
    return any(ident in model_name.lower() for ident in _CLAUDE_IDENTIFIERS)


def is_openai_reasoning_model(model_name: str) -> bool:
    """检测是否是 OpenAI 推理模型（o1/o3/o4）"""
    return any(
        model_name.lower().startswith(prefix)
        for prefix in _OPENAI_REASONING_PREFIXES
    )


def is_reasoning_model(model_name: str, provider: str) -> bool:
    """检测是否是推理模型

    包括:
    - OpenAI: o1, o3, o4 系列
    - Anthropic: Claude（支持 extended thinking）
    - DeepSeek: reasoner/R1
    """
    model_lower = model_name.lower()
    provider_lower = provider.lower()

    # OpenAI reasoning
    if provider_lower == LlmProviderNames.OPENAI and is_openai_reasoning_model(model_name):
        return True

    # Anthropic Claude（支持 thinking）
    if provider_lower == LlmProviderNames.ANTHROPIC and is_claude_model(model_name):
        return True

    # DeepSeek reasoner
    return bool(provider_lower == LlmProviderNames.DEEPSEEK and ("reasoner" in model_lower or "r1" in model_lower))


def is_true_openai_model(provider: str, model_name: str) -> bool:
    """检测是否是真正的 OpenAI 模型（非兼容代理）"""
    if provider != LlmProviderNames.OPENAI:
        return False
    # 排除通过 OpenRouter 等路由的 OpenAI 模型
    return not model_name.startswith(("openrouter/",))


def is_openai_compatible_proxy(provider: str) -> bool:
    """检测是否是 OpenAI 兼容代理"""
    return provider in (LlmProviderNames.BIFROST, LlmProviderNames.OPENAI_COMPATIBLE)


# ---------------------------------------------------------------------------
# 推理参数构建（核心函数，参考 Onyx multi_llm.py 中的 reasoning 处理）
# ---------------------------------------------------------------------------

def build_reasoning_kwargs(
    model_name: str,
    provider: str,
    reasoning_effort: ReasoningEffort,
    max_tokens: int | None = None,
    has_tool_call_history: bool = False,
) -> dict[str, Any]:
    """构建推理模型参数

    根据不同提供商的 API 要求，构建正确的推理参数:
    - OpenAI: reasoning (effort + summary)
    - Anthropic: thinking (type + budget_tokens)
    - 其他: reasoning_effort（让 LiteLLM 处理）

    Args:
        model_name: 模型名称
        provider: 提供商名称
        reasoning_effort: 推理努力等级
        max_tokens: 最大输出 token 数（Anthropic 可能需要调整）
        has_tool_call_history: 是否包含工具调用历史（影响 Anthropic thinking）

    Returns:
        可合并到 LLM 调用参数的字典

    参考 Onyx multi_llm.py 中的 reasoning_effort 处理逻辑。
    """
    kwargs: dict[str, Any] = {}

    # 如果不是推理模式，直接返回
    if reasoning_effort == ReasoningEffort.OFF:
        return kwargs

    is_openai_model = is_true_openai_model(provider, model_name)
    is_claude = is_claude_model(model_name)
    is_proxy = is_openai_compatible_proxy(provider)

    # ------------------------------------------------------------------
    # OpenAI 推理模型（o1/o3/o4）
    # ------------------------------------------------------------------
    if is_openai_model or (is_proxy and is_openai_reasoning_model(model_name)):
        # OpenAI API 不接受 GPT-5 chat 模型的 reasoning 参数
        #（即使它们是推理模型，这也是 OpenAI 的 bug）
        if "-chat" not in model_name.lower():
            kwargs["reasoning"] = {
                "effort": OPENAI_REASONING_EFFORT.get(reasoning_effort, "medium"),
                "summary": "auto",
            }

    # ------------------------------------------------------------------
    # Anthropic Claude（extended thinking）
    # ------------------------------------------------------------------
    elif is_claude:
        budget_tokens: int | None = ANTHROPIC_REASONING_EFFORT_BUDGET.get(reasoning_effort)

        # Anthropic 要求每个带 tool_use 的 assistant 消息必须以 thinking 块开始
        # 由于我们不保存 thinking_blocks（带加密签名），
        # 当历史包含工具调用时必须跳过 thinking
        can_enable_thinking = budget_tokens is not None and not has_tool_call_history

        if can_enable_thinking:
            assert budget_tokens is not None  # mypy

            # Anthropic 有个奇怪规则: max_tokens 必须至少等于 budget_tokens
            # 且 budget_tokens 最小值是 1024
            # 注意：覆盖开发者设置的 max_tokens 不理想，但为了保证 LLM
            # 能输出更多推理 token，这是最好的办法
            if max_tokens is not None:
                max_tokens = max(budget_tokens + 1, max_tokens)

            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget_tokens,
            }

            # 返回调整后的 max_tokens（调用方需要应用）
            if max_tokens is not None:
                kwargs["_adjusted_max_tokens"] = max_tokens

    # ------------------------------------------------------------------
    # 其他提供商（通过 LiteLLM 代理）
    # ------------------------------------------------------------------
    else:
        # 希望 LiteLLM 能正确处理
        if reasoning_effort in (ReasoningEffort.LOW, ReasoningEffort.MEDIUM, ReasoningEffort.HIGH):
            kwargs["reasoning_effort"] = reasoning_effort.value
        else:
            kwargs["reasoning_effort"] = ReasoningEffort.MEDIUM.value

    return kwargs


# ---------------------------------------------------------------------------
# 温度调整（推理模型强制 temperature=1）
# ---------------------------------------------------------------------------

def get_temperature_for_reasoning_model(
    model_name: str,
    provider: str,
    default_temperature: float = 0.7,
) -> float:
    """获取推理模型的温度

    推理模型（如 o1/Claude thinking）必须使用 temperature=1。

    参考 Onyx: temperature = 1 if is_reasoning else self._temperature
    """
    if is_reasoning_model(model_name, provider):
        return 1.0
    return default_temperature


# ---------------------------------------------------------------------------
# 工具选择策略修复（参考 Onyx tool_choice 处理）
# ---------------------------------------------------------------------------

def fix_tool_choice_for_provider(
    tool_choice: str | None,
    provider: str,
    model_name: str,
    has_tools: bool,
) -> str | None:
    """修复工具选择策略以适配不同提供商

    参考 Onyx 的 tool_choice 条件包含逻辑:
    - Claude: tool_choice=required 时会禁用 reasoning
    - Anthropic/Mistral: tool_choice 参数会破坏请求
    - Ollama: tool_choice 不被支持（会产生警告）
    - OpenAI: 必须通过 allowed_openai_params 传递

    Args:
        tool_choice: 工具选择策略（auto/required/none）
        provider: 提供商名称
        model_name: 模型名称
        has_tools: 是否提供了工具列表

    Returns:
        修正后的 tool_choice（可能为 None）
    """
    # 没有工具时，tool_choice 应为 None
    if not has_tools:
        return None

    # Claude: required 会禁用 reasoning，改为 auto
    if is_claude_model(model_name) and tool_choice == "required":
        logger.debug(
            "Claude models will not use reasoning if tool_choice is required. "
            "Changing from 'required' to 'auto'."
        )
        return "auto"

    # Anthropic/Mistral: tool_choice 会破坏请求
    if provider in _PROVIDERS_BREAKING_TOOL_CHOICE:
        return None

    # Ollama: tool_choice 不被支持
    if provider == LlmProviderNames.OLLAMA_CHAT:
        return None

    return tool_choice


def needs_allowed_openai_params(provider: str, model_name: str) -> bool:
    """检测是否需要传递 allowed_openai_params 参数

    参考 Onyx:
    LiteLLM 的 bug: 如果不在此处指定，tool_choice 会被静默丢弃（OpenAI）
    但此参数会破坏 Anthropic 和 Mistral
    """
    is_claude = is_claude_model(model_name)
    is_ollama = provider == LlmProviderNames.OLLAMA_CHAT
    is_mistral = provider == LlmProviderNames.MISTRAL
    is_proxy = is_openai_compatible_proxy(provider)

    return not (is_claude or is_ollama or is_mistral) or is_proxy


__all__ = [
    "ANTHROPIC_REASONING_EFFORT_BUDGET",
    "OPENAI_REASONING_EFFORT",
    "build_reasoning_kwargs",
    "fix_tool_choice_for_provider",
    "get_temperature_for_reasoning_model",
    "is_claude_model",
    "is_openai_compatible_proxy",
    "is_openai_reasoning_model",
    "is_reasoning_model",
    "is_true_openai_model",
    "needs_allowed_openai_params",
]

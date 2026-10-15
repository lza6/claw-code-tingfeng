"""LLM Factory — LLM 工厂模式（借鉴 Onyx factory.py）

设计目标:
    1. 统一的 LLM 创建入口（替代直接调用 LiteLLM 单例）
    2. 自动绑定 tokenizer
    3. 提供商特殊 Header 自动构建
    4. Vision 模型自动检测
    5. 向后兼容旧接口

用法:
    from src.llm.factory import get_llm, get_default_llm

    # 创建指定模型的 LLM 实例
    llm = get_llm(
        provider="openai",
        model="gpt-4o",
        max_input_tokens=8192,
    )

    # 获取默认 LLM
    llm = get_default_llm()
"""
from __future__ import annotations

from typing import Any

from src.core.config.settings import AgentSettings
from src.llm.balancer import get_balancer
from src.llm.interfaces import LLM, LLMConfig, LLMUserIdentity, ReasoningEffort, ToolChoiceOptions
from src.llm.litellm_singleton import get_litellm
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _as_str(value: Any) -> str | None:
    """把第三方响应里的字段安全地收敛成 `str | None`。

    LLM 提供商的返回结构不由我们控制：字段可能缺失、可能是 None，
    也可能在代理/兼容层里变成非字符串对象。直接塞进 pydantic 模型会抛
    ValidationError 并让整条 Agent 环路失败 —— 为字段类型不标准而丢掉
    一次完整对话，代价完全不成比例。

    非字符串一律降级为 None，而不是 str() 强转 —— 强转会写出
    `<MagicMock ...>` 这类垃圾内容并混入下游上下文。
    """
    return value if isinstance(value, str) else None


def _as_int(value: Any) -> int:
    """把第三方返回的计数字段收敛成 int。

    token 用量只用于统计与成本估算，不该因为某个代理层返回了
    `"15"` 或 None 就让整次调用失败。无法解析时返回 0。
    bool 被显式排除 —— `True` 是 int 的子类，但把它当 token 数无意义。
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


# ---------------------------------------------------------------------------
# 提供商常量（参考 Onyx well_known_providers）
# ---------------------------------------------------------------------------

class LlmProviderNames:
    """LLM 提供商名称常量"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"
    OLLAMA_CHAT = "ollama_chat"
    BEDROCK = "bedrock"
    VERTEX_AI = "vertex_ai"
    LM_STUDIO = "lm_studio"
    BIFROST = "bifrost"
    OPENAI_COMPATIBLE = "openai_compatible"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    GROQ = "groq"
    TOGETHER = "together"
    MISTRAL = "mistral"


# 需要特殊 Header 处理的提供商
PROVIDERS_WITH_SPECIAL_API_KEY_HANDLING: dict[str, str] = {
    LlmProviderNames.BEDROCK: "aws_bearer_token",
}


# ---------------------------------------------------------------------------
# 提供商特殊 Header 构建（参考 Onyx _build_provider_extra_headers）
# ---------------------------------------------------------------------------

def _build_provider_extra_headers(
    provider: str,
    custom_config: dict[str, str] | None,
) -> dict[str, str]:
    """为特定提供商构建额外 Header

    参考 Onyx 的实现:
    - Bedrock: Bearer Token 认证
    - OpenRouter: HTTP-Referer + X-Title（排行榜追踪）
    """
    if provider in PROVIDERS_WITH_SPECIAL_API_KEY_HANDLING and custom_config:
        raw = custom_config.get(PROVIDERS_WITH_SPECIAL_API_KEY_HANDLING[provider])
        api_key = raw.strip() if raw else None
        if not api_key:
            return {}
        return {
            "Authorization": (
                api_key
                if api_key.lower().startswith("bearer ")
                else f"Bearer {api_key}"
            )
        }

    # OpenRouter 排行榜追踪
    elif provider == LlmProviderNames.OPENROUTER:
        return {
            "HTTP-Referer": "https://github.com/claw-code/clawd",
            "X-Title": "Clawd Code",
        }

    return {}


# ---------------------------------------------------------------------------
# 模型参数构建（参考 Onyx _build_model_kwargs）
# ---------------------------------------------------------------------------

def _build_model_kwargs(
    provider: str,
    max_input_tokens: int | None,
) -> dict[str, Any]:
    """构建模型特定参数

    例如 Ollama 需要 num_ctx 参数。
    """
    model_kwargs: dict[str, Any] = {}
    if provider == LlmProviderNames.OLLAMA_CHAT and max_input_tokens and max_input_tokens > 0:
        model_kwargs["num_ctx"] = max_input_tokens
    return model_kwargs


# ---------------------------------------------------------------------------
# Vision 模型检测（参考 Onyx get_default_llm_with_vision）
# ---------------------------------------------------------------------------

_VISION_MODEL_PATTERNS = [
    "gpt-4o", "gpt-4-turbo", "gpt-4-vision",
    "claude-3", "claude-sonnet-4", "claude-opus",
    "gemini-2.5-pro", "gemini-3-pro",
    "llava", "cogvlm",
]


def _is_vision_model(model_name: str) -> bool:
    """检测模型是否支持视觉输入"""
    model_lower = model_name.lower()
    return any(pattern in model_lower for pattern in _VISION_MODEL_PATTERNS)


# ---------------------------------------------------------------------------
# 推理模型检测（参考 Onyx model_is_reasoning_model）
# ---------------------------------------------------------------------------

_REASONING_MODEL_PATTERNS = [
    "o1", "o3", "o4",
    "deepseek-reasoner", "deepseek-r1",
    "claude",  # Claude 支持 extended thinking
]


def _is_reasoning_model(model_name: str, provider: str) -> bool:
    """检测是否是推理模型"""
    model_lower = model_name.lower()
    provider_lower = provider.lower()

    # OpenAI reasoning models
    if provider_lower == LlmProviderNames.OPENAI and any(model_lower.startswith(m) for m in ["o1", "o3", "o4"]):
        return True

    # DeepSeek reasoner
    return bool(provider_lower == LlmProviderNames.DEEPSEEK and ("reasoner" in model_lower or "r1" in model_lower))


# ---------------------------------------------------------------------------
# LLM 创建（核心工厂函数，参考 Onyx get_llm）
# ---------------------------------------------------------------------------

def get_llm(
    provider: str,
    model: str,
    max_input_tokens: int,
    api_key: str | None = None,
    api_base: str | None = None,
    api_version: str | None = None,
    deployment_name: str | None = None,
    custom_config: dict[str, str] | None = None,
    temperature: float | None = None,
    timeout: int | None = None,
    additional_headers: dict[str, str] | None = None,
) -> LLM:
    """创建 LLM 实例（核心工厂函数）

    参考 Onyx get_llm() 的设计:
    1. 构建提供商特殊 Header
    2. 构建模型特定参数
    3. 创建 LiteLLM 包装实例

    Args:
        provider: LLM 提供商名称
        model: 模型名称
        max_input_tokens: 最大输入 token 数
        api_key: API 密钥
        api_base: API 基础 URL
        api_version: API 版本
        deployment_name: 部署名称
        custom_config: 自定义配置
        temperature: 温度参数
        timeout: 超时时间（秒）
        additional_headers: 额外 Header

    Returns:
        LLM 实例（适配 A 项目的 LiteLLM 包装类）
    """
    # 如果没有指定 api_key 或 api_base，尝试从负载均衡器获取
    if not api_key or not api_base:
        balancer = get_balancer()
        # 注意：如果 balancer 中有配置，它会覆盖传入的 provider 和 model 参数
        # 这符合“多模型 Provider”和“负载均衡”的设计
        next_provider = balancer.get_next_config()
        if next_provider:
            logger.info(f"使用负载均衡 Provider: {next_provider.name} ({next_provider.provider})")
            provider = next_provider.provider
            api_key = next_provider.api_key
            api_base = next_provider.base_url
            # 如果 balancer 中有更具体的配置，可以在此处进一步细化

    if temperature is None:
        temperature = 0.7

    # 构建额外 Header
    extra_headers = additional_headers.copy() if additional_headers else {}
    provider_extra_headers = _build_provider_extra_headers(provider, custom_config)
    if provider_extra_headers:
        extra_headers.update(provider_extra_headers)

    # 构建模型特定参数
    model_kwargs = _build_model_kwargs(provider, max_input_tokens)

    # 创建 LLM 配置
    config = LLMConfig(
        model_provider=provider,
        model_name=model,
        temperature=temperature,
        api_key=api_key,
        api_base=api_base,
        api_version=api_version,
        deployment_name=deployment_name,
        custom_config=custom_config,
        max_input_tokens=max_input_tokens,
    )

    # 创建并返回 LLM 实例
    # 注意：这里使用 A 项目现有的 LiteLLMSingleton 作为底层实现
    # 但通过工厂函数统一创建接口，未来可平滑替换为标准接口实现
    logger.debug(
        f"Creating LLM: provider={provider}, model={model}, "
        f"max_input_tokens={max_input_tokens}"
    )

    return _create_litellm_wrapper(
        config=config,
        timeout=timeout,
        extra_headers=extra_headers if extra_headers else None,
        model_kwargs=model_kwargs if model_kwargs else None,
    )


def get_default_llm(
    temperature: float | None = None,
    additional_headers: dict[str, str] | None = None,
) -> LLM:
    """获取默认 LLM 实例

    从 AgentSettings 读取默认模型配置。
    """
    settings = AgentSettings()
    model_name = settings.llm_model or "gpt-4o"

    # 解析提供商
    provider = _detect_provider_from_model(model_name)

    return get_llm(
        provider=provider,
        model=model_name,
        max_input_tokens=settings.max_context_tokens or 8192,
        # 必须显式透传密钥与自定义端点。
        # 否则 get_llm 会退回到空负载均衡器，api_base 为 None，
        # litellm 将请求打到官方 api.openai.com —— 对使用自定义
        # 端点（OpenRouter / NIM / 自建网关）的用户必然是 401。
        api_key=settings.llm_api_key,
        api_base=settings.llm_base_url,
        temperature=temperature,
        additional_headers=additional_headers,
    )


def get_vision_llm(
    model_name: str | None = None,
    temperature: float | None = None,
) -> LLM | None:
    """获取支持视觉的 LLM 实例

    参考 Onyx get_default_llm_with_vision() 的降级逻辑:
    1. 如果指定了模型，检测是否支持视觉
    2. 否则返回 None（让调用者处理）
    """
    settings = AgentSettings()
    target_model = model_name or settings.llm_model

    if not target_model:
        logger.warning("No model specified for vision LLM")
        return None

    provider = _detect_provider_from_model(target_model)

    if not _is_vision_model(target_model):
        logger.warning(f"Model {target_model} may not support vision input")
        return None

    return get_llm(
        provider=provider,
        model=target_model,
        max_input_tokens=settings.max_context_tokens or 8192,
        api_key=settings.llm_api_key,
        api_base=settings.llm_base_url,
        temperature=temperature,
    )


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _detect_provider_from_model(model_name: str) -> str:
    """从模型名称检测提供商"""
    model_lower = model_name.lower()

    if model_lower.startswith(("claude",)):
        return LlmProviderNames.ANTHROPIC
    elif model_lower.startswith(("gpt", "o1", "o3", "o4")):
        return LlmProviderNames.OPENAI
    elif model_lower.startswith(("gemini",)):
        return LlmProviderNames.GEMINI
    elif model_lower.startswith(("deepseek",)):
        return LlmProviderNames.DEEPSEEK
    elif model_lower.startswith(("llama",)):
        return LlmProviderNames.OPENROUTER  # 通常通过 OpenRouter
    elif "ollama" in model_lower:
        return LlmProviderNames.OLLAMA_CHAT

    # 默认 OpenAI
    return LlmProviderNames.OPENAI


def _create_litellm_wrapper(
    config: LLMConfig,
    timeout: int | None = None,
    extra_headers: dict[str, str] | None = None,
    model_kwargs: dict[str, Any] | None = None,
) -> LLM:
    """创建 LiteLLM 包装实例

    适配 A 项目现有的 LiteLLMSingleton。
    返回一个符合 LLM 接口的包装对象。

    注意：这里返回的是兼容对象，实际 LiteLLM 调用通过单例完成。
    未来可替换为完整的 LiteLLMImpl 类。
    """
    # 暂时返回一个兼容字典对象，包含配置信息
    # 调用方应通过 get_litellm() 执行实际调用
    wrapper = _LiteLLMCompatWrapper(
        config=config,
        timeout=timeout,
        extra_headers=extra_headers,
        model_kwargs=model_kwargs,
    )
    return wrapper


class _LiteLLMCompatWrapper:
    """LiteLLM 兼容包装器

    实现 LLM 接口的最小子集，适配 A 项目现有的单例调用模式。
    这确保工厂函数可以平滑接入，同时保持向后兼容。
    """

    def __init__(
        self,
        config: LLMConfig,
        timeout: int | None = None,
        extra_headers: dict[str, str] | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ):
        self._config = config
        self._timeout = timeout
        self._extra_headers = extra_headers
        self._model_kwargs = model_kwargs or {}

    @property
    def config(self) -> LLMConfig:
        return self._config

    def _build_call_kwargs(self) -> dict[str, Any]:
        """构建 litellm.completion() 的公共参数。

        必须包含 api_key / api_base —— 这是使用自定义端点
        （OpenRouter / NVIDIA NIM / 自建 OpenAI 兼容网关）的前提。
        遗漏 api_base 会让 litellm 把请求打到官方 api.openai.com，
        对自建网关用户表现为 401 而非"端点未配置"。

        抽成独立方法是为了让 invoke/stream 共用同一份参数，
        避免两处各自演化导致行为漂移。
        """
        kwargs: dict[str, Any] = {
            "model": f"{self._config.model_provider}/{self._config.model_name}",
            "temperature": self._config.temperature,
        }
        if self._config.api_key:
            kwargs["api_key"] = self._config.api_key
        if self._config.api_base:
            kwargs["api_base"] = self._config.api_base
        if self._extra_headers:
            kwargs["extra_headers"] = self._extra_headers
        if self._model_kwargs:
            kwargs.update(self._model_kwargs)
        return kwargs

    def _apply_call_options(
        self,
        kwargs: dict[str, Any],
        tools: list[dict] | None,
        tool_choice: ToolChoiceOptions | None,
        max_tokens: int | None,
        timeout: int | None,
    ) -> None:
        """把单次调用的可选参数合并进 kwargs（原地修改）"""
        if timeout:
            kwargs["request_timeout"] = timeout
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice.value

    def invoke(
        self,
        prompt: list[dict[str, Any]],
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> ModelResponse:
        """同步调用（通过 LiteLLM 单例）"""
        from src.core.exceptions import LLMProviderError
        from src.llm.interfaces import Message, ModelResponse, ToolCall, Usage

        litellm = get_litellm()
        timeout = timeout_override or self._timeout

        kwargs = self._build_call_kwargs()
        kwargs["messages"] = prompt
        self._apply_call_options(kwargs, tools, tool_choice, max_tokens, timeout)

        try:
            response = litellm.completion(**kwargs)
        except Exception as e:
            logger.error(f"LLM invoke failed: {e}")
            raise LLMProviderError.from_exception(e) from e

        # 解析响应
        choice = response.choices[0] if response.choices else None
        if not choice:
            return ModelResponse()

        raw_message = choice.message
        message_data = raw_message.model_dump() if hasattr(raw_message, 'model_dump') else {}

        # 工具调用必须被完整还原，否则 Agent 环路拿不到任何 tool_calls，
        # 表现为"模型说了要调用工具但框架当作普通回复处理"。
        # litellm 返回的是 OpenAI 嵌套结构（function.name / function.arguments），
        # 而本项目的 ToolCall 是扁平结构（name / arguments），此处做映射。
        tool_calls: list[ToolCall] | None = None
        raw_tool_calls = message_data.get("tool_calls") or getattr(raw_message, "tool_calls", None)
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                tc_data = tc if isinstance(tc, dict) else (
                    tc.model_dump() if hasattr(tc, "model_dump") else {}
                )
                fn = tc_data.get("function") or {}
                if isinstance(fn, dict):
                    fn_name, fn_args = fn.get("name", ""), fn.get("arguments", "")
                else:  # pragma: no cover - 防御非标准返回
                    fn_name, fn_args = getattr(fn, "name", ""), getattr(fn, "arguments", "")
                tool_calls.append(ToolCall(
                    id=tc_data.get("id", ""),
                    name=fn_name,
                    arguments=fn_args or "{}",
                ))

        message = Message(
            role=_as_str(message_data.get("role")) or "assistant",
            content=_as_str(message_data.get("content")) or None,
            tool_calls=tool_calls,
            finish_reason=_as_str(getattr(choice, "finish_reason", None)),
            reasoning_content=_as_str(message_data.get("reasoning_content")),
        )

        raw_usage = getattr(response, "usage", None)
        usage = Usage(
            prompt_tokens=_as_int(getattr(raw_usage, "prompt_tokens", 0)),
            completion_tokens=_as_int(getattr(raw_usage, "completion_tokens", 0)),
            total_tokens=_as_int(getattr(raw_usage, "total_tokens", 0)),
        )

        return ModelResponse(
            id=_as_str(getattr(response, 'id', None)) or "",
            model=_as_str(getattr(response, 'model', None)) or self._config.model_name,
            choices=[message],
            usage=usage,
        )

    def stream(
        self,
        prompt: list[dict[str, Any]],
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ):
        """流式调用（通过 LiteLLM 单例）"""
        from src.core.exceptions import LLMProviderError
        from src.llm.interfaces import Message, ModelResponseStream, ToolCall

        litellm = get_litellm()
        timeout = timeout_override or self._timeout

        kwargs = self._build_call_kwargs()
        kwargs["messages"] = prompt
        kwargs["stream"] = True
        self._apply_call_options(kwargs, tools, tool_choice, max_tokens, timeout)

        try:
            response_stream = litellm.completion(**kwargs)
            for chunk in response_stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                delta_data = delta.model_dump() if hasattr(delta, 'model_dump') else {}

                # 流式增量同样需要还原工具调用与推理内容，
                # 否则流式路径下 Agent 无法触发工具、无法展示思维链。
                delta_tool_calls: list[ToolCall] | None = None
                raw_deltas = delta_data.get("tool_calls") or getattr(delta, "tool_calls", None)
                if raw_deltas:
                    delta_tool_calls = []
                    for tc in raw_deltas:
                        tc_data = tc if isinstance(tc, dict) else (
                            tc.model_dump() if hasattr(tc, "model_dump") else {}
                        )
                        fn = tc_data.get("function") or {}
                        if isinstance(fn, dict):
                            fn_name, fn_args = fn.get("name") or "", fn.get("arguments") or ""
                        else:  # pragma: no cover - 防御非标准返回
                            fn_name = getattr(fn, "name", "") or ""
                            fn_args = getattr(fn, "arguments", "") or ""
                        delta_tool_calls.append(ToolCall(
                            id=tc_data.get("id") or "",
                            name=fn_name,
                            arguments=fn_args,
                        ))

                yield ModelResponseStream(
                    id=_as_str(getattr(chunk, 'id', None)) or "",
                    model=_as_str(getattr(chunk, 'model', None)) or self._config.model_name,
                    delta=Message(
                        role=_as_str(delta_data.get("role")) or "assistant",
                        content=_as_str(delta_data.get("content")),
                        tool_calls=delta_tool_calls,
                        reasoning_content=_as_str(delta_data.get("reasoning_content")),
                    ),
                    finish_reason=_as_str(chunk.choices[0].finish_reason) if chunk.choices else None,
                )
        except Exception as e:
            logger.error(f"LLM stream failed: {e}")
            raise LLMProviderError.from_exception(e) from e

    def supports_vision(self) -> bool:
        return _is_vision_model(self._config.model_name)

    def supports_function_calling(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"LiteLLMCompatWrapper(provider={self._config.model_provider}, model={self._config.model_name})"


# 延迟导入避免循环依赖
if True:
    from src.llm.interfaces import ModelResponse


__all__ = [
    "LlmProviderNames",
    "_detect_provider_from_model",
    "_is_reasoning_model",
    "_is_vision_model",
    "get_default_llm",
    "get_llm",
    "get_vision_llm",
]

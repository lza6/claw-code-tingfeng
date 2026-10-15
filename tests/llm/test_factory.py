"""LLM Factory 模块单元测试"""
import pytest
from unittest.mock import patch, MagicMock
from src.llm.factory import (
    LlmProviderNames,
    _build_provider_extra_headers,
    _build_model_kwargs,
    _is_vision_model,
    _is_reasoning_model,
    _detect_provider_from_model,
    get_llm,
    get_default_llm,
    get_vision_llm,
    _LiteLLMCompatWrapper,
)
from src.llm.interfaces import LLMConfig


class TestLlmProviderNames:
    """LLM 提供商名称常量测试"""

    def test_openai(self):
        assert LlmProviderNames.OPENAI == "openai"

    def test_anthropic(self):
        assert LlmProviderNames.ANTHROPIC == "anthropic"

    def test_openrouter(self):
        assert LlmProviderNames.OPENROUTER == "openrouter"


class TestProviderDetection:
    """提供商检测测试"""

    def test_detect_openai(self):
        provider = _detect_provider_from_model("gpt-4")
        assert provider == LlmProviderNames.OPENAI


class TestVisionDetection:
    """视觉模型检测测试"""

    def test_vision_model(self):
        assert _is_vision_model("gpt-4o") is True

    def test_ollama_chat(self):
        assert LlmProviderNames.OLLAMA_CHAT == "ollama_chat"

    def test_bedrock(self):
        assert LlmProviderNames.BEDROCK == "bedrock"

    def test_gemini(self):
        assert LlmProviderNames.GEMINI == "gemini"

    def test_groq(self):
        assert LlmProviderNames.GROQ == "groq"

    def test_mistral(self):
        assert LlmProviderNames.MISTRAL == "mistral"


class TestBuildProviderExtraHeaders:
    """_build_provider_extra_headers 测试"""

    def test_bedrock_with_token(self):
        """Bedrock 带 token"""
        config = {"aws_bearer_token": "my-aws-token"}
        headers = _build_provider_extra_headers("bedrock", config)
        assert headers["Authorization"] == "Bearer my-aws-token"

    def test_bedrock_with_bearer_prefix(self):
        """Bedrock 已有 Bearer 前缀"""
        config = {"aws_bearer_token": "Bearer existing-token"}
        headers = _build_provider_extra_headers("bedrock", config)
        assert headers["Authorization"] == "Bearer existing-token"

    def test_bedrock_without_token(self):
        """Bedrock 无 token 返回空"""
        headers = _build_provider_extra_headers("bedrock", {})
        assert headers == {}

    def test_bedrock_no_config(self):
        """Bedrock 无配置返回空"""
        headers = _build_provider_extra_headers("bedrock", None)
        assert headers == {}

    def test_openrouter(self):
        """OpenRouter 排行榜追踪"""
        headers = _build_provider_extra_headers("openrouter", None)
        assert headers["HTTP-Referer"] == "https://github.com/claw-code/clawd"
        assert headers["X-Title"] == "Clawd Code"

    def test_unknown_provider(self):
        """未知提供商返回空"""
        headers = _build_provider_extra_headers("unknown", None)
        assert headers == {}


class TestBuildModelKwargs:
    """_build_model_kwargs 测试"""

    def test_ollama_with_tokens(self):
        """Ollama 带 context tokens"""
        kwargs = _build_model_kwargs("ollama_chat", 4096)
        assert kwargs == {"num_ctx": 4096}

    def test_ollama_zero_tokens(self):
        """Ollama 零 tokens 返回空"""
        kwargs = _build_model_kwargs("ollama_chat", 0)
        assert kwargs == {}

    def test_ollama_none_tokens(self):
        """Ollama None tokens 返回空"""
        kwargs = _build_model_kwargs("ollama_chat", None)
        assert kwargs == {}

    def test_other_provider(self):
        """其他提供商返回空"""
        kwargs = _build_model_kwargs("openai", 4096)
        assert kwargs == {}


class TestIsVisionModel:
    """_is_vision_model 测试"""

    @pytest.mark.parametrize("model", [
        "gpt-4o",
        "gpt-4-turbo",
        "gpt-4-vision",
        "claude-3-sonnet",
        "claude-opus-4",
        "gemini-2.5-pro",
        "gemini-3-pro",
        "llava-1.6",
        "cogvlm-chat",
    ])
    def test_vision_models(self, model):
        """视觉模型检测"""
        assert _is_vision_model(model) is True

    @pytest.mark.parametrize("model", [
        "gpt-3.5-turbo",
        "gpt-4-0613",
        "claude-2",
        "llama-3-8b",
        "mistral-small",
    ])
    def test_non_vision_models(self, model):
        """非视觉模型检测"""
        assert _is_vision_model(model) is False


class TestIsReasoningModel:
    """_is_reasoning_model 测试"""

    @pytest.mark.parametrize("model,provider", [
        ("o1", "openai"),
        ("o1-preview", "openai"),
        ("o3-mini", "openai"),
        ("o4-mini", "openai"),
        ("deepseek-reasoner", "deepseek"),
        ("deepseek-r1", "deepseek"),
    ])
    def test_reasoning_models(self, model, provider):
        """推理模型检测"""
        assert _is_reasoning_model(model, provider) is True

    @pytest.mark.parametrize("model,provider", [
        ("gpt-4o", "openai"),
        ("claude-3-sonnet", "anthropic"),
        ("deepseek-chat", "deepseek"),
        ("gemma-2", "google"),
    ])
    def test_non_reasoning_models(self, model, provider):
        """非推理模型检测"""
        assert _is_reasoning_model(model, provider) is False


class TestDetectProviderFromModel:
    """_detect_provider_from_model 测试"""

    @pytest.mark.parametrize("model,expected", [
        ("claude-3-sonnet", "anthropic"),
        ("claude-opus-4", "anthropic"),
        ("gpt-4o", "openai"),
        ("gpt-3.5-turbo", "openai"),
        ("o1", "openai"),
        ("o3-mini", "openai"),
        ("gemini-pro", "gemini"),
        ("deepseek-chat", "deepseek"),
        ("llama-3-70b", "openrouter"),
        ("ollama-llama3", "ollama_chat"),
        ("unknown-model", "openai"),  # 默认
    ])
    def test_provider_detection(self, model, expected):
        """提供商检测"""
        assert _detect_provider_from_model(model) == expected


class TestGetLLM:
    """get_llm 测试"""

    @patch("src.llm.factory._create_litellm_wrapper")
    def test_create_openai_llm(self, mock_wrapper):
        """创建 OpenAI LLM"""
        mock_wrapper.return_value = MagicMock()
        llm = get_llm(
            provider="openai",
            model="gpt-4o",
            max_input_tokens=8192,
            api_key="test-key",
        )
        assert llm is not None
        mock_wrapper.assert_called_once()

    @patch("src.llm.factory._create_litellm_wrapper")
    def test_default_temperature(self, mock_wrapper):
        """默认温度 0.7"""
        mock_wrapper.return_value = MagicMock()
        get_llm(
            provider="openai",
            model="gpt-4",
            max_input_tokens=4096,
        )
        call_kwargs = mock_wrapper.call_args[1]
        config = call_kwargs["config"]
        assert config.temperature == 0.7

    @patch("src.llm.factory._create_litellm_wrapper")
    def test_custom_temperature(self, mock_wrapper):
        """自定义温度"""
        mock_wrapper.return_value = MagicMock()
        get_llm(
            provider="anthropic",
            model="claude-3",
            max_input_tokens=8192,
            temperature=0.9,
        )
        call_kwargs = mock_wrapper.call_args[1]
        config = call_kwargs["config"]
        assert config.temperature == 0.9


class TestLiteLLMCompatWrapper:
    """_LiteLLMCompatWrapper 测试"""

    @pytest.fixture
    def config(self):
        return LLMConfig(
            model_provider="openai",
            model_name="gpt-4o",
            temperature=0.7,
            max_input_tokens=8192,
        )

    def test_repr(self, config):
        """__repr__ 测试"""
        wrapper = _LiteLLMCompatWrapper(config=config)
        assert "openai" in repr(wrapper)
        assert "gpt-4o" in repr(wrapper)

    def test_supports_vision(self, config):
        """supports_vision 测试"""
        wrapper = _LiteLLMCompatWrapper(config=config)
        assert wrapper.supports_vision() is True

    def test_supports_function_calling(self, config):
        """supports_function_calling 测试"""
        wrapper = _LiteLLMCompatWrapper(config=config)
        assert wrapper.supports_function_calling() is True

    def test_supports_streaming(self, config):
        """supports_streaming 测试"""
        wrapper = _LiteLLMCompatWrapper(config=config)
        assert wrapper.supports_streaming() is True

    @patch("src.llm.factory.get_litellm")
    def test_invoke(self, mock_litellm, config):
        """invoke 测试"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.model_dump.return_value = {
            "role": "assistant",
            "content": "Hello!",
        }
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15
        mock_response.id = "resp-123"
        mock_response.model = "gpt-4o"

        mock_client = MagicMock()
        mock_client.completion.return_value = mock_response
        mock_litellm.return_value = mock_client

        wrapper = _LiteLLMCompatWrapper(config=config)
        messages = [{"role": "user", "content": "Hi"}]
        result = wrapper.invoke(messages)

        assert result.id == "resp-123"
        assert result.model == "gpt-4o"
        assert len(result.choices) == 1
        assert result.choices[0].role == "assistant"
        assert result.usage.prompt_tokens == 10


class TestMalformedProviderResponse:
    """第三方响应结构异常时的健壮性回归测试。

    背景: 真实 E2E 修复过程中给 Message 补上了 finish_reason 字段，
    但直接透传 choice.finish_reason。当 provider / 代理层返回的该字段
    不是字符串时，pydantic 抛 ValidationError，整条 Agent 环路失败 ——
    为"某个字段类型不标准"而丢掉一次完整对话，代价完全不成比例。
    现在非字符串字段一律降级，绝不 str() 强转（那会写出 "<MagicMock ...>"
    这类垃圾内容并混入下游上下文）。
    """

    def _wrapper(self):
        config = MagicMock()
        config.model_provider = "openai"
        config.model_name = "gpt-4o"
        config.temperature = 0.7
        config.api_key = "test-key"
        config.api_base = None
        return _LiteLLMCompatWrapper(config=config)

    def test_non_string_fields_are_degraded_not_crashing(self):
        """finish_reason / id / model 为非字符串时不应抛异常"""
        from src.llm import factory as factory_mod

        response = MagicMock()
        response.choices[0].message.model_dump.return_value = {"role": "assistant", "content": "hi"}
        # 关键：这些字段不是字符串
        response.id = 12345
        response.model = object()
        response.choices[0].finish_reason = object()

        with patch.object(factory_mod, "get_litellm") as mock_litellm:
            mock_client = MagicMock()
            mock_client.completion.return_value = response
            mock_litellm.return_value = mock_client

            result = self._wrapper().invoke([{"role": "user", "content": "Hi"}])

        assert result.choices[0].content == "hi"
        assert result.choices[0].finish_reason is None
        assert result.id == ""
        assert result.model == "gpt-4o"   # 回退到配置里的模型名

    def test_non_numeric_usage_is_degraded_to_zero(self):
        """token 计数为非数值时降级为 0，而不是让统计拖垮主流程"""
        from src.llm import factory as factory_mod

        response = MagicMock()
        response.choices[0].message.model_dump.return_value = {"role": "assistant", "content": "hi"}
        response.usage.prompt_tokens = "not-a-number"
        response.usage.completion_tokens = None
        response.usage.total_tokens = object()

        with patch.object(factory_mod, "get_litellm") as mock_litellm:
            mock_client = MagicMock()
            mock_client.completion.return_value = response
            mock_litellm.return_value = mock_client

            result = self._wrapper().invoke([{"role": "user", "content": "Hi"}])

        assert result.usage.prompt_tokens == 0
        assert result.usage.completion_tokens == 0
        assert result.usage.total_tokens == 0

    def test_numeric_string_usage_is_parsed(self):
        """字符串形式的 token 数应被解析而不是丢弃"""
        from src.llm import factory as factory_mod

        response = MagicMock()
        response.choices[0].message.model_dump.return_value = {"role": "assistant", "content": "hi"}
        response.usage.prompt_tokens = "17"
        response.usage.completion_tokens = 15
        response.usage.total_tokens = 32.0

        with patch.object(factory_mod, "get_litellm") as mock_litellm:
            mock_client = MagicMock()
            mock_client.completion.return_value = response
            mock_litellm.return_value = mock_client

            result = self._wrapper().invoke([{"role": "user", "content": "Hi"}])

        assert result.usage.prompt_tokens == 17
        assert result.usage.completion_tokens == 15
        assert result.usage.total_tokens == 32

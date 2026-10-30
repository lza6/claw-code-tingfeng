"""生产 LLM 提供商测试（OpenAI 兼容路径）。

## 为什么这个文件重要

`src/llm/providers/` 是**生产环境真正使用的 LLM 路径**：

    src/agent/engine.py:203
      -> create_llm_provider()      (src/llm/providers/__init__.py)
        -> OpenAICompatibleProvider.chat() / .chat_stream()

`src/llm/factory.py::get_default_llm()` 是另一条路径，但**从生产入口不可达**
（由 scripts/reachability.py 的传递可达性分析确认）。因此对 providers/ 的测试
才是对生产的保护。

本文件覆盖真实发生过的缺陷与高风险边界，全部用 mock，不依赖网络。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.config import LLMConfig, LLMMessage, LLMProviderType
from src.llm.parsers import ThinkTagParser
from src.llm.providers import OpenAIProvider, create_llm_provider


@pytest.fixture
def config() -> LLMConfig:
    return LLMConfig(
        provider=LLMProviderType.OPENAI,
        api_key="test-key-1234567890",
        base_url="https://example.invalid/v1",
        model="test-model",
        max_retries=2,
        timeout=5,
    )


@pytest.fixture
def provider(config: LLMConfig) -> OpenAIProvider:
    return OpenAIProvider(config)


def _response(content: str, reasoning: str | None = None, finish: str = "stop"):
    """构造 OpenAI SDK 形状的响应"""
    resp = MagicMock()
    resp.model = "test-model"
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].message.reasoning_content = reasoning
    resp.choices[0].finish_reason = finish
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    resp.usage.total_tokens = 15
    return resp


def _patch_client(provider, response=None, side_effect=None):
    """把 provider 的底层 client 换成 mock"""
    inner = MagicMock()
    if side_effect is not None:
        inner.chat.completions.create = AsyncMock(side_effect=side_effect)
    else:
        inner.chat.completions.create = AsyncMock(return_value=response)
    return patch.object(type(provider), "_get_client", return_value=inner)


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------


class TestCreateProvider:
    def test_creates_openai_provider(self, config):
        assert isinstance(create_llm_provider(config), OpenAIProvider)

    def test_unsupported_provider_raises(self, config):
        config.provider = LLMProviderType.CUSTOM  # 未在 providers 表中注册
        with pytest.raises(ValueError, match="不支持的 LLM 提供商"):
            create_llm_provider(config)


# ---------------------------------------------------------------------------
# <think> 标签提取 —— 曾经的 P0
# ---------------------------------------------------------------------------


class TestThinkTagExtraction:
    """`chat()` 里的启发式提取曾写成 `content.split('', 1)`。

    分隔符是**空字符串**，Python 直接抛 `ValueError: empty separator`。
    触发条件是"响应内容含 `<think>`" —— 也就是任何推理模型的思考输出。
    异常被重试逻辑吞掉 max_retries 次后整次调用失败。
    下面这组用例锁定该回归。
    """

    def test_splits_think_tag_into_thinking_and_content(self, provider):
        body = "<think>先算 17*23=391</think>答案是 391"
        with _patch_client(provider, _response(body)):
            resp = asyncio.run(provider.chat([LLMMessage(role="user", content="x")]))

        assert resp.content == "答案是 391"
        assert resp.thinking == "先算 17*23=391"

    def test_does_not_crash_on_think_tag(self, provider):
        """回归核心：含 <think> 时不得抛 ValueError"""
        body = "<think>思考中</think>结果"
        with _patch_client(provider, _response(body)):
            resp = asyncio.run(provider.chat([LLMMessage(role="user", content="x")]))
        assert resp.content == "结果"

    def test_plain_content_untouched(self, provider):
        body = "就是一段普通回复"
        with _patch_client(provider, _response(body)):
            resp = asyncio.run(provider.chat([LLMMessage(role="user", content="x")]))

        assert resp.content == body
        assert resp.thinking == ""

    def test_native_reasoning_content_takes_priority(self, provider):
        """提供商原生 reasoning_content 优先于 <think> 启发式"""
        with _patch_client(provider, _response("正文", reasoning="原生推理")):
            resp = asyncio.run(provider.chat([LLMMessage(role="user", content="x")]))

        assert resp.thinking == "原生推理"
        assert resp.content == "正文"

    def test_close_tag_constant_matches_parser(self):
        """用常量而非字面量，避免再次被编辑操作截断成空串"""
        assert ThinkTagParser.CLOSE_TAG == "</think>"
        assert ThinkTagParser.OPEN_TAG == "<think>"


# ---------------------------------------------------------------------------
# 重试与错误路径
# ---------------------------------------------------------------------------


class TestRetryAndErrors:
    def test_retries_then_succeeds(self, provider):
        provider._max_retries = 3
        calls = {"n": 0}

        async def flaky(**_kw):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("transient")
            return _response("终于成功")

        with _patch_client(provider, side_effect=flaky):
            resp = asyncio.run(provider.chat([LLMMessage(role="user", content="x")]))

        assert resp.content == "终于成功"
        assert calls["n"] == 3

    def test_raises_after_exhausting_retries(self, provider):
        provider._max_retries = 2

        async def always_fail(**_kw):
            raise RuntimeError("permanent")

        with _patch_client(provider, side_effect=always_fail), pytest.raises(RuntimeError, match="permanent"):
            asyncio.run(provider.chat([LLMMessage(role="user", content="x")]))

    def test_original_exception_propagates_not_swallowed(self, provider):
        """错误必须向上抛，不得静默返回空内容"""
        provider._max_retries = 1

        async def boom(**_kw):
            raise ValueError("upstream said no")

        with _patch_client(provider, side_effect=boom), pytest.raises(ValueError):
            asyncio.run(provider.chat([LLMMessage(role="user", content="x")]))


# ---------------------------------------------------------------------------
# 消息编解码
# ---------------------------------------------------------------------------


class TestMessageEncoding:
    def test_role_and_content_are_forwarded(self, provider):
        captured = {}

        async def spy(**kw):
            captured.update(kw)
            return _response("ok")

        with _patch_client(provider, side_effect=spy):
            asyncio.run(provider.chat([
                LLMMessage(role="system", content="sys"),
                LLMMessage(role="user", content="hi"),
            ]))

        assert captured["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]

    def test_model_from_config_is_used(self, provider):
        captured = {}

        async def spy(**kw):
            captured.update(kw)
            return _response("ok")

        with _patch_client(provider, side_effect=spy):
            asyncio.run(provider.chat([LLMMessage(role="user", content="hi")]))

        assert captured["model"] == "test-model"

    def test_usage_is_mapped(self, provider):
        with _patch_client(provider, _response("ok")):
            resp = asyncio.run(provider.chat([LLMMessage(role="user", content="x")]))

        assert resp.usage["prompt_tokens"] == 10
        assert resp.usage["completion_tokens"] == 5
        assert resp.usage["total_tokens"] == 15


# ---------------------------------------------------------------------------
# 流式
# ---------------------------------------------------------------------------


class TestChatStream:
    def _stream_of(self, chunks):
        async def gen():
            for c in chunks:
                yield c

        inner = MagicMock()

        async def _create(**_kw):
            return gen()

        inner.chat.completions.create = _create
        return inner

    def test_yields_text_chunks(self, provider):
        chunks = []
        for text in ("He", "llo"):
            ch = MagicMock()
            ch.choices = [MagicMock()]
            ch.choices[0].delta.content = text
            ch.choices[0].delta.reasoning_content = None
            chunks.append(ch)

        async def consume() -> list:
            out = []
            async for item in provider.chat_stream([LLMMessage(role="user", content="x")]):
                out.append(item)
            return out

        with patch.object(type(provider), "_get_client", return_value=self._stream_of(chunks)):
            out = asyncio.run(consume())

        assert "".join(out) == "Hello"

    def test_reasoning_content_yielded_as_thinking(self, provider):
        ch = MagicMock()
        ch.choices = [MagicMock()]
        ch.choices[0].delta.content = None
        ch.choices[0].delta.reasoning_content = "推理片段"

        async def consume() -> list:
            out = []
            async for item in provider.chat_stream([LLMMessage(role="user", content="x")]):
                out.append(item)
            return out

        with patch.object(type(provider), "_get_client", return_value=self._stream_of([ch])):
            out = asyncio.run(consume())

        assert ("thinking", "推理片段") in out

    def test_stream_error_is_raised_not_swallowed(self, provider):
        inner = MagicMock()

        async def _create(**_kw):
            raise RuntimeError("stream broke")

        inner.chat.completions.create = _create

        async def consume():
            async for _ in provider.chat_stream([LLMMessage(role="user", content="x")]):
                pass

        with patch.object(type(provider), "_get_client", return_value=inner), pytest.raises(RuntimeError):
            asyncio.run(consume())

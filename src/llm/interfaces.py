"""LLM Standard Interfaces — LLM 标准接口定义

借鉴 Onyx 的 LLM 接口设计，提供统一的 ABC 抽象。

设计目标:
    1. 统一所有 LLM 提供商的调用接口
    2. 支持 invoke (同步) 和 stream (流式) 两种模式
    3. 标准化配置、身份追踪、推理努力等级
    4. 与 Braintrust @traced 装饰器集成

用法:
    from src.llm.interfaces import LLM, LLMConfig, ReasoningEffort

    # 任何 L 提供商都必须实现 LLM 接口
    class MyProvider(LLM):
        @property
        def config(self) -> LLMConfig: ...
        def invoke(self, prompt, ...) -> ModelResponse: ...
        def stream(self, prompt, ...) -> Iterator[ModelResponseStream]: ...
"""
from __future__ import annotations

import abc
from collections.abc import Iterator
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ReasoningEffort(str, Enum):
    """推理努力等级（参考 Onyx ReasoningEffort）

    适用于 o1/o3/Claude reasoning 等推理模型。
    AUTO 表示让模型自行决定。
    """
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    AUTO = "auto"


class ToolChoiceOptions(str, Enum):
    """工具调用选择策略

    AUTO: 模型自行决定是否调用工具
    REQUIRED: 必须调用至少一个工具
    NONE: 不调用任何工具
    """
    AUTO = "auto"
    REQUIRED = "required"
    NONE = "none"


class LLMUserIdentity(BaseModel):
    """LLM 调用身份追踪（参考 Onyx LLMUserIdentity）

    用于成本追踪、审计和速率限制。
    """
    user_id: str | None = Field(default=None, description="用户 ID")
    session_id: str | None = Field(default=None, description="会话 ID")
    request_id: str | None = Field(default=None, description="请求 ID")


class LLMConfig(BaseModel):
    """LLM 统一配置（参考 Onyx LLMConfig）

    所有 LLM 提供商共享的配置模型。
    """
    model_provider: str = Field(description="提供商名称 (e.g. 'openai', 'anthropic')")
    model_name: str = Field(description="模型名称 (e.g. 'gpt-4o', 'claude-sonnet-4-5')")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    api_key: str | None = Field(default=None, description="API 密钥")
    api_base: str | None = Field(default=None, description="API 基础 URL")
    api_version: str | None = Field(default=None, description="API 版本 (Azure 需要)")
    deployment_name: str | None = Field(default=None, description="部署名称 (Azure 需要)")
    custom_config: dict[str, str] | None = Field(default=None, description="自定义配置")
    max_input_tokens: int = Field(default=8192, gt=0, description="最大输入 token 数")

    # 禁用 pydantic 的 "model_" 命名空间保护，允许 max_input_tokens 等字段
    model_config = {"protected_namespaces": ()}

    @property
    def full_model_name(self) -> str:
        """获取完整模型名称（provider/model 格式）"""
        if self.deployment_name:
            return f"{self.model_provider}/{self.deployment_name}"
        return f"{self.model_provider}/{self.model_name}"


class LLM(abc.ABC):
    """LLM 抽象基类（参考 Onyx LLM ABC）

    所有 LLM 提供商实现都必须继承此类。
    提供统一的 invoke/stream 接口。
    """

    @property
    @abc.abstractmethod
    def config(self) -> LLMConfig:
        """获取 LLM 配置"""
        raise NotImplementedError

    @abc.abstractmethod
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
        """同步调用 LLM

        Args:
            prompt: 消息列表（字典格式）
            tools: 可用工具列表
            tool_choice: 工具选择策略
            structured_response_format: 结构化输出格式 (JSON Schema)
            timeout_override: 超时覆盖（秒）
            max_tokens: 最大输出 token 数
            reasoning_effort: 推理努力等级
            user_identity: 用户身份信息

        Returns:
            ModelResponse 对象
        """
        raise NotImplementedError

    @abc.abstractmethod
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
    ) -> Iterator[ModelResponseStream]:
        """流式调用 LLM

        参数同 invoke()。
        返回 Iterator[ModelResponseStream]。
        """
        raise NotImplementedError

    def supports_vision(self) -> bool:
        """检查是否支持视觉输入"""
        return False

    def supports_function_calling(self) -> bool:
        """检查是否支持函数调用"""
        return True

    def supports_streaming(self) -> bool:
        """检查是否支持流式输出"""
        return True

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(provider={self.config.model_provider}, model={self.config.model_name})"


# ---------------------------------------------------------------------------
# 响应模型（参考 Onyx ModelResponse/ModelResponseStream）
# ---------------------------------------------------------------------------

class Usage(BaseModel):
    """Token 使用统计"""
    prompt_tokens: int = Field(default=0, description="输入 token 数")
    completion_tokens: int = Field(default=0, description="输出 token 数")
    total_tokens: int = Field(default=0, description="总 token 数")
    cost_cents: float = Field(default=0.0, description="成本（美分）")


class ToolCall(BaseModel):
    """工具调用信息"""
    id: str = Field(description="工具调用 ID")
    name: str = Field(description="工具名称")
    arguments: str = Field(description="工具参数 (JSON 字符串)")


class Message(BaseModel):
    """LLM 响应消息"""
    role: str = Field(default="assistant")
    content: str | None = Field(default=None)
    tool_calls: list[ToolCall] | None = Field(default=None)
    finish_reason: str | None = Field(default=None)
    reasoning_content: str | None = Field(default=None, description="推理内容（如存在）")


class ModelResponse(BaseModel):
    """LLM 同步调用响应（参考 Onyx ModelResponse）"""
    id: str = Field(default="", description="响应 ID")
    model: str = Field(default="", description="使用的模型")
    choices: list[Message] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    created_at: int = Field(default=0, description="创建时间戳")

    @property
    def message(self) -> Message | None:
        """获取第一条消息"""
        return self.choices[0] if self.choices else None

    @property
    def content(self) -> str | None:
        """获取响应文本"""
        return self.message.content if self.message else None

    @property
    def tool_calls(self) -> list[ToolCall] | None:
        """获取工具调用列表"""
        return self.message.tool_calls if self.message else None


class ModelResponseStream(BaseModel):
    """LLM 流式响应块（参考 Onyx ModelResponseStream）"""
    id: str = Field(default="", description="响应 ID")
    model: str = Field(default="", description="使用的模型")
    delta: Message = Field(default_factory=lambda: Message(role="assistant"))
    usage: Usage | None = Field(default=None, description="仅在最后一个块出现")
    finish_reason: str | None = Field(default=None)

    @property
    def content(self) -> str | None:
        """获取增量文本"""
        return self.delta.content

    @property
    def is_last(self) -> bool:
        """是否是最后一个块"""
        return self.finish_reason is not None


__all__ = [
    "LLM",
    "LLMConfig",
    "LLMUserIdentity",
    "Message",
    "ModelResponse",
    "ModelResponseStream",
    "ReasoningEffort",
    "ToolCall",
    "ToolChoiceOptions",
    "Usage",
]

"""Weak Model Router — 从 Aider 借鉴的双模型调度系统

使用低成本模型（如 GPT-4o-mini）处理低复杂度任务：
- Commit message 生成
- 聊天历史压缩/摘要
- 代码 lint 反馈分析
- 错误分类

主模型处理需要高推理能力的任务（代码生成、架构设计等）。

用法:
    from src.llm.weak_model_router import WeakModelRouter

    router = WeakModelRouter(main_provider, weak_provider)
    message = await router.generate_commit_message(diff_text)
    summary = await router.summarize_chat(messages)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import BaseLLMProvider, LLMMessage

logger = logging.getLogger(__name__)


# 默认弱模型映射（借鉴 Aider 的 weak_model 设计）
# 每个主模型对应一个推荐的弱模型
DEFAULT_WEAK_MODEL_MAP: dict[str, str] = {
    # OpenAI
    'gpt-4o': 'gpt-4o-mini',
    'gpt-4-turbo': 'gpt-4o-mini',
    'gpt-4': 'gpt-3.5-turbo',
    'gpt-4.1': 'gpt-4o-mini',
    'o1': 'gpt-4o-mini',
    'o3': 'gpt-4o-mini',
    'o4-mini': 'gpt-4o-mini',
    # Anthropic
    'claude-3-5-sonnet-20241022': 'claude-3-haiku-20240307',
    'claude-3-5-sonnet-latest': 'claude-3-haiku-20240307',
    'claude-3-opus-20240229': 'claude-3-sonnet-20240229',
    'claude-sonnet-4-5': 'claude-haiku-4-5-20251001',
    'claude-opus-4-6': 'claude-sonnet-4-6',
    # Google
    'gemini-2.0-flash': 'gemini-2.0-flash-lite',
    'gemini-1.5-pro': 'gemini-1.5-flash',
    # DeepSeek
    'deepseek-reasoner': 'deepseek-chat',
    # Groq
    'llama-3.3-70b-versatile': 'llama-3.1-8b-instant',
}


@dataclass
class WeakModelConfig:
    """弱模型配置"""
    model_name: str
    provider: str  # LLM provider type
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 1024  # 弱模型通常不需要太多 token
    temperature: float = 0.3  # 低温度，更确定性


class WeakModelRouter:
    """弱模型路由器

    根据任务类型自动选择使用主模型还是弱模型：
    - 高推理任务（代码生成、架构设计）→ 主模型
    - 低推理任务（commit message、摘要、分类）→ 弱模型

    当弱模型不可用时，自动回退到主模型。
    """

    # 适合弱模型处理的任务类型
    WEAK_MODEL_TASKS = frozenset({
        'commit_message',
        'chat_summarize',
        'error_classify',
        'lint_analyze',
        'simple_question',
        'file_rename',
        'tag_extract',
    })

    def __init__(
        self,
        main_provider: BaseLLMProvider | None = None,
        weak_provider: BaseLLMProvider | None = None,
        main_model_name: str = '',
        weak_model_name: str | None = None,
    ) -> None:
        self._main_provider = main_provider
        self._weak_provider = weak_provider
        self._main_model_name = main_model_name
        self._weak_model_name = weak_model_name
        self._fallback_count = 0

        # 自动推断弱模型名称
        if not weak_model_name and main_model_name:
            self._weak_model_name = DEFAULT_WEAK_MODEL_MAP.get(
                main_model_name, 'gpt-4o-mini'
            )

    @property
    def has_weak_model(self) -> bool:
        """是否配置了弱模型"""
        return self._weak_provider is not None

    def get_weak_model_name(self) -> str:
        """获取弱模型名称"""
        return self._weak_model_name or 'gpt-4o-mini'

    def should_use_weak_model(self, task_type: str) -> bool:
        """判断任务是否应该使用弱模型

        Args:
            task_type: 任务类型

        Returns:
            True 如果应该使用弱模型
        """
        return task_type in self.WEAK_MODEL_TASKS and self.has_weak_model

    def set_weak_provider(self, provider: BaseLLMProvider) -> None:
        """设置弱模型 provider"""
        self._weak_provider = provider
        logger.info(f'弱模型已设置: {provider.__class__.__name__}')

    def get_provider(self, task_type: str) -> BaseLLMProvider:
        """根据任务类型获取合适的 provider

        Args:
            task_type: 任务类型

        Returns:
            LLM provider 实例
        """
        if self.should_use_weak_model(task_type):
            return self._weak_provider
        return self._main_provider

    async def generate_commit_message(self, diff_text: str) -> str:
        """使用弱模型生成 commit message

        借鉴 Aider 的 commit message 生成策略：
        - 分析 diff 内容
        - 生成简洁的 conventional commit 格式消息
        - 失败时回退到主模型

        Args:
            diff_text: git diff 内容

        Returns:
            commit message
        """
        from . import LLMMessage

        prompt = [
            LLMMessage(
                role='system',
                content=(
                    '你是一个 commit message 生成器。根据 git diff 生成简洁的 commit message。\n'
                    '格式要求：\n'
                    '- 使用 conventional commit 格式 (feat/fix/refactor/docs/test/chore)\n'
                    '- 第一行不超过 72 个字符\n'
                    '- 不要包含 diff 统计信息\n'
                    '- 用英文编写\n'
                ),
            ),
            LLMMessage(
                role='user',
                content=f'请为以下 diff 生成 commit message:\n\n{diff_text[:3000]}',
            ),
        ]

        return await self._call_with_fallback(prompt, 'commit_message')

    async def summarize_chat(self, messages: list[LLMMessage]) -> str:
        """使用弱模型压缩聊天历史

        Args:
            messages: 聊天消息列表

        Returns:
            压缩后的摘要
        """
        from . import LLMMessage

        history_text = ''
        for m in messages:
            content = m.content[:500] if len(m.content) > 500 else m.content
            history_text += f'{m.role.upper()}: {content}\n---\n'

        prompt = [
            LLMMessage(
                role='system',
                content=(
                    '你是一个对话摘要专家。将以下对话历史压缩为精炼的摘要。\n'
                    '保留：任务进度、关键发现、文件路径、重要参数。\n'
                    '丢弃：冗余工具输出、中间推理过程。\n'
                    '格式：<state_snapshot>摘要内容</state_snapshot>'
                ),
            ),
            LLMMessage(
                role='user',
                content=f'对话历史：\n\n{history_text[:4000]}',
            ),
        ]

        return await self._call_with_fallback(prompt, 'chat_summarize')

    async def classify_error(self, error_text: str) -> dict[str, Any]:
        """使用弱模型分类错误类型

        Args:
            error_text: 错误信息

        Returns:
            包含 category, severity, suggestion 的字典
        """
        from . import LLMMessage

        prompt = [
            LLMMessage(
                role='system',
                content=(
                    '你是一个错误分类专家。分析错误信息并返回 JSON 格式的分类结果。\n'
                    '{"category": "syntax|runtime|import|type|config|network", '
                    '"severity": "low|medium|high|critical", '
                    '"suggestion": "修复建议（一句话）"}'
                ),
            ),
            LLMMessage(
                role='user',
                content=f'错误信息：\n\n{error_text[:2000]}',
            ),
        ]

        result = await self._call_with_fallback(prompt, 'error_classify')

        try:
            import json
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return {
                'category': 'unknown',
                'severity': 'medium',
                'suggestion': result[:100],
            }

    async def _call_with_fallback(
        self,
        messages: list[LLMMessage],
        task_type: str,
    ) -> str:
        """使用弱模型调用，失败时回退到主模型

        Args:
            messages: 消息列表
            task_type: 任务类型

        Returns:
            模型响应文本
        """
        # 尝试弱模型
        if self.should_use_weak_model(task_type):
            try:
                provider = self.get_provider(task_type)
                response = await provider.chat(messages)
                return response.content
            except Exception as e:
                self._fallback_count += 1
                logger.warning(f'弱模型调用失败，回退到主模型 ({self._fallback_count}次): {e}')

        # 回退到主模型
        if self._main_provider:
            try:
                response = await self._main_provider.chat(messages)
                return response.content
            except Exception as e:
                logger.error(f'主模型也调用失败: {e}')
                return ''

        return ''

    def get_stats(self) -> dict[str, Any]:
        """获取路由统计"""
        return {
            'has_weak_model': self.has_weak_model,
            'weak_model_name': self._weak_model_name,
            'fallback_count': self._fallback_count,
        }


def auto_detect_weak_model(main_model: str) -> str:
    """自动为主模型选择合适的弱模型

    Args:
        main_model: 主模型名称

    Returns:
        推荐的弱模型名称
    """
    # 精确匹配
    if main_model in DEFAULT_WEAK_MODEL_MAP:
        return DEFAULT_WEAK_MODEL_MAP[main_model]

    # 模糊匹配（前缀匹配）
    for key, value in DEFAULT_WEAK_MODEL_MAP.items():
        if main_model.startswith(key):
            return value

    # 默认回退
    return 'gpt-4o-mini'


__all__ = [
    'DEFAULT_WEAK_MODEL_MAP',
    'WeakModelConfig',
    'WeakModelRouter',
    'auto_detect_weak_model',
]

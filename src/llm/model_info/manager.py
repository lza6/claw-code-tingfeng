"""模型信息管理器

集中管理模型元数据和设置。
支持从 litellm API / 远程 JSON 缓存动态获取模型价格信息。
"""
from __future__ import annotations

import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from .aliases import MODEL_ALIASES
from .builtins import BUILTIN_MODEL_INFO, BUILTIN_MODEL_SETTINGS
from .dataclasses import ModelInfo, ModelSettings

logger = logging.getLogger(__name__)


class ModelInfoManager:
    """模型信息管理器

    集中管理模型元数据和设置。
    支持从 litellm API / 远程 JSON 缓存动态获取模型价格信息。
    """

    # 远程价格数据库 URL (BerriAI/litellm)
    MODEL_INFO_URL = (
        'https://raw.githubusercontent.com/BerriAI/litellm/main/'
        'model_prices_and_context_window.json'
    )
    CACHE_TTL = 60 * 60 * 24  # 24 小时

    def __init__(self) -> None:
        self._model_info: dict[str, ModelInfo] = dict(BUILTIN_MODEL_INFO)
        self._model_settings: dict[str, ModelSettings] = {
            s.name: s for s in BUILTIN_MODEL_SETTINGS
        }

        # 远程价格缓存
        self._cache_dir = Path.home() / '.clawd' / 'caches'
        self._cache_file = self._cache_dir / 'model_prices_and_context_window.json'
        self._remote_content: dict[str, Any] | None = None
        self._cache_loaded = False
        self.verify_ssl = True

        # 尝试加载外部配置
        self._load_external_config()

    # ---------- 远程价格缓存 ----------

    def _load_remote_cache(self) -> None:
        """从本地缓存加载远程价格数据"""
        if self._cache_loaded:
            return
        self._cache_loaded = True

        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            if self._cache_file.exists():
                cache_age = time.time() - self._cache_file.stat().st_mtime
                if cache_age < self.CACHE_TTL:
                    self._remote_content = json.loads(
                        self._cache_file.read_text(encoding='utf-8')
                    )
                    logger.debug('Loaded model prices cache from %s', self._cache_file)
        except Exception as e:
            logger.debug('Failed to load remote cache: %s', e)

    def _update_remote_cache(self) -> None:
        """从远程 URL 更新价格缓存"""
        try:
            import urllib.request
            req = urllib.request.Request(
                self.MODEL_INFO_URL,
                headers={'User-Agent': 'ClawdCode/1.0'},
            )
            with urllib.request.urlopen(req, timeout=5, context=self._ssl_context()) as resp:
                self._remote_content = json.loads(resp.read().decode('utf-8'))
            with contextlib.suppress(OSError):
                self._cache_file.write_text(
                    json.dumps(self._remote_content), encoding='utf-8'
                )
        except Exception as e:
            logger.debug('Failed to update remote cache: %s', e)

    def _ssl_context(self) -> Any:
        """创建 SSL 上下文"""
        import ssl
        if not self.verify_ssl:
            return ssl._create_unverified_context()
        return None

    def _get_remote_model_info(self, model_name: str) -> dict[str, Any]:
        """从远程缓存获取模型信息"""
        self._load_remote_cache()

        if not self._remote_content:
            self._update_remote_cache()

        if not self._remote_content:
            return {}

        info = self._remote_content.get(model_name, {})
        if info:
            return info

        # 尝试 provider/model 格式
        if '/' in model_name:
            pieces = model_name.split('/')
            if len(pieces) == 2:
                info = self._remote_content.get(pieces[1], {})
                if info and info.get('litellm_provider') == pieces[0]:
                    return info

        return {}

    # ---------- 外部配置 ----------

    def _load_external_config(self) -> None:
        """加载外部模型配置文件"""
        for config_dir in [Path.cwd(), Path.home() / '.clawd']:
            config_path = config_dir / 'model-info.json'
            if config_path.exists():
                try:
                    data = json.loads(config_path.read_text(encoding='utf-8'))
                    for name, info in data.get('models', {}).items():
                        self._model_info[name] = ModelInfo(
                            name=name,
                            **{k: v for k, v in info.items() if k in ModelInfo.__dataclass_fields__},
                        )
                except Exception as e:
                    logger.warning(f'加载 model-info.json 失败: {e}')

    def resolve_alias(self, model_name: str) -> str:
        """解析模型别名

        参数:
            model_name: 模型名称或别名

        返回:
            规范化的模型名称
        """
        # 精确匹配
        if model_name in self._model_info:
            return model_name

        # 别名匹配
        alias_lower = model_name.lower().strip()
        if alias_lower in MODEL_ALIASES:
            return MODEL_ALIASES[alias_lower]

        # 尝试直接返回
        return model_name

    def get_model_info(self, model_name: str) -> ModelInfo:
        """获取模型信息（内置 → 远程 → 默认）

        参数:
            model_name: 模型名称

        返回:
            ModelInfo 对象
        """
        resolved = self.resolve_alias(model_name)
        if resolved in self._model_info:
            return self._model_info[resolved]

        # 尝试从远程价格数据库获取
        remote = self._get_remote_model_info(resolved)
        if remote:
            info = ModelInfo(name=resolved)
            if remote.get('max_input_tokens'):
                info.max_input_tokens = remote['max_input_tokens']
                info.context_window = remote['max_input_tokens']
            if remote.get('max_output_tokens'):
                info.max_output_tokens = remote['max_output_tokens']
            if remote.get('input_cost_per_token'):
                info.input_price_per_million = remote['input_cost_per_token'] * 1_000_000
            if remote.get('output_cost_per_token'):
                info.output_price_per_million = remote['output_cost_per_token'] * 1_000_000
            if remote.get('cache_read_input_token_cost'):
                info.cache_read_price_per_million = (
                    remote['cache_read_input_token_cost'] * 1_000_000
                )
            if remote.get('cache_creation_input_token_cost'):
                info.cache_write_price_per_million = (
                    remote['cache_creation_input_token_cost'] * 1_000_000
                )
            supports_vision = remote.get('supports_vision', False)
            supports_fc = remote.get('supports_function_calling', False)
            if isinstance(supports_vision, bool):
                info.supports_vision = supports_vision
            if isinstance(supports_fc, bool):
                info.supports_function_calling = supports_fc

            # 缓存到本地
            self._model_info[resolved] = info
            return info

        # 返回默认信息
        return ModelInfo(name=resolved)

    def get_model_settings(self, model_name: str) -> ModelSettings | None:
        """获取模型设置

        参数:
            model_name: 模型名称

        返回:
            ModelSettings 对象，或 None
        """
        resolved = self.resolve_alias(model_name)
        return self._model_settings.get(resolved)

    def get_edit_format(self, model_name: str) -> str:
        """获取模型推荐的编辑格式

        参数:
            model_name: 模型名称

        返回:
            编辑格式字符串
        """
        settings = self.get_model_settings(model_name)
        if settings:
            return settings.edit_format
        return 'diff'

    def get_weak_model(self, model_name: str) -> str | None:
        """获取弱模型推荐

        参数:
            model_name: 模型名称

        返回:
            弱模型名称，或 None
        """
        settings = self.get_model_settings(model_name)
        if settings and settings.weak_model_name:
            return settings.weak_model_name

        # 默认弱模型映射
        weak_map = {
            'claude-opus-4-6': 'claude-haiku-4-5',
            'claude-sonnet-4-5': 'claude-haiku-4-5',
            'gpt-4o': 'gpt-4o-mini',
        }
        resolved = self.resolve_alias(model_name)
        return weak_map.get(resolved)

    def validate_model(self, model_name: str) -> tuple[bool, str]:
        """验证模型名称

        参数:
            model_name: 模型名称

        返回:
            (是否有效, 错误描述)
        """
        resolved = self.resolve_alias(model_name)

        if resolved in self._model_info:
            return True, ''

        # 检查是否是有效的提供商/模型格式
        if '/' in resolved:
            provider, _ = resolved.split('/', 1)
            known_providers = ['openai', 'anthropic', 'google', 'deepseek', 'openrouter',
                             'ollama', 'groq', 'together', 'mistral', 'bedrock', 'vertex_ai']
            if provider in known_providers:
                return True, ''

        return False, f'未知模型: {model_name}'

    def list_models(self) -> list[str]:
        """列出所有已知模型"""
        return sorted(self._model_info.keys())

    def list_aliases(self) -> dict[str, str]:
        """列出所有别名映射"""
        return dict(MODEL_ALIASES)


# ==================== 全局实例 ====================

# 全局模型信息管理器
_model_info_manager: ModelInfoManager | None = None


def get_model_info_manager() -> ModelInfoManager:
    """获取全局模型信息管理器"""
    global _model_info_manager
    if _model_info_manager is None:
        _model_info_manager = ModelInfoManager()
    return _model_info_manager

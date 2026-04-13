"""Model Manager — 模型管理系统

借鉴 Aider 的模型配置系统，提供:
1. 100+ 模型支持
2. 模型别名映射
3. 模型 metadata 管理
4. Context window 和价格信息

使用:
    from src.llm.model_manager import ModelManager, get_model_manager

    mm = get_model_manager()
    model = mm.get_model("claude-sonnet-4-5")
    print(model.info.max_input_tokens)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from ..utils import get_logger

logger = get_logger(__name__)


# 模型元数据 (借鉴 Aider)
MODEL_METADATA_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

CACHE_TTL = 60 * 60 * 24  # 24 hours


@dataclass
class ModelInfo:
    """模型信息"""
    name: str
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    supports_vision: bool = False
    supports_function_calling: bool = False
    supports_caching: bool = False
    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0
    description: str = ""
    edit_format: str = "editblock"


@dataclass
class ModelConfig:
    """模型配置"""
    name: str
    edit_format: str = "editblock"
    weak_model_name: str | None = None
    use_repo_map: bool = False
    lazy: bool = False
    overeager: bool = False
    cache_control: bool = False
    streaming: bool = True
    reasoning_tag: str | None = None
    system_prompt_prefix: str | None = None


# 模型别名映射 (借鉴 Aider)
MODEL_ALIASES: dict[str, str] = {
    # Claude models
    "sonnet": "claude-sonnet-4-5",
    "sonnet4": "claude-sonnet-4-5",
    "haiku": "claude-haiku-4-5",
    "haiku4": "claude-haiku-4-5",
    "opus": "claude-opus-4-6",
    "opus4": "claude-opus-4-6",
    # GPT models
    "4": "gpt-4-0613",
    "4o": "gpt-4o",
    "4-turbo": "gpt-4-1106-preview",
    "35turbo": "gpt-3.5-turbo",
    "35-turbo": "gpt-3.5-turbo",
    "3": "gpt-3.5-turbo",
    "o1": "o1",
    "o1-mini": "o1-mini",
    "o3-mini": "o3-mini",
    # Other models
    "deepseek": "deepseek/deepseek-chat",
    "deepseek-r1": "deepseek/deepseek-reasoner",
    "flash": "gemini/gemini-flash-latest",
    "flash-lite": "gemini/gemini-2.5-flash-lite",
    "gemini": "gemini/gemini-3-pro-preview",
    "gemini-pro": "gemini/gemini-2.5-pro",
    "quasar": "openrouter/openrouter/quasar-alpha",
    "r1": "deepseek/deepseek-reasoner",
    "grok3": "xai/grok-3-beta",
    "optimus": "openrouter/openrouter/optimus-alpha",
}


# 预设模型列表 (来自 Aider)
OPENAI_MODELS = [
    "o1",
    "o1-preview",
    "o1-mini",
    "o3-mini",
    "gpt-4",
    "gpt-4o",
    "gpt-4o-2024-05-13",
    "gpt-4-turbo-preview",
    "gpt-4-0314",
    "gpt-4-0613",
    "gpt-4-32k",
    "gpt-4-32k-0314",
    "gpt-4-32k-0613",
    "gpt-4-turbo",
    "gpt-4-turbo-2024-04-09",
    "gpt-4-1106-preview",
    "gpt-4-0125-preview",
    "gpt-4-vision-preview",
    "gpt-4-1106-vision-preview",
    "gpt-4o-mini",
    "gpt-4o-mini-2024-07-18",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-0301",
    "gpt-3.5-turbo-0613",
    "gpt-3.5-turbo-1106",
    "gpt-3.5-turbo-0125",
    "gpt-3.5-turbo-16k",
    "gpt-3.5-turbo-16k-0613",
]

ANTHROPIC_MODELS = [
    "claude-2",
    "claude-2.1",
    "claude-3-haiku-20240307",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-5-sonnet-20240620",
    "claude-3-5-sonnet-20241022",
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-opus-4-6",
    "claude-sonnet-4-5",
    "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5",
    "claude-haiku-4-5-20251001",
]


class ModelManager:
    """模型管理器

    功能:
    - 模型别名解析
    - 模型元数据缓存
    - 模型配置管理
    - 弱模型路由
    """

    def __init__(self, cache_dir: Path | None = None):
        self._cache_dir = cache_dir or (Path.home() / ".clawd" / "caches")
        self._cache_file = self._cache_dir / "model_prices_and_context_window.json"
        self._model_metadata: dict = {}
        self._model_configs: dict[str, ModelConfig] = {}
        self._cache_loaded = False

        # 初始化默认配置
        self._init_default_configs()

    def _init_default_configs(self) -> None:
        """初始化默认模型配置 (借鉴 Aider)"""
        default_configs = {
            "claude-sonnet-4-5": ModelConfig(
                name="claude-sonnet-4-5",
                edit_format="editblock",
                cache_control=True,
                reasoning_tag="<thinking>",
            ),
            "claude-opus-4-6": ModelConfig(
                name="claude-opus-4-6",
                edit_format="editblock",
                cache_control=True,
                reasoning_tag="<thinking>",
            ),
            "claude-haiku-4-5": ModelConfig(
                name="claude-haiku-4-5",
                edit_format="editblock",
                cache_control=True,
            ),
            "gpt-4o": ModelConfig(
                name="gpt-4o",
                edit_format="editblock",
                use_repo_map=True,
            ),
            "gpt-4o-mini": ModelConfig(
                name="gpt-4o-mini",
                edit_format="wholefile",
                use_repo_map=True,
            ),
            "deepseek/deepseek-chat": ModelConfig(
                name="deepseek/deepseek-chat",
                edit_format="editblock",
                lazy=True,
            ),
            "deepseek/deepseek-reasoner": ModelConfig(
                name="deepseek/deepseek-reasoner",
                edit_format="editblock",
                reasoning_tag="<reasoning>",
            ),
        }

        for name, config in default_configs.items():
            self._model_configs[name] = config

    def resolve_alias(self, model_name: str) -> str:
        """解析模型别名

        Args:
            model_name: 模型名称或别名

        Returns:
            规范化的模型名称
        """
        return MODEL_ALIASES.get(model_name, model_name)

    def get_model_config(self, model_name: str) -> ModelConfig:
        """获取模型配置

        Args:
            model_name: 模型名称

        Returns:
            ModelConfig 对象
        """
        # 解析别名
        resolved = self.resolve_alias(model_name)

        # 返回配置或默认
        if resolved in self._model_configs:
            return self._model_configs[resolved]

        # 创建默认配置
        return ModelConfig(
            name=resolved,
            edit_format="editblock",
        )

    def get_model_info(self, model_name: str) -> ModelInfo | None:
        """获取模型信息 (从缓存)

        Args:
            model_name: 模型名称

        Returns:
            ModelInfo 或 None
        """
        # 解析别名
        resolved = self.resolve_alias(model_name)

        # 尝试从缓存获取
        if not self._cache_loaded:
            self._load_cache()

        if resolved in self._model_metadata:
            data = self._model_metadata[resolved]
            return ModelInfo(
                name=resolved,
                max_input_tokens=data.get("max_input_tokens", 0),
                max_output_tokens=data.get("max_output_tokens", 0),
                supports_vision=data.get("supports_vision", False),
                input_cost_per_token=data.get("input_cost_per_token", 0.0),
                output_cost_per_token=data.get("output_cost_per_token", 0.0),
                description=data.get("description", ""),
            )

        return None

    def list_models(self, provider: str | None = None) -> list[str]:
        """列出支持的模型

        Args:
            provider: 可选的 provider 过滤

        Returns:
            模型列表
        """
        models = list(MODEL_ALIASES.keys())

        if provider == "openai":
            models = [m for m in models if "gpt" in m.lower() or m in OPENAI_MODELS]
        elif provider == "anthropic":
            models = [m for m in models if "claude" in m.lower() or m in ANTHROPIC_MODELS]
        elif provider == "deepseek":
            models = [m for m in models if "deepseek" in m.lower()]

        return sorted(set(models))

    def get_edit_format(self, model_name: str) -> str:
        """获取模型的编辑格式

        Args:
            model_name: 模型名称

        Returns:
            编辑格式
        """
        config = self.get_model_config(model_name)
        return config.edit_format

    def supports_caching(self, model_name: str) -> bool:
        """检查模型是否支持缓存

        Args:
            model_name: 模型名称

        Returns:
            是否支持
        """
        config = self.get_model_config(model_name)
        return config.cache_control

    def get_weak_model(self, model_name: str) -> str | None:
        """获取模型的弱模型

        Args:
            model_name: 模型名称

        Returns:
            弱模型名称或 None
        """
        config = self.get_model_config(model_name)
        return config.weak_model_name

    # ---------- 缓存管理 ----------

    def _load_cache(self) -> None:
        """加载模型元数据缓存"""
        if self._cache_loaded:
            return

        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            if self._cache_file.exists():
                cache_age = time.time() - self._cache_file.stat().st_mtime
                if cache_age < CACHE_TTL:
                    try:
                        self._model_metadata = json.loads(
                            self._cache_file.read_text(encoding='utf-8')
                        )
                        logger.debug(f"Loaded {len(self._model_metadata)} models from cache")
                    except json.JSONDecodeError:
                        logger.warning("Model metadata cache corrupted")
        except OSError as e:
            logger.debug(f"Cannot load model cache: {e}")

        self._cache_loaded = True

    def update_cache(self, force: bool = False) -> None:
        """更新模型元数据缓存

        Args:
            force: 强制更新
        """
        if not force:
            self._load_cache()
            if self._model_metadata:
                return

        try:
            import requests
            response = requests.get(MODEL_METADATA_URL, timeout=10)
            if response.status_code == 200:
                self._model_metadata = response.json()
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                self._cache_file.write_text(
                    json.dumps(self._model_metadata, indent=2),
                    encoding='utf-8'
                )
                logger.info(f"Updated model metadata: {len(self._model_metadata)} models")
        except Exception as e:
            logger.warning(f"Failed to update model cache: {e}")

    def clear_cache(self) -> None:
        """清除模型元数据缓存"""
        try:
            if self._cache_file.exists():
                self._cache_file.unlink()
                logger.info("Model cache cleared")
        except Exception as e:
            logger.warning(f"Failed to clear cache: {e}")


# 全局实例
_model_manager: ModelManager | None = None


def get_model_manager() -> ModelManager:
    """获取全局 ModelManager 实例"""
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager

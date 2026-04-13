"""Model Metadata — 模型元数据（扩展自 Onyx model_metadata_enrichments.json）"""

import json
from pathlib import Path


class ModelMetadata:
    """模型元数据管理器"""

    def __init__(self, metadata_file: Path | None = None):
        self._metadata: dict = {}
        if metadata_file and metadata_file.exists():
            self._load_from_file(metadata_file)

    def _load_from_file(self, path: Path):
        """从文件加载元数据"""
        with open(path, encoding="utf-8") as f:
            self._metadata = json.load(f)

    def _load_default(self):
        """加载默认元数据"""
        # Claude models
        self._metadata = {
            "claude-3-5-sonnet-6-20241022": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "supports_vision": True,
                "supports_function_calling": True,
                "supports_caching": True,
                "input_cost_per_token": 0.000003,
                "output_cost_per_token": 0.000015,
                "description": "Claude Sonnet 4.5 - Balanced",
            },
            "claude-3-5-sonnet-6-20241022": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "supports_vision": True,
                "supports_function_calling": True,
                "supports_caching": True,
                "input_cost_per_token": 0.000003,
                "output_cost_per_token": 0.000015,
            },
            "claude-sonnet-4-5": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "supports_vision": True,
                "supports_function_calling": True,
                "supports_caching": True,
                "input_cost_per_token": 0.000003,
                "output_cost_per_token": 0.000015,
            },
            "claude-haiku-4-5": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "supports_vision": True,
                "supports_function_calling": True,
                "supports_caching": True,
                "input_cost_per_token": 0.00000025,
                "output_cost_per_token": 0.00000125,
            },
            "claude-opus-4-6": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "supports_vision": True,
                "supports_function_calling": True,
                "supports_caching": True,
                "input_cost_per_token": 0.000015,
                "output_cost_per_token": 0.000075,
            },
            # GPT models
            "gpt-4o": {
                "max_input_tokens": 128000,
                "max_output_tokens": 16384,
                "supports_vision": True,
                "supports_function_calling": True,
                "input_cost_per_token": 0.0000025,
                "output_cost_per_token": 0.00001,
            },
            "gpt-4o-mini": {
                "max_input_tokens": 128000,
                "max_output_tokens": 16384,
                "supports_vision": True,
                "supports_function_calling": True,
                "input_cost_per_token": 0.00000015,
                "output_cost_per_token": 0.0000006,
            },
            # DeepSeek
            "deepseek-chat": {
                "max_input_tokens": 64000,
                "max_output_tokens": 8192,
                "supports_function_calling": True,
                "input_cost_per_token": 0.00000014,
                "output_cost_per_token": 0.00000028,
            },
            "deepseek-coder": {
                "max_input_tokens": 64000,
                "max_output_tokens": 8192,
                "input_cost_per_token": 0.00000014,
                "output_cost_per_token": 0.00000028,
            },
            # Qwen
            "qwen-turbo": {
                "max_input_tokens": 100000,
                "max_output_tokens": 8000,
                "supports_function_calling": True,
                "input_cost_per_token": 0.0000002,
                "output_cost_per_token": 0.0000006,
            },
            "qwen-plus": {
                "max_input_tokens": 30000,
                "max_output_tokens": 8000,
                "supports_function_calling": True,
                "input_cost_per_token": 0.0000004,
                "output_cost_per_token": 0.0000012,
            },
            "qwen-max": {
                "max_input_tokens": 30000,
                "max_output_tokens": 8000,
                "input_cost_per_token": 0.000002,
                "output_cost_per_token": 0.000006,
            },
            # Mistral
            "mistral-large": {
                "max_input_tokens": 128000,
                "max_output_tokens": 32000,
                "supports_function_calling": True,
                "input_cost_per_token": 0.000002,
                "output_cost_per_token": 0.000006,
            },
            "mistral-small": {
                "max_input_tokens": 128000,
                "max_output_tokens": 32000,
                "supports_function_calling": True,
                "input_cost_per_token": 0.0000002,
                "output_cost_per_token": 0.0000006,
            },
            # Gemini
            "gemini-1.5-pro": {
                "max_input_tokens": 200000,
                "max_output_tokens": 8192,
                "supports_vision": True,
                "supports_function_calling": True,
                "input_cost_per_token": 0.00000125,
                "output_cost_per_token": 0.000005,
            },
            "gemini-1.5-flash": {
                "max_input_tokens": 1000000,
                "max_output_tokens": 8192,
                "supports_vision": True,
                "supports_function_calling": True,
                "input_cost_per_token": 0.000000075,
                "output_cost_per_token": 0.0000003,
            },
        }

    def get(self, model_name: str) -> dict | None:
        """获取模型元数据"""
        # 尝试直接匹配
        if model_name in self._metadata:
            return self._metadata[model_name]

        # 尝试别名匹配
        for key, meta in self._metadata.items():
            if model_name.lower().startswith(key.lower()):
                return meta

        return None

    def get_max_input_tokens(self, model_name: str) -> int:
        """获取最大输入 token"""
        meta = self.get(model_name)
        return meta.get("max_input_tokens", 4096) if meta else 4096

    def get_max_output_tokens(self, model_name: str) -> int:
        """获取最大输出 token"""
        meta = self.get(model_name)
        return meta.get("max_output_tokens", 4096) if meta else 4096

    def supports_vision(self, model_name: str) -> bool:
        """是否支持视觉"""
        meta = self.get(model_name)
        return meta.get("supports_vision", False) if meta else False

    def supports_function_calling(self, model_name: str) -> bool:
        """是否支持函数调用"""
        meta = self.get(model_name)
        return meta.get("supports_function_calling", False) if meta else False

    def get_cost(self, model_name: str) -> tuple[float, float]:
        """获取成本 (input, output) per token"""
        meta = self.get(model_name)
        if meta:
            return (
                meta.get("input_cost_per_token", 0.0),
                meta.get("output_cost_per_token", 0.0)
            )
        return (0.0, 0.0)

    def list_all_models(self) -> list[str]:
        """列出所有模型"""
        return list(self._metadata.keys())


# 全局实例
_model_metadata: ModelMetadata | None = None


def get_model_metadata() -> ModelMetadata:
    """获取全局模型元数据"""
    global _model_metadata
    if _model_metadata is None:
        _model_metadata = ModelMetadata()
        _model_metadata._load_default()
    return _model_metadata


__all__ = ["ModelMetadata", "get_model_metadata"]

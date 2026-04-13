"""OpenRouter Model Manager — 从 Aider openrouter.py 移植

提供 OpenRouter 模型元数据缓存和查询功能。

使用:
    from src.llm.openrouter_manager import OpenRouterModelManager

    mgr = OpenRouterModelManager()
    info = mgr.get_model_info("openrouter/anthropic/claude-3-sonnet")
    print(info)
"""
from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any

import requests


def _cost_per_token(val: str | None) -> float | None:
    """将价格字符串转换为浮点数"""
    if val in (None, "", "0"):
        return 0.0 if val == "0" else None
    try:
        return float(val)
    except Exception:
        return None


class OpenRouterModelManager:
    """OpenRouter 模型管理器

    功能:
    - 本地缓存 OpenRouter 模型列表
    - 模型元数据查询（context length, pricing）
    - 24 小时缓存 TTL
    - SSL 验证控制
    """

    MODELS_URL = "https://openrouter.ai/api/v1/models"
    CACHE_TTL = 60 * 60 * 24  # 24 hours

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".clawd" / "caches"

        self.cache_file = self.cache_dir / "openrouter_models.json"
        self.content: dict | None = None
        self.verify_ssl: bool = True
        self._cache_loaded: bool = False

    def set_verify_ssl(self, verify_ssl: bool) -> None:
        """启用/禁用 SSL 验证"""
        self.verify_ssl = verify_ssl

    def get_model_info(self, model: str) -> dict[str, Any]:
        """获取模型元数据

        参数:
            model: 模型名称，使用 aider 命名约定，如 "openrouter/nousresearch/deephermes-3-mistral-24b-preview:free"

        返回:
            模型元数据字典，包含 max_input_tokens, pricing 等信息
        """
        self._ensure_content()
        if not self.content or "data" not in self.content:
            return {}

        route = self._strip_prefix(model)

        # 同时考虑精确匹配和不含 :suffix 的匹配
        candidates = {route}
        if ":" in route:
            candidates.add(route.split(":", 1)[0])

        record = next(
            (item for item in self.content["data"] if item.get("id") in candidates), None
        )
        if not record:
            return {}

        context_len = (
            record.get("top_provider", {}).get("context_length")
            or record.get("context_length")
            or None
        )

        pricing = record.get("pricing", {})
        return {
            "max_input_tokens": context_len,
            "max_tokens": context_len,
            "max_output_tokens": context_len,
            "input_cost_per_token": _cost_per_token(pricing.get("prompt")),
            "output_cost_per_token": _cost_per_token(pricing.get("completion")),
            "litellm_provider": "openrouter",
        }

    def _strip_prefix(self, model: str) -> str:
        """去除 openrouter/ 前缀"""
        return model[len("openrouter/") :] if model.startswith("openrouter/") else model

    def _ensure_content(self) -> None:
        """确保缓存内容已加载"""
        self._load_cache()
        if not self.content:
            self._update_cache()

    def _load_cache(self) -> None:
        """从本地文件加载缓存"""
        if self._cache_loaded:
            return

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            if self.cache_file.exists():
                cache_age = time.time() - self.cache_file.stat().st_mtime
                if cache_age < self.CACHE_TTL:
                    try:
                        self.content = json.loads(self.cache_file.read_text())
                    except json.JSONDecodeError:
                        self.content = None
        except OSError:
            # 缓存目录可能不可写
            pass

        self._cache_loaded = True

    def _update_cache(self) -> None:
        """从网络更新缓存"""
        try:
            response = requests.get(self.MODELS_URL, timeout=10, verify=self.verify_ssl)
            if response.status_code == 200:
                self.content = response.json()
                try:
                    self.cache_file.write_text(json.dumps(self.content, indent=2))
                except OSError:
                    pass  # 不可写时忽略
        except Exception as e:
            print(f"Failed to fetch OpenRouter model list: {e}")
            with contextlib.suppress(OSError):
                self.cache_file.write_text("{}")

    def clear_cache(self) -> None:
        """清除缓存文件"""
        if self.cache_file.exists():
            self.cache_file.unlink()
        self._cache_loaded = False
        self.content = None


# 全局实例
_openrouter_manager: OpenRouterModelManager | None = None


def get_openrouter_manager() -> OpenRouterModelManager:
    """获取全局 OpenRouter 模型管理器实例"""
    global _openrouter_manager
    if _openrouter_manager is None:
        _openrouter_manager = OpenRouterModelManager()
    return _openrouter_manager


__all__ = [
    "OpenRouterModelManager",
    "get_openrouter_manager",
]

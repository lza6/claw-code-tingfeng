"""
Dynamic Pricing Service - 动态定价服务（整合自 New-API）
支持多种计费模式：倍率/固定价格/Prompt Cache/多媒体
线程安全，带缓存机制
"""

import threading
from dataclasses import dataclass

from loguru import logger


@dataclass
class PricingConfig:
    """定价配置"""
    # 基础倍率（默认 1.0）
    base_ratio: float = 1.0

    # 固定价格模式
    fixed_price: float | None = None  # 每 1K tokens 的价格

    # Prompt Cache 定价
    cache_input_ratio: float = 0.1  # 缓存命中输入倍率（通常更便宜）
    cache_creation_ratio: float = 1.2  # 缓存创建倍率（通常更贵）

    # 多媒体定价（每单位 tokens）
    image_price: float = 0.0  # 图片定价
    audio_input_price: float = 0.0  # 音频输入定价
    audio_output_price: float = 0.0  # 音频输出定价
    video_price: float = 0.0  # 视频定价


class PricingService:
    """
    动态定价服务（整合自 New-API）

    功能:
    - 支持倍率/固定价格两种模式
    - Prompt Cache 定价
    - 多媒体定价（图像/音频/视频）
    - 线程安全的 RLock 缓存
    """

    def __init__(self):
        # 模型定价配置缓存
        self._pricing_cache: dict[str, PricingConfig] = {}
        self._lock = threading.RLock()

        # 默认倍率
        self._default_ratio = 1.0

        logger.info("动态定价服务已初始化")

    def set_model_pricing(
        self,
        model: str,
        base_ratio: float = 1.0,
        fixed_price: float | None = None,
        cache_input_ratio: float = 0.1,
        cache_creation_ratio: float = 1.2,
        image_price: float = 0.0,
        audio_input_price: float = 0.0,
        audio_output_price: float = 0.0,
        video_price: float = 0.0,
    ):
        """
        设置模型定价

        Args:
            model: 模型名称
            base_ratio: 基础倍率
            fixed_price: 固定价格（覆盖倍率）
            cache_input_ratio: 缓存命中输入倍率
            cache_creation_ratio: 缓存创建倍率
            image_price: 图片定价
            audio_input_price: 音频输入定价
            audio_output_price: 音频输出定价
            video_price: 视频定价
        """
        with self._lock:
            config = PricingConfig(
                base_ratio=base_ratio,
                fixed_price=fixed_price,
                cache_input_ratio=cache_input_ratio,
                cache_creation_ratio=cache_creation_ratio,
                image_price=image_price,
                audio_input_price=audio_input_price,
                audio_output_price=audio_output_price,
                video_price=video_price,
            )
            self._pricing_cache[model] = config
            logger.debug(f"设置模型定价: {model} (ratio={base_ratio}, fixed={fixed_price})")

    def get_model_pricing(self, model: str) -> PricingConfig:
        """
        获取模型定价配置

        Args:
            model: 模型名称

        Returns:
            定价配置
        """
        with self._lock:
            # 精确匹配
            if model in self._pricing_cache:
                return self._pricing_cache[model]

            # 前缀匹配
            for model_prefix, config in self._pricing_cache.items():
                if model.startswith(model_prefix):
                    return config

            # 返回默认配置
            return PricingConfig(base_ratio=self._default_ratio)

    def calculate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int = 0,
        cache_hit_tokens: int = 0,
        cache_creation_tokens: int = 0,
        image_count: int = 0,
        audio_input_seconds: int = 0,
        audio_output_seconds: int = 0,
        video_seconds: int = 0,
    ) -> float:
        """
        计算请求成本

        Args:
            model: 模型名称
            prompt_tokens: 输入 tokens
            completion_tokens: 输出 tokens
            cache_hit_tokens: 缓存命中 tokens
            cache_creation_tokens: 缓存创建 tokens
            image_count: 图片数量
            audio_input_seconds: 音频输入秒数
            audio_output_seconds: 音频输出秒数
            video_seconds: 视频秒数

        Returns:
            成本（配额单位）
        """
        pricing = self.get_model_pricing(model)

        # 基础成本
        if pricing.fixed_price is not None:
            # 固定价格模式
            total_tokens = prompt_tokens + completion_tokens
            base_cost = (total_tokens / 1000.0) * pricing.fixed_price
        else:
            # 倍率模式
            base_cost = (prompt_tokens + completion_tokens) * pricing.base_ratio

        # Cache 定价调整
        cache_cost = 0.0
        if cache_hit_tokens > 0:
            cache_cost += cache_hit_tokens * pricing.base_ratio * pricing.cache_input_ratio
        if cache_creation_tokens > 0:
            cache_cost += cache_creation_tokens * pricing.base_ratio * pricing.cache_creation_ratio

        # 多媒体定价
        media_cost = 0.0
        if image_count > 0:
            media_cost += image_count * pricing.image_price
        if audio_input_seconds > 0:
            media_cost += audio_input_seconds * pricing.audio_input_price
        if audio_output_seconds > 0:
            media_cost += audio_output_seconds * pricing.audio_output_price
        if video_seconds > 0:
            media_cost += video_seconds * pricing.video_price

        total_cost = base_cost + cache_cost + media_cost

        logger.debug(
            f"计算成本: {model} "
            f"(prompt={prompt_tokens}, completion={completion_tokens}, "
            f"cache_hit={cache_hit_tokens}, cache_creation={cache_creation_tokens}, "
            f"images={image_count}, cost={total_cost:.2f})"
        )

        return total_cost

    def estimate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int = 0,
    ) -> float:
        """
        快速估算成本（不包含 cache 和多媒体）

        Args:
            model: 模型名称
            prompt_tokens: 输入 tokens
            completion_tokens: 输出 tokens

        Returns:
            估算成本
        """
        return self.calculate_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def set_default_ratio(self, ratio: float):
        """
        设置默认倍率

        Args:
            ratio: 默认倍率
        """
        with self._lock:
            self._default_ratio = ratio
            logger.info(f"设置默认倍率: {ratio}")

    def get_default_ratio(self) -> float:
        """获取默认倍率"""
        with self._lock:
            return self._default_ratio

    def clear_cache(self):
        """清空定价缓存"""
        with self._lock:
            self._pricing_cache.clear()
            logger.info("定价缓存已清空")

    def get_all_pricing(self) -> dict[str, PricingConfig]:
        """
        获取所有定价配置

        Returns:
            定价配置字典
        """
        with self._lock:
            return self._pricing_cache.copy()


# 全局单例
_pricing_service = PricingService()


def get_pricing_service() -> PricingService:
    """获取定价服务单例"""
    return _pricing_service


def calculate_model_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int = 0,
    **kwargs
) -> float:
    """
    快捷函数：计算模型成本

    Args:
        model: 模型名称
        prompt_tokens: 输入 tokens
        completion_tokens: 输出 tokens
        **kwargs: 其他参数（cache_hit_tokens 等）

    Returns:
        成本
    """
    return _pricing_service.calculate_cost(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        **kwargs
    )


def set_model_pricing(model: str, **kwargs):
    """
    快捷函数：设置模型定价

    Args:
        model: 模型名称
        **kwargs: 定价参数
    """
    _pricing_service.set_model_pricing(model, **kwargs)

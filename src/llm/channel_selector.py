"""
Channel Selector - 渠道选择器（整合自 New-API）
支持优先级分组 + 权重随机负载均衡 + 重试降级
适用于多 LLM Provider 场景的智能路由选择
"""

import random
import threading
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class ChannelInfo:
    """渠道信息"""
    id: str
    name: str
    provider: str  # LLM Provider (openai, anthropic, gemini, etc.)
    base_url: str
    models: list[str]  # 支持的模型列表
    weight: int = 1  # 权重
    priority: int = 0  # 优先级（越高越优先）
    status: int = 1  # 状态: 1=启用, 0=禁用
    retry_count: int = 0  # 重试计数
    response_time: float = 0.0  # 响应时间（EMA）

    # 多Key支持
    keys: list[str] = field(default_factory=list)
    is_multi_key: bool = False
    multi_key_mode: str = "random"  # random, polling
    multi_key_polling_index: int = 0

    @property
    def is_enabled(self) -> bool:
        return self.status == 1

    def get_next_key(self) -> str | None:
        """
        获取下一个 API Key（多Key支持）

        Returns:
            API Key 字符串
        """
        if not self.keys:
            return None

        if not self.is_multi_key:
            return self.keys[0]

        if self.multi_key_mode == "polling":
            # 轮询模式
            key = self.keys[self.multi_key_polling_index % len(self.keys)]
            self.multi_key_polling_index += 1
            return key
        else:
            # 随机模式
            return random.choice(self.keys)


class ChannelSelector:
    """
    渠道选择器（整合自 New-API）

    功能:
    - 按优先级分组
    - 同组内权重随机负载均衡
    - 失败自动降级到下一优先级
    - 平滑因子调整避免低权重渠道饥饿
    """

    def __init__(self):
        self._channels: dict[str, ChannelInfo] = {}
        self._lock = threading.RLock()

        # 模型 -> 渠道ID列表（按优先级排序）
        self._model_channels: dict[str, list[str]] = {}

        logger.info("渠道选择器已初始化")

    def add_channel(self, channel: ChannelInfo):
        """
        添加渠道

        Args:
            channel: 渠道信息
        """
        with self._lock:
            self._channels[channel.id] = channel

            # 更新模型映射
            for model in channel.models:
                if model not in self._model_channels:
                    self._model_channels[model] = []

                if channel.id not in self._model_channels[model]:
                    self._model_channels[model].append(channel.id)

            # 按优先级排序
            self._sort_channels()

            logger.info(f"添加渠道: {channel.name} (provider={channel.provider}, priority={channel.priority}, weight={channel.weight})")

    def remove_channel(self, channel_id: str):
        """
        移除渠道

        Args:
            channel_id: 渠道ID
        """
        with self._lock:
            if channel_id in self._channels:
                channel = self._channels.pop(channel_id)

                # 从映射中移除
                for model in channel.models:
                    if model in self._model_channels:
                        self._model_channels[model] = [
                            cid for cid in self._model_channels[model]
                            if cid != channel_id
                        ]

                logger.info(f"移除渠道: {channel.name}")

    def update_channel_status(self, channel_id: str, status: int):
        """
        更新渠道状态

        Args:
            channel_id: 渠道ID
            status: 新状态
        """
        with self._lock:
            if channel_id in self._channels:
                old_status = self._channels[channel_id].status
                self._channels[channel_id].status = status

                if status != 1 and old_status == 1:
                    logger.warning(f"渠道 {channel_id} 被禁用")

    def select_channel(
        self,
        model: str,
        retry: int = 0
    ) -> ChannelInfo | None:
        """
        选择合适的渠道

        Args:
            model: 模型名称
            retry: 重试次数（用于降级到下一优先级）

        Returns:
            渠道信息，如果没有可用渠道返回 None
        """
        with self._lock:
            # 精确匹配
            channel_ids = self._model_channels.get(model, [])

            # 如果没有找到，尝试前缀匹配
            if not channel_ids:
                for available_model in self._model_channels:
                    if model.startswith(available_model) or available_model.startswith(model):
                        channel_ids = self._model_channels[available_model]
                        break

            if not channel_ids:
                logger.warning(f"没有找到模型 {model} 的可用渠道")
                return None

            # 获取唯一优先级列表
            unique_priorities = set()
            for cid in channel_ids:
                if cid in self._channels:
                    channel = self._channels[cid]
                    if channel.is_enabled:
                        unique_priorities.add(channel.priority)

            sorted_priorities = sorted(unique_priorities, reverse=True)

            if not sorted_priorities:
                logger.warning(f"模型 {model} 没有启用的渠道")
                return None

            # 根据重试次数选择优先级（失败降级）
            if retry >= len(sorted_priorities):
                retry = len(sorted_priorities) - 1

            target_priority = sorted_priorities[retry]

            # 筛选该优先级的渠道
            target_channels = [
                self._channels[cid]
                for cid in channel_ids
                if cid in self._channels and
                   self._channels[cid].is_enabled and
                   self._channels[cid].priority == target_priority
            ]

            if not target_channels:
                logger.warning(f"优先级 {target_priority} 没有可用渠道")
                return None

            # 权重随机选择
            selected = self._weighted_random_select(target_channels)

            if selected:
                logger.debug(
                    f"选择渠道: {selected.name} "
                    f"(model={model}, priority={selected.priority}, weight={selected.weight})"
                )

            return selected

    def _weighted_random_select(self, channels: list[ChannelInfo]) -> ChannelInfo | None:
        """
        根据权重随机选择渠道（带平滑因子）

        Args:
            channels: 候选渠道列表

        Returns:
            选中的渠道
        """
        if not channels:
            return None

        if len(channels) == 1:
            return channels[0]

        # 计算总权重
        total_weight = sum(ch.weight for ch in channels)

        if total_weight == 0:
            # 所有权重为0，均匀随机
            return random.choice(channels)

        # 平滑因子：低权重渠道获得额外调整，避免饥饿
        smoothing_factor = 1
        smoothing_adjustment = 0

        avg_weight = total_weight / len(channels)
        if avg_weight < 10:
            smoothing_factor = 100

        total_weight_smooth = total_weight * smoothing_factor

        # 随机选择
        random_weight = random.randint(0, total_weight_smooth - 1)

        for channel in channels:
            effective_weight = channel.weight * smoothing_factor + smoothing_adjustment
            random_weight -= effective_weight
            if random_weight < 0:
                return channel

        # 兜底
        return channels[-1]

    def _sort_channels(self):
        """按优先级和权重排序渠道"""
        for model in self._model_channels:
            channel_ids = self._model_channels[model]
            channel_ids.sort(
                key=lambda cid: (
                    self._channels[cid].priority if cid in self._channels else 0,
                    self._channels[cid].weight if cid in self._channels else 0
                ),
                reverse=True
            )

    def update_response_time(self, channel_id: str, response_time: float):
        """
        更新渠道响应时间（使用 EMA 平滑）

        Args:
            channel_id: 渠道ID
            response_time: 新的响应时间
        """
        with self._lock:
            if channel_id in self._channels:
                channel = self._channels[channel_id]

                # EMA（指数移动平均）
                alpha = 0.3  # 平滑系数：新数据占30%，历史占70%
                if channel.response_time == 0:
                    channel.response_time = response_time
                else:
                    channel.response_time = alpha * response_time + (1 - alpha) * channel.response_time

    def get_all_channels(self) -> list[ChannelInfo]:
        """获取所有渠道"""
        with self._lock:
            return list(self._channels.values())

    def get_channels_by_model(self, model: str) -> list[ChannelInfo]:
        """
        获取支持指定模型的所有渠道

        Args:
            model: 模型名称

        Returns:
            渠道列表
        """
        with self._lock:
            channel_ids = self._model_channels.get(model, [])
            return [
                self._channels[cid]
                for cid in channel_ids
                if cid in self._channels
            ]

    def get_stats(self) -> dict[str, Any]:
        """获取渠道统计"""
        with self._lock:
            total = len(self._channels)
            enabled = sum(1 for ch in self._channels.values() if ch.is_enabled)

            return {
                "total_channels": total,
                "enabled_channels": enabled,
                "disabled_channels": total - enabled,
                "total_models": len(self._model_channels),
            }


# 全局单例
_channel_selector = ChannelSelector()


def get_channel_selector() -> ChannelSelector:
    """获取渠道选择器单例"""
    return _channel_selector


def select_channel(model: str, retry: int = 0) -> ChannelInfo | None:
    """
    快捷函数：选择渠道

    Args:
        model: 模型名称
        retry: 重试次数

    Returns:
        渠道信息
    """
    return _channel_selector.select_channel(model, retry)


def add_channel(channel: ChannelInfo):
    """
    快捷函数：添加渠道

    Args:
        channel: 渠道信息
    """
    _channel_selector.add_channel(channel)

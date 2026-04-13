"""
配额管理器 - 整合自 New-API
支持 Token 配额检查、扣减、增加、查询
"""

from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass
class QuotaInfo:
    """配额信息"""
    total_quota: int = 0  # 总额度
    used_quota: int = 0  # 已用额度
    remaining_quota: int = 0  # 剩余额度

    @property
    def is_unlimited(self) -> bool:
        """是否无限额度"""
        return self.total_quota <= 0

    @property
    def usage_percentage(self) -> float:
        """使用百分比"""
        if self.is_unlimited:
            return 0.0
        if self.total_quota == 0:
            return 100.0
        return (self.used_quota / self.total_quota) * 100

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "total_quota": self.total_quota,
            "used_quota": self.used_quota,
            "remaining_quota": self.remaining_quota,
            "is_unlimited": self.is_unlimited,
            "usage_percentage": round(self.usage_percentage, 2)
        }


# 模型倍率配置（整合自 New-API）
MODEL_RATIO = {
    # GPT-4 系列
    "gpt-4": 15.0,
    "gpt-4-32k": 30.0,
    "gpt-4o": 15.0,
    "gpt-4o-mini": 5.0,
    "gpt-4-turbo": 10.0,
    "gpt-4-vision": 15.0,

    # GPT-3.5 系列
    "gpt-3.5-turbo": 0.75,
    "gpt-3.5-turbo-16k": 1.5,

    # Claude 系列
    "claude-3-opus": 45.0,
    "claude-3-sonnet": 7.5,
    "claude-3-haiku": 1.25,
    "claude-3.5-sonnet": 10.0,

    # Gemini 系列
    "gemini-pro": 1.0,
    "gemini-1.5-pro": 7.5,
    "gemini-1.5-flash": 2.5,

    # 其他模型
    "deepseek-chat": 1.0,
    "mistral-large": 5.0,
    "llama-3-70b": 3.0,
    "llama-3-8b": 1.0,
}

# 默认倍率
DEFAULT_RATIO = 1.0


def get_model_ratio(model: str) -> float:
    """
    获取模型倍率（支持前缀匹配）

    Args:
        model: 模型名称

    Returns:
        float: 倍率
    """
    model_lower = model.lower()

    # 精确匹配
    if model_lower in MODEL_RATIO:
        return MODEL_RATIO[model_lower]

    # 前缀匹配
    for model_prefix, ratio in MODEL_RATIO.items():
        if model_prefix in model_lower:
            return ratio

    # 返回默认倍率
    logger.warning(f"未找到模型 {model} 的倍率配置，使用默认倍率 {DEFAULT_RATIO}")
    return DEFAULT_RATIO


def calculate_quota(
    model: str,
    prompt_tokens: int,
    completion_tokens: int
) -> int:
    """
    计算配额消耗

    计算公式: quota = max(1, int((prompt_tokens + completion_tokens) * ratio / 500_000))

    Args:
        model: 模型名称
        prompt_tokens: 提示词 token 数
        completion_tokens: 完成 token 数

    Returns:
        int: 消耗的配额
    """
    ratio = get_model_ratio(model)
    total_tokens = prompt_tokens + completion_tokens

    # 计算配额
    quota = int(total_tokens * ratio / 500_000)

    # 至少消耗 1 配额
    return max(1, quota)


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    price_per_million: float = 10.0
) -> float:
    """
    估算成本（美元）

    Args:
        model: 模型名称
        prompt_tokens: 提示词 token 数
        completion_tokens: 完成 token 数
        price_per_million: 每百万 token 价格（美元）

    Returns:
        float: 估算成本
    """
    ratio = get_model_ratio(model)
    total_tokens = prompt_tokens + completion_tokens

    # 计算成本
    cost = (total_tokens / 1_000_000) * price_per_million * ratio

    return cost


class QuotaManager:
    """
    配额管理器
    """

    def __init__(self):
        self._quotas: dict[str, QuotaInfo] = {}

    def set_quota(self, user_id: str, total_quota: int, used_quota: int = 0):
        """
        设置用户配额

        Args:
            user_id: 用户 ID
            total_quota: 总额度（<=0 表示无限）
            used_quota: 已用额度
        """
        remaining = total_quota - used_quota if total_quota > 0 else -1

        self._quotas[user_id] = QuotaInfo(
            total_quota=total_quota,
            used_quota=used_quota,
            remaining_quota=remaining
        )

        logger.debug(f"用户 {user_id} 配额已设置: {total_quota}")

    def get_quota(self, user_id: str) -> QuotaInfo | None:
        """
        获取用户配额

        Args:
            user_id: 用户 ID

        Returns:
            QuotaInfo: 配额信息，如果不存在返回 None
        """
        return self._quotas.get(user_id)

    def check_quota(self, user_id: str, required_quota: int) -> bool:
        """
        检查配额是否充足

        Args:
            user_id: 用户 ID
            required_quota: 需要的配额

        Returns:
            bool: 配额是否充足
        """
        quota = self._quotas.get(user_id)

        if quota is None:
            logger.warning(f"用户 {user_id} 未设置配额")
            return False

        # 无限额度
        if quota.is_unlimited:
            return True

        # 检查剩余额度
        return quota.remaining_quota >= required_quota

    def consume_quota(self, user_id: str, quota: int) -> bool:
        """
        扣减配额

        Args:
            user_id: 用户 ID
            quota: 要扣减的配额

        Returns:
            bool: 是否成功
        """
        if quota <= 0:
            return True

        user_quota = self._quotas.get(user_id)

        if user_quota is None:
            logger.warning(f"用户 {user_id} 未设置配额")
            return False

        # 无限额度，不扣减
        if user_quota.is_unlimited:
            user_quota.used_quota += quota
            return True

        # 检查配额是否充足
        if user_quota.remaining_quota < quota:
            logger.warning(f"用户 {user_id} 配额不足: 需要 {quota}, 剩余 {user_quota.remaining_quota}")
            return False

        # 扣减配额
        user_quota.used_quota += quota
        user_quota.remaining_quota -= quota

        logger.debug(f"用户 {user_id} 配额已扣减: {quota}, 剩余: {user_quota.remaining_quota}")

        return True

    def add_quota(self, user_id: str, quota: int):
        """
        增加配额（充值/签到）

        Args:
            user_id: 用户 ID
            quota: 要增加的配额
        """
        if quota <= 0:
            return

        user_quota = self._quotas.get(user_id)

        if user_quota is None:
            # 创建新配额
            self.set_quota(user_id, quota, 0)
        else:
            # 无限额度保持不变
            if user_quota.is_unlimited:
                return

            # 增加配额
            user_quota.total_quota += quota
            user_quota.remaining_quota += quota

        logger.info(f"用户 {user_id} 配额已增加: {quota}")

    def get_usage_stats(self) -> dict[str, Any]:
        """
        获取使用统计

        Returns:
            Dict: 统计信息
        """
        total_users = len(self._quotas)
        unlimited_users = sum(1 for q in self._quotas.values() if q.is_unlimited)
        total_quota = sum(q.total_quota for q in self._quotas.values() if not q.is_unlimited)
        total_used = sum(q.used_quota for q in self._quotas.values())

        return {
            "total_users": total_users,
            "unlimited_users": unlimited_users,
            "limited_users": total_users - unlimited_users,
            "total_quota": total_quota,
            "total_used": total_used,
            "total_remaining": total_quota - total_used,
            "usage_percentage": round((total_used / total_quota * 100) if total_quota > 0 else 0, 2)
        }


# 全局配额管理器实例
quota_manager = QuotaManager()

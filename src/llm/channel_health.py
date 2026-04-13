"""
Channel Health Monitor - 渠道健康监测（整合自 New-API）
支持单渠道测试、批量测试、自动禁用、EMA 响应时间追踪
"""

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger


class ChannelStatus(Enum):
    """渠道状态"""
    ENABLED = "enabled"
    DISABLED = "disabled"
    TESTING = "testing"


@dataclass
class TestResult:
    """测试结果"""
    channel_id: str
    success: bool
    response_time: float  # 毫秒
    error_message: str | None = None
    model_tested: str = ""
    timestamp: float = field(default_factory=time.time)


class ChannelHealthMonitor:
    """
    渠道健康监测器（整合自 New-API）

    功能:
    - 单渠道测试
    - 批量并发测试
    - 自动禁用故障渠道
    - EMA（指数移动平均）响应时间追踪
    - 失败阈值检测
    """

    def __init__(
        self,
        auto_disable_threshold: int = 5,  # 连续失败次数阈值
        ema_alpha: float = 0.3,  # EMA 平滑系数
        max_concurrent_tests: int = 10,  # 最大并发测试数
    ):
        """
        初始化监测器

        Args:
            auto_disable_threshold: 自动禁用阈值（连续失败次数）
            ema_alpha: EMA 平滑系数（0.3 = 新数据30%，历史70%）
            max_concurrent_tests: 最大并发测试数
        """
        self._auto_disable_threshold = auto_disable_threshold
        self._ema_alpha = ema_alpha
        self._max_concurrent_tests = max_concurrent_tests

        # 渠道状态追踪
        self._channel_status: dict[str, ChannelStatus] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._ema_response_times: dict[str, float] = {}
        self._test_history: dict[str, list[TestResult]] = {}

        # 回调函数
        self._on_channel_disabled: Callable | None = None

        # 并发控制
        self._semaphore = asyncio.Semaphore(max_concurrent_tests)
        self._lock = threading.RLock()

        logger.info(
            f"渠道健康监测器已初始化 "
            f"(threshold={auto_disable_threshold}, ema_alpha={ema_alpha}, "
            f"max_concurrent={max_concurrent_tests})"
        )

    def set_on_channel_disabled(self, callback: Callable):
        """
        设置渠道禁用回调

        Args:
            callback: 回调函数 (channel_id: str) -> None
        """
        self._on_channel_disabled = callback

    async def test_channel(
        self,
        channel_id: str,
        test_func: Callable,
        model: str = "gpt-3.5-turbo",
    ) -> TestResult:
        """
        测试单个渠道

        Args:
            channel_id: 渠道ID
            test_func: 测试函数 (async)，返回 (success: bool, response_time: float, error: Optional[str])
            model: 测试模型

        Returns:
            测试结果
        """
        async with self._semaphore:
            with self._lock:
                self._channel_status[channel_id] = ChannelStatus.TESTING

            logger.info(f"开始测试渠道: {channel_id} (model={model})")

            try:
                success, response_time, error = await test_func()

                result = TestResult(
                    channel_id=channel_id,
                    success=success,
                    response_time=response_time,
                    error_message=error,
                    model_tested=model,
                )

                # 更新统计
                self._update_stats(channel_id, result)

                if success:
                    logger.info(
                        f"渠道测试成功: {channel_id} "
                        f"(response_time={response_time:.0f}ms)"
                    )
                else:
                    logger.warning(
                        f"渠道测试失败: {channel_id} "
                        f"(error={error})"
                    )

                return result

            except Exception as e:
                result = TestResult(
                    channel_id=channel_id,
                    success=False,
                    response_time=0.0,
                    error_message=str(e),
                    model_tested=model,
                )

                self._update_stats(channel_id, result)
                logger.error(f"渠道测试异常: {channel_id} ({e})")

                return result

            finally:
                with self._lock:
                    self._channel_status[channel_id] = ChannelStatus.ENABLED

    async def batch_test_channels(
        self,
        channel_ids: list[str],
        test_func_factory: Callable,
        model: str = "gpt-3.5-turbo",
    ) -> list[TestResult]:
        """
        批量测试渠道

        Args:
            channel_ids: 渠道ID列表
            test_func_factory: 测试函数工厂 (channel_id: str) -> Callable
            model: 测试模型

        Returns:
            测试结果列表
        """
        logger.info(f"开始批量测试 {len(channel_ids)} 个渠道")

        tasks = []
        for channel_id in channel_ids:
            test_func = test_func_factory(channel_id)
            task = self.test_channel(channel_id, test_func, model)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    TestResult(
                        channel_id=channel_ids[i],
                        success=False,
                        response_time=0.0,
                        error_message=str(result),
                        model_tested=model,
                    )
                )
            else:
                final_results.append(result)

        success_count = sum(1 for r in final_results if r.success)
        logger.info(
            f"批量测试完成: {success_count}/{len(channel_ids)} 成功"
        )

        return final_results

    def _update_stats(self, channel_id: str, result: TestResult):
        """
        更新渠道统计

        Args:
            channel_id: 渠道ID
            result: 测试结果
        """
        with self._lock:
            # 记录测试历史
            if channel_id not in self._test_history:
                self._test_history[channel_id] = []
            self._test_history[channel_id].append(result)

            if result.success:
                # 成功：重置连续失败计数，更新 EMA
                self._consecutive_failures[channel_id] = 0

                # EMA 更新
                old_ema = self._ema_response_times.get(channel_id, 0.0)
                if old_ema == 0.0:
                    self._ema_response_times[channel_id] = result.response_time
                else:
                    new_ema = (
                        self._ema_alpha * result.response_time +
                        (1 - self._ema_alpha) * old_ema
                    )
                    self._ema_response_times[channel_id] = new_ema
            else:
                # 失败：增加计数
                self._consecutive_failures[channel_id] = \
                    self._consecutive_failures.get(channel_id, 0) + 1

                # 检查是否达到自动禁用阈值
                if self._consecutive_failures[channel_id] >= self._auto_disable_threshold:
                    logger.warning(
                        f"渠道 {channel_id} 连续失败 "
                        f"{self._consecutive_failures[channel_id]} 次，自动禁用"
                    )
                    self._disable_channel(channel_id)

    def _disable_channel(self, channel_id: str):
        """
        禁用渠道

        Args:
            channel_id: 渠道ID
        """
        with self._lock:
            self._channel_status[channel_id] = ChannelStatus.DISABLED

            # 触发回调
            if self._on_channel_disabled:
                try:
                    self._on_channel_disabled(channel_id)
                except Exception as e:
                    logger.error(f"渠道禁用回调异常: {e}")

    def get_ema_response_time(self, channel_id: str) -> float:
        """
        获取 EMA 响应时间

        Args:
            channel_id: 渠道ID

        Returns:
            EMA 响应时间（毫秒）
        """
        with self._lock:
            return self._ema_response_times.get(channel_id, 0.0)

    def get_consecutive_failures(self, channel_id: str) -> int:
        """
        获取连续失败次数

        Args:
            channel_id: 渠道ID

        Returns:
            连续失败次数
        """
        with self._lock:
            return self._consecutive_failures.get(channel_id, 0)

    def get_channel_status(self, channel_id: str) -> ChannelStatus:
        """
        获取渠道状态

        Args:
            channel_id: 渠道ID

        Returns:
            渠道状态
        """
        with self._lock:
            return self._channel_status.get(channel_id, ChannelStatus.ENABLED)

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """
        获取所有渠道统计

        Returns:
            渠道统计字典
        """
        with self._lock:
            stats = {}

            for channel_id in set(
                list(self._ema_response_times.keys()) +
                list(self._consecutive_failures.keys())
            ):
                stats[channel_id] = {
                    "ema_response_time": self._ema_response_times.get(channel_id, 0.0),
                    "consecutive_failures": self._consecutive_failures.get(channel_id, 0),
                    "status": self._channel_status.get(channel_id, ChannelStatus.ENABLED).value,
                    "total_tests": len(self._test_history.get(channel_id, [])),
                }

            return stats

    def reset_channel(self, channel_id: str):
        """
        重置渠道统计

        Args:
            channel_id: 渠道ID
        """
        with self._lock:
            self._consecutive_failures.pop(channel_id, None)
            self._ema_response_times.pop(channel_id, None)
            self._channel_status[channel_id] = ChannelStatus.ENABLED
            logger.info(f"渠道统计已重置: {channel_id}")


# 全局单例
_channel_health_monitor = ChannelHealthMonitor()


def get_channel_health_monitor() -> ChannelHealthMonitor:
    """获取渠道健康监测器单例"""
    return _channel_health_monitor


def get_ema_response_time(channel_id: str) -> float:
    """
    快捷函数：获取 EMA 响应时间

    Args:
        channel_id: 渠道ID

    Returns:
        EMA 响应时间
    """
    return _channel_health_monitor.get_ema_response_time(channel_id)

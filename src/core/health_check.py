"""
健康检查模块 - 整合自 Onyx
服务健康检查、依赖检查
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger


class HealthStatus(str, Enum):
    """健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    name: str
    status: HealthStatus
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class HealthCheck:
    """
    健康检查基类
    """

    def __init__(self, name: str, critical: bool = False):
        self.name = name
        self.critical = critical

    async def check(self) -> HealthCheckResult:
        """执行检查"""
        raise NotImplementedError


class DependencyHealthCheck(HealthCheck):
    """
    依赖服务健康检查（整合自 Onyx 的健康检查模式）
    """

    def __init__(
        self,
        name: str,
        check_fn: Callable[[], bool],
        critical: bool = False,
        timeout: float = 5.0,
    ):
        super().__init__(name, critical)
        self.check_fn = check_fn
        self.timeout = timeout

    async def check(self) -> HealthCheckResult:
        """执行依赖检查"""
        try:
            if asyncio.iscoroutinefunction(self.check_fn):
                result = await asyncio.wait_for(self.check_fn(), timeout=self.timeout)
            else:
                result = self.check_fn()

            if result:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message=f"{self.name} is available",
                )
            else:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"{self.name} is unavailable",
                )

        except asyncio.TimeoutError:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"{self.name} check timed out",
            )
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.DEGRADED,
                message=f"{self.name} check failed: {e!s}",
            )


class LLMHealthCheck(HealthCheck):
    """
    LLM 服务健康检查
    """

    def __init__(
        self,
        name: str,
        check_fn: Callable[[], bool],
        critical: bool = True,
        timeout: float = 10.0,
    ):
        super().__init__(name, critical)
        self.check_fn = check_fn
        self.timeout = timeout

    async def check(self) -> HealthCheckResult:
        """执行 LLM 检查"""
        try:
            if asyncio.iscoroutinefunction(self.check_fn):
                result = await asyncio.wait_for(self.check_fn(), timeout=self.timeout)
            else:
                result = self.check_fn()

            if result:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message=f"LLM {self.name} is available",
                )
            else:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"LLM {self.name} is unavailable",
                )

        except asyncio.TimeoutError:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"LLM {self.name} check timed out",
            )
        except Exception as e:
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.DEGRADED,
                message=f"LLM {self.name} check failed: {e!s}",
            )


class HealthCheckManager:
    """
    健康检查管理器（整合自 Onyx 的健康检查系统）
    """

    def __init__(self):
        self._checks: list[HealthCheck] = []
        self._last_results: dict[str, HealthCheckResult] = {}

    def register(self, check: HealthCheck):
        """注册健康检查"""
        self._checks.append(check)
        logger.info(f"健康检查已注册: {check.name}")

    def register_dependency(
        self,
        name: str,
        check_fn: Callable[[], bool],
        critical: bool = False,
        timeout: float = 5.0,
    ):
        """注册依赖检查"""
        check = DependencyHealthCheck(name, check_fn, critical, timeout)
        self.register(check)

    def register_llm(
        self,
        name: str,
        check_fn: Callable[[], bool],
        critical: bool = True,
        timeout: float = 10.0,
    ):
        """注册 LLM 检查"""
        check = LLMHealthCheck(name, check_fn, critical, timeout)
        self.register(check)

    async def check_all(self) -> dict[str, HealthCheckResult]:
        """执行所有健康检查"""
        results = {}

        # 并行执行所有检查
        tasks = [check.check() for check in self._checks]
        check_results = await asyncio.gather(*tasks, return_exceptions=True)

        for check, result in zip(self._checks, check_results, strict=False):
            if isinstance(result, Exception):
                results[check.name] = HealthCheckResult(
                    name=check.name,
                    status=HealthStatus.UNHEALTHY,
                    message=str(result),
                )
            else:
                results[check.name] = result

            # 保存最后结果
            self._last_results[check.name] = results[check.name]

        return results

    def get_overall_status(self) -> HealthStatus:
        """获取整体状态"""
        if not self._last_results:
            return HealthStatus.HEALTHY

        # 检查是否有 critical 检查失败
        for check in self._checks:
            result = self._last_results.get(check.name)
            if not result:
                continue

            if check.critical and result.status == HealthStatus.UNHEALTHY:
                return HealthStatus.UNHEALTHY

        # 检查是否有任何 degraded 状态
        for result in self._last_results.values():
            if result.status == HealthStatus.DEGRADED:
                return HealthStatus.DEGRADED

        return HealthStatus.HEALTHY

    def get_health_report(self) -> dict[str, Any]:
        """获取健康报告"""
        return {
            "status": self.get_overall_status().value,
            "timestamp": time.time(),
            "checks": {
                name: {
                    "status": result.status.value,
                    "message": result.message,
                    "details": result.details,
                }
                for name, result in self._last_results.items()
            },
        }

    def get_last_results(self) -> dict[str, HealthCheckResult]:
        """获取最后检查结果"""
        return self._last_results.copy()


# 全局健康检查管理器
health_check_manager = HealthCheckManager()


# ==================== 便捷函数 ====================

def register_dependency_check(
    name: str,
    check_fn: Callable[[], bool],
    critical: bool = False,
    timeout: float = 5.0,
):
    """注册依赖检查"""
    health_check_manager.register_dependency(name, check_fn, critical, timeout)


def register_llm_check(
    name: str,
    check_fn: Callable[[], bool],
    critical: bool = True,
    timeout: float = 10.0,
):
    """注册 LLM 检查"""
    health_check_manager.register_llm(name, check_fn, critical, timeout)


async def check_health() -> dict[str, Any]:
    """执行健康检查"""
    return health_check_manager.get_health_report()

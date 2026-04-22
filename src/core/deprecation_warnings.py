"""
Deprecation Warnings - 弃用警告机制

从 oh-my-codex-main/src/modes/base.ts 汲取。
帮助用户平滑迁移过时功能,提供清晰的迁移路径。

核心功能:
- 声明式弃用定义
- 自动检测并警告
- 提供迁移建议
- 支持分级警告 (warning, error)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ===== 数据类 =====

@dataclass
class DeprecationInfo:
    """弃用信息"""
    name: str
    deprecated_since: str  # 版本号或日期
    removed_in: str | None = None  # 预计移除版本
    reason: str = ""
    migration_guide: str = ""
    alternative: str | None = None  # 替代方案
    severity: str = "warning"  # 'warning' | 'error'
    auto_migrate: Callable | None = None  # 自动迁移函数

    def format_message(self) -> str:
        """格式化为可读的警告消息"""
        parts = [f"\n⚠️  DEPRECATED: {self.name}"]

        if self.deprecated_since:
            parts.append(f"   Deprecated since: {self.deprecated_since}")

        if self.removed_in:
            parts.append(f"   Will be removed in: {self.removed_in}")

        if self.reason:
            parts.append(f"   Reason: {self.reason}")

        if self.alternative:
            parts.append(f"   Alternative: {self.alternative}")

        if self.migration_guide:
            parts.append(f"   Migration guide: {self.migration_guide}")

        parts.append("")  # 空行
        return "\n".join(parts)


# ===== 弃用注册表 =====

class DeprecationRegistry:
    """
    弃用注册表

    管理所有已弃用的功能、参数和模式。
    """

    def __init__(self):
        self._deprecated: dict[str, DeprecationInfo] = {}

    def register(self, info: DeprecationInfo) -> None:
        """注册一个弃用项"""
        self._deprecated[info.name] = info
        logger.info(f"[Deprecation] Registered: {info.name}")

    def check(self, name: str) -> DeprecationInfo | None:
        """检查某个功能是否已弃用"""
        return self._deprecated.get(name)

    def warn_if_deprecated(self, name: str, context: str = "") -> bool:
        """
        如果功能已弃用则发出警告

        Args:
            name: 功能名称
            context: 上下文信息

        Returns:
            True 如果已弃用
        """
        info = self.check(name)
        if not info:
            return False

        message = info.format_message()
        if context:
            message += f"   Context: {context}\n"

        if info.severity == "error":
            logger.error(message)
            raise DeprecationError(
                f"{name} has been removed. {info.migration_guide}"
            )
        else:
            logger.warning(message)

        return True

    def list_all(self) -> list[DeprecationInfo]:
        """列出所有弃用项"""
        return list(self._deprecated.values())

    def clear(self) -> None:
        """清空注册表"""
        self._deprecated.clear()


# ===== 全局实例 =====

_global_registry = DeprecationRegistry()


def get_deprecation_registry() -> DeprecationRegistry:
    """获取全局弃用注册表"""
    return _global_registry


# ===== 预定义的弃用项 =====

def register_common_deprecations() -> None:
    """注册常见的弃用项"""
    registry = get_deprecation_registry()

    # 示例: 旧的工作流模式
    registry.register(DeprecationInfo(
        name="legacy-workflow",
        deprecated_since="v2026.04.10",
        removed_in="v2026.05.01",
        reason="Replaced by new pipeline orchestrator with better state management",
        alternative="Use 'pipeline' mode instead",
        migration_guide="Replace 'workflow.run()' with 'pipeline.execute()'",
    ))

    # 示例: 旧的 RAG 索引
    registry.register(DeprecationInfo(
        name="simple-text-index",
        deprecated_since="v2026.04.12",
        removed_in="v2026.06.01",
        reason="Limited semantic search capabilities",
        alternative="Use trigram-based index with dependency graph",
        migration_guide="Update config to use 'trigram_index: true'",
    ))

    # 示例: 旧的意图路由
    registry.register(DeprecationInfo(
        name="basic-intent-router",
        deprecated_since="v2026.04.14",
        reason="Enhanced with keyword detection from oh-my-codex",
        alternative="Use enhanced intent_router with keyword registry",
        migration_guide="No action needed - automatic upgrade applied",
        auto_migrate=lambda: logger.info("Auto-migrated to enhanced intent router"),
    ))


# ===== 装饰器 =====

def deprecated(alternative: str, reason: str = "", version: str = ""):
    """
    标记函数为已弃用的装饰器

    Usage:
        @deprecated(alternative="new_function()", reason="Better performance")
        def old_function():
            pass
    """
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            info = DeprecationInfo(
                name=func.__qualname__,
                deprecated_since=version,
                reason=reason,
                alternative=alternative,
            )
            logger.warning(info.format_message())
            return func(*args, **kwargs)

        wrapper.__doc__ = f"**DEPRECATED**: {reason}\n\nUse {alternative} instead.\n\n{func.__doc__ or ''}"
        return wrapper
    return decorator


# ===== 异常 =====

class DeprecationError(Exception):
    """弃用错误 - 当使用已移除的功能时抛出"""
    pass


# ===== 初始化 =====

# 自动注册常见弃用项
register_common_deprecations()


# ===== 导出 =====
__all__ = [
    "DeprecationError",
    "DeprecationInfo",
    "DeprecationRegistry",
    "deprecated",
    "get_deprecation_registry",
    "register_common_deprecations",
]

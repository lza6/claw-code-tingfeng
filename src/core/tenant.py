"""Multi-Tenant Support — 多租户支持（参考 Onyx）"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from datetime import datetime

# 租户上下文变量
tenant_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tenant_context", default=None
)


@dataclass
class Tenant:
    """租户数据模型"""
    id: str
    name: str
    slug: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True
    settings: dict = field(default_factory=dict)

    # 资源限制
    max_api_keys: int = 10
    max_users: int = 100
    max_storage_mb: int = 1024
    rate_limit: int = 60

    # 权限
    features: list[str] = field(default_factory=list)


class TenantContext:
    """租户上下文管理器"""

    _current_tenant: Tenant | None = None

    @classmethod
    def set_tenant(cls, tenant: Tenant | None):
        """设置当前租户"""
        cls._current_tenant = tenant
        if tenant:
            tenant_context.set(tenant.id)
        else:
            tenant_context.set(None)

    @classmethod
    def get_tenant(cls) -> Tenant | None:
        """获取当前租户"""
        return cls._current_tenant

    @classmethod
    def get_tenant_id(cls) -> str | None:
        """获取当前租户 ID"""
        return tenant_context.get()

    @classmethod
    def clear(cls):
        """清除租户上下文"""
        cls._current_tenant = None
        tenant_context.set(None)


class TenantManager:
    """租户管理器"""

    def __init__(self):
        self._tenants: dict[str, Tenant] = {}

    def create_tenant(
        self,
        id: str,
        name: str,
        slug: str,
        **kwargs
    ) -> Tenant:
        """创建租户"""
        tenant = Tenant(
            id=id,
            name=name,
            slug=slug,
            **kwargs
        )
        self._tenants[id] = tenant
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        """获取租户"""
        return self._tenants.get(tenant_id)

    def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        """通过 slug 获取租户"""
        for tenant in self._tenants.values():
            if tenant.slug == slug:
                return tenant
        return None

    def update_tenant(self, tenant_id: str, **kwargs) -> Tenant | None:
        """更新租户"""
        tenant = self._tenants.get(tenant_id)
        if tenant:
            for key, value in kwargs.items():
                if hasattr(tenant, key):
                    setattr(tenant, key, value)
        return tenant

    def delete_tenant(self, tenant_id: str) -> bool:
        """删除租户"""
        if tenant_id in self._tenants:
            tenant = self._tenants[tenant_id]
            tenant.is_active = False
            return True
        return False

    def list_tenants(self) -> list[Tenant]:
        """列出所有租户"""
        return list(self._tenants.values())


# 中间件辅助
class TenantMiddleware:
    """租户中间件 - 从请求中提取租户信息"""

    @staticmethod
    def extract_tenant_id(headers: dict) -> str | None:
        """从请求头提取租户 ID"""
        # 常见方式：X-Tenant-ID, Tenant-ID, x-tenant-id
        return (
            headers.get("X-Tenant-ID")
            or headers.get("Tenant-ID")
            or headers.get("x-tenant-id")
        )

    @staticmethod
    def extract_from_subdomain(host: str) -> str | None:
        """从子域名提取租户"""
        # 例如: tenant.onyx.app -> tenant
        parts = host.split(".")
        if len(parts) >= 2:
            return parts[0]
        return None


# 全局实例
_tenant_manager: TenantManager | None = None


def get_tenant_manager() -> TenantManager:
    """获取全局租户管理器"""
    global _tenant_manager
    if _tenant_manager is None:
        _tenant_manager = TenantManager()
    return _tenant_manager


__all__ = [
    "Tenant",
    "TenantContext",
    "TenantManager",
    "TenantMiddleware",
    "get_tenant_manager",
    "tenant_context",
]

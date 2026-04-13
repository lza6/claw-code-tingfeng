"""Tenant 测试 - 多租户支持"""
from __future__ import annotations

import pytest
from datetime import datetime

from src.core.tenant import (
    Tenant,
    TenantContext,
    TenantManager,
    TenantMiddleware,
    get_tenant_manager,
    tenant_context,
)


class TestTenant:
    """Tenant 数据模型测试"""

    def test_create_tenant_minimal(self):
        """测试最小创建"""
        tenant = Tenant(
            id="tenant1",
            name="测试租户",
            slug="test",
        )
        assert tenant.id == "tenant1"
        assert tenant.name == "测试租户"
        assert tenant.slug == "test"
        assert tenant.is_active is True
        assert isinstance(tenant.created_at, datetime)

    def test_create_tenant_full(self):
        """测试完整创建"""
        tenant = Tenant(
            id="tenant1",
            name="测试租户",
            slug="test",
            is_active=True,
            settings={"theme": "dark"},
            max_api_keys=20,
            max_users=200,
            max_storage_mb=2048,
            rate_limit=120,
            features=["feature1", "feature2"],
        )
        assert tenant.settings["theme"] == "dark"
        assert tenant.max_api_keys == 20
        assert tenant.max_users == 200
        assert tenant.max_storage_mb == 2048
        assert tenant.rate_limit == 120
        assert len(tenant.features) == 2

    def test_create_tenant_defaults(self):
        """测试默认值"""
        tenant = Tenant(
            id="tenant1",
            name="测试",
            slug="test",
        )
        assert tenant.max_api_keys == 10
        assert tenant.max_users == 100
        assert tenant.max_storage_mb == 1024
        assert tenant.rate_limit == 60
        assert tenant.features == []


class TestTenantContext:
    """TenantContext 上下文管理器测试"""

    def setup_method(self):
        """测试前清理"""
        TenantContext.clear()

    def test_set_tenant(self):
        """测试设置租户"""
        tenant = Tenant(id="t1", name="测试", slug="test")
        TenantContext.set_tenant(tenant)

        assert TenantContext.get_tenant() == tenant
        assert TenantContext.get_tenant_id() == "t1"

    def test_clear_tenant(self):
        """测试清除租户"""
        tenant = Tenant(id="t1", name="测试", slug="test")
        TenantContext.set_tenant(tenant)
        TenantContext.clear()

        assert TenantContext.get_tenant() is None
        assert TenantContext.get_tenant_id() is None

    def test_tenant_context_var(self):
        """测试上下文变量"""
        tenant = Tenant(id="t1", name="测试", slug="test")
        TenantContext.set_tenant(tenant)

        assert tenant_context.get() == "t1"


class TestTenantManager:
    """TenantManager 管理器测试"""

    def test_create_tenant(self):
        """测试创建租户"""
        manager = TenantManager()
        tenant = manager.create_tenant(
            id="t1",
            name="测试租户",
            slug="test",
        )
        assert tenant.id == "t1"
        assert tenant.name == "测试租户"

    def test_get_tenant(self):
        """测试获取租户"""
        manager = TenantManager()
        manager.create_tenant(id="t1", name="测试", slug="test")
        tenant = manager.get_tenant("t1")
        assert tenant is not None
        assert tenant.id == "t1"

    def test_get_tenant_not_found(self):
        """测试获取不存在的租户"""
        manager = TenantManager()
        tenant = manager.get_tenant("nonexistent")
        assert tenant is None

    def test_get_tenant_by_slug(self):
        """测试通过 slug 获取租户"""
        manager = TenantManager()
        manager.create_tenant(id="t1", name="测试", slug="test-slug")
        tenant = manager.get_tenant_by_slug("test-slug")
        assert tenant is not None
        assert tenant.slug == "test-slug"

    def test_get_tenant_by_slug_not_found(self):
        """测试 slug 不存在"""
        manager = TenantManager()
        tenant = manager.get_tenant_by_slug("nonexistent")
        assert tenant is None

    def test_update_tenant(self):
        """测试更新租户"""
        manager = TenantManager()
        manager.create_tenant(id="t1", name="原名称", slug="test")
        manager.update_tenant("t1", name="新名称", max_users=500)

        tenant = manager.get_tenant("t1")
        assert tenant.name == "新名称"
        assert tenant.max_users == 500

    def test_update_nonexistent_tenant(self):
        """测试更新不存在的租户"""
        manager = TenantManager()
        result = manager.update_tenant("nonexistent", name="新名称")
        assert result is None

    def test_delete_tenant(self):
        """测试删除租户"""
        manager = TenantManager()
        manager.create_tenant(id="t1", name="测试", slug="test")
        result = manager.delete_tenant("t1")
        assert result is True

        # 删除后应为非活跃状态
        tenant = manager.get_tenant("t1")
        assert tenant.is_active is False

    def test_delete_nonexistent_tenant(self):
        """测试删除不存在的租户"""
        manager = TenantManager()
        result = manager.delete_tenant("nonexistent")
        assert result is False

    def test_list_tenants(self):
        """测试列出所有租户"""
        manager = TenantManager()
        manager.create_tenant(id="t1", name="租户1", slug="test1")
        manager.create_tenant(id="t2", name="租户2", slug="test2")

        tenants = manager.list_tenants()
        assert len(tenants) == 2


class TestTenantMiddleware:
    """TenantMiddleware 中间件测试"""

    def test_extract_tenant_id_from_header(self):
        """测试从头提取租户ID"""
        headers = {"X-Tenant-ID": "tenant123"}
        tenant_id = TenantMiddleware.extract_tenant_id(headers)
        assert tenant_id == "tenant123"

    def test_extract_tenant_id_alternative_header(self):
        """测试替代头"""
        headers = {"Tenant-ID": "tenant456"}
        tenant_id = TenantMiddleware.extract_tenant_id(headers)
        assert tenant_id == "tenant456"

    def test_extract_tenant_id_lowercase_header(self):
        """测试小写头"""
        headers = {"x-tenant-id": "tenant789"}
        tenant_id = TenantMiddleware.extract_tenant_id(headers)
        assert tenant_id == "tenant789"

    def test_extract_tenant_id_missing(self):
        """测试缺失头"""
        headers = {}
        tenant_id = TenantMiddleware.extract_tenant_id(headers)
        assert tenant_id is None

    def test_extract_from_subdomain(self):
        """测试从子域名提取"""
        tenant_id = TenantMiddleware.extract_from_subdomain("tenant.onyx.app")
        assert tenant_id == "tenant"

    def test_extract_from_subdomain_complex(self):
        """测试复杂子域名"""
        tenant_id = TenantMiddleware.extract_from_subdomain("mytenant.example.com")
        assert tenant_id == "mytenant"

    def test_extract_from_subdomain_invalid(self):
        """测试无效子域名"""
        tenant_id = TenantMiddleware.extract_from_subdomain("localhost")
        # 只有1部分，应返回 None
        assert tenant_id is None


class TestGlobalFunctions:
    """全局函数测试"""

    def test_get_tenant_manager_singleton(self):
        """测试租户管理器单例"""
        manager1 = get_tenant_manager()
        manager2 = get_tenant_manager()
        assert manager1 is manager2

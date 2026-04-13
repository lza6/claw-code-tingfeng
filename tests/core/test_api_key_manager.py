"""API Key Manager 测试 - API密钥管理"""
from __future__ import annotations

import pytest
import time

from src.core.api_key_manager import (
    ApiKeyManager,
    ApiKeyInfo,
    ApiKeyPrefix,
    generate_api_key,
    verify_api_key,
    list_api_keys,
    delete_api_key,
    get_api_key_usage,
)


class TestApiKeyPrefix:
    """API Key 前缀测试"""

    def test_default_prefix(self):
        """测试默认前缀"""
        assert ApiKeyPrefix.DEFAULT == "sk"

    def test_deprecated_prefix(self):
        """测试废弃前缀"""
        assert ApiKeyPrefix.DEPRECATED == "on"


class TestApiKeyInfo:
    """API Key 信息测试"""

    def test_create_key_info(self):
        """测试创建 Key 信息"""
        info = ApiKeyInfo(
            key_id="test-id",
            key_hash="hash123",
            key_display="sk****test",
        )
        assert info.key_id == "test-id"
        assert info.is_available is True
        assert info.enabled is True

    def test_key_info_not_available_when_disabled(self):
        """测试禁用状态不可用"""
        info = ApiKeyInfo(
            key_id="test-id",
            key_hash="hash123",
            key_display="sk****test",
            enabled=False,
        )
        assert info.is_available is False

    def test_key_info_not_available_when_rate_limited(self):
        """测试限流状态不可用"""
        info = ApiKeyInfo(
            key_id="test-id",
            key_hash="hash123",
            key_display="sk****test",
            rate_limited_until=time.time() + 1000,
        )
        assert info.is_available is False

    def test_key_info_available_after_rate_limit(self):
        """测试限流结束后可用"""
        info = ApiKeyInfo(
            key_id="test-id",
            key_hash="hash123",
            key_display="sk****test",
            rate_limited_until=time.time() - 1000,  # 过去的时间
        )
        assert info.is_available is True


class TestApiKeyManagerGeneration:
    """API Key 生成测试"""

    def test_generate_key_basic(self):
        """测试基本生成"""
        manager = ApiKeyManager()
        key = manager.generate_key()
        assert key.startswith(ApiKeyPrefix.DEFAULT)
        assert len(key) > 10

    def test_generate_key_with_name(self):
        """测试带名称生成"""
        manager = ApiKeyManager()
        key = manager.generate_key(name="测试Key")
        assert key is not None

    def test_generate_key_with_user(self):
        """测试带用户生成"""
        manager = ApiKeyManager()
        key = manager.generate_key(user_id="user123")
        info = manager.verify_key(key)
        assert info is not None
        assert info.user_id == "user123"

    def test_generate_key_with_tenant(self):
        """测试带租户生成"""
        manager = ApiKeyManager()
        key = manager.generate_key(tenant_id="tenant123")
        info = manager.verify_key(key)
        assert info is not None
        assert info.tenant_id == "tenant123"

    def test_generate_key_with_role(self):
        """测试带角色生成"""
        manager = ApiKeyManager()
        key = manager.generate_key(role="admin")
        info = manager.verify_key(key)
        assert info is not None
        assert info.role == "admin"

    def test_generate_multiple_keys_unique(self):
        """测试生成多个唯一Key"""
        manager = ApiKeyManager()
        key1 = manager.generate_key()
        key2 = manager.generate_key()
        assert key1 != key2


class TestApiKeyManagerVerification:
    """API Key 验证测试"""

    def test_verify_valid_key(self):
        """测试验证有效Key"""
        manager = ApiKeyManager()
        key = manager.generate_key()
        info = manager.verify_key(key)
        assert info is not None
        assert info.enabled is True

    def test_verify_invalid_key(self):
        """测试验证无效Key"""
        manager = ApiKeyManager()
        info = manager.verify_key("sk-invalid-key")
        assert info is None

    def test_verify_disabled_key(self):
        """测试验证已禁用Key"""
        manager = ApiKeyManager()
        key = manager.generate_key()
        info = manager.verify_key(key)
        manager.disable_key(info.key_id)
        info2 = manager.verify_key(key)
        assert info2 is None

    def test_verify_updates_usage(self):
        """测试验证更新使用统计"""
        manager = ApiKeyManager()
        key = manager.generate_key()
        info_before = manager.verify_key(key)
        info_after = manager.get_key_info(info_before.key_id)
        assert info_after.request_count == 1
        assert info_after.last_used_at is not None


class TestApiKeyManagerOperations:
    """API Key 操作测试"""

    def test_enable_key(self):
        """测试启用Key"""
        manager = ApiKeyManager()
        key = manager.generate_key()
        info = manager.verify_key(key)
        manager.disable_key(info.key_id)
        result = manager.enable_key(info.key_id)
        assert result is True

    def test_disable_key(self):
        """测试禁用Key"""
        manager = ApiKeyManager()
        key = manager.generate_key()
        info = manager.verify_key(key)
        result = manager.disable_key(info.key_id)
        assert result is True

    def test_delete_key(self):
        """测试删除Key"""
        manager = ApiKeyManager()
        key = manager.generate_key()
        info = manager.verify_key(key)
        result = manager.delete_key(info.key_id)
        assert result is True

        # 删除后验证失败
        info2 = manager.verify_key(key)
        assert info2 is None

    def test_delete_nonexistent_key(self):
        """测试删除不存在Key"""
        manager = ApiKeyManager()
        result = manager.delete_key("nonexistent-id")
        assert result is False

    def test_regenerate_key(self):
        """测试重新生成Key"""
        manager = ApiKeyManager()
        old_key = manager.generate_key(name="测试", user_id="user1")
        old_info = manager.verify_key(old_key)

        new_key = manager.regenerate_key(old_info.key_id)
        assert new_key is not None
        assert new_key != old_key

        # 旧Key应已失效
        assert manager.verify_key(old_key) is None

        # 新Key应有效
        new_info = manager.verify_key(new_key)
        assert new_info is not None
        assert new_info.user_id == "user1"

    def test_regenerate_nonexistent_key(self):
        """测试重新生成不存在Key"""
        manager = ApiKeyManager()
        result = manager.regenerate_key("nonexistent-id")
        assert result is None


class TestApiKeyManagerListing:
    """API Key 列表测试"""

    def test_list_all_keys(self):
        """测试列出所有Key"""
        manager = ApiKeyManager()
        manager.generate_key()
        manager.generate_key()
        keys = manager.list_keys()
        assert len(keys) == 2

    def test_list_keys_by_user(self):
        """测试按用户列出Key"""
        manager = ApiKeyManager()
        manager.generate_key(user_id="user1")
        manager.generate_key(user_id="user1")
        manager.generate_key(user_id="user2")

        user1_keys = manager.list_keys(user_id="user1")
        assert len(user1_keys) == 2

    def test_list_keys_by_tenant(self):
        """测试按租户列出Key"""
        manager = ApiKeyManager()
        manager.generate_key(tenant_id="tenant1")
        manager.generate_key(tenant_id="tenant1")
        manager.generate_key(tenant_id="tenant2")

        tenant1_keys = manager.list_keys(tenant_id="tenant1")
        assert len(tenant1_keys) == 2


class TestApiKeyManagerUsage:
    """API Key 使用统计测试"""

    def test_add_usage(self):
        """测试添加使用统计"""
        manager = ApiKeyManager()
        key = manager.generate_key()
        info = manager.verify_key(key)

        result = manager.add_usage(info.key_id, 100)
        assert result is True

        stats = manager.get_usage_stats(info.key_id)
        assert stats['token_count'] == 100

    def test_add_usage_nonexistent_key(self):
        """测试添加不存在Key使用统计"""
        manager = ApiKeyManager()
        result = manager.add_usage("nonexistent-id", 100)
        assert result is False

    def test_set_rate_limit(self):
        """测试设置限流"""
        manager = ApiKeyManager()
        key = manager.generate_key()
        info = manager.verify_key(key)

        result = manager.set_rate_limit(info.key_id, time.time() + 1000)
        assert result is True

        # 限流后Key不可用
        assert manager.verify_key(key) is None

    def test_get_usage_stats(self):
        """测试获取使用统计"""
        manager = ApiKeyManager()
        key = manager.generate_key()
        info = manager.verify_key(key)
        manager.add_usage(info.key_id, 500)

        stats = manager.get_usage_stats(info.key_id)
        assert stats is not None
        assert stats['request_count'] == 1
        assert stats['token_count'] == 500

    def test_get_usage_stats_nonexistent(self):
        """测试获取不存在Key使用统计"""
        manager = ApiKeyManager()
        stats = manager.get_usage_stats("nonexistent-id")
        assert stats is None

    def test_get_tenant_usage(self):
        """测试获取租户使用统计"""
        manager = ApiKeyManager()
        manager.generate_key(tenant_id="tenant1")
        manager.generate_key(tenant_id="tenant1")

        usage = manager.get_tenant_usage(tenant_id="tenant1")
        assert usage is not None
        assert usage['key_count'] == 2


class TestGlobalFunctions:
    """全局便捷函数测试"""

    def test_generate_api_key_global(self):
        """测试全局生成函数"""
        key = generate_api_key(name="测试", user_id="user1")
        assert key is not None

    def test_verify_api_key_global(self):
        """测试全局验证函数"""
        key = generate_api_key()
        info = verify_api_key(key)
        assert info is not None

    def test_list_api_keys_global(self):
        """测试全局列表函数"""
        generate_api_key(user_id="user_test")
        keys = list_api_keys(user_id="user_test")
        assert len(keys) > 0

    def test_delete_api_key_global(self):
        """测试全局删除函数"""
        key = generate_api_key()
        info = verify_api_key(key)
        result = delete_api_key(info.key_id)
        assert result is True

    def test_get_api_key_usage_global(self):
        """测试全局获取使用函数"""
        key = generate_api_key()
        info = verify_api_key(key)
        usage = get_api_key_usage(info.key_id)
        assert usage is not None

"""
API Key 管理器 - 整合自 Onyx
多租户API Key、轮换、使用追踪、速率限制
"""

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


class ApiKeyPrefix:
    """API Key 前缀"""
    DEFAULT = "sk"
    DEPRECATED = "on"


@dataclass
class ApiKeyInfo:
    """API Key 信息"""
    key_id: str
    key_hash: str
    key_display: str  # 脱敏显示
    name: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    role: str = "user"
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    last_used_at: float | None = None
    rate_limited_until: float | None = None

    # 使用统计
    request_count: int = 0
    token_count: int = 0

    @property
    def is_available(self) -> bool:
        """是否可用"""
        if not self.enabled:
            return False
        return not (self.rate_limited_until and time.time() < self.rate_limited_until)


class ApiKeyManager:
    """
    API Key 管理器（整合自 Onyx 的 API Key 模式）

    功能:
    - 多租户支持
    - Key 生成、验证、轮换
    - 使用追踪
    - 速率限制
    - 权限管理
    """

    def __init__(self):
        self._keys: dict[str, ApiKeyInfo] = {}  # hash -> info
        self._key_ids: dict[str, ApiKeyInfo] = {}  # key_id -> info
        self._user_keys: dict[str, list[str]] = {}  # user_id -> [key_ids]
        self._tenant_keys: dict[str, list[str]] = {}  # tenant_id -> [key_ids]

    def generate_key(
        self,
        name: str | None = None,
        user_id: str | None = None,
        tenant_id: str | None = None,
        role: str = "user"
    ) -> str:
        """
        生成 API Key

        Args:
            name: Key 名称
            user_id: 用户ID
            tenant_id: 租户ID
            role: 角色

        Returns:
            str: 生成的 API Key
        """
        # 生成 Key
        if tenant_id:
            # 多租户格式: sk{tenant_id}.{random}
            key = f"{ApiKeyPrefix.DEFAULT}{tenant_id}.{secrets.token_urlsafe(16)}"
        else:
            key = f"{ApiKeyPrefix.DEFAULT}{secrets.token_urlsafe(24)}"

        # 计算 Hash（用于存储和验证）
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()

        # 生成 Key ID
        key_id = str(uuid.uuid4())

        # 脱敏显示
        key_display = self._build_displayable_key(key)

        # 创建 Key 信息
        info = ApiKeyInfo(
            key_id=key_id,
            key_hash=key_hash,
            key_display=key_display,
            name=name,
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
        )

        # 存储
        self._keys[key_hash] = info
        self._key_ids[key_id] = info

        if user_id:
            if user_id not in self._user_keys:
                self._user_keys[user_id] = []
            self._user_keys[user_id].append(key_id)

        if tenant_id:
            if tenant_id not in self._tenant_keys:
                self._tenant_keys[tenant_id] = []
            self._tenant_keys[tenant_id].append(key_id)

        logger.info(f"API Key 已生成: {key_id}, tenant={tenant_id}, user={user_id}")

        return key

    def _build_displayable_key(self, key: str) -> str:
        """构建脱敏显示的 Key"""
        if key.startswith(ApiKeyPrefix.DEFAULT):
            key = key[len(ApiKeyPrefix.DEFAULT):]
        elif key.startswith(ApiKeyPrefix.DEPRECATED):
            key = key[len(ApiKeyPrefix.DEPRECATED):]

        return f"{ApiKeyPrefix.DEFAULT}{key[:4]}****{key[-4:]}"

    def verify_key(self, key: str) -> ApiKeyInfo | None:
        """
        验证 API Key

        Args:
            key: API Key

        Returns:
            ApiKeyInfo: Key 信息（验证失败返回 None）
        """
        # 计算 Hash
        key_hash = self._hash_key(key)

        # 查找
        info = self._keys.get(key_hash)
        if not info:
            logger.warning("API Key 验证失败: 无效的 Key")
            return None

        # 检查可用性
        if not info.is_available:
            logger.warning(f"API Key 不可用: {info.key_id}")
            return None

        # 更新使用时间
        info.last_used_at = time.time()
        info.request_count += 1

        return info

    def _hash_key(self, key: str) -> str:
        """Hash API Key"""
        if key.startswith(ApiKeyPrefix.DEFAULT) or key.startswith(ApiKeyPrefix.DEPRECATED):
            return hashlib.sha256(key.encode("utf-8")).hexdigest()
        raise ValueError("Invalid API key prefix")

    def get_key_info(self, key_id: str) -> ApiKeyInfo | None:
        """获取 Key 信息"""
        return self._key_ids.get(key_id)

    def list_keys(
        self,
        user_id: str | None = None,
        tenant_id: str | None = None
    ) -> list[ApiKeyInfo]:
        """列出 Keys"""
        if user_id:
            key_ids = self._user_keys.get(user_id, [])
            return [self._key_ids[kid] for kid in key_ids if kid in self._key_ids]
        elif tenant_id:
            key_ids = self._tenant_keys.get(tenant_id, [])
            return [self._key_ids[kid] for kid in key_ids if kid in self._key_ids]
        return list(self._key_ids.values())

    def enable_key(self, key_id: str) -> bool:
        """启用 Key"""
        info = self._key_ids.get(key_id)
        if info:
            info.enabled = True
            return True
        return False

    def disable_key(self, key_id: str) -> bool:
        """禁用 Key"""
        info = self._key_ids.get(key_id)
        if info:
            info.enabled = False
            return True
        return False

    def delete_key(self, key_id: str) -> bool:
        """删除 Key"""
        info = self._key_ids.pop(key_id, None)
        if info:
            self._keys.pop(info.key_hash, None)

            # 从用户/租户列表中移除
            if info.user_id and info.user_id in self._user_keys:
                self._user_keys[info.user_id].remove(key_id)
            if info.tenant_id and info.tenant_id in self._tenant_keys:
                self._tenant_keys[info.tenant_id].remove(key_id)

            logger.info(f"API Key 已删除: {key_id}")
            return True
        return False

    def regenerate_key(self, key_id: str) -> str | None:
        """
        重新生成 Key

        Args:
            key_id: 原 Key ID

        Returns:
            str: 新的 API Key
        """
        info = self._key_ids.get(key_id)
        if not info:
            return None

        # 生成新 Key
        new_key = self.generate_key(
            name=info.name,
            user_id=info.user_id,
            tenant_id=info.tenant_id,
            role=info.role,
        )

        # 删除旧 Key
        self.delete_key(key_id)

        return new_key

    def add_usage(self, key_id: str, token_count: int) -> bool:
        """记录 Token 使用"""
        info = self._key_ids.get(key_id)
        if info:
            info.token_count += token_count
            return True
        return False

    def set_rate_limit(self, key_id: str, rate_limited_until: float) -> bool:
        """设置限流"""
        info = self._key_ids.get(key_id)
        if info:
            info.rate_limited_until = rate_limited_until
            return True
        return False

    def get_usage_stats(self, key_id: str) -> dict[str, Any] | None:
        """获取使用统计"""
        info = self._key_ids.get(key_id)
        if info:
            return {
                "key_id": key_id,
                "request_count": info.request_count,
                "token_count": info.token_count,
                "last_used_at": info.last_used_at,
                "enabled": info.enabled,
            }
        return None

    def get_tenant_usage(self, tenant_id: str) -> dict[str, Any]:
        """获取租户使用统计"""
        keys = self.list_keys(tenant_id=tenant_id)
        total_requests = sum(k.request_count for k in keys)
        total_tokens = sum(k.token_count for k in keys)

        return {
            "tenant_id": tenant_id,
            "key_count": len(keys),
            "total_requests": total_requests,
            "total_tokens": total_tokens,
        }


# 全局实例
api_key_manager = ApiKeyManager()


# ==================== 便捷函数 ====================

def generate_api_key(
    name: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    role: str = "user"
) -> str:
    """生成 API Key"""
    return api_key_manager.generate_key(name, user_id, tenant_id, role)


def verify_api_key(key: str) -> ApiKeyInfo | None:
    """验证 API Key"""
    return api_key_manager.verify_key(key)


def list_api_keys(
    user_id: str | None = None,
    tenant_id: str | None = None
) -> list[ApiKeyInfo]:
    """列出 API Keys"""
    return api_key_manager.list_keys(user_id, tenant_id)


def delete_api_key(key_id: str) -> bool:
    """删除 API Key"""
    return api_key_manager.delete_key(key_id)


def get_api_key_usage(key_id: str) -> dict[str, Any] | None:
    """获取 API Key 使用统计"""
    return api_key_manager.get_usage_stats(key_id)

"""API Key Manager — API Key 管理与限制（参考 Onyx）"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel


class APIKeyScope(str, Enum):
    """API Key 权限范围"""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"


class APIKeyStatus(str, Enum):
    """API Key 状态"""
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class APIKeyUsage(BaseModel):
    """API Key 使用记录"""
    key_id: str
    endpoint: str
    method: str
    status_code: int
    tokens_used: int = 0
    latency_ms: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class APIKeyConfig:
    """API Key 配置"""
    name: str
    scopes: list[APIKeyScope]
    rate_limit: int = 60  # 每分钟请求数
    daily_quota: int | None = None  # 每日配额，None=无限
    expires_at: datetime | None = None
    allowed_ips: list[str] | None = None


@dataclass
class APIKey:
    """API Key 数据模型"""
    id: str
    key_hash: str
    prefix: str  # 用于显示给用户
    config: APIKeyConfig
    created_at: datetime
    last_used_at: datetime | None = None
    status: APIKeyStatus = APIKeyStatus.ACTIVE
    usage_today: int = 0
    usage_stats: list[APIKeyUsage] = field(default_factory=list)

    def is_valid(self) -> bool:
        """检查是否有效"""
        if self.status != APIKeyStatus.ACTIVE:
            return False
        if self.config.expires_at and self.config.expires_at < datetime.utcnow():
            return False
        return not (self.config.daily_quota and self.usage_today >= self.config.daily_quota)

    def check_rate_limit(self) -> bool:
        """检查速率限制"""
        # 简化：基于今日使用量检查
        return not (self.config.daily_quota and self.usage_today >= self.config.daily_quota)

    def check_ip(self, ip: str) -> bool:
        """检查 IP 白名单"""
        if not self.config.allowed_ips:
            return True
        return ip in self.config.allowed_ips

    def check_scope(self, required_scope: APIKeyScope) -> bool:
        """检查权限"""
        return required_scope in self.config.scopes or APIKeyScope.ADMIN in self.config.scopes


class APIKeyManager:
    """API Key 管理系统"""

    def __init__(self):
        self._keys: dict[str, APIKey] = {}
        self._hash_index: dict[str, str] = {}  # hash -> key_id

    def create_key(self, config: APIKeyConfig) -> tuple[str, str]:
        """创建新的 API Key
        Returns: (key_id, raw_key) - raw_key 只在创建时返回一次
        """
        key_id = secrets.token_hex(8)
        raw_key = f"ck_{secrets.token_hex(32)}"
        prefix = raw_key[:12] + "..."

        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        api_key = APIKey(
            id=key_id,
            key_hash=key_hash,
            prefix=prefix,
            config=config,
            created_at=datetime.utcnow(),
        )

        self._keys[key_id] = api_key
        self._hash_index[key_hash] = key_id

        return key_id, raw_key

    def get_key(self, key_id: str) -> APIKey | None:
        """获取 Key"""
        return self._keys.get(key_id)

    def verify_key(self, raw_key: str) -> APIKey | None:
        """验证 Key"""
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = self._hash_index.get(key_hash)

        if not key_id:
            return None

        key = self._keys.get(key_id)
        if key and key.is_valid():
            return key
        return None

    def revoke_key(self, key_id: str) -> bool:
        """撤销 Key"""
        key = self._keys.get(key_id)
        if key:
            key.status = APIKeyStatus.REVOKED
            return True
        return False

    def record_usage(self, key_id: str, usage: APIKeyUsage):
        """记录使用"""
        key = self._keys.get(key_id)
        if key:
            key.usage_stats.append(usage)
            key.last_used_at = datetime.utcnow()
            key.usage_today += 1

            # 清理旧记录（保留7天）
            cutoff = datetime.utcnow() - timedelta(days=7)
            key.usage_stats = [u for u in key.usage_stats if u.timestamp > cutoff]

    def list_keys(self) -> list[APIKey]:
        """列出所有 Key"""
        return list(self._keys.values())

    def get_stats(self, key_id: str) -> dict:
        """获取统计"""
        key = self._keys.get(key_id)
        if not key:
            return {}

        return {
            "total_requests": len(key.usage_stats),
            "usage_today": key.usage_today,
            "last_used": key.last_used_at.isoformat() if key.last_used_at else None,
            "average_latency_ms": sum(u.latency_ms for u in key.usage_stats) / max(len(key.usage_stats), 1),
        }


# 全局实例
_api_key_manager: APIKeyManager | None = None


def get_api_key_manager() -> APIKeyManager:
    """获取全局 API Key 管理器"""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager()
    return _api_key_manager


__all__ = [
    "APIKey",
    "APIKeyConfig",
    "APIKeyManager",
    "APIKeyScope",
    "APIKeyStatus",
    "APIKeyUsage",
    "get_api_key_manager",
]

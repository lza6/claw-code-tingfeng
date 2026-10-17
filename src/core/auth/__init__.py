"""Auth Package — 认证与授权模块 (整合自 Onyx)

支持:
- JWT 验证 (RS256/HS256)
- API Key 管理
- 权限系统 (RBAC)
- 速率限制

## 历史与现状

本包原先是 `src/core/auth_module/` 的**重复副本**：两个目录各自持有一份
`api_key.py` / `jwt.py` / `permissions.py`，且都无外部消费者。后来
`auth_module/` 一侧保留为真实实现，本目录的 `.py` 文件被删空，只剩这份
`__init__.py` —— 它的 `from .api_key import ...` 指向不存在的文件，
导致 `import src.core.auth` 必然抛 `ModuleNotFoundError`。

现将其改为对 `auth_module` 的**转发门面**：保留 `src.core.auth` 这个导入
路径可用，同时消灭第二份实现。
"""

from ..auth_module.api_key import (
    APIKey,
    APIKeyConfig,
    APIKeyManager,
    APIKeyScope,
    APIKeyStatus,
    APIKeyUsage,
    get_api_key_manager,
)
from ..auth_module.jwt import (
    JWT_PUBLIC_KEY_URL,
    JWT_SECRET_KEY,
    create_jwt_token,
    decode_jwt_token,
    verify_jwt_token,
)
from ..auth_module.permissions import (
    Permission,
    UserRole,
    can_access_document,
    check_permission_or_403,
    get_role_permissions,
    has_all_permissions,
    has_any_permission,
    has_permission,
)
from ..auth_module.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    RateLimitStats,
    TokenRateLimiter,
    get_rate_limiter,
    get_token_rate_limiter,
)

__all__ = [
    "JWT_PUBLIC_KEY_URL",
    "JWT_SECRET_KEY",
    "APIKey",
    "APIKeyConfig",
    "APIKeyManager",
    # API Key
    "APIKeyScope",
    "APIKeyStatus",
    "APIKeyUsage",
    "Permission",
    "RateLimitConfig",
    "RateLimitStats",
    "RateLimiter",
    "TokenRateLimiter",
    # Permissions
    "UserRole",
    "can_access_document",
    "check_permission_or_403",
    "create_jwt_token",
    "decode_jwt_token",
    "get_api_key_manager",
    "get_rate_limiter",
    "get_role_permissions",
    "get_token_rate_limiter",
    "has_all_permissions",
    "has_any_permission",
    "has_permission",
    # JWT
    "verify_jwt_token",
]

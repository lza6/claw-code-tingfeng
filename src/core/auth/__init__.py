"""Auth Package — 认证与授权模块 (整合自 Onyx)

支持:
- JWT 验证 (RS256/HS256)
- API Key 管理
- 权限系统 (RBAC)
- 速率限制
"""
from .api_key import (
    APIKey,
    APIKeyConfig,
    APIKeyManager,
    APIKeyScope,
    APIKeyStatus,
    APIKeyUsage,
    get_api_key_manager,
)
from .jwt import (
    JWT_PUBLIC_KEY_URL,
    JWT_SECRET_KEY,
    create_jwt_token,
    decode_jwt_token,
    verify_jwt_token,
)
from .permissions import (
    Permission,
    UserRole,
    can_access_document,
    check_permission_or_403,
    get_role_permissions,
    has_all_permissions,
    has_any_permission,
    has_permission,
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
    # Permissions
    "UserRole",
    "can_access_document",
    "check_permission_or_403",
    "create_jwt_token",
    "decode_jwt_token",
    "get_api_key_manager",
    "get_role_permissions",
    "has_all_permissions",
    "has_any_permission",
    "has_permission",
    # JWT
    "verify_jwt_token",
]

"""
权限系统 - 整合自 Onyx

基于角色的访问控制 (RBAC)
"""
from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class UserRole(str, Enum):
    """用户角色"""
    ADMIN = "admin"
    PASSED_VERIFICATION = "passed_verification"
    EDITOR = "editor"
    VIEWER = "viewer"
    UNauthenticated = "unauthenticated"


# 角色继承关系
ROLE_HIERARCHY = {
    UserRole.ADMIN: {UserRole.ADMIN, UserRole.PASSED_VERIFICATION, UserRole.EDITOR, UserRole.VIEWER},
    UserRole.PASSED_VERIFICATION: {UserRole.PASSED_VERIFICATION, UserRole.EDITOR, UserRole.VIEWER},
    UserRole.EDITOR: {UserRole.EDITOR, UserRole.VIEWER},
    UserRole.VIEWER: {UserRole.VIEWER},
    UserRole.UNauthenticated: {UserRole.UNauthenticated},
}


class Permission(str, Enum):
    """权限类型"""
    # 文档权限
    READ_DOCUMENT = "read_document"
    EDIT_DOCUMENT = "edit_document"
    DELETE_DOCUMENT = "delete_document"

    # 搜索权限
    SEARCH = "search"

    # 管理权限
    ADMIN = "admin"
    MANAGE_USERS = "manage_users"
    MANAGE_CONNECTORS = "manage_connectors"
    MANAGE_SETTINGS = "manage_settings"

    # API 权限
    CREATE_API_KEY = "create_api_key"
    USE_API = "use_api"


# 角色权限映射
ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.ADMIN: {
        Permission.READ_DOCUMENT,
        Permission.EDIT_DOCUMENT,
        Permission.DELETE_DOCUMENT,
        Permission.SEARCH,
        Permission.ADMIN,
        Permission.MANAGE_USERS,
        Permission.MANAGE_CONNECTORS,
        Permission.MANAGE_SETTINGS,
        Permission.CREATE_API_KEY,
        Permission.USE_API,
    },
    UserRole.PASSED_VERIFICATION: {
        Permission.READ_DOCUMENT,
        Permission.EDIT_DOCUMENT,
        Permission.SEARCH,
        Permission.USE_API,
    },
    UserRole.EDITOR: {
        Permission.READ_DOCUMENT,
        Permission.EDIT_DOCUMENT,
        Permission.SEARCH,
    },
    UserRole.VIEWER: {
        Permission.READ_DOCUMENT,
        Permission.SEARCH,
    },
    UserRole.UNauthenticated: {
        # 无权限
    },
}


def get_role_permissions(role: UserRole) -> set[Permission]:
    """获取角色权限"""
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(role: UserRole, permission: Permission) -> bool:
    """检查角色是否有权限"""
    permissions = get_role_permissions(role)
    return permission in permissions


def has_any_permission(role: UserRole, permissions: list[Permission]) -> bool:
    """检查角色是否有任一权限"""
    role_perms = get_role_permissions(role)
    return any(p in role_perms for p in permissions)


def has_all_permissions(role: UserRole, permissions: list[Permission]) -> bool:
    """检查角色是否有所有权限"""
    role_perms = get_role_permissions(role)
    return all(p in role_perms for p in permissions)


def can_access_document(role: UserRole, document_owner_id: str | None, user_id: str | None) -> bool:
    """检查是否可以访问文档"""
    # 管理员总是可以访问
    if role == UserRole.ADMIN:
        return True

    # 未登录用户只能访问公开文档
    if role == UserRole.UNauthenticated:
        return False

    # 编辑器及以上可以访问所有文档
    if role in [UserRole.PASSED_VERIFICATION, UserRole.EDITOR]:
        return True

    # 查看者只能访问自己的文档或公开文档
    if role == UserRole.VIEWER:
        return document_owner_id == user_id

    return False


def check_permission_or_403(role: UserRole, permission: Permission) -> None:
    """检查权限，不通过则抛出异常"""
    if not has_permission(role, permission):
        from .exceptions import ClawdError, ErrorCode
        raise ClawdError(ErrorCode.FORBIDDEN, f"Missing permission: {permission}")


__all__ = [
    "Permission",
    "UserRole",
    "can_access_document",
    "check_permission_or_403",
    "get_role_permissions",
    "has_all_permissions",
    "has_any_permission",
    "has_permission",
]

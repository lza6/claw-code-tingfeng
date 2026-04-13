from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretStore(Protocol):
    """秘密存储提供者协议"""

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        """获取秘密"""
        ...

    def set_secret(self, key: str, value: str) -> bool:
        """设置秘密"""
        ...

    def delete_secret(self, key: str) -> bool:
        """删除秘密"""
        ...


class EnvSecretStore(SecretStore):
    """基于环境变量的秘密存储（基础版）"""

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default)

    def set_secret(self, key: str, value: str) -> bool:
        os.environ[key] = value
        return True

    def delete_secret(self, key: str) -> bool:
        if key in os.environ:
            del os.environ[key]
            return True
        return False

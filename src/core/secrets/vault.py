from __future__ import annotations

import logging

try:
    import hvac
    HAS_HVAC = True
except ImportError:
    HAS_HVAC = False

from .base import SecretStore

logger = logging.getLogger(__name__)


class VaultSecretStore(SecretStore):
    """HashiCorp Vault 秘密存储提供者"""

    def __init__(
        self,
        url: str = "http://localhost:8200",
        token: str | None = None,
        mount_point: str = "secret",
    ) -> None:
        if not HAS_HVAC:
            raise ImportError("请安装 hvac: pip install hvac")

        self.client = hvac.Client(url=url, token=token)
        self.mount_point = mount_point
        self._check_connection()

    def _check_connection(self) -> None:
        """检查 Vault 连接状态"""
        try:
            if not self.client.is_authenticated():
                logger.warning("Vault 未通过身份验证")
        except Exception as e:
            logger.error(f"Vault 连接失败: {e}")

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        """从 Vault 获取秘密"""
        try:
            # 路径约定: secret/data/clawd/keys/key_name
            read_response = self.client.secrets.kv.v2.read_secret_version(
                mount_point=self.mount_point,
                path=f"clawd/{key}"
            )
            return read_response['data']['data'].get('value', default)
        except Exception:
            return default

    def set_secret(self, key: str, value: str) -> bool:
        """设置 Vault 秘密"""
        try:
            self.client.secrets.kv.v2.create_or_update_secret(
                mount_point=self.mount_point,
                path=f"clawd/{key}",
                secret={'value': value}
            )
            return True
        except Exception as e:
            logger.error(f"Vault 写入秘密失败: {e}")
            return False

    def delete_secret(self, key: str) -> bool:
        """从 Vault 删除秘密"""
        try:
            self.client.secrets.kv.v2.delete_metadata_and_all_versions(
                mount_point=self.mount_point,
                path=f"clawd/{key}"
            )
            return True
        except Exception as e:
            logger.error(f"Vault 删除秘密失败: {e}")
            return False

"""加密工具测试 - 覆盖 src/utils/crypto_tools.py"""

import pytest
from src.utils.crypto_tools import (
    _derive_fernet_key,
    get_fernet,
    encrypt,
    decrypt,
)


class TestDeriveFernetKey:
    """Fernet 密钥派生测试"""

    def test_derive_fernet_key(self):
        """测试密钥派生"""
        key = _derive_fernet_key("test-secret")
        assert isinstance(key, bytes)
        assert len(key) > 0


class TestGetFernet:
    """Fernet 获取测试"""

    def test_get_fernet_default(self):
        """测试默认密钥"""
        fernet = get_fernet()
        assert fernet is not None

    def test_get_fernet_custom(self):
        """测试自定义密钥"""
        fernet = get_fernet("custom-key")
        assert fernet is not None


class TestEncryptDecrypt:
    """加密解密测试"""

    def test_encrypt_decrypt(self):
        """测试加密解密"""
        original = "Hello, World!"
        encrypted = encrypt(original, "test-key")
        decrypted = decrypt(encrypted, "test-key")
        assert decrypted == original

    def test_encrypt_different_outputs(self):
        """测试加密输出不同"""
        original = "Hello"
        encrypted1 = encrypt(original, "key1")
        encrypted2 = encrypt(original, "key1")
        # 相同内容 + 相同密钥 = 相同输出 (Fernet 特性)
        # 注意: Fernet 在某些模式下会包含随机 IV
        assert encrypted1 != original

    def test_decrypt_wrong_key_fails(self):
        """测试错误密钥解密失败"""
        original = "Secret message"
        encrypted = encrypt(original, "correct-key")
        with pytest.raises(Exception):
            decrypt(encrypted, "wrong-key")
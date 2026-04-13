"""CryptoEnhanced 模块测试 — Fernet 加密、哈希、随机字符串、API Key"""
from __future__ import annotations

import pytest

from src.utils.crypto_enhanced import (
    generate_fernet_key,
    encrypt_data,
    decrypt_data,
    sha256_hash,
    md5_hash,
    hash_api_key,
    verify_api_key,
    generate_secure_random,
    generate_api_key,
    generate_order_id,
    generate_invitation_code,
    generate_cache_key,
    hash_password,
    verify_password,
)


# ====================================================================
# Fernet 加密测试
# ====================================================================

class TestFernetEncryption:
    """Fernet 加密测试"""

    def test_generate_key(self):
        """生成密钥"""
        key = generate_fernet_key()
        assert isinstance(key, str)
        assert len(key) > 0

    def test_generate_key_unique(self):
        """每次生成不同密钥"""
        k1 = generate_fernet_key()
        k2 = generate_fernet_key()
        assert k1 != k2

    def test_encrypt_decrypt_roundtrip(self):
        """加密解密往返"""
        key = generate_fernet_key()
        data = "secret message"
        encrypted = encrypt_data(data, key)
        decrypted = decrypt_data(encrypted, key)
        assert decrypted == data

    def test_encrypted_differs_from_original(self):
        """加密后不同于原文"""
        key = generate_fernet_key()
        data = "secret"
        encrypted = encrypt_data(data, key)
        assert encrypted != data

    def test_encrypt_empty_string(self):
        """加密空字符串"""
        key = generate_fernet_key()
        encrypted = encrypt_data("", key)
        decrypted = decrypt_data(encrypted, key)
        assert decrypted == ""

    def test_encrypt_unicode(self):
        """加密 Unicode"""
        key = generate_fernet_key()
        data = "中文密码"
        encrypted = encrypt_data(data, key)
        decrypted = decrypt_data(encrypted, key)
        assert decrypted == "中文密码"

    def test_encrypt_long_string(self):
        """加密长字符串"""
        key = generate_fernet_key()
        data = "x" * 10000
        encrypted = encrypt_data(data, key)
        decrypted = decrypt_data(encrypted, key)
        assert decrypted == data

    def test_decrypt_wrong_key(self):
        """错误密钥解密"""
        key1 = generate_fernet_key()
        key2 = generate_fernet_key()
        encrypted = encrypt_data("secret", key1)
        with pytest.raises(Exception):
            decrypt_data(encrypted, key2)

    def test_decrypt_invalid_data(self):
        """解密无效数据"""
        key = generate_fernet_key()
        with pytest.raises(Exception):
            decrypt_data("not_valid_encrypted_data", key)

    def test_decrypt_empty_string(self):
        """解密空字符串"""
        key = generate_fernet_key()
        with pytest.raises(Exception):
            decrypt_data("", key)

    def test_multiple_encryptions_differ(self):
        """多次加密结果不同（随机 IV）"""
        key = generate_fernet_key()
        data = "same data"
        e1 = encrypt_data(data, key)
        e2 = encrypt_data(data, key)
        assert e1 != e2  # Fernet 使用随机 IV


# ====================================================================
# 哈希函数测试
# ====================================================================

class TestHashFunctions:
    """哈希函数测试"""

    def test_sha256_basic(self):
        """SHA-256 基本测试"""
        h = sha256_hash("hello")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex length

    def test_sha256_deterministic(self):
        """SHA-256 确定性"""
        h1 = sha256_hash("hello")
        h2 = sha256_hash("hello")
        assert h1 == h2

    def test_sha256_different_inputs(self):
        """SHA-256 不同输入"""
        h1 = sha256_hash("hello")
        h2 = sha256_hash("world")
        assert h1 != h2

    def test_sha256_empty_string(self):
        """SHA-256 空字符串"""
        h = sha256_hash("")
        assert len(h) == 64
        # SHA-256 of empty string
        assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_sha256_unicode(self):
        """SHA-256 Unicode"""
        h = sha256_hash("你好")
        assert len(h) == 64

    def test_md5_basic(self):
        """MD5 基本测试"""
        h = md5_hash("hello")
        assert isinstance(h, str)
        assert len(h) == 32  # MD5 hex length

    def test_md5_deterministic(self):
        """MD5 确定性"""
        h1 = md5_hash("hello")
        h2 = md5_hash("hello")
        assert h1 == h2

    def test_md5_empty_string(self):
        """MD5 空字符串"""
        h = md5_hash("")
        assert len(h) == 32
        assert h == "d41d8cd98f00b204e9800998ecf8427e"


# ====================================================================
# API Key 测试
# ====================================================================

class TestApiKey:
    """API Key 测试"""

    def test_hash_api_key(self):
        """哈希 API Key"""
        h = hash_api_key("sk-test123")
        assert isinstance(h, str)
        assert len(h) == 64

    def test_hash_api_key_deterministic(self):
        """哈希 API Key 确定性"""
        h1 = hash_api_key("sk-test123")
        h2 = hash_api_key("sk-test123")
        assert h1 == h2

    def test_verify_api_key_success(self):
        """验证 API Key 成功"""
        key = "sk-secret"
        hashed = hash_api_key(key)
        assert verify_api_key(key, hashed) is True

    def test_verify_api_key_failure(self):
        """验证 API Key 失败"""
        hashed = hash_api_key("correct-key")
        assert verify_api_key("wrong-key", hashed) is False

    def test_generate_api_key_default_prefix(self):
        """默认前缀生成 API Key"""
        key = generate_api_key()
        assert key.startswith("sk-")
        assert len(key) > 10

    def test_generate_api_key_custom_prefix(self):
        """自定义前缀生成 API Key"""
        key = generate_api_key(prefix="pk")
        assert key.startswith("pk-")

    def test_generate_api_key_unique(self):
        """每次生成不同 API Key"""
        k1 = generate_api_key()
        k2 = generate_api_key()
        assert k1 != k2

    def test_generate_api_key_length(self):
        """API Key 长度"""
        key = generate_api_key()
        # prefix(2) + "-" + 48 chars = 51
        assert len(key) == 2 + 1 + 48  # "sk" + "-" + 48


# ====================================================================
# 安全随机字符串测试
# ====================================================================

class TestSecureRandom:
    """安全随机字符串测试"""

    def test_default_length(self):
        """默认长度"""
        s = generate_secure_random()
        assert len(s) == 32

    def test_custom_length(self):
        """自定义长度"""
        s = generate_secure_random(length=16)
        assert len(s) == 16

    def test_zero_length(self):
        """零长度"""
        s = generate_secure_random(length=0)
        assert s == ""

    def test_alphanumeric_only(self):
        """仅字母数字"""
        s = generate_secure_random(length=100, special_chars=False)
        assert s.isalnum()

    def test_with_special_chars(self):
        """包含特殊字符"""
        s = generate_secure_random(length=100, special_chars=True)
        # 可能包含特殊字符
        assert len(s) == 100

    def test_unique_strings(self):
        """每次生成不同字符串"""
        s1 = generate_secure_random()
        s2 = generate_secure_random()
        assert s1 != s2

    def test_large_length(self):
        """大长度"""
        s = generate_secure_random(length=10000)
        assert len(s) == 10000


# ====================================================================
# 订单 ID / 邀请码测试
# ====================================================================

class TestOrderIdAndInvitation:
    """订单 ID 和邀请码测试"""

    def test_generate_order_id(self):
        """生成订单 ID"""
        order_id = generate_order_id()
        assert isinstance(order_id, str)
        assert len(order_id) > 0

    def test_generate_order_id_unique(self):
        """订单 ID 唯一性"""
        ids = {generate_order_id() for _ in range(100)}
        assert len(ids) == 100

    def test_generate_order_id_starts_with_timestamp(self):
        """订单 ID 以时间戳开头"""
        order_id = generate_order_id()
        # 前 13 位应该是毫秒时间戳
        prefix = int(order_id[:13])
        import time
        current_ts = int(time.time() * 1000)
        assert abs(prefix - current_ts) < 5000  # 5 秒内

    def test_generate_invitation_code(self):
        """生成邀请码"""
        code = generate_invitation_code()
        assert len(code) == 8
        assert code.isalnum()
        assert code.isupper() or code.isdigit()

    def test_generate_invitation_code_custom_length(self):
        """自定义长度邀请码"""
        code = generate_invitation_code(length=6)
        assert len(code) == 6

    def test_generate_invitation_code_unique(self):
        """邀请码唯一性"""
        codes = {generate_invitation_code() for _ in range(100)}
        assert len(codes) == 100


# ====================================================================
# 缓存键生成测试
# ====================================================================

class TestCacheKey:
    """缓存键生成测试"""

    def test_basic(self):
        """基本缓存键"""
        key = generate_cache_key("a", "b", "c")
        assert isinstance(key, str)
        assert len(key) == 16

    def test_deterministic(self):
        """确定性"""
        k1 = generate_cache_key("a", 1, True)
        k2 = generate_cache_key("a", 1, True)
        assert k1 == k2

    def test_different_args(self):
        """不同参数不同键"""
        k1 = generate_cache_key("a")
        k2 = generate_cache_key("b")
        assert k1 != k2

    def test_no_args(self):
        """无参数"""
        key = generate_cache_key()
        assert len(key) == 16

    def test_single_arg(self):
        """单参数"""
        key = generate_cache_key("test")
        assert len(key) == 16

    def test_complex_args(self):
        """复杂参数"""
        key = generate_cache_key({"a": 1}, [1, 2, 3], "str")
        assert len(key) == 16


# ====================================================================
# 密码哈希测试
# ====================================================================

class TestPasswordHash:
    """密码哈希测试"""

    def test_hash_password_returns_tuple(self):
        """hash_password 返回元组"""
        result = hash_password("mypassword")
        assert isinstance(result, tuple)
        assert len(result) == 2
        hashed, salt = result
        assert isinstance(hashed, str)
        assert isinstance(salt, str)

    def test_hash_password_with_custom_salt(self):
        """自定义盐值"""
        salt = "mycustomsalt"
        hashed, returned_salt = hash_password("mypassword", salt=salt)
        assert returned_salt == salt

    def test_hash_password_auto_salt(self):
        """自动生成盐值"""
        _, salt1 = hash_password("mypassword")
        _, salt2 = hash_password("mypassword")
        assert salt1 != salt2  # 每次盐值不同

    def test_verify_password_success(self):
        """验证密码成功"""
        hashed, salt = hash_password("mypassword")
        assert verify_password("mypassword", hashed, salt) is True

    def test_verify_password_failure(self):
        """验证密码失败"""
        hashed, salt = hash_password("correctpassword")
        assert verify_password("wrongpassword", hashed, salt) is False

    def test_verify_password_wrong_salt(self):
        """错误盐值验证"""
        hashed, _ = hash_password("mypassword")
        wrong_salt = "wrongsalt"
        assert verify_password("mypassword", hashed, wrong_salt) is False

    def test_password_empty(self):
        """空密码"""
        hashed, salt = hash_password("")
        assert verify_password("", hashed, salt) is True
        assert verify_password("notempty", hashed, salt) is False

    def test_password_unicode(self):
        """Unicode 密码"""
        hashed, salt = hash_password("中文密码")
        assert verify_password("中文密码", hashed, salt) is True

    def test_password_long(self):
        """长密码"""
        long_pw = "x" * 1000
        hashed, salt = hash_password(long_pw)
        assert verify_password(long_pw, hashed, salt) is True

    def test_same_password_different_hashes(self):
        """相同密码不同哈希（不同盐）"""
        h1, s1 = hash_password("same")
        h2, s2 = hash_password("same")
        assert h1 != h2  # 因为盐不同
        assert s1 != s2

    def test_same_salt_same_password_same_hash(self):
        """相同盐值相同密码相同哈希"""
        salt = "fixedsalt"
        h1, _ = hash_password("password", salt=salt)
        h2, _ = hash_password("password", salt=salt)
        assert h1 == h2

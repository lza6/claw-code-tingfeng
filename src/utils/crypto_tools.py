"""
加密工具模块 - 整合自 New-API
提供 Fernet 对称加密、哈希计算、安全随机等功能
"""

import hashlib
import os
import secrets
import string

from cryptography.fernet import Fernet
from loguru import logger

# Fernet 密钥缓存
_fernet_instances = {}


def _derive_fernet_key(secret_key: str) -> bytes:
    """
    从密钥派生 Fernet 密钥

    Args:
        secret_key: 原始密钥字符串

    Returns:
        bytes: Fernet 密钥（URL-safe base64 编码）
    """
    # 使用 SHA-256 哈希并取前 32 字节
    key_hash = hashlib.sha256(secret_key.encode()).digest()

    # Fernet 需要 URL-safe base64 编码的 32 字节密钥
    import base64
    return base64.urlsafe_b64encode(key_hash)


def get_fernet(secret_key: str | None = None) -> Fernet:
    """
    获取或创建 Fernet 实例（带缓存）

    Args:
        secret_key: 密钥字符串，如果为 None 则从环境变量读取

    Returns:
        Fernet: Fernet 加密实例
    """
    if secret_key is None:
        secret_key = os.getenv("SECRET_KEY", "default-secret-key-change-in-production")

    if secret_key in _fernet_instances:
        return _fernet_instances[secret_key]

    try:
        fernet_key = _derive_fernet_key(secret_key)
        fernet = Fernet(fernet_key)
        _fernet_instances[secret_key] = fernet
        return fernet
    except Exception as e:
        logger.error(f"Fernet 初始化失败: {e}")
        raise


def encrypt(data: str, secret_key: str | None = None) -> str:
    """
    加密字符串

    Args:
        data: 要加密的字符串
        secret_key: 密钥，如果为 None 则从环境变量读取

    Returns:
        str: 加密后的字符串（URL-safe base64 编码）
    """
    try:
        fernet = get_fernet(secret_key)
        encrypted = fernet.encrypt(data.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"加密失败: {e}")
        raise


def decrypt(encrypted_data: str, secret_key: str | None = None) -> str:
    """
    解密字符串

    Args:
        encrypted_data: 加密的字符串
        secret_key: 密钥

    Returns:
        str: 解密后的原始字符串
    """
    try:
        fernet = get_fernet(secret_key)
        decrypted = fernet.decrypt(encrypted_data.encode())
        return decrypted.decode()
    except Exception as e:
        logger.error(f"解密失败: {e}")
        raise


def generate_random_string(length: int = 32,
                          use_letters: bool = True,
                          use_digits: bool = True,
                          use_punctuation: bool = False) -> str:
    """
    生成安全的随机字符串

    Args:
        length: 字符串长度
        use_letters: 是否包含字母
        use_digits: 是否包含数字
        use_punctuation: 是否包含标点符号

    Returns:
        str: 随机字符串
    """
    charset = ""
    if use_letters:
        charset += string.ascii_letters
    if use_digits:
        charset += string.digits
    if use_punctuation:
        charset += string.punctuation

    if not charset:
        charset = string.ascii_letters + string.digits

    return ''.join(secrets.choice(charset) for _ in range(length))


def generate_api_key(prefix: str = "sk") -> str:
    """
    生成 API Key

    Args:
        prefix: 前缀（默认 "sk"）

    Returns:
        str: API Key（格式: prefix-随机字符串）
    """
    random_part = generate_random_string(48)
    return f"{prefix}-{random_part}"


def hash_api_key(api_key: str) -> str:
    """
    对 API Key 进行哈希（用于安全存储）

    Args:
        api_key: 原始 API Key

    Returns:
        str: SHA-256 哈希值（十六进制）
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: str, hashed_key: str) -> bool:
    """
    验证 API Key

    Args:
        api_key: 原始 API Key
        hashed_key: 存储的哈希值

    Returns:
        bool: 是否匹配
    """
    return hash_api_key(api_key) == hashed_key


def md5(data: str) -> str:
    """
    计算 MD5 哈希

    Args:
        data: 输入数据

    Returns:
        str: MD5 哈希（十六进制）
    """
    return hashlib.md5(data.encode()).hexdigest()


def sha256(data: str) -> str:
    """
    计算 SHA-256 哈希

    Args:
        data: 输入数据

    Returns:
        str: SHA-256 哈希（十六进制）
    """
    return hashlib.sha256(data.encode()).hexdigest()


def generate_order_id(prefix: str = "ORD") -> str:
    """
    生成唯一订单 ID

    Args:
        prefix: 前缀

    Returns:
        str: 订单 ID（格式: PREFIX-时间戳-随机字符串）
    """
    import time
    timestamp = int(time.time() * 1000)
    random_part = generate_random_string(8, use_letters=True, use_digits=True)
    return f"{prefix}-{timestamp}-{random_part}"


def secure_compare(a: str, b: str) -> bool:
    """
    安全比较两个字符串（防止时序攻击）

    Args:
        a: 字符串 a
        b: 字符串 b

    Returns:
        bool: 是否相等
    """
    return secrets.compare_digest(a.encode(), b.encode())

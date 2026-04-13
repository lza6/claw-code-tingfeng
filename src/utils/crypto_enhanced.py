"""
Crypto Utilities - 加密工具（整合自 New-API）
支持 Fernet 对称加密、哈希、安全随机字符串、API Key 生成
"""

import hashlib
import secrets
import string

from cryptography.fernet import Fernet
from loguru import logger

# ==================== Fernet 对称加密 ====================

def generate_fernet_key() -> str:
    """
    生成 Fernet 加密密钥

    Returns:
        Base64 编码的密钥字符串
    """
    return Fernet.generate_key().decode('utf-8')


def encrypt_data(data: str, key: str) -> str:
    """
    使用 Fernet 加密数据

    Args:
        data: 待加密数据
        key: 加密密钥

    Returns:
        Base64 编码的加密数据
    """
    fernet = Fernet(key.encode('utf-8'))
    encrypted = fernet.encrypt(data.encode('utf-8'))
    return encrypted.decode('utf-8')


def decrypt_data(encrypted_data: str, key: str) -> str:
    """
    使用 Fernet 解密数据

    Args:
        encrypted_data: 加密数据
        key: 解密密钥

    Returns:
        原始数据字符串
    """
    try:
        fernet = Fernet(key.encode('utf-8'))
        decrypted = fernet.decrypt(encrypted_data.encode('utf-8'))
        return decrypted.decode('utf-8')
    except Exception as e:
        logger.error(f"解密失败: {e}")
        raise


# ==================== 哈希函数 ====================

def sha256_hash(data: str) -> str:
    """
    计算 SHA-256 哈希

    Args:
        data: 输入数据

    Returns:
        十六进制哈希字符串
    """
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def md5_hash(data: str) -> str:
    """
    计算 MD5 哈希

    Args:
        data: 输入数据

    Returns:
        十六进制哈希字符串
    """
    return hashlib.md5(data.encode('utf-8')).hexdigest()


def hash_api_key(api_key: str) -> str:
    """
    哈希 API Key（用于安全存储）

    Args:
        api_key: 原始 API Key

    Returns:
        哈希后的 API Key
    """
    return sha256_hash(api_key)


def verify_api_key(api_key: str, hashed_key: str) -> bool:
    """
    验证 API Key

    Args:
        api_key: 原始 API Key
        hashed_key: 哈希后的 API Key

    Returns:
        是否匹配
    """
    return hash_api_key(api_key) == hashed_key


# ==================== 安全随机字符串 ====================

def generate_secure_random(length: int = 32, special_chars: bool = False) -> str:
    """
    生成安全随机字符串

    Args:
        length: 字符串长度
        special_chars: 是否包含特殊字符

    Returns:
        随机字符串
    """
    # 基础字符集：字母 + 数字
    alphabet = string.ascii_letters + string.digits

    if special_chars:
        alphabet += string.punctuation

    # 使用 secrets 模块生成安全随机
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ==================== API Key 生成 ====================

def generate_api_key(prefix: str = "sk") -> str:
    """
    生成 API Key（sk- 前缀）

    Args:
        prefix: 前缀（默认 sk）

    Returns:
        API Key 字符串
    """
    random_part = generate_secure_random(48)
    return f"{prefix}-{random_part}"


def generate_order_id() -> str:
    """
    生成订单 ID（时间戳 + 随机）

    Returns:
        订单 ID 字符串
    """
    import time
    timestamp = int(time.time() * 1000)  # 毫秒级时间戳
    random_part = secrets.token_hex(4)  # 8 位随机十六进制
    return f"{timestamp}{random_part}"


def generate_invitation_code(length: int = 8) -> str:
    """
    生成邀请码（大写字母 + 数字）

    Args:
        length: 码长度

    Returns:
        邀请码字符串
    """
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ==================== 缓存键生成 ====================

def generate_cache_key(*args) -> str:
    """
    生成缓存键（SHA-256 前 16 位）

    Args:
        *args: 参数列表

    Returns:
        缓存键字符串
    """
    key_str = '|'.join(str(arg) for arg in args)
    return hashlib.sha256(key_str.encode('utf-8')).hexdigest()[:16]


# ==================== 密码哈希（bcrypt 替代） ====================

def hash_password(password: str, salt: str | None = None) -> tuple:
    """
    哈希密码（使用 SHA-256 + salt）

    Args:
        password: 原始密码
        salt: 盐值（可选，默认自动生成）

    Returns:
        (哈希密码, 盐值) 元组
    """
    if salt is None:
        salt = secrets.token_hex(16)

    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return hashed, salt


def verify_password(password: str, hashed_password: str, salt: str) -> bool:
    """
    验证密码

    Args:
        password: 原始密码
        hashed_password: 哈希后的密码
        salt: 盐值

    Returns:
        是否匹配
    """
    computed_hash, _ = hash_password(password, salt)
    return computed_hash == hashed_password

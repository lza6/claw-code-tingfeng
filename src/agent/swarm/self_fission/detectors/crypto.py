"""CryptoDetector — 加密/密码学逻辑检测

检测代码中涉及的加密、解密、哈希、签名等密码学操作。
触发标签: #Crypto
"""
from __future__ import annotations

from .base import CodeContext, FeatureDetector, SemanticFeature

# 加密相关模块/库
CRYPTO_IMPORTS: set[str] = {
    'hashlib', 'cryptography', 'Crypto', 'pycryptodome',
    'jwt', 'PyJWT', 'rsa', 'ecdsa', 'nacl', 'pynacl',
    'bcrypt', 'argon2', 'passlib', 'hmac',
    'Crypto.Cipher', 'Crypto.PublicKey', 'Crypto.Hash',
    'cryptography.fernet', 'cryptography.hazmat',
}

# 加密相关关键词
CRYPTO_KEYWORDS: set[str] = {
    'encrypt', 'decrypt', 'cipher', 'plaintext', 'ciphertext',
    'hash', 'digest', 'sha256', 'sha512', 'md5', 'sha1',
    'sign', 'verify', 'signature', 'public_key', 'private_key',
    'secret_key', 'aes', 'rsa', 'dsa', 'ecdh', 'hmac',
    'fernet', 'padding', 'iv', 'nonce', 'salt',
    'key_derivation', 'pbkdf2', 'bcrypt', 'scrypt', 'argon2',
    'JWT', 'token', 'certificate', 'ssl', 'tls',
}


class CryptoDetector(FeatureDetector):
    """加密逻辑检测器

    检测代码中的加密、哈希、签名等密码学操作。
    """

    @property
    def tag(self) -> str:
        return "#Crypto"

    def detect(self, context: CodeContext) -> SemanticFeature | None:
        """检测加密相关特征

        评分规则:
        - 导入加密库: +0.3 per import (max 0.6)
        - 使用加密关键词: +0.1 per keyword (max 0.4)
        - 综合置信度 >= 0.5 时触发
        """
        score = 0.0
        evidence: list[str] = []

        # 检查导入
        crypto_imports_found = set()
        for imp in context.imports:
            # 检查完整导入路径
            for crypto_imp in CRYPTO_IMPORTS:
                if crypto_imp in imp or imp in crypto_imp:
                    score += 0.3
                    crypto_imports_found.add(imp)
                    evidence.append(f"import: {imp}")
                    break

        # 限制导入分数上限
        import_score = min(0.6, score)
        score = import_score

        # 检查关键词
        keywords_found = set()
        source_lower = context.source_code.lower()
        for keyword in CRYPTO_KEYWORDS:
            if keyword.lower() in source_lower:
                score += 0.1
                keywords_found.add(keyword)
                # 找到关键词所在行
                for i, line in enumerate(context.source_code.split('\n'), 1):
                    if keyword.lower() in line.lower():
                        evidence.append(f"line {i}: {line.strip()[:80]}")
                        break

        # 限制关键词分数上限
        if score > import_score + 0.4:
            score = import_score + 0.4

        # 根据找到的证据调整严重程度
        severity = "medium"
        high_risk_keywords = {'md5', 'sha1', 'des', 'eval(', 'exec('}
        if any(kw in keywords_found for kw in high_risk_keywords):
            severity = "high"

        confidence = min(1.0, score)

        if confidence >= 0.5:
            return SemanticFeature(
                tag=self.tag,
                confidence=confidence,
                evidence=evidence[:10],  # 最多保留 10 条证据
                severity=severity,
            )

        return None

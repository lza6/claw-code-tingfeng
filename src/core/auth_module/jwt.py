"""
JWT 认证模块 - 整合自 Onyx

支持:
- JWT 验证 (RS256)
- JWKS / PEM 格式公钥
- 异步验证
"""
from __future__ import annotations

import json
import logging
import os
from enum import Enum
from functools import lru_cache
from typing import Any

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import InvalidTokenError, PyJWTError
from jwt import decode as jwt_decode
from jwt.algorithms import RSAAlgorithm

logger = logging.getLogger(__name__)


class PublicKeyFormat(Enum):
    JWKS = "jwks"
    PEM = "pem"


# JWT 配置
JWT_PUBLIC_KEY_URL = os.environ.get("JWT_PUBLIC_KEY_URL")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_MINUTES = int(os.environ.get("JWT_EXPIRATION_MINUTES", "60"))

_PUBLIC_KEY_FETCH_ATTEMPTS = 2


@lru_cache
def _fetch_public_key_payload() -> tuple[str | dict[str, Any], PublicKeyFormat] | None:
    """Fetch and cache the raw JWT verification material."""
    if JWT_PUBLIC_KEY_URL is None:
        logger.error("JWT_PUBLIC_KEY_URL is not set")
        return None

    try:
        response = requests.get(JWT_PUBLIC_KEY_URL, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error(f"Failed to fetch JWT public key: {exc!s}")
        return None
    content_type = response.headers.get("Content-Type", "").lower()
    raw_body = response.text
    body_lstripped = raw_body.lstrip()

    if "application/json" in content_type or body_lstripped.startswith("{"):
        try:
            data = response.json()
        except ValueError:
            logger.error("JWT public key URL returned invalid JSON")
            return None

        if isinstance(data, dict) and "keys" in data:
            return data, PublicKeyFormat.JWKS

        logger.error(
            "JWT public key URL returned JSON but no JWKS 'keys' field was found"
        )
        return None

    body = raw_body.strip()
    if not body:
        logger.error("JWT public key URL returned an empty response")
        return None

    return body, PublicKeyFormat.PEM


def get_public_key(token: str) -> RSAPublicKey | str | None:
    """Return the concrete public key used to verify the provided JWT token."""
    payload = _fetch_public_key_payload()
    if payload is None:
        # 尝试使用对称密钥 (HS256)
        if JWT_SECRET_KEY:
            return JWT_SECRET_KEY
        logger.error("Failed to retrieve public key payload")
        return None

    key_material, key_format = payload

    if key_format == PublicKeyFormat.JWKS:
        return _resolve_public_key_from_jwks(token, key_material)

    return key_material


def _resolve_public_key_from_jwks(
    token: str, jwks_payload: dict[str, Any]
) -> RSAPublicKey | None:
    try:
        header = jwt.get_unverified_header(token)
    except PyJWTError as e:
        logger.error(f"Unable to parse JWT header: {e!s}")
        return None

    keys = jwks_payload.get("keys", []) if isinstance(jwks_payload, dict) else []
    if not keys:
        logger.error("JWKS payload did not contain any keys")
        return None

    kid = header.get("kid")
    thumbprint = header.get("x5t")

    candidates = []
    if kid:
        candidates = [k for k in keys if k.get("kid") == kid]
    if not candidates and thumbprint:
        candidates = [k for k in keys if k.get("x5t") == thumbprint]
    if not candidates and len(keys) == 1:
        candidates = keys

    if not candidates:
        logger.warning(
            "No matching JWK found for token header (kid=%s, x5t=%s)", kid, thumbprint
        )
        return None

    if len(candidates) > 1:
        logger.warning(
            "Multiple JWKs matched token header kid=%s; selecting the first occurrence",
            kid,
        )

    jwk = candidates[0]
    try:
        return RSAAlgorithm.from_jwk(json.dumps(jwk))
    except ValueError as e:
        logger.error(f"Failed to construct RSA key from JWK: {e!s}")
        return None


async def verify_jwt_token(token: str) -> dict[str, Any] | None:
    """Verify JWT token and return payload."""
    for attempt in range(_PUBLIC_KEY_FETCH_ATTEMPTS):
        public_key = get_public_key(token)
        if public_key is None:
            logger.error("Unable to resolve a public key for JWT verification")
            if attempt < _PUBLIC_KEY_FETCH_ATTEMPTS - 1:
                _fetch_public_key_payload.cache_clear()
                continue
            return None

        # 根据密钥类型选择算法
        if isinstance(public_key, str):
            # 对称密钥 (HS256, etc.)
            algorithms = [JWT_ALGORITHM]
        else:
            # 非对称密钥 (RS256, etc.)
            algorithms = ["RS256"]

        try:
            payload = jwt_decode(
                token,
                public_key,
                algorithms=algorithms,
                options={"verify_aud": False},
            )
            return payload
        except InvalidTokenError as e:
            logger.error(f"Invalid JWT token: {e!s}")
            if attempt < _PUBLIC_KEY_FETCH_ATTEMPTS - 1:
                _fetch_public_key_payload.cache_clear()
                continue
            return None
        except PyJWTError as e:
            logger.error(f"JWT decoding error: {e!s}")
            if attempt < _PUBLIC_KEY_FETCH_ATTEMPTS - 1:
                _fetch_public_key_payload.cache_clear()
                continue
            return None

    return None


def create_jwt_token(payload: dict[str, Any], expires_in: int = JWT_EXPIRATION_MINUTES) -> str:
    """Create JWT token with payload."""
    from datetime import datetime, timedelta

    if JWT_SECRET_KEY:
        # 使用对称密钥
        return jwt.encode(
            {**payload, "exp": datetime.utcnow() + timedelta(minutes=expires_in)},
            JWT_SECRET_KEY,
            algorithm=JWT_ALGORITHM,
        )
    else:
        logger.warning("JWT_SECRET_KEY not set, token creation skipped")
        return ""


def decode_jwt_token(token: str) -> dict[str, Any] | None:
    """Decode JWT token without verification (for debugging)."""
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except PyJWTError as e:
        logger.error(f"JWT decode error: {e!s}")
        return None

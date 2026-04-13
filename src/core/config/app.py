"""
企业级配置模块 - 整合自 Onyx 的配置模式

提供：
1. 环境变量加载
2. 配置验证
3. 运行时重载
4. 多租户支持
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AuthType(str, Enum):
    """认证类型 (Ported from Onyx)"""
    NONE = "none"
    BASIC = "basic"
    LDAP = "ldap"
    GOOGLE = "google"
    SAML = "saml"
    OIDC = "oidc"


class QueryHistoryType(str, Enum):
    """查询历史类型 (Ported from Onyx)"""
    NORMAL = "normal"
    ANONYMIZED = "anonymized"
    DISABLED = "disabled"


@dataclass
class DatabaseConfig:
    """数据库配置"""
    # PostgreSQL
    postgres_user: str = "postgres"
    postgres_password: str = "password"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "postgres"
    postgres_pool_size: int = 40
    postgres_pool_overflow: int = 10

    # 连接池设置
    pool_size: int = 20
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 3600


@dataclass
class SearchConfig:
    """搜索引擎配置"""
    # OpenSearch
    opensearch_host: str = "localhost"
    opensearch_port: int = 9200
    opensearch_admin_username: str = "admin"
    opensearch_admin_password: str = "StrongPassword123!"
    opensearch_use_ssl: bool = True
    opensearch_timeout: int = 60

    # Vespa
    vespa_host: str = "localhost"
    vespa_port: int = 8081
    vespa_tenant_port: int = 19071

    # 索引设置
    index_batch_size: int = 16


@dataclass
class CacheConfig:
    """缓存配置"""
    backend: str = "redis"  # redis/postgres
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    redis_max_connections: int = 50


@dataclass
class AuthConfig:
    """认证配置"""
    auth_type: AuthType = AuthType.BASIC
    session_expire_seconds: int = 86400 * 7  # 7天

    # OAuth (Google)
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_enabled: bool = False

    # OIDC
    openid_config_url: str = ""
    oidc_pkce_enabled: bool = False

    # SAML
    saml_conf_dir: str = "/app/onyx/configs/saml_config"

    # JWT
    jwt_public_key_url: str = ""
    user_auth_secret: str = ""

    # Password
    password_min_length: int = 8
    password_max_length: int = 64
    password_require_uppercase: bool = False
    password_require_lowercase: bool = False
    password_require_digit: bool = False
    password_require_special_char: bool = False


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8080
    api_prefix: str = ""
    web_domain: str = "http://localhost:3000"
    workers: int = 4
    reload: bool = False
    log_level: str = "INFO"


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str = "openai"
    model: str = "gpt-4"
    api_key: str = ""
    base_url: str | None = None
    timeout: int = 60
    max_retries: int = 3
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass
class AppConfig:
    """应用主配置 (整合 Onyx 的 app_configs)"""

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    api_prefix: str = ""

    # Web
    web_domain: str = "http://localhost:3000"
    api_server_protocol: str = "http"
    api_server_host: str = "127.0.0.1"

    # User Features
    blurp_size: int = 128
    max_upload_size_mb: int = 250
    default_upload_size_mb: int = 100
    send_user_metadata_to_llm: bool = False
    disable_user_knowledge: bool = False
    disable_vector_db: bool = False
    show_extra_connectors: bool = False
    query_history_type: QueryHistoryType = QueryHistoryType.NORMAL

    # Sub-configs
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def from_env(cls) -> AppConfig:
        """从环境变量加载配置"""
        config = cls()

        # App 配置
        config.app_host = os.environ.get("APP_HOST", config.app_host)
        config.app_port = int(os.environ.get("APP_PORT", config.app_port))
        config.api_prefix = os.environ.get("API_PREFIX", config.api_prefix)
        config.web_domain = os.environ.get("WEB_DOMAIN", config.web_domain)
        config.api_server_protocol = os.environ.get("API_SERVER_PROTOCOL", config.api_server_protocol)
        config.api_server_host = os.environ.get("API_SERVER_HOST", config.api_server_host)

        # User Features
        config.max_upload_size_mb = int(os.environ.get("MAX_ALLOWED_UPLOAD_SIZE_MB", config.max_upload_size_mb))
        config.default_upload_size_mb = int(os.environ.get("DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB", config.default_upload_size_mb))
        config.send_user_metadata_to_llm = os.environ.get("SEND_USER_METADATA_TO_LLM_PROVIDER", "").lower() == "true"
        config.disable_user_knowledge = os.environ.get("DISABLE_USER_KNOWLEDGE", "").lower() == "true"
        config.disable_vector_db = os.environ.get("DISABLE_VECTOR_DB", "").lower() == "true"
        config.show_extra_connectors = os.environ.get("SHOW_EXTRA_CONNECTORS", "").lower() == "true"

        # Database
        config.db.postgres_user = os.environ.get("POSTGRES_USER", config.db.postgres_user)
        config.db.postgres_password = os.environ.get("POSTGRES_PASSWORD", config.db.postgres_password)
        config.db.postgres_host = os.environ.get("POSTGRES_HOST", config.db.postgres_host)
        config.db.postgres_port = int(os.environ.get("POSTGRES_PORT", config.db.postgres_port))
        config.db.postgres_db = os.environ.get("POSTGRES_DB", config.db.postgres_db)
        config.db.postgres_pool_size = int(os.environ.get("POSTGRES_API_SERVER_POOL_SIZE", config.db.postgres_pool_size))
        config.db.postgres_pool_overflow = int(os.environ.get("POSTGRES_API_SERVER_POOL_OVERFLOW", config.db.postgres_pool_overflow))

        # Search
        config.search.opensearch_host = os.environ.get("OPENSEARCH_HOST", config.search.opensearch_host)
        config.search.opensearch_port = int(os.environ.get("OPENSEARCH_REST_API_PORT", config.search.opensearch_port))
        config.search.opensearch_admin_username = os.environ.get("OPENSEARCH_ADMIN_USERNAME", config.search.opensearch_admin_username)
        config.search.opensearch_admin_password = os.environ.get("OPENSEARCH_ADMIN_PASSWORD", config.search.opensearch_admin_password)
        config.search.vespa_host = os.environ.get("VESPA_HOST", config.search.vespa_host)
        config.search.vespa_port = int(os.environ.get("VESPA_PORT", config.search.vespa_port))

        # Cache
        config.cache.backend = os.environ.get("CACHE_BACKEND", config.cache.backend)
        config.cache.redis_host = os.environ.get("REDIS_HOST", config.cache.redis_host)
        config.cache.redis_port = int(os.environ.get("REDIS_PORT", config.cache.redis_port))
        config.cache.redis_password = os.environ.get("REDIS_PASSWORD") or None

        # Auth
        auth_type_str = os.environ.get("AUTH_TYPE", "basic").lower()
        if auth_type_str in [a.value for a in AuthType]:
            config.auth.auth_type = AuthType(auth_type_str)
        config.auth.session_expire_seconds = int(os.environ.get("SESSION_EXPIRE_TIME_SECONDS", config.auth.session_expire_seconds))
        config.auth.oauth_client_id = os.environ.get("OAUTH_CLIENT_ID", "")
        config.auth.oauth_client_secret = os.environ.get("OAUTH_CLIENT_SECRET", "")
        config.auth.oauth_enabled = bool(config.auth.oauth_client_id and config.auth.oauth_client_secret)
        config.auth.openid_config_url = os.environ.get("OPENID_CONFIG_URL", "")
        config.auth.oidc_pkce_enabled = os.environ.get("OIDC_PKCE_ENABLED", "").lower() == "true"
        config.auth.jwt_public_key_url = os.environ.get("JWT_PUBLIC_KEY_URL", "")
        config.auth.user_auth_secret = os.environ.get("USER_AUTH_SECRET", "")
        config.auth.password_min_length = int(os.environ.get("PASSWORD_MIN_LENGTH", 8))

        # Server
        config.server.host = os.environ.get("APP_HOST", config.server.host)
        config.server.port = int(os.environ.get("APP_PORT", config.server.port))
        config.server.log_level = os.environ.get("LOG_LEVEL", "INFO")

        # LLM (从现有配置读取)
        config.llm.provider = os.environ.get("LLM_PROVIDER", config.llm.provider)
        config.llm.model = os.environ.get("LLM_MODEL", config.llm.model)
        config.llm.api_key = os.environ.get("LLM_API_KEY", "")
        config.llm.base_url = os.environ.get("LLM_BASE_URL") or None
        config.llm.timeout = int(os.environ.get("LLM_TIMEOUT", config.llm.timeout))

        return config

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "app": {
                "host": self.app_host,
                "port": self.app_port,
                "api_prefix": self.api_prefix,
                "web_domain": self.web_domain,
            },
            "db": self.db.__dict__,
            "search": self.search.__dict__,
            "cache": self.cache.__dict__,
            "auth": {
                "auth_type": self.auth.auth_type.value,
                "oauth_enabled": self.auth.oauth_enabled,
            },
            "server": self.server.__dict__,
            "llm": self.llm.__dict__,
        }


# 全局配置实例
_config: AppConfig | None = None


def get_app_config() -> AppConfig:
    """获取应用配置"""
    global _config
    if _config is None:
        _config = AppConfig.from_env()
    return _config


def reload_app_config() -> AppConfig:
    """重新加载配置"""
    global _config
    _config = AppConfig.from_env()
    logger.info("应用配置已重新加载")
    return _config

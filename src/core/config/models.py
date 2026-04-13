"""Settings Model — AgentSettings pydantic 模型

提取自 settings.py (v0.60.0)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .enums import (
    ApprovalMode,
    ConfigSource,
    ConfigSourceKind,
    LLMProviderEnum,
    LogLevelEnum,
)

logger = logging.getLogger(__name__)


class AgentSettings(BaseSettings):
    """Agent 核心配置"""

    # LLM 配置
    llm_provider: LLMProviderEnum = Field(
        default=LLMProviderEnum.OPENAI,
        description="LLM 提供商名称",
    )
    llm_api_key: str | None = Field(
        default=None,
        description="LLM API 密钥",
    )
    llm_model: str = Field(
        default="gpt-4",
        description="LLM 模型名称",
    )
    llm_base_url: str | None = Field(
        default=None,
        description="LLM API 基础 URL（自定义端点）",
    )

    # Weak Model (借鉴 Aider) — 用于摘要、commit message 等低成本操作
    weak_model: str | None = Field(
        default=None,
        description="弱模型名称 (用于摘要/commit message，降低成本)",
    )

    # Agent 行为配置
    max_iterations: int = Field(
        default=10,
        ge=1,
        le=100,
        description="最大迭代次数",
    )
    command_timeout: int = Field(
        default=30,
        ge=1,
        le=600,
        description="命令执行超时（秒）",
    )
    max_context_tokens: int = Field(
        default=8000,
        ge=1000,
        le=128000,
        description="最大上下文 token 数",
    )
    approval_mode: ApprovalMode = Field(
        default=ApprovalMode.DEFAULT,
        description="工具执行审批模式 (Plan/Default/Auto-edit/YOLO)",
    )

    # 性能配置
    provider_rate_limit: int = Field(
        default=40,
        ge=1,
        description="API 速率限制（请求/分钟）",
    )
    provider_max_concurrency: int = Field(
        default=5,
        ge=1,
        le=20,
        description="最大并发请求数",
    )

    # 功能开关
    enable_cost_tracking: bool = Field(
        default=True,
        description="启用成本追踪",
    )
    enable_events: bool = Field(
        default=True,
        description="启用事件系统",
    )
    enable_request_optimization: bool = Field(
        default=True,
        description="启用请求优化",
    )

    # God Mode / Developer Features (Ported from Project B)
    developer_mode: bool = Field(
        default=False,
        description="启用开发者模式 (God Mode)，解锁受限操作和额外工具",
    )
    features_path: Path = Field(
        default=Path(".clawd/features.json"),
        description="实验性功能开关配置文件路径",
    )

    # RTK 风格输出压缩 (v0.40.0 新增)
    enable_output_compression: bool = Field(
        default=True,
        description="启用输出压缩 (借鉴 RTK 的 12 种过滤策略)",
    )
    enable_tee_mode: bool = Field(
        default=True,
        description="启用 tee 模式 — 命令失败时保存原始输出 (借鉴 RTK tee.rs)",
    )
    enable_token_tracking: bool = Field(
        default=True,
        description="启用 token 用量追踪 — 记录原始 vs 压缩后的 token 量",
    )

    # 聊天历史压缩 (借鉴 Project B)
    enable_chat_summarization: bool = Field(
        default=True,
        description="启用聊天历史总结 (当上下文接近上限时自动压缩)",
    )
    compression_token_threshold: float = Field(
        default=0.7,
        ge=0.1,
        le=0.9,
        description="触发压缩的 token 比例阈值 (默认 0.7)",
    )
    compression_preserve_threshold: float = Field(
        default=0.3,
        ge=0.1,
        le=0.5,
        description="压缩后保留的最近历史比例 (默认 0.3)",
    )

    # 向量存储配置 (Task 28)
    vector_store_type: str = Field(
        default="local",
        description="向量存储类型 (local/faiss/qdrant)",
    )
    vector_store_path: Path | None = Field(
        default=None,
        description="向量存储持久化路径 (对于 local 模式)",
    )
    vector_store_dimension: int = Field(
        default=1536,
        description="向量维度",
    )

    # 日志配置
    log_level: LogLevelEnum = Field(
        default=LogLevelEnum.INFO,
        description="日志级别",
    )
    enable_file_logging: bool = Field(
        default=False,
        description="启用文件日志",
    )

    # 服务器配置
    agent_server_host: str = Field(
        default="127.0.0.1",
        description="Agent 服务器监听地址",
    )
    agent_server_port: int = Field(
        default=8765,
        ge=1,
        le=65535,
        description="Agent 服务器端口",
    )

    # 工作目录
    workdir: Path | None = Field(
        default=None,
        description="工作目录路径",
    )

    # ===== Aider 风格参数 (v0.40.0 整合) =====

    # 模型配置文件 (借鉴 Aider args.py)
    model_settings_file: Path = Field(
        default=Path(".clawd.model.settings.yml"),
        description="模型设置配置文件 (YAML)",
    )
    model_metadata_file: Path = Field(
        default=Path(".clawd.model.metadata.json"),
        description="模型元数据文件 (JSON)",
    )

    # 代码地图配置 (借鉴 Aider repomap)
    map_tokens: int = Field(
        default=1024,
        ge=0,
        le=32000,
        description="代码地图 token 预算 (0 表示禁用)",
    )
    map_refresh: str = Field(
        default="auto",
        description="代码地图刷新策略 (auto/always/files/manual)",
    )
    map_multiplier_no_files: float = Field(
        default=2.0,
        ge=1.0,
        description="无文件指定时的 token 乘数",
    )

    # 编辑格式 (借鉴 Aider coders)
    edit_format: str = Field(
        default="diff",
        description="编辑格式 (editblock/diff/wholefile/udiff/patch)",
    )

    # 思考 token (借鉴 Aider o1 系列)
    reasoning_effort: str | None = Field(
        default=None,
        description="思考努力级别 (low/medium/high)",
    )
    thinking_tokens: int | None = Field(
        default=None,
        description="思考 token 预算 (0 禁用)",
    )

    # SSL 验证
    verify_ssl: bool = Field(
        default=True,
        description="验证 SSL 证书",
    )

    # 流式输出
    stream: bool = Field(
        default=True,
        description="启用流式输出",
    )

    # 深色/浅色模式
    dark_mode: bool = Field(
        default=False,
        description="深色模式",
    )
    light_mode: bool = Field(
        default=False,
        description="浅色模式",
    )

    # 历史文件配置
    input_history_file: Path = Field(
        default=Path(".clawd.input.history"),
        description="输入历史文件",
    )
    chat_history_file: Path = Field(
        default=Path(".clawd.chat.history.md"),
        description="聊天历史文件",
    )
    restore_chat_history: bool = Field(
        default=False,
        description="恢复上次的聊天历史",
    )

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 来源追踪 (Enhanced for v0.60.0)
    _sources: dict[str, ConfigSource] = PrivateAttr(default_factory=dict)

    def _track_sources(self) -> None:
        """追踪配置来源 (Enhanced based on Project B's configResolver)

        配置优先级 (从高到低):
            0. CLAUDE_INTERNAL_FC_OVERRIDES (JSON env var, 最高优先级)
            1. OS Environment
            2. provider.json (借鉴 ClawGod 的结构化配置)
            3. Hierarchical .env files
            4. features.json (功能开关)
            5. Built-in defaults
        """
        from pathlib import Path

        # Priority 0: CLAUDE_INTERNAL_FC_OVERRIDES (ClawGod 风格最高优先级)
        self._apply_internal_overrides()

        # ClawGod v2: 自动设置隐私保护环境变量
        self._apply_clawgod_privacy_defaults()

        # Paths for hierarchical config (Project -> User Home)
        env_files = self.model_config.get("env_file", ".env")
        if isinstance(env_files, str):
            env_files = [env_files]

        config_paths = [Path(f) for f in env_files]
        config_paths.append(Path.home() / ".clawd" / ".env")

        env_keys_by_file = {}
        for p in config_paths:
            if p.exists():
                try:
                    content = p.read_text(encoding="utf-8")
                    keys = set()
                    for line in content.splitlines():
                        if "=" in line and not line.strip().startswith("#"):
                            keys.add(line.split("=")[0].strip())
                    env_keys_by_file[str(p)] = keys
                except Exception:
                    pass

        for field_name, field_info in self.__class__.model_fields.items():
            env_key = field_info.validation_alias or field_name.upper()
            env_key = str(env_key)

            # Priority 1: OS Environment (Highest)
            if os.environ.get(env_key):
                self._sources[field_name] = ConfigSource(kind=ConfigSourceKind.ENV, env_key=env_key, detail="OS Environment")
            # Priority 2: Hierarchical .env files
            else:
                found_in_file = False
                for p_str, keys in env_keys_by_file.items():
                    if env_key in keys:
                        kind = ConfigSourceKind.SETTINGS if "home" not in p_str.lower() else ConfigSourceKind.USER_SETTINGS
                        self._sources[field_name] = ConfigSource(kind=kind, env_key=env_key, file_path=p_str)
                        found_in_file = True
                        break

                if not found_in_file:
                    # Priority 3: Default value
                    if field_name in self.__dict__ and self.__dict__[field_name] == field_info.default:
                        self._sources[field_name] = ConfigSource(kind=ConfigSourceKind.DEFAULT, detail="Built-in Default")
                    # Priority 4: Computed or CLI
                    else:
                        self._sources[field_name] = ConfigSource(kind=ConfigSourceKind.COMPUTED, detail="In-memory/CLI override")

        # Priority 2: provider.json (ClawGod 风格结构化 API 配置)
        self._load_provider_json()

        # Priority 4: features.json Overrides (功能开关)
        self._load_features_json()

    def _load_provider_json(self) -> None:
        """加载 provider.json 配置（借鉴 ClawGod 的设计）

        查找顺序:
            1. ~/.clawd/provider.json (用户级)
            2. .clawd/provider.json (项目级)

        如果 activeProvider 存在，从 providers 字典加载对应配置。
        """
        from pathlib import Path

        provider_paths = [
            Path.home() / ".clawd" / "provider.json",
            Path.cwd() / ".clawd" / "provider.json",
        ]

        for provider_path in provider_paths:
            if provider_path.exists():
                try:
                    data = json.loads(provider_path.read_text(encoding="utf-8"))
                    self._sources["provider_config"] = ConfigSource(
                        kind=ConfigSourceKind.USER_SETTINGS,
                        file_path=str(provider_path),
                        detail=f"Loaded from {provider_path}"
                    )

                    # 如果指定了 activeProvider，加载对应提供商配置
                    active = data.get("activeProvider")
                    providers = data.get("providers", {})

                    if active and active in providers:
                        provider_cfg = providers[active]
                        if provider_cfg.get("apiKey"):
                            self.llm_api_key = provider_cfg["apiKey"]
                            self._sources["llm_api_key"] = ConfigSource(
                                kind=ConfigSourceKind.USER_SETTINGS,
                                file_path=str(provider_path),
                                detail=f"provider.json -> {active}"
                            )
                        if provider_cfg.get("baseURL"):
                            self.llm_base_url = provider_cfg["baseURL"]
                        if provider_cfg.get("model"):
                            self.llm_model = provider_cfg["model"]
                        if provider_cfg.get("timeoutMs"):
                            self.command_timeout = provider_cfg["timeoutMs"] // 1000

                        logger.info(f"已从 provider.json 加载 {active} 配置")
                    elif data.get("apiKey"):
                        # 使用顶层配置
                        self.llm_api_key = data["apiKey"]
                        if data.get("baseURL"):
                            self.llm_base_url = data["baseURL"]
                        if data.get("model"):
                            self.llm_model = data["model"]
                        if data.get("timeoutMs"):
                            self.command_timeout = data["timeoutMs"] // 1000

                        logger.info("已从 provider.json 加载配置")
                    break
                except Exception as e:
                    logger.warning(f"加载 provider.json 失败: {e}")
                    break

    def _load_features_json(self) -> None:
        """加载 features.json 功能开关（增强版）"""
        if self.features_path and self.features_path.exists():
            try:
                feature_flags = json.loads(self.features_path.read_text(encoding="utf-8"))
                for k, v in feature_flags.items():
                    if hasattr(self, k):
                        setattr(self, k, v)
                        self._sources[k] = ConfigSource(kind=ConfigSourceKind.USER_SETTINGS, file_path=str(self.features_path), detail="features.json override")
            except Exception as e:
                logger.warning(f"加载 features.json 失败: {e}")

    def _apply_internal_overrides(self) -> None:
        """应用 ClawGod 风格的内部覆盖（通过环境变量 CLAUDE_INTERNAL_FC_OVERRIDES）"""
        overrides_json = os.environ.get("CLAUDE_INTERNAL_FC_OVERRIDES")
        if not overrides_json:
            return

        try:
            overrides = json.loads(overrides_json)
            if not isinstance(overrides, dict):
                logger.warning("CLAUDE_INTERNAL_FC_OVERRIDES must be a JSON object")
                return

            for key, value in overrides.items():
                if hasattr(self, key):
                    if isinstance(value, dict):
                        value = value.get("enabled", True)
                    setattr(self, key, value)
                    self._sources[key] = ConfigSource(
                        kind=ConfigSourceKind.USER_SETTINGS,
                        detail="CLAUDE_INTERNAL_FC_OVERRIDES"
                    )

            logger.debug(f"已应用 {len(overrides)} 个内部覆盖")
        except json.JSONDecodeError as e:
            logger.warning(f"无效的 CLAUDE_INTERNAL_FC_OVERRIDES JSON: {e}")
        except Exception as e:
            logger.warning(f"应用内部覆盖失败: {e}")

    def _apply_clawgod_privacy_defaults(self) -> None:
        """应用 ClawGod 风格的隐私保护默认值

        ClawGod 标准行为:
        - CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 (禁用遥测)
        - DISABLE_INSTALLATION_CHECKS=1 (禁用安装检查)
        - 扩展超时到 50 分钟 (3000000ms)
        """

        # 遥测控制 — 仅在未显式设置时应用默认值
        if os.environ.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") is None:
            os.environ.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")

        if os.environ.get("DISABLE_INSTALLATION_CHECKS") is None:
            os.environ.setdefault("DISABLE_INSTALLATION_CHECKS", "1")

        # 超时控制 — 使用 ClawGod 标准 50 分钟
        timeout_env = os.environ.get("API_TIMEOUT_MS")
        if timeout_env is None:
            os.environ.setdefault("API_TIMEOUT_MS", "3000000")
            # 同步到 command_timeout (秒)
            if self.command_timeout <= 60:  # 仅当使用默认小超时时才扩展
                self.command_timeout = 3000
                self._sources["command_timeout"] = ConfigSource(
                    kind=ConfigSourceKind.COMPUTED,
                    detail="ClawGod extended timeout (50min)"
                )

    def get_source(self, field_name: str) -> ConfigSource:
        """获取字段的来源"""
        return self._sources.get(field_name, ConfigSource(kind=ConfigSourceKind.UNKNOWN))

    @field_validator("llm_api_key")
    @classmethod
    def validate_api_key(cls, v: str | None, info: Any) -> str | None:
        """验证 API 密钥格式"""
        if v is None:
            logger.warning("未配置 LLM API 密钥")
            return v

        # 基本格式检查
        if len(v.strip()) < 10:
            raise ValueError("API 密钥长度不足，请检查配置")

        # 检测常见占位符
        placeholders = ["<your-api-key>", "your-api-key", "YOUR_API_KEY", "sk-xxx"]
        if v.strip() in placeholders:
            raise ValueError("API 密钥仍为占位符，请替换为真实密钥")

        return v.strip()

    @model_validator(mode="after")
    def validate_provider_config(self) -> AgentSettings:
        """验证提供商配置完整性"""
        if self.llm_provider != LLMProviderEnum.OPENAI and self.llm_base_url is None:
            # 非 OpenAI 提供商通常需要自定义 base_url
            logger.debug(f"提供商 {self.llm_provider.value} 可能需要自定义 base_url")

        return self

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于日志和调试）"""
        result = self.model_dump()
        # 隐藏敏感信息
        if result.get("llm_api_key"):
            result["llm_api_key"] = result["llm_api_key"][:8] + "..."
        return result

    def get_tool_timeouts(self) -> dict[str, int]:
        """获取工具超时配置"""
        tool_timeouts_str = os.environ.get("TOOL_TIMEOUTS")
        if tool_timeouts_str:
            try:
                return json.loads(tool_timeouts_str)
            except (json.JSONDecodeError, ValueError):
                logger.warning(f"TOOL_TIMEOUTS 格式错误: {tool_timeouts_str[:50]}")
        return {}


def load_settings() -> AgentSettings:
    """加载并验证配置

    返回:
        验证通过的 AgentSettings 实例

    异常:
        ValidationError: 配置验证失败
    """
    try:
        settings = AgentSettings()
        settings._track_sources()  # 启动后追踪来源
        logger.info(f"配置已加载: {settings.llm_provider.value} / {settings.llm_model}")
        return settings
    except Exception as e:
        logger.error(f"配置加载失败: {e}")
        raise


# 向后兼容：提供全局设置实例
_settings: AgentSettings | None = None


def get_settings() -> AgentSettings:
    """获取全局配置实例（单例模式）"""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reload_settings() -> AgentSettings:
    """重新加载配置"""
    global _settings
    _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """重置全局配置单例（主要用于测试）"""
    global _settings
    _settings = None
    return _settings

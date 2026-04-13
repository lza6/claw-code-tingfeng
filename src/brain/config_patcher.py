"""Config Patcher — 配置热修补模块

动态热修补运行时参数。
例如自动调整 MAX_ITERATIONS 或 TOKEN_LIMIT。

存储路径: 项目目录/.clawd/brain/runtime_config.json
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..core.project_context import ProjectContext
from .models import ConfigPatchResult

# 默认配置存储路径（向后兼容）
DEFAULT_CONFIG_DIR = Path('.clawd') / 'brain'
CONFIG_PATCH_FILE = "runtime_config.json"


# 可修补的参数白名单
PATCHABLE_PARAMS = {
    "MAX_ITERATIONS",
    "TOKEN_LIMIT",
    "TEMPERATURE",
    "TOP_P",
    "MAX_CONTEXT_LENGTH",
    "TOOL_TIMEOUT_SECONDS",
    "RETRY_COUNT",
    "ENABLE_SELF_HEALING",
    "ENABLE_EXPERIENCE_RETRIEVAL",
    "EXPERIENCE_MIN_SUCCESS_RATE",
    # Effort Level 机制 (从 goalx-main 整合)
    "EFFORT_LEVEL",
    "PREFERRED_MODEL",
}


class EffortLevel(str, Enum):
    """推理努力等级 (从 goalx-main 整合)

    用于动态调节 LLM 的推理深度和资源消耗:
    - MINIMAL: 最轻量，适合简单任务
    - LOW: 低推理深度，常规任务
    - MEDIUM: 中等推理深度 (默认)
    - HIGH: 高推理深度，复杂分析
    - MAX: 最大推理深度，架构决策/关键任务
    """
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


@dataclass
class EngineConfig:
    """引擎配置 (从 goalx-main 整合)

    定义如何启动和配置 AI 引擎。
    """
    name: str = ""
    command: str = ""
    prompt: str = ""
    models: dict[str, str] = field(default_factory=dict)      # 模型别名 -> 实际 ID
    effort_mode: str = "flag"                                  # flag | config
    effort_flag: str = "--effort"                              # CLI 标志
    effort_key: str = ""                                       # 配置键
    effort_map: dict[str, str] = field(default_factory=dict)  # 努力等级映射


@dataclass
class RuntimeConfig:
    """运行时配置"""
    MAX_ITERATIONS: int = 10
    TOKEN_LIMIT: int = 4096
    TEMPERATURE: float = 0.7
    TOP_P: float = 0.9
    MAX_CONTEXT_LENGTH: int = 8000
    TOOL_TIMEOUT_SECONDS: int = 60
    RETRY_COUNT: int = 3
    ENABLE_SELF_HEALING: bool = True
    ENABLE_EXPERIENCE_RETRIEVAL: bool = True
    EXPERIENCE_MIN_SUCCESS_RATE: float = 0.6
    # Effort Level 机制 (从 goalx-main 整合)
    EFFORT_LEVEL: str = "medium"
    PREFERRED_MODEL: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "MAX_ITERATIONS": self.MAX_ITERATIONS,
            "TOKEN_LIMIT": self.TOKEN_LIMIT,
            "TEMPERATURE": self.TEMPERATURE,
            "TOP_P": self.TOP_P,
            "MAX_CONTEXT_LENGTH": self.MAX_CONTEXT_LENGTH,
            "TOOL_TIMEOUT_SECONDS": self.TOOL_TIMEOUT_SECONDS,
            "RETRY_COUNT": self.RETRY_COUNT,
            "ENABLE_SELF_HEALING": self.ENABLE_SELF_HEALING,
            "ENABLE_EXPERIENCE_RETRIEVAL": self.ENABLE_EXPERIENCE_RETRIEVAL,
            "EXPERIENCE_MIN_SUCCESS_RATE": self.EXPERIENCE_MIN_SUCCESS_RATE,
            "EFFORT_LEVEL": self.EFFORT_LEVEL,
            "PREFERRED_MODEL": self.PREFERRED_MODEL,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeConfig:
        return cls(
            MAX_ITERATIONS=data.get("MAX_ITERATIONS", cls.MAX_ITERATIONS),
            TOKEN_LIMIT=data.get("TOKEN_LIMIT", cls.TOKEN_LIMIT),
            TEMPERATURE=data.get("TEMPERATURE", cls.TEMPERATURE),
            TOP_P=data.get("TOP_P", cls.TOP_P),
            MAX_CONTEXT_LENGTH=data.get("MAX_CONTEXT_LENGTH", cls.MAX_CONTEXT_LENGTH),
            TOOL_TIMEOUT_SECONDS=data.get("TOOL_TIMEOUT_SECONDS", cls.TOOL_TIMEOUT_SECONDS),
            RETRY_COUNT=data.get("RETRY_COUNT", cls.RETRY_COUNT),
            ENABLE_SELF_HEALING=data.get("ENABLE_SELF_HEALING", cls.ENABLE_SELF_HEALING),
            ENABLE_EXPERIENCE_RETRIEVAL=data.get("ENABLE_EXPERIENCE_RETRIEVAL", cls.ENABLE_EXPERIENCE_RETRIEVAL),
            EXPERIENCE_MIN_SUCCESS_RATE=data.get("EXPERIENCE_MIN_SUCCESS_RATE", cls.EXPERIENCE_MIN_SUCCESS_RATE),
            EFFORT_LEVEL=data.get("EFFORT_LEVEL", cls.EFFORT_LEVEL),
            PREFERRED_MODEL=data.get("PREFERRED_MODEL", cls.PREFERRED_MODEL),
        )


class ConfigPatcher:
    """配置热修补器

    动态修改运行时参数，无需重启服务。
    """

    def __init__(self, config_dir: Path | None = None, project_ctx: ProjectContext | None = None) -> None:
        """初始化配置热修补器

        Args:
            config_dir: 配置目录（显式指定时优先使用）
            project_ctx: 项目上下文（用于自动推导路径）
        """
        if config_dir is not None:
            self._config_dir = config_dir
        elif project_ctx is not None:
            self._config_dir = project_ctx.brain_dir
        else:
            self._config_dir = DEFAULT_CONFIG_DIR
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._patch_file = self._config_dir / CONFIG_PATCH_FILE
        self._config = self._load_config()

    def _load_config(self) -> RuntimeConfig:
        """加载配置 (补丁优先)"""
        if self._patch_file.exists():
            try:
                data = json.loads(self._patch_file.read_text(encoding="utf-8"))
                return RuntimeConfig.from_dict(data)
            except (json.JSONDecodeError, ValueError):
                pass
        return RuntimeConfig()

    def get_config(self) -> RuntimeConfig:
        """获取当前配置"""
        return self._config

    def get_value(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return getattr(self._config, key, default)

    def apply_patch(self, patch: dict[str, Any]) -> ConfigPatchResult:
        """应用配置补丁

        参数:
            patch: 配置键值对

        返回:
            ConfigPatchResult
        """
        # 验证参数
        invalid_keys = set(patch.keys()) - PATCHABLE_PARAMS
        if invalid_keys:
            return ConfigPatchResult(
                success=False,
                error=f"不支持的参数: {', '.join(invalid_keys)}。"
                      f"支持的参数: {', '.join(sorted(PATCHABLE_PARAMS))}",
            )

        # 验证类型
        type_checks = {
            "MAX_ITERATIONS": int,
            "TOKEN_LIMIT": int,
            "TEMPERATURE": (int, float),
            "TOP_P": (int, float),
            "MAX_CONTEXT_LENGTH": int,
            "TOOL_TIMEOUT_SECONDS": int,
            "RETRY_COUNT": int,
            "ENABLE_SELF_HEALING": bool,
            "ENABLE_EXPERIENCE_RETRIEVAL": bool,
            "EXPERIENCE_MIN_SUCCESS_RATE": (int, float),
        }

        for key, value in patch.items():
            expected_type = type_checks.get(key)
            if expected_type and not isinstance(value, expected_type):
                return ConfigPatchResult(
                    success=False,
                    error=f"参数 {key} 类型错误，期望 {expected_type}，得到 {type(value).__name__}",
                )

        # 验证 Effort Level 值
        if "EFFORT_LEVEL" in patch:
            valid_efforts = {"minimal", "low", "medium", "high", "max"}
            if patch["EFFORT_LEVEL"] not in valid_efforts:
                return ConfigPatchResult(
                    success=False,
                    error=f"EFFORT_LEVEL 必须是以下之一: {', '.join(sorted(valid_efforts))}",
                )

        # 验证范围
        range_checks = {
            "TEMPERATURE": (0.0, 2.0),
            "TOP_P": (0.0, 1.0),
            "EXPERIENCE_MIN_SUCCESS_RATE": (0.0, 1.0),
            "MAX_ITERATIONS": (1, 100),
            "RETRY_COUNT": (0, 10),
        }

        for key, value in patch.items():
            if key in range_checks:
                min_val, max_val = range_checks[key]
                if not (min_val <= value <= max_val):
                    return ConfigPatchResult(
                        success=False,
                        error=f"参数 {key} 超出范围: {min_val} ~ {max_val}",
                    )

        # 应用补丁
        old_values = {}
        for key, value in patch.items():
            old_values[key] = getattr(self._config, key)
            setattr(self._config, key, value)

        # 持久化
        try:
            self._save_config()
        except Exception as e:
            # 回滚
            for key, value in old_values.items():
                setattr(self._config, key, value)
            return ConfigPatchResult(
                success=False,
                error=f"保存配置失败: {e}",
            )

        return ConfigPatchResult(
            success=True,
            patched_params=patch,
        )

    def _save_config(self) -> None:
        """保存配置到文件"""
        data = self._config.to_dict()
        self._patch_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def reset_to_defaults(self) -> ConfigPatchResult:
        """重置为默认配置"""
        old_config = self._config
        self._config = RuntimeConfig()
        try:
            self._save_config()
            return ConfigPatchResult(
                success=True,
                patched_params=self._config.to_dict(),
            )
        except Exception as e:
            self._config = old_config
            return ConfigPatchResult(
                success=False,
                error=f"重置配置失败: {e}",
            )

    def get_patchable_params(self) -> dict[str, dict[str, Any]]:
        """获取可修补参数列表及其约束"""
        param_info = {
            "MAX_ITERATIONS": {"type": "int", "range": (1, 100), "default": 10, "description": "最大迭代次数"},
            "TOKEN_LIMIT": {"type": "int", "range": (256, 32768), "default": 4096, "description": "Token 限制"},
            "TEMPERATURE": {"type": "float", "range": (0.0, 2.0), "default": 0.7, "description": "采样温度"},
            "TOP_P": {"type": "float", "range": (0.0, 1.0), "default": 0.9, "description": "Top-p 采样"},
            "MAX_CONTEXT_LENGTH": {"type": "int", "range": (1000, 32768), "default": 8000, "description": "最大上下文长度"},
            "TOOL_TIMEOUT_SECONDS": {"type": "int", "range": (5, 300), "default": 60, "description": "工具超时时间"},
            "RETRY_COUNT": {"type": "int", "range": (0, 10), "default": 3, "description": "重试次数"},
            "ENABLE_SELF_HEALING": {"type": "bool", "default": True, "description": "启用自愈"},
            "ENABLE_EXPERIENCE_RETRIEVAL": {"type": "bool", "default": True, "description": "启用经验检索"},
            "EXPERIENCE_MIN_SUCCESS_RATE": {"type": "float", "range": (0.0, 1.0), "default": 0.6, "description": "经验最小成功率"},
            # Effort Level 机制 (从 goalx-main 整合)
            "EFFORT_LEVEL": {"type": "str", "choices": ["minimal", "low", "medium", "high", "max"], "default": "medium",
                             "description": "推理努力等级 (控制 LLM 推理深度)"},
            "PREFERRED_MODEL": {"type": "str", "default": "", "description": "首选模型 (覆盖默认选择)"},
        }
        return param_info

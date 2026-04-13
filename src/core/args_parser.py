"""Args Parser — 命令行参数解析增强

借鉴 Aider 的参数解析设计，提供:
1. 增强的参数验证
2. 编辑格式动态获取
3. 环境变量自动映射
4. 配置文件支持

使用:
    from src.core.args_parser import ClawdArgParser, create_parser

    parser = create_parser()
    args = parser.parse_args()
"""
from __future__ import annotations

import os
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

from ..utils import get_logger

logger = get_logger(__name__)

# 尝试导入可选依赖
try:
    import configargparse as _configargparse  # noqa: F401
    CONFIGARGPARSE_AVAILABLE = True
except ImportError:
    CONFIGARGPARSE_AVAILABLE = False


class EditFormatChoices:
    """动态获取支持的编辑格式"""

    @staticmethod
    def get_choices() -> list[str]:
        """获取所有支持的编辑格式"""
        # 尝试从 code_edit 模块获取
        try:
            from src.tools_runtime.code_edit import EDIT_FORMAT_REGISTRY
            return sorted(EDIT_FORMAT_REGISTRY.keys())
        except ImportError:
            pass

        # 回退到默认列表
        return [
            "editblock",
            "editblock-fenced",
            "editblock-func",
            "wholefile",
            "wholefile-func",
            "single-wholefile-func",
            "udiff",
            "udiff-simple",
            "patch",
            "architect",
            "ask",
            "context",
            "help",
            "search_replace",
            "shell",
        ]

    @staticmethod
    def get_default() -> str:
        """获取默认编辑格式"""
        return "editblock"


class ClawdArgParser:
    """增强的参数解析器

    借鉴 Aider 的设计:
    - 动态编辑格式选择
    - 环境变量自动映射
    - 配置文件支持
    """

    def __init__(
        self,
        prog: str | None = None,
        description: str | None = None,
        config_files: list[str] | None = None,
    ):
        self.prog = prog
        self.description = description
        self.config_files = config_files or [".clawd/settings.json", ".env"]
        self._parser: ArgumentParser | None = None

    def _create_parser(self) -> ArgumentParser:
        """创建 ArgumentParser"""
        parser = ArgumentParser(
            prog=self.prog,
            description=self.description or "Clawd Code - AI Pair Programming",
            # 启用环境变量自动映射
            # environ_prefix="CLAWD_",
        )
        return parser

    def add_main_args(self, parser: ArgumentParser) -> None:
        """添加主参数组"""
        parser.add_argument_group("Main")

        # 位置参数：文件
        parser.add_argument(
            "files",
            metavar="FILE",
            nargs="*",
            help="Files to edit with AI (optional)",
        )

        # 模型选择
        parser.add_argument(
            "--model", "-m",
            metavar="MODEL",
            default=None,
            help="Specify the model to use",
        )

    def add_model_args(self, parser: ArgumentParser) -> None:
        """添加模型参数组"""
        parser.add_argument_group("Model Settings")

        # 弱模型（用于摘要和提交信息）
        parser.add_argument(
            "--weak-model",
            metavar="MODEL",
            default=None,
            help="Model for commit messages and summarization",
        )

        # 编辑模型
        parser.add_argument(
            "--editor-model",
            metavar="MODEL",
            default=None,
            help="Model for editor tasks",
        )

        # 编辑格式
        choices = EditFormatChoices.get_choices()
        parser.add_argument(
            "--edit-format", "--chat-mode",
            metavar="FORMAT",
            choices=choices,
            default=None,
            help=f"Edit format (default: {EditFormatChoices.get_default()})",
        )

        # 架构师模式
        parser.add_argument(
            "--architect",
            action="store_true",
            help="Use architect edit format",
        )

        # 思维 token
        parser.add_argument(
            "--thinking-tokens",
            type=str,
            default=None,
            help="Thinking token budget (0 to disable)",
        )

    def add_api_args(self, parser: ArgumentParser) -> None:
        """添加 API 参数组"""
        parser.add_argument_group("API Keys")

        # OpenAI
        parser.add_argument(
            "--openai-api-key",
            default=None,
            help="OpenAI API key",
        )

        # Anthropic
        parser.add_argument(
            "--anthropic-api-key",
            default=None,
            help="Anthropic API key",
        )

        # 通用 API 密钥
        parser.add_argument(
            "--api-key",
            action="append",
            metavar="PROVIDER=KEY",
            help="Set API key (can be used multiple times)",
            default=[],
        )

        # 环境变量设置
        parser.add_argument(
            "--set-env",
            action="append",
            metavar="VAR=value",
            help="Set environment variable",
            default=[],
        )

    def add_output_args(self, parser: ArgumentParser) -> None:
        """添加输出参数组"""
        parser.add_argument_group("Output")

        # 颜色输出
        parser.add_argument(
            "--no-color",
            action="store_true",
            help="Disable color output",
        )

        # 详细输出
        parser.add_argument(
            "--verbose", "-v",
            action="count",
            default=0,
            help="Increase verbosity",
        )

        # 静默模式
        parser.add_argument(
            "--quiet", "-q",
            action="store_true",
            help="Suppress non-essential output",
        )

    def add_git_args(self, parser: ArgumentParser) -> None:
        """添加 Git 参数组"""
        parser.add_argument_group("Git")

        # 自动提交
        parser.add_argument(
            "--auto-commit",
            action="store_true",
            default=True,
            help="Auto-commit changes (default: True)",
        )

        # 提交语言
        parser.add_argument(
            "--commit-language",
            default=None,
            help="Language for commit messages",
        )

    def build(self) -> ArgumentParser:
        """构建完整的解析器"""
        if self._parser is not None:
            return self._parser

        self._parser = self._create_parser()

        # 添加所有参数组
        self.add_main_args(self._parser)
        self.add_model_args(self._parser)
        self.add_api_args(self._parser)
        self.add_output_args(self._parser)
        self.add_git_args(self._parser)

        return self._parser

    def parse_args(self, args: list[str] | None = None) -> Namespace:
        """解析参数"""
        parser = self.build()
        return parser.parse_args(args)

    def parse_known_args(self, args: list[str] | None = None) -> tuple[Namespace, list[str]]:
        """解析已知参数"""
        parser = self.build()
        return parser.parse_known_args(args)


def create_parser(
    config_files: list[str] | None = None,
    prog: str | None = None,
) -> ClawdArgParser:
    """创建参数解析器的便捷函数

    参数:
        config_files: 配置文件列表
        prog: 程序名

    返回:
        ClawdArgParser 实例
    """
    return ClawdArgParser(
        config_files=config_files,
        prog=prog,
    )


def resolve_env_vars(args: Namespace) -> Namespace:
    """从参数中解析环境变量设置

    参数:
        args: 解析后的参数对象

    返回:
        更新后的参数对象
    """
    # 处理 --set-env 参数
    if hasattr(args, 'set_env') and args.set_env:
        for env_spec in args.set_env:
            if '=' in env_spec:
                key, value = env_spec.split('=', 1)
                os.environ[key.strip()] = value.strip()
                logger.debug(f"Set env: {key}={value}")

    return args


def load_config_file(config_path: str) -> dict[str, Any]:
    """从配置文件加载设置

    参数:
        config_path: 配置文件路径

    返回:
        配置字典
    """
    path = Path(config_path)
    if not path.exists():
        return {}

    try:
        if path.suffix == ".json":
            import json
            return json.loads(path.read_text(encoding='utf-8'))
        elif path.suffix in (".yaml", ".yml"):
            import yaml
            return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception as e:
        logger.warning(f"Failed to load config {config_path}: {e}")

    return {}


# ==================== 便捷函数 ====================

def quick_parse(model: str | None = None, edit_format: str | None = None) -> Namespace:
    """快速解析常用参数

    参数:
        model: 模型名称
        edit_format: 编辑格式

    返回:
        参数对象
    """
    parser = create_parser()
    args = parser.parse_args()

    # 应用覆盖
    if model:
        args.model = model
    if edit_format:
        args.edit_format = edit_format

    return args


def validate_edit_format(format: str) -> bool:
    """验证编辑格式是否有效

    参数:
        format: 编辑格式名称

    返回:
        是否有效
    """
    return format in EditFormatChoices.get_choices()


# 导出
__all__ = [
    "ClawdArgParser",
    "EditFormatChoices",
    "create_parser",
    "load_config_file",
    "quick_parse",
    "resolve_env_vars",
    "validate_edit_format",
]

"""Arg Formatter — 参数格式化器（从 Aider args_formatter.py 移植）

提供 argparse 帮助信息的格式化。

用法:
    from src.utils.arg_formatter import DotEnvFormatter, MarkdownFormatter
"""
from __future__ import annotations

import argparse
from typing import Any


class DotEnvFormatter(argparse.HelpFormatter):
    """Dotenv 格式的帮助格式化器

    将命令行参数转换为 .env 文件格式的示例。
    """

    def start_section(self, heading: str) -> None:
        res = "\n\n"
        res += "#" * (len(heading) + 3)
        res += f"\n# {heading}"
        super().start_section(res)

    def _format_usage(self, usage: str, actions: list, groups: list, prefix: str | None) -> str:
        return ""

    def _format_text(self, text: str) -> str:
        return """
##########################################################
# Sample Clawd .env file.
# Place at the root of your git repo.
# Or use `clawd --env <fname>` to specify.
##########################################################

#################
# LLM parameters:
#
# Include xxx_API_KEY parameters and other params needed for your LLMs.

## OpenAI
#OPENAI_API_KEY=

## Anthropic
#ANTHROPIC_API_KEY=

## DeepSeek
#DEEPSEEK_API_KEY=

##...
"""

    def _format_action(self, action: argparse.Action) -> str:
        if not action.option_strings:
            return ""

        if not getattr(action, 'env_var', None):
            return ""

        parts = [""]

        default = action.default
        if default == argparse.SUPPRESS:
            default = ""
        elif isinstance(default, str):
            pass
        elif isinstance(default, list) and not default:
            default = ""
        elif action.default is not None:
            default = "true" if default else "false"
        else:
            default = ""

        if action.help:
            parts.append(f"## {action.help}")

        env_var = getattr(action, 'env_var', None)
        if env_var:
            if default:
                parts.append(f"#{env_var}={default}\n")
            else:
                parts.append(f"#{env_var}=\n")

        return "\n".join(parts) + "\n"

    def _format_action_invocation(self, action: argparse.Action) -> str:
        return ""

    def _format_args(self, action: argparse.Action, default_metavar: str) -> str:
        return ""


class MarkdownFormatter(argparse.HelpFormatter):
    """Markdown 格式的帮助格式化器"""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._in_code_block = False

    def start_section(self, heading: str) -> None:
        super().start_section(f"## {heading}")

    def _format_action(self, action: argparse.Action) -> str:
        lines = []

        # 动作选项
        if action.option_strings:
            lines.append(f"### `{', '.join(action.option_strings)}`")
        else:
            lines.append(f"### `{action.dest}`")

        # 帮助文本
        if action.help:
            lines.append(action.help.format(**{}))

        # 默认值
        if action.default and action.default != argparse.SUPPRESS:
            lines.append(f"**Default:** `{action.default}`")

        return "\n".join(lines) + "\n\n"


# 导出
__all__ = [
    "DotEnvFormatter",
    "MarkdownFormatter",
]

"""Hook 配置加载器 - 从 TOML 配置文件加载 Hook 定义

功能:
    - 从 hooks/config.toml 加载 Hook 配置
    - 支持 PreToolUse / PostToolUse 类型
    - 自动注册到 HookRegistry
    - 支持命令类型 Hook (shell command)

配置文件格式 (hooks/config.toml):
    [hooks.PostToolUse]
    [hooks.PostToolUse.format]
    matcher = "Write|Edit"
    command = "ruff format"

    [hooks.PreToolUse.size_guard]
    matcher = "Write"
    command = "python -c '...'"

参考: oh-my-codex-main 的 hooks 系统
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import toml

from src.core.hook_registry.enums import HookPoint
from src.core.hook_registry.registry import register_hook
from src.core.hook_registry.specs import FunctionHookSpec, HookExecutionResult, HookResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Hook 类型映射
HOOK_TYPE_MAP = {
    "PostToolUse": HookPoint.POST_TOOL_USE,
    "PreToolUse": HookPoint.PRE_TOOL_USE,
    "SessionStart": HookPoint.SESSION_START,
    "SessionEnd": HookPoint.SESSION_END,
}


@dataclass
class ConfigHookDefinition:
    """从 TOML 解析的 Hook 定义"""
    hook_type: str  # PostToolUse, PreToolUse, etc.
    name: str
    matcher: str  # 工具名称正则 (如 "Write|Edit")
    command: str | None = None
    condition: str | None = None  # 可选的条件表达式


class ConfigHookExecutor:
    """配置 Hook 执行器 - 执行 shell 命令"""

    def __init__(self, definition: ConfigHookDefinition):
        self.definition = definition

    def should_run(self, tool_name: str) -> bool:
        """检查是否应该运行此 Hook"""
        import re

        return bool(re.search(self.definition.matcher, tool_name))

    def execute(self, context) -> HookExecutionResult:
        """执行配置的 shell 命令"""
        if not self.definition.command:
            return HookExecutionResult(
                result=HookResult.CONTINUE,
                message="No command configured",
            )

        try:
            # 替换环境变量
            cmd = os.path.expandvars(self.definition.command)

            # 执行命令（超时 30s）
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.getenv("CLAWD_WORKDIR", "."),
            )

            if result.returncode == 0:
                logger.info(f"Hook '{self.definition.name}' completed")
                return HookExecutionResult(
                    result=HookResult.CONTINUE,
                    message=f"Command succeeded: {self.definition.command}",
                )
            else:
                logger.warning(f"Hook '{self.definition.name}' failed: {result.stderr}")
                return HookExecutionResult(
                    result=HookResult.WARN,
                    message=f"Command failed: {result.stderr}",
                )

        except subprocess.TimeoutExpired:
            return HookExecutionResult(
                result=HookResult.WARN,
                message="Hook command timed out after 30s",
            )
        except Exception as e:
            return HookExecutionResult(
                result=HookResult.WARN,
                message=f"Hook execution error: {e}",
                error=e,
            )


def load_hooks_config(config_path: str | Path = "hooks/config.toml") -> None:
    """从 TOML 文件加载并注册所有 Hook

    Args:
        config_path: 配置文件路径，相对于项目根目录
    """
    path = Path(config_path)
    if not path.exists():
        logger.info(f"No hooks config file found at {path}")
        return

    try:
        config = toml.load(path)
    except Exception as e:
        logger.error(f"Failed to parse hooks config: {e}")
        return

    hooks_section = config.get("hooks", {})
    loaded_count = 0

    for hook_type_str, type_config in hooks_section.items():
        if hook_type_str not in HOOK_TYPE_MAP:
            logger.warning(f"Unknown hook type: {hook_type_str}")
            continue

        hook_point = HOOK_TYPE_MAP[hook_type_str]

        # type_config 应该是一个 dict of hook_name -> {matcher, command, ...}
        for hook_name, hook_def in type_config.items():
            if isinstance(hook_def, dict):
                definition = ConfigHookDefinition(
                    hook_type=hook_type_str,
                    name=hook_name,
                    matcher=hook_def.get("matcher", ""),
                    command=hook_def.get("command"),
                    condition=hook_def.get("condition"),
                )

                executor = ConfigHookExecutor(definition)

                spec = FunctionHookSpec(
                    hook_point=hook_point,
                    handler=executor.execute,
                    name=f"config:{hook_type_str}.{hook_name}",
                )

                register_hook(hook_point, spec)
                loaded_count += 1
                logger.info(f"Loaded hook: {hook_type_str}.{hook_name}")

    logger.info(f"Loaded {loaded_count} hooks from {config_path}")


def get_config_loader_hook_point() -> HookPoint:
    """返回配置加载器应该注册的 Hook 点"""
    return HookPoint.SESSION_START


# 默认配置示例（用于生成 config.toml）
DEFAULT_HOOKS_CONFIG = """
# Hook 配置文件 - 自动在 SessionStart 时加载
# 参考: https://docs.clawd.engineering/hooks

[hooks.PostToolUse]

# 自动格式化代码 (Write/Edit 工具后)
[hooks.PostToolUse.format]
matcher = "Write|Edit"
command = "ruff format {file_path}"

# 运行 linter
[hooks.PostToolUse.lint]
matcher = "Write|Edit|Patch"
command = "ruff check {file_path}"
# condition = "file_path endswith '.py'"  # 可选条件

# Type check
[hooks.PostToolUse.typecheck]
matcher = "Write|Edit"
command = "mypy {file_path} --no-error-summary"

[hooks.PreToolUse]

# 文件大小 Guard (防止超大写入)
[hooks.PreToolUse.size_guard]
matcher = "Write"
command = "python -c \"import sys; content = sys.stdin.read(); lines = len(content.splitlines()); max_lines=800; print(f'{lines}/{max_lines}' if lines <= max_lines else exit(2))\""

[hooks.SessionStart]

# 清理工作区
[hooks.SessionStart.cleanup]
matcher = "*"
command = "python scripts/cleanup_workspace.py"

[hooks.SessionEnd]

# 最终验证
[hooks.SessionEnd.verify]
matcher = "*"
command = "pytest tests/ -x --tb=short"
"""

__all__ = [
    "DEFAULT_HOOKS_CONFIG",
    "ConfigHookDefinition",
    "ConfigHookExecutor",
    "get_config_loader_hook_point",
    "load_hooks_config",
]

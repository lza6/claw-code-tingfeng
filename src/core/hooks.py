"""Hook 系统 — 从 Rust hooks.rs 移植

两种 Hook 运行器:
1. PluginHookRunner — 聚合所有已启用插件的钩子
2. ConfigHookRunner — 从配置驱动的钩子

退出码协议:
- 0 = Allow（继续执行，stdout 作为消息）
- 2 = Deny（立即阻止，停止后续钩子）
- 其他 = Warn（继续，但附带警告）

钩子执行方式:
- 将 JSON payload 通过 stdin 传给钩子命令
- 通过环境变量传递上下文: HOOK_EVENT, HOOK_TOOL_NAME, HOOK_TOOL_INPUT, HOOK_TOOL_OUTPUT, HOOK_TOOL_IS_ERROR
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger('hooks')


# ==================== 数据模型 ====================

class HookEvent(str, Enum):
    """钩子事件类型"""
    PRE_TOOL_USE = 'PreToolUse'
    POST_TOOL_USE = 'PostToolUse'


@dataclass
class HookRunResult:
    """钩子执行结果"""
    denied: bool = False
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'denied': self.denied,
            'messages': self.messages,
        }


@dataclass
class HookPayload:
    """传递给钩子的 JSON payload"""
    hook_event_name: str
    tool_name: str
    tool_input: str
    tool_input_json: str = ''
    tool_output: str = ''
    tool_result_is_error: bool = False

    def to_json(self) -> str:
        return json.dumps({
            'hook_event_name': self.hook_event_name,
            'tool_name': self.tool_name,
            'tool_input': self.tool_input,
            'tool_input_json': self.tool_input_json,
            'tool_output': self.tool_output,
            'tool_result_is_error': self.tool_result_is_error,
        }, ensure_ascii=False)


# ==================== 钩子运行器 ====================

def _run_single_hook(command: str, payload: HookPayload, env_extra: dict[str, str] | None = None) -> HookRunResult:
    """执行单个钩子命令

    退出码协议:
    - 0 = Allow
    - 2 = Deny
    - 其他 = Warn
    """
    try:
        # Parse command string into argument list — avoid shell=True for security
        cmd_list = shlex.split(command)

        # Build a minimal, safe environment (do not leak all parent env vars like API keys)
        safe_env: dict[str, str] = {}
        # PATH is required for the command to be found
        if 'PATH' in os.environ:
            safe_env['PATH'] = os.environ['PATH']
        # Platform-specific essentials
        for key in ('HOME', 'USER', 'LOGNAME', 'SHELL', 'SystemRoot', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
            if key in os.environ:
                safe_env[key] = os.environ[key]

        # Add hook-specific environment variables
        safe_env.update(env_extra or {})
        safe_env.update({
            'HOOK_EVENT': payload.hook_event_name,
            'HOOK_TOOL_NAME': payload.tool_name,
            'HOOK_TOOL_INPUT': payload.tool_input,
            'HOOK_TOOL_OUTPUT': payload.tool_output,
            'HOOK_TOOL_IS_ERROR': str(payload.tool_result_is_error).lower(),
        })

        proc = subprocess.run(
            cmd_list,
            shell=False,
            input=payload.to_json(),
            capture_output=True,
            text=True,
            timeout=30,
            env=safe_env,
        )

        if proc.returncode == 0:
            message = proc.stdout.strip() if proc.stdout.strip() else ''
            messages = [message] if message else []
            return HookRunResult(denied=False, messages=messages)

        if proc.returncode == 2:
            reason = proc.stdout.strip() or proc.stderr.strip() or 'Hook denied tool execution'
            return HookRunResult(denied=True, messages=[reason])

        # Warn
        warning = proc.stderr.strip() or f'Hook exited with code {proc.returncode}'
        return HookRunResult(denied=False, messages=[f'[Hook Warning] {warning}'])

    except subprocess.TimeoutExpired:
        return HookRunResult(denied=False, messages=['[Hook Warning] Hook timed out after 30s'])
    except OSError as e:
        logger.warning(f'Hook execution failed: {e}')
        return HookRunResult(denied=False, messages=[f'[Hook Warning] Hook execution error: {e}'])


class PluginHookRunner:
    """插件钩子运行器 — 聚合所有已启用插件的钩子"""

    def __init__(self, hook_commands: dict[str, list[str]] | None = None) -> None:
        """
        参数:
            hook_commands: {'pre_tool_use': [...], 'post_tool_use': [...]}
        """
        self._commands = hook_commands or {}

    @classmethod
    def from_plugin_manager(cls, plugin_manager: Any) -> PluginHookRunner:
        """从 PluginManager 创建"""
        hooks = plugin_manager.aggregated_hooks()
        return cls(hook_commands={
            'pre_tool_use': hooks.pre_tool_use,
            'post_tool_use': hooks.post_tool_use,
        })

    @classmethod
    def from_plugin_hooks(cls, hooks: Any) -> PluginHookRunner:
        """从 PluginHooks 创建"""
        return cls(hook_commands={
            'pre_tool_use': hooks.pre_tool_use,
            'post_tool_use': hooks.post_tool_use,
        })

    def run_pre_tool_use(self, tool_name: str, tool_input: str) -> HookRunResult:
        """运行 PreToolUse 钩子"""
        return self._run_hooks('pre_tool_use', tool_name, tool_input)

    def run_post_tool_use(self, tool_name: str, tool_input: str,
                          tool_output: str, is_error: bool) -> HookRunResult:
        """运行 PostToolUse 钩子"""
        return self._run_hooks('post_tool_use', tool_name, tool_input,
                               tool_output=tool_output, is_error=is_error)

    def _run_hooks(self, hook_type: str, tool_name: str, tool_input: str,
                   tool_output: str = '', is_error: bool = False) -> HookRunResult:
        """执行钩子链"""
        commands = self._commands.get(hook_type, [])
        if not commands:
            return HookRunResult()

        event_name = 'PreToolUse' if hook_type == 'pre_tool_use' else 'PostToolUse'
        payload = HookPayload(
            hook_event_name=event_name,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            tool_result_is_error=is_error,
        )

        result = HookRunResult()
        for cmd in commands:
            hook_result = _run_single_hook(cmd, payload)
            result.messages.extend(hook_result.messages)
            if hook_result.denied:
                result.denied = True
                break  # Deny 立即停止

        return result


class ConfigHookRunner:
    """配置驱动钩子运行器 — 从运行时配置读取钩子命令"""

    def __init__(self, pre_tool_use: list[str] | None = None,
                 post_tool_use: list[str] | None = None) -> None:
        self._pre_tool_use = pre_tool_use or []
        self._post_tool_use = post_tool_use or []

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ConfigHookRunner:
        """从配置字典创建"""
        hooks = config.get('hooks', {})
        return cls(
            pre_tool_use=hooks.get('PreToolUse', hooks.get('pre_tool_use', [])),
            post_tool_use=hooks.get('PostToolUse', hooks.get('post_tool_use', [])),
        )

    def run_pre_tool_use(self, tool_name: str, tool_input: str) -> HookRunResult:
        if not self._pre_tool_use:
            return HookRunResult()
        payload = HookPayload(
            hook_event_name='PreToolUse',
            tool_name=tool_name,
            tool_input=tool_input,
        )
        result = HookRunResult()
        for cmd in self._pre_tool_use:
            hook_result = _run_single_hook(cmd, payload)
            result.messages.extend(hook_result.messages)
            if hook_result.denied:
                result.denied = True
                break
        return result

    def run_post_tool_use(self, tool_name: str, tool_input: str,
                          tool_output: str, is_error: bool) -> HookRunResult:
        if not self._post_tool_use:
            return HookRunResult()
        payload = HookPayload(
            hook_event_name='PostToolUse',
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            tool_result_is_error=is_error,
        )
        result = HookRunResult()
        for cmd in self._post_tool_use:
            hook_result = _run_single_hook(cmd, payload)
            result.messages.extend(hook_result.messages)
            if hook_result.denied:
                result.denied = True
                break
        return result


class CompositeHookRunner:
    """组合钩子运行器 — 同时运行 Plugin 和 Config 钩子"""

    def __init__(self, runners: list[Any] | None = None) -> None:
        self._runners = runners or []

    def add_runner(self, runner: Any) -> None:
        self._runners.append(runner)

    def run_pre_tool_use(self, tool_name: str, tool_input: str) -> HookRunResult:
        result = HookRunResult()
        for runner in self._runners:
            hook_result = runner.run_pre_tool_use(tool_name, tool_input)
            result.messages.extend(hook_result.messages)
            if hook_result.denied:
                result.denied = True
                break
        return result

    def run_post_tool_use(self, tool_name: str, tool_input: str,
                          tool_output: str, is_error: bool) -> HookRunResult:
        result = HookRunResult()
        for runner in self._runners:
            hook_result = runner.run_post_tool_use(tool_name, tool_input, tool_output, is_error)
            result.messages.extend(hook_result.messages)
            if hook_result.denied:
                result.denied = True
                break
        return result

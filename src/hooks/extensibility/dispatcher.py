"""
Hook Dispatcher - 钩子事件分发器

从 oh-my-codex-main/src/hooks/extensibility/dispatcher.ts 转换而来。
提供钩子事件的调度和执行功能。
"""

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .loader import (
    HookPluginDescriptor,
    discover_hook_plugins,
    is_hook_plugins_enabled,
    resolve_hook_plugin_timeout_ms,
)
from .types import (
    HookDispatchOptions,
    HookDispatchResult,
    HookEventEnvelope,
    HookPluginDispatchResult,
    HookPluginDispatchStatus,
)

RESULT_PREFIX = "__OMX_PLUGIN_RESULT__ "
RUNNER_SIGKILL_GRACE_MS = 250


def hooks_log_path(cwd: str) -> str:
    """获取钩子日志路径"""
    day = datetime.now().strftime("%Y-%m-%d")
    return str(Path(cwd) / ".omx" / "logs" / f"hooks-{day}.jsonl")


async def append_hooks_log(cwd: str, payload: dict[str, Any]) -> None:
    """追加钩子日志"""
    log_dir = Path(cwd) / ".omx" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = hooks_log_path(cwd)
    entry = json.dumps({"timestamp": datetime.now().isoformat(), **payload})

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception as e:
        print(f"[omx] warning: failed to append hook dispatch log entry: {e}")


def is_team_worker(env: dict | None = None) -> bool:
    """检查是否在团队工作器中运行"""
    env = env or os.environ
    return bool(env.get("OMX_TEAM_WORKER", "").strip())


@dataclass
class RunnerResult:
    """运行器结果"""
    ok: bool
    plugin: str
    reason: str
    error: str | None = None


async def run_plugin_runner(
    plugin: HookPluginDescriptor,
    event: HookEventEnvelope,
    cwd: str,
    env: dict | None = None,
    timeout_ms: int | None = None,
    side_effects_enabled: bool = True,
) -> HookPluginDispatchResult:
    """运行插件运行器"""
    started = datetime.now().timestamp() * 1000

    # TODO: 找到正确的运行器路径
    runner_path = str(Path(__file__).parent / "plugin_runner.py")
    timeout = timeout_ms or resolve_hook_plugin_timeout_ms(env)

    if not Path(runner_path).exists():
        duration = int(datetime.now().timestamp() * 1000 - started)
        return HookPluginDispatchResult(
            plugin=plugin.id,
            path=plugin.path,
            ok=False,
            duration_ms=duration,
            status=HookPluginDispatchStatus.RUNNER_MISSING,
            reason="runner_missing",
            skipped=True,
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            "python",
            runner_path,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **(env or {})},
        )

        request_data = json.dumps({
            "cwd": cwd,
            "plugin_id": plugin.id,
            "plugin_path": plugin.path,
            "event": event.to_dict() if hasattr(event, 'to_dict') else event,
            "side_effects_enabled": side_effects_enabled,
        })

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=request_data.encode()),
            timeout=timeout / 1000,
        )

        duration = int(datetime.now().timestamp() * 1000 - started)
        stdout_text = stdout.decode().strip()

        # 解析结果
        lines = [line.strip() for line in stdout_text.split("\n") if line.strip()]
        raw_result = None
        for line in reversed(lines):
            if line.startswith(RESULT_PREFIX):
                raw_result = line[len(RESULT_PREFIX):]
                break

        if raw_result:
            try:
                parsed = json.loads(raw_result)
                return HookPluginDispatchResult(
                    plugin=plugin.id,
                    path=plugin.path,
                    ok=parsed.get("ok", False),
                    duration_ms=duration,
                    status=HookPluginDispatchStatus.OK if parsed.get("ok") else HookPluginDispatchStatus.ERROR,
                    reason=parsed.get("reason", "ok"),
                )
            except json.JSONDecodeError:
                pass

        return HookPluginDispatchResult(
            plugin=plugin.id,
            path=plugin.path,
            ok=False,
            duration_ms=duration,
            status=HookPluginDispatchStatus.ERROR,
            reason="parse_error",
            error=stderr.decode().strip() if stderr else None,
        )

    except asyncio.TimeoutError:
        duration = int(datetime.now().timestamp() * 1000 - started)
        return HookPluginDispatchResult(
            plugin=plugin.id,
            path=plugin.path,
            ok=False,
            duration_ms=duration,
            status=HookPluginDispatchStatus.TIMEOUT,
            reason="timeout",
            skipped=True,
        )
    except Exception as e:
        duration = int(datetime.now().timestamp() * 1000 - started)
        return HookPluginDispatchResult(
            plugin=plugin.id,
            path=plugin.path,
            ok=False,
            duration_ms=duration,
            status=HookPluginDispatchStatus.RUNNER_ERROR,
            reason="spawn_failed",
            error=str(e),
        )


def is_hook_plugin_feature_enabled(env: dict | None = None) -> bool:
    """检查钩子插件功能是否启用"""
    return is_hook_plugins_enabled(env)


def should_force_enable_runtime_hook_dispatch(event: HookEventEnvelope) -> bool:
    """检查是否应强制启用运行时钩子调度"""
    return event.source in ("native", "derived")


async def dispatch_hook_event(
    event: HookEventEnvelope,
    options: HookDispatchOptions | None = None,
) -> HookDispatchResult:
    """调度钩子事件"""
    options = options or HookDispatchOptions(cwd=os.getcwd())
    cwd = options.cwd or os.getcwd()
    env = options.env or dict(os.environ)

    runtime_hook_dispatch_enabled = (
        should_force_enable_runtime_hook_dispatch(event)
        or is_hook_plugins_enabled(env)
    )
    enabled = options.enabled if options.enabled is not None else runtime_hook_dispatch_enabled

    summary = HookDispatchResult(
        enabled=enabled,
        reason="ok" if enabled else "disabled",
        event=event.event,
        source=event.source,
        plugin_count=0,
        results=[],
    )

    if not enabled:
        await append_hooks_log(cwd, {
            "type": "hook_dispatch",
            "event": event.event,
            "source": event.source,
            "enabled": False,
            "reason": "plugins_disabled",
        })
        return summary

    plugins = await discover_hook_plugins(cwd)
    summary.plugin_count = len(plugins)

    in_team_worker = is_team_worker(env)
    allow_team_side_effects = (
        options.allow_team_worker_side_effects
        if options and options.allow_team_worker_side_effects is not None
        else options.allow_in_team_worker if options and options.allow_in_team_worker is not None
        else False
    )
    side_effects_enabled = (
        options.side_effects_enabled
        if options and options.side_effects_enabled is not None
        else (not in_team_worker or allow_team_side_effects)
    )

    for plugin in plugins:
        result = await run_plugin_runner(
            plugin,
            event,
            cwd,
            env,
            options.timeout_ms if options else None,
            side_effects_enabled,
        )
        summary.results.append(result)

        await append_hooks_log(cwd, {
            "type": "hook_plugin_dispatch",
            "event": event.event,
            "source": event.source,
            "plugin": plugin.id,
            "file": plugin.file,
            "ok": result.ok,
            "status": result.status,
            "reason": result.reason,
            "error": result.error,
            "duration_ms": result.duration_ms,
        })

    return summary


# ===== 导出 =====
__all__ = [
    "HookDispatchResult",
    "dispatch_hook_event",
    "is_hook_plugin_feature_enabled",
    "should_force_enable_runtime_hook_dispatch",
]

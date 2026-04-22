"""
Hook Plugin Runner - 钩子插件运行器

从 oh-my-codex-main/src/hooks/extensibility/plugin-runner.ts 转换而来。
从 stdin 读取请求并执行钩子插件。
"""

import asyncio

# 导入 SDK 和类型
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunnerRequest:
    """运行器请求"""
    cwd: str
    plugin_id: str | None = None
    plugin_path: str = ""
    event: dict = field(default_factory=dict)
    side_effects_enabled: bool = True


@dataclass
class RunnerResult:
    """运行器结果"""
    ok: bool
    plugin: str
    reason: str
    error: str | None = None


RESULT_PREFIX = "__OMX_PLUGIN_RESULT__ "


def emit_result(result: RunnerResult) -> None:
    """输出结果"""
    print(f"{RESULT_PREFIX}{json.dumps(result)}")


async def read_stdin() -> str:
    """从 stdin 读取数据"""
    chunks = []
    async for chunk in asyncio.StreamReader(sys.stdin):
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8").strip()


async def main() -> None:
    """主函数"""
    raw = await read_stdin()
    if not raw:
        emit_result(RunnerResult(ok=False, plugin="unknown", reason="empty_request"))
        sys.exit(1)
        return

    try:
        request = json.loads(raw)
    except json.JSONDecodeError:
        emit_result(RunnerResult(ok=False, plugin="unknown", reason="invalid_json"))
        sys.exit(1)
        return

    plugin_id = request.get("plugin_id") or Path(request.get("plugin_path", "")).stem or "unknown"

    try:
        # 动态加载插件模块
        plugin_path = request.get("plugin_path")
        if not plugin_path:
            emit_result(RunnerResult(ok=False, plugin=plugin_id, reason="missing_plugin_path"))
            sys.exit(1)
            return

        # 创建简单的 SDK（实际实现需要完整的 SDK）
        sdk = create_hook_plugin_sdk(request.get("cwd", "."), plugin_id, request.get("event", {}), request.get("side_effects_enabled", True))

        # 加载插件模块（Python 版本）
        spec = importlib.util.spec_from_file_location("hook_plugin", plugin_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules["hook_plugin"] = module
            spec.loader.exec_module(module)

            # 调用 on_hook_event 函数
            if hasattr(module, "on_hook_event"):
                event = request.get("event", {})
                await module.on_hook_event(event, sdk)
                emit_result(RunnerResult(ok=True, plugin=plugin_id, reason="ok"))
                sys.exit(0)
            else:
                emit_result(RunnerResult(ok=False, plugin=plugin_id, reason="invalid_export"))
                sys.exit(1)
        else:
            emit_result(RunnerResult(ok=False, plugin=plugin_id, reason="load_failed"))
            sys.exit(1)

    except Exception as e:
        emit_result(RunnerResult(
            ok=False,
            plugin=plugin_id,
            reason="runner_error",
            error=str(e)
        ))
        sys.exit(1)


def create_hook_plugin_sdk(
    cwd: str,
    plugin_name: str,
    event: dict,
    side_effects_enabled: bool = True,
) -> dict:
    """创建钩子插件 SDK"""
    # 基础 SDK 实现
    return {
        "tmux": {"send_keys": lambda opts: {"ok": True, "reason": "not_implemented"}},
        "log": {
            "info": lambda msg, meta=None: print(f"[INFO] {msg}"),
            "warn": lambda msg, meta=None: print(f"[WARN] {msg}"),
            "error": lambda msg, meta=None: print(f"[ERROR] {msg}"),
        },
        "state": {
            "read": lambda key, fallback=None: None,
            "write": lambda key, value: None,
            "delete": lambda key: None,
            "all": lambda: {},
        },
        "omx": {
            "session": {"read": lambda: None},
            "hud": {"read": lambda: None},
            "notify_fallback": {"read": lambda: None},
            "update_check": {"read": lambda: None},
        },
    }


if __name__ == "__main__":
    asyncio.run(main())

"""
Hook SDK - 钩子插件 SDK

从 oh-my-codex-main/src/hooks/extensibility/sdk.ts 转换而来。
创建钩子插件的 SDK 接口。
"""

import json
from pathlib import Path
from typing import Any


def create_hook_plugin_sdk(
    cwd: str,
    plugin_name: str,
    event: dict,
    side_effects_enabled: bool = True,
) -> dict:
    """创建钩子插件 SDK"""
    plugin_name = sanitize_hook_plugin_name(plugin_name)

    return {
        "tmux": create_hook_plugin_tmux_api(cwd, plugin_name),
        "log": create_hook_plugin_logger(cwd, plugin_name, event),
        "state": create_hook_plugin_state_api(cwd, plugin_name),
        "omx": create_hook_plugin_omx_api(cwd),
    }


def sanitize_hook_plugin_name(name: str) -> str:
    """清理插件名称"""
    return name.lower().replace(r"[^a-z0-9_-]", "-").replace(r"-+", "-").strip("-")


def create_hook_plugin_tmux_api(cwd: str, plugin_name: str) -> dict:
    """创建 TMux API"""
    async def send_keys(options: dict) -> dict:
        # TODO: 实现 TMux 集成
        return {"ok": True, "reason": "not_implemented"}
    return {"send_keys": send_keys}


def create_hook_plugin_logger(cwd: str, plugin_name: str, event: dict) -> dict:
    """创建日志 API"""
    def log_info(message: str, meta: dict | None = None) -> None:
        print(f"[{plugin_name}] INFO: {message}")

    def log_warn(message: str, meta: dict | None = None) -> None:
        print(f"[{plugin_name}] WARN: {message}")

    def log_error(message: str, meta: dict | None = None) -> None:
        print(f"[{plugin_name}] ERROR: {message}")

    return {
        "info": log_info,
        "warn": log_warn,
        "error": log_error,
    }


def create_hook_plugin_state_api(cwd: str, plugin_name: str) -> dict:
    """创建状态 API"""
    state_dir = Path(cwd) / ".omx" / "hooks" / "state" / plugin_name
    state_dir.mkdir(parents=True, exist_ok=True)

    async def state_read(key: str, fallback: Any = None) -> Any:
        file_path = state_dir / f"{key}.json"
        if file_path.exists():
            try:
                with open(file_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return fallback

    async def state_write(key: str, value: Any) -> None:
        file_path = state_dir / f"{key}.json"
        with open(file_path, "w") as f:
            json.dump(value, f)

    async def state_delete(key: str) -> None:
        file_path = state_dir / f"{key}.json"
        if file_path.exists():
            file_path.unlink()

    async def state_all() -> dict:
        result = {}
        for f in state_dir.glob("*.json"):
            try:
                with open(f) as f:
                    result[f.stem] = json.load(f)
            except Exception:
                pass
        return result

    return {
        "read": state_read,
        "write": state_write,
        "delete": state_delete,
        "all": state_all,
    }


def create_hook_plugin_omx_api(cwd: str) -> dict:
    """创建 OMX 状态 API"""
    async def read_session() -> dict | None:
        session_file = Path(cwd) / ".omx" / "state" / "session.json"
        if session_file.exists():
            try:
                with open(session_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    async def read_hud() -> dict | None:
        hud_file = Path(cwd) / ".omx" / "state" / "hud.json"
        if hud_file.exists():
            try:
                with open(hud_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    async def read_notify_fallback() -> dict | None:
        notify_file = Path(cwd) / ".omx" / "state" / "notify_fallback.json"
        if notify_file.exists():
            try:
                with open(notify_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    async def read_update_check() -> dict | None:
        update_file = Path(cwd) / ".omx" / "state" / "update_check.json"
        if update_file.exists():
            try:
                with open(update_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    return {
        "session": {"read": read_session},
        "hud": {"read": read_hud},
        "notify_fallback": {"read": read_notify_fallback},
        "update_check": {"read": read_update_check},
    }


async def clear_hook_plugin_state(cwd: str, plugin_name: str) -> None:
    """清除插件状态"""
    state_dir = Path(cwd) / ".omx" / "hooks" / "state" / plugin_name
    if state_dir.exists():
        for f in state_dir.glob("*.json"):
            f.unlink()


# ===== 导出 =====
__all__ = [
    "clear_hook_plugin_state",
    "create_hook_plugin_sdk",
]

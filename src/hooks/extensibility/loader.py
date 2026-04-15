"""
Hook Loader - 钩子插件发现和加载

从 oh-my-codex-main/src/hooks/extensibility/loader.ts 转换而来。
提供钩子插件的发现、验证和加载功能。
"""

import os
import re
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


# ===== 环境变量 =====
HOOK_PLUGIN_ENABLE_ENV = "OMX_HOOK_PLUGINS"
HOOK_PLUGIN_TIMEOUT_ENV = "OMX_HOOK_PLUGIN_TIMEOUT_MS"


def sanitize_plugin_id(file_name: str) -> str:
    """清理插件ID"""
    stem = Path(file_name).stem
    normalized = (
        stem.lower()
        .replace(r"[^a-z0-9_-]+", "-")
        .replace(r"-+", "-")
        .strip("-")
    )
    return normalized or "plugin"


def short_file_hash(file_name: str) -> str:
    """生成短文件哈希"""
    return hashlib.sha256(file_name.encode()).hexdigest()[:8]


def read_timeout(raw: Optional[str], fallback: int) -> int:
    """读取超时配置"""
    if not raw:
        return fallback
    try:
        parsed = int(raw)
        if parsed < 100:
            return 100
        if parsed > 60000:
            return 60000
        return parsed
    except (ValueError, TypeError):
        return fallback


def hooks_dir(cwd: str) -> str:
    """获取钩子目录路径"""
    return str(Path(cwd) / ".omx" / "hooks")


def is_hook_plugins_enabled(env: Optional[dict] = None) -> bool:
    """检查钩子插件是否启用"""
    env = env or os.environ
    raw = env.get(HOOK_PLUGIN_ENABLE_ENV, "").strip().lower()
    # 默认启用 - 只有显式禁用才关闭
    if raw in ("0", "false", "no"):
        return False
    return True


def resolve_hook_plugin_timeout_ms(env: Optional[dict] = None, fallback: int = 1500) -> int:
    """解析插件超时毫秒数"""
    env = env or os.environ
    return read_timeout(env.get(HOOK_PLUGIN_TIMEOUT_ENV), fallback)


async def ensure_hooks_dir(cwd: str) -> str:
    """确保钩子目录存在"""
    dir_path = hooks_dir(cwd)
    Path(dir_path).mkdir(parents=True, exist_ok=True)
    return dir_path


# ===== 插件验证 =====
ON_HOOK_EVENT_EXPORT_PATTERN = re.compile(
    r"(?:^|\n)\s*export\s+(?:async\s+)?function\s+onHookEvent\b"
    r"|(?:^|\n)\s*export\s+(?:const|let|var)\s+onHookEvent\b"
    r"|(?:^|\n)\s*export\s*\{[^}]*\bonHookEvent\b[^}]*\}",
    re.MULTILINE,
)


@dataclass
class HookPluginValidation:
    """插件验证结果"""
    valid: bool
    reason: Optional[str] = None


async def validate_plugin_export(plugin_path: str) -> HookPluginValidation:
    """验证插件导出"""
    try:
        with open(plugin_path, "r", encoding="utf-8") as f:
            source = f.read()
        if not ON_HOOK_EVENT_EXPORT_PATTERN.search(source):
            return HookPluginValidation(valid=False, reason="missing_onHookEvent_export")
        return HookPluginValidation(valid=True)
    except Exception as e:
        return HookPluginValidation(valid=False, reason=str(e))


async def validate_hook_plugin_export(plugin_path: str) -> HookPluginValidation:
    """验证钩子插件导出（别名）"""
    return await validate_plugin_export(plugin_path)


# ===== 插件发现 =====
@dataclass
class HookPluginDescriptor:
    """钩子插件描述符"""
    id: str
    name: str
    file: str
    path: str
    file_path: str
    file_name: str
    valid: bool = True
    reason: Optional[str] = None


async def discover_hook_plugins(cwd: str) -> list[HookPluginDescriptor]:
    """发现钩子插件"""
    dir_path = hooks_dir(cwd)
    hooks_dir_path = Path(dir_path)

    if not hooks_dir_path.exists():
        return []

    discovered: list[dict] = []
    try:
        for name in hooks_dir_path.iterdir():
            if not name.is_file() or not name.suffix == ".mjs":
                continue
            discovered.append({
                "id_base": sanitize_plugin_id(name.name),
                "file": name.name,
                "path": str(name),
            })
    except Exception:
        return []

    # 处理ID冲突
    id_counts: dict[str, int] = {}
    for plugin in discovered:
        id_counts[plugin["id_base"]] = id_counts.get(plugin["id_base"], 0) + 1

    plugins: list[HookPluginDescriptor] = []
    for plugin in discovered:
        has_collision = id_counts[plugin["id_base"]] > 1
        plugin_id = (
            f"{plugin['id_base']}-{short_file_hash(plugin['file'])}"
            if has_collision
            else plugin["id_base"]
        )
        plugins.append(HookPluginDescriptor(
            id=plugin_id,
            name=plugin_id,
            file=plugin["file"],
            path=plugin["path"],
            file_path=plugin["path"],
            file_name=plugin["file"],
            valid=True,
        ))

    # 按文件名排序
    plugins.sort(key=lambda p: p.file)
    return plugins


async def load_hook_plugin_descriptors(cwd: str) -> list[HookPluginDescriptor]:
    """加载并验证钩子插件描述符"""
    discovered = await discover_hook_plugins(cwd)
    validated: list[HookPluginDescriptor] = []

    for plugin in discovered:
        validation = await validate_plugin_export(plugin.path)
        validated.append(HookPluginDescriptor(
            id=plugin.id,
            name=plugin.name,
            file=plugin.file,
            path=plugin.path,
            file_path=plugin.file_path,
            file_name=plugin.file_name,
            valid=validation.valid,
            reason=validation.reason,
        ))

    return validated


# ===== 导出 =====
__all__ = [
    "HOOK_PLUGIN_ENABLE_ENV",
    "HOOK_PLUGIN_TIMEOUT_ENV",
    "hooks_dir",
    "is_hook_plugins_enabled",
    "resolve_hook_plugin_timeout_ms",
    "ensure_hooks_dir",
    "validate_plugin_export",
    "validate_hook_plugin_export",
    "HookPluginDescriptor",
    "discover_hook_plugins",
    "load_hook_plugin_descriptors",
]

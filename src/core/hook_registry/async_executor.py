"""异步钩子执行器 — 从 oh-my-codex 汲取的异步插件系统

核心能力:
    - 异步执行钩子插件
    - 插件发现机制 (.omx/hooks/*.mjs 或 .clawd/hooks/*.py)
    - 超时控制 (OMX_HOOK_PLUGIN_TIMEOUT_MS)
    - 并行执行与错误隔离
    - SDK 集成 (tmux, state, omx APIs)

参考: oh-my-codex-main/src/hooks/extensibility/dispatcher.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ============================================================================
# 类型定义 (对标 OMX HookEventEnvelope)
# ============================================================================

@dataclass
class HookEventEnvelope:
    """钩子事件信封 (参考 OMX HookEventEnvelope)

    包含事件的所有上下文信息，传递给插件执行。
    """
    event_name: str  # HookPoint 值或自定义事件名
    source: str = "native"  # 'native' | 'derived' | 'plugin'
    payload: dict[str, Any] | None = None
    session_id: str | None = None
    turn_id: str | None = None
    timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.payload is None:
            self.payload = {}
        if self.timestamp is None:
            from datetime import datetime
            self.timestamp = datetime.now().isoformat()


@dataclass
class HookPluginResult:
    """单个插件钩子执行结果"""
    plugin_name: str
    success: bool
    duration_ms: float
    output: str | None = None
    error: str | None = None
    modified_payload: dict[str, Any] | None = None


@dataclass
class HookDispatchResult:
    """钩子分发聚合结果"""
    results: list[HookPluginResult]
    timeout: float
    total_duration_ms: float
    any_denied: bool = False
    any_error: bool = False


def _should_use_plugins() -> bool:
    """检查是否启用插件系统 (环境变量开关)"""
    return os.environ.get("CLAWD_HOOK_PLUGINS", "0") == "1"


# ============================================================================
# Plugin Runner (对标 OMX runPluginRunner)
# ============================================================================

async def run_plugin_runner(
    plugin_path: Path,
    envelope: HookEventEnvelope,
    timeout_ms: int = 5000,
    side_effects_enabled: bool = True,
) -> HookPluginResult:
    """执行单个钩子插件

    Args:
        plugin_path: 插件文件路径 (.py 或 .mjs)
        envelope: 事件信封
        timeout_ms: 超时时间 (毫秒)
        side_effects_enabled: 是否允许副作用 (Team Worker 场景可禁用)

    Returns:
        HookPluginResult 实例
    """
    start_time = time.time()

    try:
        # 根据文件扩展名选择执行方式
        suffix = plugin_path.suffix.lower()

        if suffix == ".py":
            result = await _run_python_plugin(plugin_path, envelope, timeout_ms, side_effects_enabled)
        elif suffix in (".js", ".mjs", ".ts"):
            result = await _run_node_plugin(plugin_path, envelope, timeout_ms, side_effects_enabled)
        else:
            logger.warning(f"Unsupported plugin type: {suffix} for {plugin_path}")
            return HookPluginResult(
                plugin_name=plugin_path.name,
                success=False,
                duration_ms=0,
                error=f"Unsupported plugin type: {suffix}"
            )

        duration = (time.time() - start_time) * 1000
        result.duration_ms = duration
        return result

    except asyncio.TimeoutError:
        duration = (time.time() - start_time) * 1000
        logger.warning(f"Plugin {plugin_path.name} timed out after {timeout_ms}ms")
        return HookPluginResult(
            plugin_name=plugin_path.name,
            success=False,
            duration_ms=duration,
            error=f"Timeout after {timeout_ms}ms"
        )
    except Exception as e:
        duration = (time.time() - start_time) * 1000
        logger.exception(f"Plugin {plugin_path.name} failed: {e}")
        return HookPluginResult(
            plugin_name=plugin_path.name,
            success=False,
            duration_ms=duration,
            error=str(e)
        )


async def _run_python_plugin(
    plugin_path: Path,
    envelope: HookEventEnvelope,
    timeout_ms: int,
    side_effects_enabled: bool,
) -> HookPluginResult:
    """运行 Python 插件

    插件 API:
        async def main(envelope: dict, sdk: HookSdk) -> dict|None:
            return {"modified_payload": {...}} or None
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    # 动态加载插件模块
    spec = importlib.util.spec_from_file_location(plugin_path.stem, plugin_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load plugin: {plugin_path}")

    module = importlib.util.module_from_spec(spec)

    # 在线程池中执行以避免阻塞事件循环
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as executor:
        def load_and_run():
            spec.loader.exec_module(module)
            # 构造 SDK
            from .sdk import HookSdk
            sdk = HookSdk(
                cwd=os.getcwd(),
                event=envelope.event_name,
                side_effects_enabled=side_effects_enabled
            )
            # 调用插件 main 函数
            if hasattr(module, 'main'):
                return module.main(envelope.__dict__, sdk)
            else:
                raise RuntimeError(f"Plugin {plugin_path.name} missing main() function")

        result = await asyncio.wait_for(
            loop.run_in_executor(executor, load_and_run),
            timeout=timeout_ms / 1000
        )

    # 解析结果
    if result and isinstance(result, dict):
        return HookPluginResult(
            plugin_name=plugin_path.name,
            success=True,
            duration_ms=0,
            output=None,
            modified_payload=result.get("modified_payload")
        )
    return HookPluginResult(
        plugin_name=plugin_path.name,
        success=True,
        duration_ms=0,
        output=None
    )


async def _run_node_plugin(
    plugin_path: Path,
    envelope: HookEventEnvelope,
    timeout_ms: int,
    side_effects_enabled: bool,
) -> HookPluginResult:
    """运行 Node.js 插件 (通过子进程)"""
    import json

    # 通过 node 执行
    cmd = ["node", str(plugin_path)]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=json.dumps(envelope.__dict__).encode()),
            timeout=timeout_ms / 1000
        )

        if process.returncode != 0:
            raise RuntimeError(f"Plugin exited {process.returncode}: {stderr.decode()}")

        output = stdout.decode().strip()
        if output:
            try:
                result_data = json.loads(output)
                return HookPluginResult(
                    plugin_name=plugin_path.name,
                    success=True,
                    duration_ms=0,
                    output=output,
                    modified_payload=result_data.get("modified_payload")
                )
            except json.JSONDecodeError:
                return HookPluginResult(
                    plugin_name=plugin_path.name,
                    success=True,
                    duration_ms=0,
                    output=output
                )

        return HookPluginResult(
            plugin_name=plugin_path.name,
            success=True,
            duration_ms=0
        )

    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


# ============================================================================
# Plugin Discovery (对标 OMX discoverHookPlugins)
# ============================================================================

async def discover_hook_plugins(cwd: str | Path) -> list[Path]:
    """发现可用的钩子插件

    搜索目录:
        .clawd/hooks/*.py  (优先)
        .omx/hooks/*.mjs 或 .js

    Args:
        cwd: 工作目录

    Returns:
        插件文件路径列表 (按文件名排序)
    """
    cwd_path = Path(cwd)
    plugins: list[Path] = []

    # 搜索 .clawd/hooks/*.py
    clawd_hooks = cwd_path / ".clawd" / "hooks"
    if clawd_hooks.exists():
        plugins.extend(sorted(clawd_hooks.glob("*.py")))

    # 搜索 .omx/hooks/*.{mjs,js}
    omx_hooks = cwd_path / ".omx" / "hooks"
    if omx_hooks.exists():
        for pattern in ("*.mjs", "*.js"):
            plugins.extend(sorted(omx_hooks.glob(pattern)))

    logger.debug(f"Discovered {len(plugins)} hook plugins in {cwd}")
    return plugins


# ============================================================================
# Async Hook Dispatcher (对标 OMX dispatchHookEvent)
# ============================================================================

class AsyncHookDispatcher:
    """异步钩子分发器 - 支持插件和注册钩子

    对应 oh-my-codex 的 HookSystem.dispatch()
    """

    def __init__(
        self,
        timeout_ms: int = 5000,
        max_parallel: int = 10,
    ) -> None:
        self.timeout_ms = timeout_ms
        self.max_parallel = max_parallel
        self._plugins_cache: list[Path] | None = None

    async def dispatch(
        self,
        envelope: HookEventEnvelope,
        cwd: str | Path,
        side_effects_enabled: bool = True,
        force_enable: bool = False,  # 强制启用 (用于测试)
    ) -> HookDispatchResult:
        """分发钩子事件

        Args:
            envelope: 事件信封
            cwd: 工作目录
            side_effects_enabled: 是否允许副作用 (Team Worker 可设为 False)
            force_enable: 强制启用 (忽略环境变量开关)

        Returns:
            HookDispatchResult 聚合结果
        """
        # 检查是否启用插件系统
        if not (force_enable or _should_use_plugins()):
            logger.debug("Hook plugins disabled by env var")
            return HookDispatchResult(
                results=[],
                timeout=self.timeout_ms,
                total_duration_ms=0,
            )

        # 发现插件
        if self._plugins_cache is None:
            self._plugins_cache = await discover_hook_plugins(cwd)

        if not self._plugins_cache:
            return HookDispatchResult(
                results=[],
                timeout=self.timeout_ms,
                total_duration_ms=0,
            )

        # 并行执行所有插件 (带并发限制)
        semaphore = asyncio.Semaphore(self.max_parallel)
        tasks = []

        async def run_with_limit(plugin_path: Path) -> HookPluginResult:
            async with semaphore:
                return await run_plugin_runner(
                    plugin_path,
                    envelope,
                    timeout_ms=self.timeout_ms,
                    side_effects_enabled=side_effects_enabled,
                )

        start_time = time.time()
        for plugin_path in self._plugins_cache:
            task = asyncio.create_task(run_with_limit(plugin_path))
            tasks.append(task)

        # 等待所有任务完成 (或超时)
        try:
            all_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.timeout_ms / 1000
            )
        except asyncio.TimeoutError:
            # 取消所有任务
            for task in tasks:
                if not task.done():
                    task.cancel()
            all_results = []

        total_duration = (time.time() - start_time) * 1000

        # 处理结果
        results: list[HookPluginResult] = []
        any_denied = False
        any_error = False

        for r in all_results:
            if isinstance(r, Exception):
                any_error = True
                results.append(HookPluginResult(
                    plugin_name="unknown",
                    success=False,
                    duration_ms=0,
                    error=str(r)
                ))
            else:
                results.append(r)
                # 检查 modified_payload 中的 deny 标志 (约定)
                if r.modified_payload and r.modified_payload.get("deny"):
                    any_denied = True

        return HookDispatchResult(
            results=results,
            timeout=self.timeout_ms,
            total_duration_ms=total_duration,
            any_denied=any_denied,
            any_error=any_error,
        )


# ============================================================================
# Convenience functions
# ============================================================================

async def dispatch_hook_event(
    event_name: str,
    cwd: str | Path,
    payload: dict[str, Any] | None = None,
    source: str = "native",
    session_id: str | None = None,
    side_effects_enabled: bool = True,
) -> HookDispatchResult:
    """便捷函数: 分发的钩子事件

    Args:
        event_name: 事件名称 (HookPoint 值)
        cwd: 工作目录
        payload: 事件载荷
        source: 事件源
        session_id: 会话 ID
        side_effects_enabled: 是否允许副作用

    Returns:
        HookDispatchResult 聚合结果
    """
    envelope = HookEventEnvelope(
        event_name=event_name,
        source=source,
        payload=payload or {},
        session_id=session_id,
    )

    dispatcher = AsyncHookDispatcher()
    return await dispatcher.dispatch(envelope, cwd, side_effects_enabled)


# ============================================================================
# Hook SDK (对标 OMX createHookPluginSdk)
# ============================================================================

class HookSdk:
    """钩子插件 SDK - 提供给插件的 API

    参考: oh-my-codex-main/src/hooks/extensibility/sdk.py
    """

    def __init__(
        self,
        cwd: str,
        event: str,
        side_effects_enabled: bool = True,
    ) -> None:
        self.cwd = Path(cwd)
        self.event = event
        self.side_effects_enabled = side_effects_enabled
        self._state_dir = self.cwd / ".clawd" / "hook_state"
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def state(self, namespace: str) -> HookStateNamespace:
        """获取命名空间状态存储"""
        return HookStateNamespace(self._state_dir / namespace)

    def tmux(self) -> TmuxApi:
        """获取 tmux API (仅 Team Worker 可用)"""
        return TmuxApi()

    def omx(self) -> OmxApi:
        """获取 OMX 状态 API"""
        return OmxApi(self.cwd)

    def log(self, message: str, level: str = "info") -> None:
        """记录日志 (插件调用)"""
        getattr(logger, level)(f"[Hook] {message}")


class HookStateNamespace:
    """命名空间状态存储 (对标 OMX state API)"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)

    def get(self, key: str, default: Any = None) -> Any:
        """获取键值"""
        file_path = self.path / f"{key}.json"
        if not file_path.exists():
            return default
        import json
        return json.loads(file_path.read_text())

    def set(self, key: str, value: Any) -> None:
        """设置键值"""
        file_path = self.path / f"{key}.json"
        import json
        file_path.write_text(json.dumps(value, indent=2), encoding="utf-8")

    def delete(self, key: str) -> bool:
        """删除键"""
        file_path = self.path / f"{key}.json"
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def list_keys(self) -> list[str]:
        """列出所有键"""
        return [p.stem for p in self.path.glob("*.json")]


class TmuxApi:
    """tmux 集成 API (对标 OMX tmux API)

    仅在 Team Worker 模式下可用。
    提供 send_keys、capture_pane 等操作。
    """

    def send_keys(self, target: str, keys: str) -> None:
        """发送键到 tmux pane"""
        import subprocess
        subprocess.run(
            ["tmux", "send-keys", "-t", target, keys],
            check=False,
            capture_output=True
        )

    def capture_pane(self, target: str) -> str:
        """捕获 tmux pane 内容"""
        import subprocess
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p"],
            capture_output=True,
            text=True,
            check=False
        )
        return result.stdout


class OmxApi:
    """OMX 状态 API (对标 OMX omx API)"""

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self._state_dir = cwd / ".clawd" / "state"

    def read_state(self, mode: str) -> dict[str, Any] | None:
        """读取模式状态"""
        state_file = self._state_dir / f"mode-{mode}.json"
        if not state_file.exists():
            return None
        import json
        return json.loads(state_file.read_text())

    def is_active(self, mode: str) -> bool:
        """检查模式是否活跃"""
        import json
        state_file = self._state_dir / f"mode-{mode}.json"
        if not state_file.exists():
            return False
        try:
            data = json.loads(state_file.read_text())
            return data.get("metadata", {}).get("active", False) is True
        except Exception:
            return False

    def get_mode_metadata(self, mode: str) -> dict[str, Any]:
        """获取模式元数据"""
        import json
        state_file = self._state_dir / f"mode-{mode}.json"
        if not state_file.exists():
            return {}
        try:
            data = json.loads(state_file.read_text())
            return data.get("metadata", {})
        except Exception:
            return {}


__all__ = [
    "AsyncHookDispatcher",
    "HookDispatchResult",
    "HookEventEnvelope",
    "HookPluginResult",
    "HookSdk",
    "HookStateNamespace",
    "OmxApi",
    "TmuxApi",
    "discover_hook_plugins",
    "dispatch_hook_event",
    "run_plugin_runner",
]

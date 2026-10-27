"""clawd 插件体系 — DSH 式"万物皆插件"的 Python 实现

插件四件套（对齐 DSH 契约，Python 化）:
1. manifest: pyproject.toml 内嵌 [tool.clawd.plugin]（entry / client / compatibility）
2. DI Context: 极简依赖注入容器（tools/events/settings/prompt/ui 注册面 + expose 公共服务）
3. 接入面: 工具注册、system prompt 注入（UI slot 随 Web UI 迭代开放）
4. CLI: clawd plugin list/add/remove（pip 安装进独立目录）

插件包结构示例:
    my-clawd-plugin/
      pyproject.toml     # [tool.clawd.plugin] entry = "my_plugin:setup"
      my_plugin/__init__.py  # def setup(ctx: PluginContext): ...
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

PLUGINS_DIR_NAME = ".clawd/plugins"


class PluginError(Exception):
    pass


# ============ manifest 解析 ============

@dataclass
class PluginManifest:
    """插件清单（来自 pyproject.toml 的 [tool.clawd.plugin]）"""
    name: str
    entry: str  # "module:function" 形式的 setup 入口
    version: str = "0.0.0"
    description: str = ""
    compatibility: str = ""  # clawd 版本区间（SemVer），空=不限
    # 接入面声明（供文档/市场展示；实际注册在 setup() 内进行）
    provides_tools: bool = False
    provides_prompt: bool = False
    provides_ui: bool = False

    @classmethod
    def from_pyproject(cls, data: dict[str, Any], source: str = "") -> "PluginManifest":
        plugin_cfg = (data.get("tool") or {}).get("clawd", {}).get("plugin")
        if not plugin_cfg:
            raise PluginError(f"缺少 [tool.clawd.plugin] 段: {source}")
        name = plugin_cfg.get("name")
        entry = plugin_cfg.get("entry")
        if not name or not entry:
            raise PluginError(f"manifest 缺少 name/entry: {source}")
        return cls(
            name=name,
            entry=entry,
            version=str(plugin_cfg.get("version", "0.0.0")),
            description=plugin_cfg.get("description", ""),
            compatibility=plugin_cfg.get("compatibility", ""),
            provides_tools=bool(plugin_cfg.get("provides_tools", False)),
            provides_prompt=bool(plugin_cfg.get("provides_prompt", False)),
            provides_ui=bool(plugin_cfg.get("provides_ui", False)),
        )


def load_manifest_from_dir(plugin_dir: Path) -> PluginManifest:
    """从插件目录的 pyproject.toml 加载 manifest"""
    try:
        import tomllib
    except ImportError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]

    pp = plugin_dir / "pyproject.toml"
    if not pp.is_file():
        raise PluginError(f"插件目录缺少 pyproject.toml: {plugin_dir}")
    try:
        data = tomllib.loads(pp.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — TOML 解析错误转结构化错误
        raise PluginError(f"pyproject.toml 解析失败 {pp}: {e}") from e
    return PluginManifest.from_pyproject(data, source=str(pp))


# ============ DI Context ============

@dataclass
class PluginContext:
    """插件运行时上下文（极简 DI 容器）

    宿主提供的注册面:
      ctx.register_tool(tool)          → 挂进 AgentEngine.tools
      ctx.inject_prompt(section)       → 追加到 system prompt
      ctx.expose(name, service)        → 跨插件公共服务（其他插件 ctx.require）
      ctx.require(name)                → 依赖其他插件的公共服务
      ctx.settings                     → 插件可读写的工作目录配置
      ctx.on_shutdown(fn)              → 生命周期钩子
    """
    plugin_name: str
    settings: dict[str, Any] = field(default_factory=dict)
    # 由宿主注入的回调（PluginManager 持有真实容器）
    _register_tool: Callable[[Any], None] = lambda t: None
    _inject_prompt: Callable[[str], None] = lambda s: None
    _expose: Callable[[str, Any], None] = lambda n, s: None
    _require: Callable[[str], Any] = lambda n: None
    _on_shutdown: Callable[[Callable[[], None]], None] = lambda f: None
    # 注册审计（谁注册了什么，供宿主展示与排障）
    audit: dict[str, list[str]] = field(default_factory=lambda: {
        "tools": [], "prompt_sections": [], "exposed": [],
    })

    def register_tool(self, tool: Any) -> None:
        self.audit["tools"].append(getattr(tool, "name", repr(tool)))
        self._register_tool(tool)

    def inject_prompt(self, section: str) -> None:
        self.audit["prompt_sections"].append(section[:50])
        self._inject_prompt(section)

    def expose(self, name: str, service: Any) -> None:
        self.audit["exposed"].append(name)
        self._expose(f"{self.plugin_name}:{name}", service)

    def require(self, name: str) -> Any:
        return self._require(name)

    def on_shutdown(self, fn: Callable[[], None]) -> None:
        self._on_shutdown(fn)


# ============ PluginManager ============

class PluginManager:
    """插件加载器与生命周期管理

    插件来源: <workdir>/.clawd/plugins/ 下的目录（每个含 pyproject.toml）
    加载语义（对齐 DSH generation dispose）:
      load_all() 幂等；reload = dispose 全部 → 重新加载
    """

    def __init__(self, workdir: Path | None = None):
        self.workdir = (workdir or Path.cwd()).resolve()
        self.plugins_dir = self.workdir / PLUGINS_DIR_NAME
        self._loaded: dict[str, PluginManifest] = {}
        self._tools: list[Any] = []
        self._prompt_sections: list[str] = []
        self._services: dict[str, Any] = {}
        self._shutdown_hooks: list[Callable[[], None]] = []

    # ---- 宿主侧取用 ----
    @property
    def loaded_names(self) -> list[str]:
        return list(self._loaded.keys())

    def get_tools(self) -> list[Any]:
        return list(self._tools)

    def get_prompt_sections(self) -> list[str]:
        return list(self._prompt_sections)

    def shutdown(self) -> None:
        """dispose 全部插件（逆序执行 shutdown 钩子）"""
        for fn in reversed(self._shutdown_hooks):
            try:
                fn()
            except Exception as e:  # noqa: BLE001 — 钩子失败不阻断其他插件
                logger.warning(f"插件 shutdown 钩子失败: {e}")
        self._shutdown_hooks.clear()
        self._loaded.clear()
        self._tools.clear()
        self._prompt_sections.clear()
        self._services.clear()

    # ---- 加载 ----
    def discover(self) -> list[Path]:
        """发现插件目录（.clawd/plugins/*/pyproject.toml）"""
        if not self.plugins_dir.is_dir():
            return []
        return sorted(
            p.parent for p in self.plugins_dir.glob("*/pyproject.toml")
        )

    def load_all(self) -> dict[str, str]:
        """加载全部插件。返回 {插件名: 状态}，单个失败不影响其他。

        状态: loaded | error:<原因>
        """
        self.shutdown()  # 幂等：先 dispose 再加载
        results: dict[str, str] = {}
        for plugin_dir in self.discover():
            try:
                manifest = load_manifest_from_dir(plugin_dir)
            except Exception as e:  # noqa: BLE001 — manifest 都读不出，用目录名报错
                logger.warning(f"插件 manifest 失败 {plugin_dir.name}: {e}")
                results[plugin_dir.name] = f"error:{e}"
                continue
            try:
                self._load_one(plugin_dir, manifest)
                results[manifest.name] = "loaded"
            except Exception as e:  # noqa: BLE001 — 单插件失败降级
                logger.warning(f"插件加载失败 {plugin_dir.name}: {e}")
                results[manifest.name] = f"error:{e}"
        return results

    def _load_one(self, plugin_dir: Path, manifest: PluginManifest) -> None:
        if manifest.name in self._loaded:
            raise PluginError(f"插件重名: {manifest.name}")

        module_name, _, func_name = manifest.entry.partition(":")
        if not module_name or not func_name:
            raise PluginError(f"entry 格式须为 'module:function': {manifest.entry}")

        # 用 spec_from_file_location 隔离加载，不污染 sys.path
        # （插件目录里的 json.py/logging.py 不得劫持宿主 import）
        init_py = plugin_dir / module_name.replace(".", "/") / "__init__.py"
        if not init_py.exists():
            init_py = plugin_dir / f"{module_name}.py"
        if not init_py.exists():
            raise PluginError(f"入口模块文件不存在: {module_name}（找 {init_py}）")
        unique_name = f"clawd_plugin_{manifest.name}_{module_name}"
        spec = importlib.util.spec_from_file_location(unique_name, init_py)
        if spec is None or spec.loader is None:
            raise PluginError(f"无法构建 import spec: {init_py}")
        module = importlib.util.module_from_spec(spec)
        # 插件目录注册为该命名空间的子模块搜索路径（支持插件内部自引用，
        # 如 from my_plugin.service import X），但不污染全局 sys.path
        submodule_search = plugin_dir / module_name.replace(".", "/")
        if submodule_search.is_dir():
            module.__path__ = [str(submodule_search)]
        sys.modules[unique_name] = module
        # 插件内部 "from <module_name>.x import y" 走全局解析：临时注册别名
        alias_key = f"__clawd_plugin_alias_{module_name}"
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            setup_fn = getattr(module, func_name, None)
            if setup_fn is None or not callable(setup_fn):
                raise PluginError(f"入口函数不可调用: {manifest.entry}")
        except PluginError:
            raise
        except Exception as e:  # noqa: BLE001 — 导入失败转结构化错误
            sys.modules.pop(unique_name, None)
            raise PluginError(f"插件模块加载失败 {module_name}: {e}") from e

        ctx = PluginContext(
            plugin_name=manifest.name,
            settings=self._load_plugin_settings(manifest.name),
            _register_tool=self._tools.append,
            _inject_prompt=self._prompt_sections.append,
            _expose=self._services.__setitem__,
            _require=lambda n: self._require_service(n),
            _on_shutdown=self._shutdown_hooks.append,
        )
        setup_fn(ctx)
        self._loaded[manifest.name] = manifest
        logger.info(
            f"插件已加载: {manifest.name} v{manifest.version} "
            f"(tools={len(ctx.audit['tools'])}, prompts={len(ctx.audit['prompt_sections'])})"
        )

    def _require_service(self, qualified: str) -> Any:
        svc = self._services.get(qualified)
        if svc is None:
            raise PluginError(f"公共服务不存在: {qualified}（依赖插件未加载或未 expose）")
        return svc

    def _load_plugin_settings(self, name: str) -> dict[str, Any]:
        cfg = self.workdir / ".clawd" / "plugin_settings" / f"{name}.json"
        if not cfg.is_file():
            return {}
        try:
            return json.loads(cfg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"插件配置读取失败 {name}: {e}")
            return {}

"""Clawd WebSocket 服务器模块

基于 websockets v15 实现的异步 WebSocket 服务器。
此模块现在主要作为启动入口，核心逻辑已拆分至 ws/ 子模块。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.events import Event, EventBus, EventType, get_event_bus
from ..core.settings import AgentSettings, get_settings
from ..llm import LLMConfig
from ..utils.logger import get_logger
from .auth import AuthManager
from .handlers import MessageRouter
from .ws.engine_factory import EngineFactory
from .ws.manager import WSManager
from .ws.shutdown import ServerShutdown

if TYPE_CHECKING:
    from websockets.asyncio.server import Server as WsServer


_HTTP_REASONS = {200: 'OK', 404: 'Not Found', 503: 'Service Unavailable'}


def _json_response(status: int, payload: dict) -> Any:
    """构造 JSON HTTP 响应（探针端点用；`Connection: close` 避免探针连接挂住）"""
    from websockets.datastructures import Headers as _H
    from websockets.http11 import Response as _WsResponse

    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    return _WsResponse(
        status,
        _HTTP_REASONS.get(status, 'OK'),
        _H([
            ('Content-Type', 'application/json; charset=utf-8'),
            ('Content-Length', str(len(body))),
            ('Cache-Control', 'no-cache'),
            ('Connection', 'close'),
        ]),
        body,
    )


class ClawdWebSocketServer:
    """Clawd WebSocket 服务器。"""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        token: str | None = None,
        heartbeat_interval: float = 30.0,
        settings: AgentSettings | None = None,
        event_bus: EventBus | None = None,
        llm_config: LLMConfig | None = None,
        max_iterations: int = 10,
        developer_mode: bool = False,
        enable_cost_tracking: bool = True,
        static_dir: str | None = None,
        static_token: str | None = None,
    ) -> None:
        self.logger = get_logger('server.websocket')
        self._shutting_down = False
        self._start_time = time.time()

        # 加载配置
        self._settings = settings or get_settings()
        self._event_bus = event_bus or get_event_bus()

        # 主机:端口
        # 注意：0 是合法端口（让操作系统分配随机端口），不能用 `or` 合并，
        # 否则 `--port 0` 会被当成"未提供"而回退到配置端口。
        if host is not None:
            self.host = host
        else:
            self.host = os.environ.get('AGENT_SERVER_HOST') or self._settings.agent_server_host
        if port is not None:
            self.port = int(port)
        else:
            self.port = int(os.environ.get('AGENT_SERVER_PORT', '0')) or self._settings.agent_server_port

        # 认证、路由、引擎工厂
        self._auth_manager = AuthManager(token=token)
        self._router = MessageRouter(
            auth_manager=self._auth_manager,
            event_bus=self._event_bus,
        )

        self._engine_factory = EngineFactory(
            default_llm_config=llm_config,
            workdir=self._settings.workdir,
            max_iterations=max_iterations,
            developer_mode=developer_mode,
            enable_events=True,
            event_bus=self._event_bus,
            enable_cost_tracking=enable_cost_tracking,
        )

        # 初始化连接管理器
        self._manager = WSManager(
            auth_manager=self._auth_manager,
            router=self._router,
            engine_factory=self._engine_factory,
            heartbeat_interval=heartbeat_interval,
            event_bus=self._event_bus,
        )

        self._ws_server: WsServer | None = None
        # 桌面端/Web 端静态托管（DSH 模式：Host 同端口托管 Web UI，壳只 loadURL）
        self._static_dir = static_dir
        # index.html 服务时注入的 token（app.js 从 URL ?token= 读取）
        self._static_token_inject = static_token
        self._static_cache: dict[str, tuple[bytes, str]] = {}

    @property
    def is_running(self) -> bool:
        return self._ws_server is not None and not self._shutting_down

    @property
    def uptime(self) -> float:
        return time.time() - self._start_time

    def liveness_payload(self) -> dict:
        """存活探针（`/healthz`）：只回答"进程还在跑"，**不含任何路径/密钥**

        故意保持零 IO：存活探针要能在磁盘打满、数据目录坏掉时仍然返回 200，
        否则编排系统会把"服务还活着"误判成"挂掉"并反复重启。
        """
        from .. import __version__

        try:
            connections = len(getattr(self._manager, '_sessions', {}) or {})
        except Exception:  # noqa: BLE001 — 探针不能因为内部结构变化而 500
            connections = -1
        return {
            'status': 'ok',
            'version': __version__,
            'uptime_s': round(self.uptime, 3),
            'connections': connections,
            'shutting_down': bool(self._shutting_down),
        }

    def readiness_payload(self) -> tuple[dict, bool]:
        """就绪探针（`/readyz`）：真做两件可能导致"跑不了活"的检查

        1. 数据目录可写（不可写 → 会话/用量/配置全落不下来）
        2. LLM 已配置（provider + model 非空；**不校验 key 是否有效**，那要真花钱）
        返回 `(payload, ok)`，ok=False 时调用方应回 503 —— 让编排系统不把流量导进来。
        """
        checks: list[dict] = []

        try:
            from ..core.data_dir import data_dir

            probe_dir = data_dir(create=True)
            probe = probe_dir / '.readyz-probe'
            probe.write_text('ok', encoding='utf-8')
            probe.unlink()
            checks.append({'name': 'data_dir_writable', 'ok': True, 'detail': 'ok'})
        except Exception as exc:  # noqa: BLE001 — 探针必须把原因写进 payload 而不是崩掉
            # 只报异常类型，不回显绝对路径（探针端点免鉴权）
            checks.append(
                {'name': 'data_dir_writable', 'ok': False, 'detail': type(exc).__name__}
            )

        raw_provider = getattr(self._settings, 'llm_provider', '')
        # 设置里的 provider 是枚举，str() 会得到 "LLMProviderEnum.OPENAI"（对人无用）
        provider = str(getattr(raw_provider, 'value', raw_provider) or '')
        model = str(getattr(self._settings, 'llm_model', '') or '')
        llm_ok = bool(provider and model)
        checks.append({
            'name': 'llm_configured',
            'ok': llm_ok,
            # **不回显 provider/model 的值**：/readyz 免鉴权，容器/内网里谁都能打，
            # 报出具体模型等于免费给出"这家在用什么"的情报；编排系统只需要"配没配"。
            'detail': 'provider/model 已配置' if llm_ok else '未配置 provider 或 model',
        })

        ready = all(c['ok'] for c in checks)
        return (
            {
                'status': 'ready' if ready else 'not_ready',
                'version': self.liveness_payload()['version'],
                'checks': checks,
            },
            ready,
        )

    async def start(self) -> tuple[str, int]:
        """启动服务器"""
        from websockets.asyncio.server import serve

        self._start_time = time.time()
        self._shutting_down = False

        # 探针端点（/healthz、/readyz）与 API 404 语义必须在**没有静态目录**时也可用：
        # 容器/纯服务模式下根本不托管 Web UI，但编排系统仍要能探活。
        process_request = self._serve_static
        self._ws_server = await serve(
            self._manager.handle_connection,
            self.host,
            self.port,
            ping_interval=self._manager.heartbeat_interval if self._manager.heartbeat_interval > 0 else None,
            process_request=process_request,
        )

        # 获取实际端口
        sockets = self._ws_server.sockets
        if sockets:
            addr, port = sockets[0].getsockname()[:2]
            self.host, self.port = str(addr), int(port)

        # 记录服务 loop（事件广播 threadsafe 目标；engine 线程 publish 时回此 loop）
        self._manager.set_service_loop(asyncio.get_running_loop())

        uri = f'ws://{self.host}:{self.port}'
        self.logger.info(f'WebSocket 服务器已启动: {uri}')

        self._event_bus.publish(Event(
            type=EventType.SERVER_STARTED,
            data={'host': self.host, 'port': self.port, 'uri': uri},
            source='websocket_server',
        ))

        return (self.host, self.port)

    def _collect_info(self) -> dict[str, Any]:
        """宿主信息（UI 版本栏 / 设置面板数据源）

        安全: 只回传 provider/model/base_url 与布尔开关，**绝不回传任何 API Key**。
        """
        info: dict[str, Any] = {
            "version": "unknown",
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "workdir": str(self._workdir()),
            "host": self.host,
            "port": self.port,
            "uptime_seconds": round(self.uptime, 1),
        }
        try:
            from .. import __version__

            info["version"] = __version__
        except Exception:
            pass

        try:
            info["provider"] = getattr(self._settings, "llm_provider", None)
            info["model"] = getattr(self._settings, "llm_model", None)
            info["base_url"] = getattr(self._settings, "llm_base_url", None)
            info["api_key_set"] = bool(getattr(self._settings, "llm_api_key", None))
            try:
                from ..core.data_dir import describe as _describe_data_dir

                info["data_dir"] = _describe_data_dir()["data_dir"]
                from ..core import providers_store as _ps

                info["providers_file"] = _ps.store_path()
            except Exception:  # noqa: BLE001
                pass
            # 多 provider：让设置页能显示"当前真正生效的那套"
            try:
                from ..core import providers_store

                info["active_provider"] = providers_store.describe_active(self._workdir())
            except Exception:  # noqa: BLE001 — provider 库坏了不能影响 /api/info
                info["active_provider"] = {"configured": False}
        except Exception:
            info["provider"] = None
            info["model"] = None
            info["api_key_set"] = False

        info["features"] = {
            "rag": os.environ.get("CLAWD_ENABLE_RAG", "").lower() in ("1", "true", "yes"),
            "native_tools": os.environ.get("CLAWD_NATIVE_TOOLS", "1").lower()
            not in ("0", "false", "no"),
            "static_ui": bool(self._static_dir),
        }
        return info

    def _workdir(self) -> Path:
        """宿主工作目录（插件发现基准）"""
        wd = getattr(self._settings, "workdir", None)
        return Path(wd).resolve() if wd else Path.cwd().resolve()

    def _collect_plugins(self) -> dict[str, Any]:
        """插件市场数据源：已加载插件 + 内置工具包（逆向/安全等能力模块）"""
        plugins: list[dict[str, Any]] = []

        # 1. PluginManager 加载的插件（若 Host 持有）
        pm = getattr(self, "_plugin_manager", None)
        if pm is not None:
            for name, manifest in pm._loaded.items():
                plugins.append({
                    "name": name,
                    "version": manifest.version,
                    "description": manifest.description or "（无描述）",
                    "status": "loaded",
                    "capabilities": [
                        cap for cap, flag in (
                            ("工具", manifest.provides_tools),
                            ("Prompt", manifest.provides_prompt),
                            ("UI", manifest.provides_ui),
                        ) if flag
                    ] or ["插件"],
                })

        # 1. 用户插件（<workdir>/.clawd/plugins/*/pyproject.toml）
        #    只发现 manifest，不执行插件代码（GET 端点不得触发任意代码执行）；
        #    实际加载走 WS `plugins_load`（需已认证）。
        try:
            from ..plugins import PluginManager, load_manifest_from_dir

            pm = PluginManager(workdir=self._workdir())
            for plugin_dir in pm.discover():
                try:
                    manifest = load_manifest_from_dir(plugin_dir)
                    plugins.append({
                        "name": manifest.name,
                        "version": manifest.version,
                        "description": manifest.description or "（无描述）",
                        "status": "available",
                        "source": str(plugin_dir),
                        "capabilities": [
                            cap for cap, flag in (
                                ("工具", manifest.provides_tools),
                                ("Prompt", manifest.provides_prompt),
                                ("UI", manifest.provides_ui),
                            ) if flag
                        ] or ["插件"],
                    })
                except Exception as exc:
                    plugins.append({
                        "name": plugin_dir.name,
                        "version": "?",
                        "description": f"manifest 读取失败: {exc}",
                        "status": "error",
                        "source": str(plugin_dir),
                        "capabilities": ["插件"],
                    })
        except Exception as exc:
            self.logger.debug(f"插件发现失败: {exc}")

        # 2. 内置能力包（逆向工具/安全目录/MCP 桥接 — 让市场不为空）
        try:
            from ..reverse_tools import get_all_tools

            n = len(get_all_tools())
            plugins.append({
                "name": "逆向工具集",
                "version": "1.0.0",
                "description": f"内置 {n} 个逆向分析工具：Ghidra 桥、strings、熵分析、hexdump、objdump、binwalk 等",
                "status": "builtin",
                "capabilities": ["逆向", "静态分析", "CLI 包装"],
            })
        except Exception:
            pass
        plugins.append({
            "name": "安全工具目录",
            "version": "1.0.0",
            "description": "YAML 数据驱动的安全工具目录：scope 授权门禁、命令注入拦截、危险工具双重确认",
            "status": "builtin",
            "capabilities": ["侦察", "安全审计"],
        })
        plugins.append({
            "name": "MCP 桥接",
            "version": "1.0.0",
            "description": "外部 MCP server 接入（stdio/HTTP），工具签名+检疫审批防投毒",
            "status": "builtin",
            "capabilities": ["MCP", "工具扩展"],
        })
        plugins.append({
            "name": "推理模式",
            "version": "1.0.0",
            "description": "四种反推推理循环：reflexion / plan-execute / lats / debate（clawd reason 命令）",
            "status": "builtin",
            "capabilities": ["推理", "反推"],
        })
        return {"plugins": plugins, "count": len(plugins)}

    # 静态托管 mime 白名单（NR-3）：显式映射，不依赖 mimetypes/注册表
    # （Windows 上 guess_type 会读注册表，可能返回错误或 None 类型）
    _STATIC_MIME_TYPES = {
        '.html': 'text/html; charset=utf-8',
        '.htm': 'text/html; charset=utf-8',
        '.js': 'application/javascript; charset=utf-8',
        '.mjs': 'application/javascript; charset=utf-8',
        '.css': 'text/css; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon',
        '.woff': 'font/woff',
        '.woff2': 'font/woff2',
        '.ttf': 'font/ttf',
        '.map': 'application/json',
        '.txt': 'text/plain; charset=utf-8',
        '.webp': 'image/webp',
    }

    @classmethod
    def _guess_static_mime(cls, path) -> str | None:
        """按扩展名查 mime 白名单；非白名单后缀返回 None（拒绝服务）"""
        from pathlib import Path as _Path

        return cls._STATIC_MIME_TYPES.get(_Path(path).suffix.lower())

    def _serve_static(self, connection, request):
        """websockets 的 process_request 回调：托管静态 Web UI

        - GET / 与 /index.html → index.html
        - GET /<file> → 静态文件（仅 mime 白名单后缀，防路径穿越）
        - 其余（/ws 等 upgrade 请求）返回 None 走正常 WS 握手
        """

        from websockets.http11 import Response as _WsResponse

        def _resp(status: int, body: bytes, ctype: str) -> _WsResponse:
            from websockets.datastructures import Headers as _H

            reason = {200: 'OK', 403: 'Forbidden', 404: 'Not Found', 405: 'Method Not Allowed'}.get(status, '?')
            return _WsResponse(
                status, reason,
                _H([
                    ('Content-Type', ctype),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'),
                    ('Connection', 'close'),
                ]),
                body,
            )

        raw_path = request.path
        path = raw_path.split('?')[0]
        if request.headers.get('Upgrade', '').lower() != 'websocket':
            # 破坏性 HTTP 写操作必须带 token。
            # 真实安全缺陷（v0.88.9）：这两个端点此前完全没有鉴权 —— 本机任意进程、
            # 或网页 CSRF（简单 GET 不触发 preflight）一条请求就能改名/删除会话。
            if path in ('/api/session/rename', '/api/session/delete'):
                if not self._http_write_authorized(raw_path, request.headers):
                    self.logger.warning(f'拒绝未授权的写操作: {path}')
                    return _resp(403, b'forbidden: token required', 'text/plain; charset=utf-8')
            try:
                # websockets 16 的 Request 无 method 属性；进入此回调的
                # 非 upgrade 请求按 GET 处理（loopback-only 服务，可接受）
                return self._handle_static_http(path, raw_path)
            except Exception as exc:
                import traceback

                self.logger.error(f"静态托管处理失败: {path} — {type(exc).__name__}: {exc}")
                self.logger.error(traceback.format_exc())
                from websockets.datastructures import Headers as _H
                from websockets.http11 import Response as _WsResponse

                return _WsResponse(
                    500, 'Internal Server Error',
                    _H([('Content-Type', 'text/plain; charset=utf-8'),
                        ('Content-Length', '21'),
                        ('Connection', 'close')]),
                    b'Internal Server Error',
                )
        return None  # WS 握手走默认流程

    def _http_write_authorized(self, raw_path: str, headers) -> bool:
        """HTTP 写操作的 token 校验（`?token=` 或 `X-Clawd-Token` 头）

        只用于**破坏性**端点；只读的 /api/* 保持免鉴权（loopback-only UI 需要它们）。
        """
        import secrets
        from urllib.parse import parse_qs

        expected = str(getattr(self._auth_manager, 'token', '') or '')
        if not expected:
            return False
        given = ''
        if '?' in raw_path:
            given = (parse_qs(raw_path.split('?', 1)[1]).get('token') or [''])[0]
        if not given:
            try:
                given = str(headers.get('X-Clawd-Token', '') or '')
            except Exception:  # noqa: BLE001 — 老版本 Headers 可能不支持 get
                given = ''
        return bool(given) and secrets.compare_digest(given, expected)

    def _handle_static_http(self, path: str, raw_path: str = ""):
        """静态 HTTP 处理主体（返回 websockets Response）"""
        from pathlib import Path as _Path

        from websockets.datastructures import Headers as _H

        # ---- 探针端点（不需要 token，也不回显任何路径/密钥）----
        # 为什么要它：docker-compose 里原来的 healthcheck 是
        # `python -c "sys.exit(0)"` —— 无论服务死活都返回 0，等于没有健康检查；
        # 而任何外部监控想探活只能打 `/health`，那个路径不存在（会掉进静态托管被
        # mime 白名单判成 403，看起来像"鉴权问题"，实际是"没有这个端点"）。
        if path == '/healthz':
            return _json_response(200, self.liveness_payload())
        if path == '/readyz':
            payload, ok = self.readiness_payload()
            return _json_response(200 if ok else 503, payload)
        from websockets.http11 import Response as _WsResponse

        # API 端点：宿主信息（版本/运行环境/模型配置 — 供 UI 显示，绝不含密钥）
        if path == '/api/info':
            body = json.dumps(self._collect_info(), ensure_ascii=False).encode('utf-8')
            return _WsResponse(
                200, 'OK',
                _H([('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'),
                    ('Connection', 'close')]),
                body,
            )

        # API 端点：多 provider 列表（密钥只给掩码）
        if path == '/api/providers':
            from ..core import providers_store

            try:
                items = providers_store.list_providers(Path.cwd())
                payload = {'providers': items, 'count': len(items), 'kinds': list(providers_store.KINDS)}
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                status = 200
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                status = 500
            return _WsResponse(
                status, 'OK' if status == 200 else 'Internal Server Error',
                _H([('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'),
                    ('Connection', 'close')]),
                body,
            )

        # API 端点：用量统计（KPI + 按小时 + 按模型）
        if path == '/api/usage':
            from ..core import usage_store

            try:
                from urllib.parse import parse_qs

                source = raw_path or path
                q = parse_qs(source.split('?', 1)[1] if '?' in source else '')
                range_key = (q.get('range') or ['today'])[0] or 'today'
                payload = usage_store.summary(range_key, Path.cwd())
                # 一次请求把"汇总 + 最近日志"都给前端（面板打开即渲染，不用二次往返）
                payload['recent'] = usage_store.recent(50, Path.cwd())
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                status = 200
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                status = 500
            return _WsResponse(
                status, 'OK' if status == 200 else 'Internal Server Error',
                _H([('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'),
                    ('Connection', 'close')]),
                body,
            )

        # API 端点：项目列表
        if path == '/api/projects':
            from ..core import projects_store

            try:
                payload = {
                    'projects': projects_store.list_projects(),
                    'active': projects_store.active_project(),
                }
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                status = 200
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                status = 500
            return _WsResponse(
                status, 'OK' if status == 200 else 'Internal Server Error',
                _H([('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'), ('Connection', 'close')]),
                body,
            )

        # API 端点：模型清单
        if path == '/api/models':
            try:
                from ..core import providers_store
                from ..llm.vision import supports_vision

                models: list[dict[str, Any]] = []
                seen: set[str] = set()
                for item in providers_store.list_providers():
                    if item.get('model') and item['model'] not in seen:
                        seen.add(item['model'])
                        models.append({'id': f"{item['id']}:{item['model']}",
                                       'model': item['model'],
                                       'label': item['name'] + ' · ' + item['model'],
                                       'source': 'provider', 'provider': item['id'],
                                       'vision': supports_vision(item['model'])})
                body = json.dumps({'models': models, 'count': len(models)}, ensure_ascii=False).encode('utf-8')
                status = 200
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                status = 500
            return _WsResponse(
                status, 'OK' if status == 200 else 'Internal Server Error',
                _H([('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'), ('Connection', 'close')]),
                body,
            )

        # API 端点：上下文用量（"这一轮上下文都被谁占了"）
        if path == '/api/context':
            import os as _os

            try:
                from ..agent.skill_loader import discover_skills
                from ..core import usage_store

                window = int(_os.environ.get('CLAWD_CONTEXT_WINDOW', '200000'))
                recent = usage_store.recent(1, Path.cwd())
                used_prompt = int((recent[0].get('prompt_tokens') or 0)) if recent else 0

                skills = discover_skills(Path.cwd())
                skills_chars = sum(len(s.name) + len(s.description) for s in skills)
                # 中文约 1.6 字/token、英文约 4 字符/token，这里取 3 作折中估算
                skills_tokens = max(1, skills_chars // 3)

                items = [
                    {'label': '消息历史', 'tokens': used_prompt, 'note': '上一轮实际 prompt token'},
                    {'label': '技能清单', 'tokens': skills_tokens, 'note': f'{len(skills)} 个技能的 name+description'},
                ]
                used = sum(i['tokens'] for i in items)
                free = max(0, window - used)
                for item in items:
                    item['percent'] = round(item['tokens'] / window, 4) if window else 0
                payload = {
                    'context_window': window,
                    'used': used,
                    'free': free,
                    'used_percent': round(used / window, 4) if window else 0,
                    'items': items + [{'label': '剩余空间', 'tokens': free,
                                       'percent': round(free / window, 4) if window else 0,
                                       'note': '可继续对话的余量'}],
                }
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                status = 200
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                status = 500
            return _WsResponse(
                status, 'OK' if status == 200 else 'Internal Server Error',
                _H([('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'),
                    ('Connection', 'close')]),
                body,
            )

        # API 端点：会话列表（侧栏"工作区"里那些历史会话）
        if path == '/api/sessions':
            from ..core import session_bridge
            from ..core.data_dir import data_path

            try:
                sessions_dir = data_path('sessions')
                views = session_bridge.list_all(sessions_dir)
                items = [
                    {
                        'id': v.session_id,
                        'title': (v.title or '')[:80],
                        'status': v.status,
                        'updated_at': v.updated_at,
                        'turns': v.turn_count,
                        'messages': len(v.messages),
                        'workdir': str((v.metadata or {}).get('workdir') or ''),
                        'provider': v.provider or '',
                        'model': v.model or '',
                    }
                    for v in views[:80]
                ]
                body = json.dumps({'sessions': items, 'count': len(items)}, ensure_ascii=False).encode('utf-8')
                status = 200
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                status = 500
            return _WsResponse(
                status, 'OK' if status == 200 else 'Internal Server Error',
                _H([('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'),
                    ('Connection', 'close')]),
                body,
            )

        # API 端点：单个会话内容（点开历史会话时加载）
        if path == '/api/session':
            from urllib.parse import parse_qs

            from ..core import session_bridge

            source = raw_path or path
            q = parse_qs(source.split('?', 1)[1] if '?' in source else '')
            sid = (q.get('id') or [''])[0]
            if not sid:
                return _WsResponse(400, 'Bad Request', _H([('Content-Type', 'text/plain; charset=utf-8'),
                                                          ('Content-Length', '4'), ('Connection', 'close')]), b'need')
            from ..core.data_dir import data_path as _dp

            try:
                view = session_bridge.load(sid, _dp('sessions'))
                payload = {
                    'id': view.session_id,
                    'title': view.title,
                    'status': view.status,
                    'messages': [
                        {'role': m.get('role'), 'content': m.get('content'), 'name': m.get('name')}
                        for m in (view.messages or [])[:200]
                    ],
                }
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                status = 200
            except (FileNotFoundError, ValueError) as exc:
                body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                status = 404
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                status = 500
            return _WsResponse(
                status, 'OK' if status == 200 else ('Not Found' if status == 404 else 'Internal Server Error'),
                _H([('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'),
                    ('Connection', 'close')]),
                body,
            )

        # API 端点：会话重命名 / 删除（侧栏 ⋯ 菜单）
        if path in ('/api/session/rename', '/api/session/delete'):
            from urllib.parse import parse_qs

            from ..core import session_bridge
            from ..core.data_dir import data_path as _dp2

            source = raw_path or path
            q = parse_qs(source.split('?', 1)[1] if '?' in source else '')
            sid = (q.get('id') or [''])[0].strip()
            if not sid:
                body = json.dumps({'error': '缺少 id'}, ensure_ascii=False).encode('utf-8')
                return _WsResponse(400, 'Bad Request', _H([
                    ('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))), ('Connection', 'close')]), body)
            try:
                if path == '/api/session/rename':
                    title = (q.get('title') or [''])[0]
                    view = session_bridge.rename(sid, title, _dp2('sessions'))
                    payload = {'ok': True, 'id': view.session_id, 'title': view.title}
                else:
                    ok = session_bridge.delete_session(sid, _dp2('sessions'))
                    payload = {'ok': ok, 'id': sid}
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                status = 200
            except (FileNotFoundError, ValueError) as exc:
                body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                status = 404
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                status = 500
            return _WsResponse(
                status, 'OK' if status == 200 else ('Not Found' if status == 404 else 'Internal Server Error'),
                _H([('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'),
                    ('Connection', 'close')]),
                body,
            )

        # API 端点：工作区文件（只给图片，供 Markdown 里内嵌图片用）
        if path == '/api/file':
            from urllib.parse import parse_qs

            source = raw_path or path
            query = parse_qs(source.split('?', 1)[1] if '?' in source else '')
            raw = (query.get('path') or [''])[0]
            img_mime = {
                '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
            }
            if not raw:
                return _WsResponse(400, 'Bad Request', _H([('Content-Type', 'text/plain; charset=utf-8'),
                                                          ('Content-Length', '4'), ('Connection', 'close')]), b'need')
            target = Path(raw)
            if not target.is_absolute():
                target = (Path.cwd() / raw)
            try:
                target = target.resolve()
                root = Path.cwd().resolve()
                # 桌面端上传的图片在数据目录（userData/data/uploads），不在 cwd 下 ——
                # 只认 cwd 会让内联图片一律 403（真实缺陷）。
                from ..core.data_dir import data_path as _dp3

                allowed_roots = [root]
                try:
                    allowed_roots.append(_dp3().resolve())
                except OSError as exc:
                    # 数据目录解析不出来时只放行 cwd（图片会 403，但不至于整个端点挂掉）
                    self.logger.debug(f'/api/file: 数据目录不可用，仅放行 cwd: {exc}')
                if not any(target.is_relative_to(r) for r in allowed_roots):
                    return _WsResponse(403, 'Forbidden', _H([('Content-Type', 'text/plain; charset=utf-8'),
                                                            ('Content-Length', '9'), ('Connection', 'close')]), b'forbidden')
                mime = img_mime.get(target.suffix.lower())
                if mime is None:
                    return _WsResponse(403, 'Forbidden', _H([('Content-Type', 'text/plain; charset=utf-8'),
                                                            ('Content-Length', '9'), ('Connection', 'close')]), b'forbidden')
                if not target.is_file() or target.stat().st_size > 8 * 1024 * 1024:
                    return _WsResponse(404, 'Not Found', _H([('Content-Type', 'text/plain; charset=utf-8'),
                                                            ('Content-Length', '7'), ('Connection', 'close')]), b'notfound')
                data = target.read_bytes()
            except OSError:
                return _WsResponse(404, 'Not Found', _H([('Content-Type', 'text/plain; charset=utf-8'),
                                                        ('Content-Length', '7'), ('Connection', 'close')]), b'notfound')
            return _WsResponse(
                200, 'OK',
                _H([('Content-Type', mime), ('Content-Length', str(len(data))),
                    ('Cache-Control', 'no-cache'), ('Connection', 'close')]),
                data,
            )

        # API 端点：插件市场数据（JSON）
        if path == '/api/plugins':
            body = json.dumps(self._collect_plugins(), ensure_ascii=False).encode('utf-8')
            return _WsResponse(
                200, 'OK',
                _H([('Content-Type', 'application/json; charset=utf-8'),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'),
                    ('Connection', 'close')]),
                body,
            )

        def _resp(status: int, body: bytes, ctype: str) -> _WsResponse:
            reason = {200: 'OK', 403: 'Forbidden', 404: 'Not Found', 405: 'Method Not Allowed'}.get(status, '?')
            return _WsResponse(
                status, reason,
                _H([
                    ('Content-Type', ctype),
                    ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-cache'),
                    ('Connection', 'close'),
                ]),
                body,
            )

        # 未知 API 路径：明确 404。此前会掉进下面的静态托管，被 mime 白名单
        # （无后缀 → ctype=None）判成 **403 Forbidden**，调用方看到"鉴权失败"
        # 而真相是"没有这个端点"，排障方向被带偏。
        if path.startswith('/api/'):
            return _json_response(404, {'error': 'not_found', 'path': path})

        if not self._static_dir:
            # 纯服务模式（无 Web UI 托管）：非探针、非 API 的路径一律 404，
            # 而不是因为拿不到静态根而抛异常变成 500。
            return _json_response(404, {'error': 'not_found', 'path': path})

        root = _Path(self._static_dir).resolve()
        if path in ('/', '/index.html'):
            target = root / 'index.html'
        else:
            target = (root / path.lstrip('/')).resolve()
            # 防路径穿越（is_relative_to 而非字符串前缀，C:\web 不会放行 C:\webstore）
            if not target.is_relative_to(root):
                return _resp(403, b'Forbidden', 'text/plain; charset=utf-8')
        # 无后缀路径不可能是静态资源（`/health` 这类）。此前会走到下面的 mime
        # 白名单分支被判 403 Forbidden —— 运维看到 403 会去查鉴权，方向被带偏。
        if not target.suffix:
            return _resp(404, b'Not Found', 'text/plain; charset=utf-8')
        # mime 白名单先行：白名单外后缀直接 403，不做无效 IO
        ctype = self._guess_static_mime(target)
        if ctype is None:
            return _resp(403, b'Forbidden', 'text/plain; charset=utf-8')
        if not target.is_file():
            return _resp(404, b'Not Found', 'text/plain; charset=utf-8')
        try:
            body = target.read_bytes()
        except OSError:
            return _resp(405, b'Read Error', 'text/plain; charset=utf-8')
        # index.html：注入 token（app.js 优先读 window.__CLAWD_TOKEN__）
        if target.name == 'index.html' and self._static_token_inject:
            inject = (
                '<script>window.__CLAWD_TOKEN__='
                + json.dumps(self._static_token_inject)
                + ';</script>'
            ).encode('utf-8')
            marker = b'</title>'
            if marker in body:
                body = body.replace(marker, marker + inject, 1)
        return _resp(200, body, ctype)

    async def stop(self) -> None:
        """停止服务器"""
        async with ServerShutdown(self):
            pass

    async def run_forever(self) -> None:
        """运行直到关闭"""
        try:
            if self._ws_server is None:
                await self.start()
            await self._ws_server.wait_closed()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def __aenter__(self) -> ClawdWebSocketServer:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    async def broadcast(self, message: dict[str, Any]) -> int:
        """广播消息"""
        return await self._manager.broadcast(message)


def create_server(
    settings: AgentSettings | None = None,
    llm_config: LLMConfig | None = None,
    **kwargs: Any,
) -> ClawdWebSocketServer:
    """创建服务器便捷函数"""
    return ClawdWebSocketServer(
        settings=settings,
        llm_config=llm_config,
        **kwargs,
    )

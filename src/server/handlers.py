"""WebSocket 消息处理器模块

负责解析和路由来自客户端的 JSON-RPC 风格消息，
执行对应的业务逻辑（目标执行、状态查询、文件操作等），
并返回标准化的响应或错误消息。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.events import Event, EventBus, EventType, get_event_bus
from ..core.exceptions import ClawdError, ErrorCode
from ..utils import get_logger

if TYPE_CHECKING:
    from websockets import ServerProtocol

    from ..llm import LLMConfig
    from .auth import AuthManager


# ------------------------------------------------------------------
# 响应构建工具
# ------------------------------------------------------------------

def build_response(
    msg_id: str | int | None,
    data: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建成功的 JSON-RPC 风格响应。

    参数:
        msg_id: 原始请求的消息 ID。
        data: 响应负载数据。
        extra: 额外的顶层字段（可选）。

    返回:
        标准化的响应字典。
    """
    resp: dict[str, Any] = {
        'id': msg_id,
        'type': 'response',
        'data': data,
    }
    if extra:
        resp.update(extra)
    return resp


def build_error(
    msg_id: str | int | None,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建错误的 JSON-RPC 风格响应。

    参数:
        msg_id: 原始请求的消息 ID。
        code: 错误码（大写字母+数字格式）。
        message: 人类可读的错误描述。
        details: 可选的额外错误上下文。

    返回:
        标准化的错误响应字典。
    """
    err: dict[str, Any] = {
        'id': msg_id,
        'type': 'error',
        'code': code,
        'message': message,
    }
    if details:
        err['details'] = details
    return err


# ------------------------------------------------------------------
# 消息路由器
# ------------------------------------------------------------------

class MessageRouter:
    """WebSocket 消息路由器。

    将传入的消息根据 ``type`` 字段分发到对应的处理函数，
    统一捕获异常并转换为结构化错误响应。
    """

    def __init__(
        self,
        auth_manager: AuthManager,
        event_bus: EventBus | None = None,
    ) -> None:
        """初始化路由器。

        参数:
            auth_manager: 认证管理器实例。
            event_bus: 事件总线实例。若为 None 则使用全局实例。
        """
        self.logger = get_logger('server.handlers')
        self.auth_manager = auth_manager
        self.event_bus = event_bus or get_event_bus()

    async def dispatch(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        """将消息分发到对应的处理器。

        参数:
            ws: 发起请求的 WebSocket 连接。
            message: 解析后的消息字典。
            engine_factory: AgentEngine 工厂，``run`` 处理器需要。

        返回:
            处理结果响应字典。

        异常:
            当消息格式无效或缺少 ``type`` 字段时返回错误响应。
        """
        msg_type = message.get('type')
        msg_id = message.get('id')

        # 认证前置检查（auth 类型除外）
        if msg_type != 'auth' and not self.auth_manager.is_authenticated(ws):
            return build_error(
                msg_id,
                'E_AUTH_REQUIRED',
                '连接未认证。请先发送 {{"type": "auth", "token": "..."}} 消息',
            )

        if not msg_type:
            return build_error(
                msg_id,
                'E_INVALID_MESSAGE',
                '消息缺少 type 字段',
            )

        # 路由表
        handlers: dict[str, callable] = {  # type: ignore[type-arg]
            'auth': self._handle_auth,
            'run': self._handle_run,
            'personas': self._handle_personas,
            'projects_list': self._handle_projects_list,
            'projects_add': self._handle_projects_add,
            'projects_remove': self._handle_projects_remove,
            'projects_set_active': self._handle_projects_set_active,
            'projects_clone': self._handle_projects_clone,
            'models_list': self._handle_models_list,
            'providers_list': self._handle_providers_list,
            'providers_save': self._handle_providers_save,
            'providers_delete': self._handle_providers_delete,
            'providers_set_default': self._handle_providers_set_default,
            'usage_summary': self._handle_usage_summary,
            'usage_recent': self._handle_usage_recent,
            'status': self._handle_status,
            'file_read': self._handle_file_read,
            'file_write': self._handle_file_write,
            'ping': self._handle_ping,
            'settings_get': self._handle_settings_get,
            'settings_set': self._handle_settings_set,
        }

        handler = handlers.get(msg_type)
        if handler is None:
            return build_error(
                msg_id,
                'E_UNKNOWN_TYPE',
                f'不支持的消息类型: {msg_type}',
                {'supported_types': list(handlers.keys())},
            )

        # 执行处理器并捕获异常
        try:
            return await handler(ws, message, engine_factory)
        except ClawdError as exc:
            self.logger.error(
                f'处理消息 [{msg_type}] 时发生业务异常: {exc}',
                type=msg_type,
            )
            return build_error(msg_id, exc.code.value, exc.message, exc.details)
        except Exception as exc:
            self.logger.error(
                f'处理消息 [{msg_type}] 时发生内部错误: {exc}',
                type=msg_type,
                exc_info=True,
            )
            return build_error(
                msg_id,
                ErrorCode.INTERNAL_ERROR.value,
                f'内部服务器错误: {exc}',
            )

    # ------------------------------------------------------------------
    # 处理器实现
    # ------------------------------------------------------------------

    async def _handle_auth(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        _engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        """处理认证请求。

        期望消息格式: {"type": "auth", "token": "..."}
        """
        token = message.get('token', '')
        if not token:
            return build_error(
                message.get('id'),
                'E_MISSING_TOKEN',
                '认证请求缺少 token 字段',
            )

        success = await self.auth_manager.authenticate(ws, token)
        if success:
            self.event_bus.publish(Event(
                type=EventType.SERVER_AUTH_SUCCESS,
                data={'client': str(ws.remote_address)},
                source='websocket_server',
            ))
            return build_response(
                message.get('id'),
                {'status': 'authenticated'},
            )
        else:
            self.event_bus.publish(Event(
                type=EventType.SERVER_AUTH_FAILURE,
                data={'client': str(ws.remote_address)},
                source='websocket_server',
            ))
            return build_error(
                message.get('id'),
                'E_AUTH_FAILED',
                '令牌无效，认证被拒绝',
            )

    async def _handle_run(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        """处理目标执行请求。

        期望消息格式:
            {"type": "run", "goal": "用户目标", "stream": false}

        使用 AgentEngine 执行目标，返回最终结果。
        如果 engine_factory 未提供则返回错误。
        """
        if engine_factory is None:
            return build_error(
                message.get('id'),
                'E_ENGINE_UNAVAILABLE',
                'AgentEngine 工厂不可用，无法执行任务',
            )

        goal = message.get('goal', '')
        if not goal:
            return build_error(
                message.get('id'),
                'E_MISSING_GOAL',
                'run 请求缺少 goal 字段',
            )

        stream = message.get('stream', False)
        chosen_model = str(message.get('model') or '').strip()
        reasoning_effort = str(message.get('reasoning_effort') or '').strip()
        fast_mode = bool(message.get('fast_mode'))
        llm_config_from_msg: LLMConfig | None = message.get('llm_config')  # type: ignore[assignment]

        # 没显式传 config 时，用用户在设置里选的"默认 provider"——否则多 provider 只是好看的表格
        if chosen_model:
            from dataclasses import replace as _dc_replace

            base_cfg = llm_config_from_msg
            if base_cfg is None:
                from ..llm.config import LLMConfig as _LLMConfig

                base_cfg = _LLMConfig.from_env()
            temp_map = {'低': 0.9, '中': 0.7, '高': 0.4, '极高': 0.2, '最大': 0.0}
            overrides: dict[str, Any] = {'model': chosen_model}
            if reasoning_effort in temp_map:
                overrides['temperature'] = temp_map[reasoning_effort]
            if fast_mode:
                overrides['max_tokens'] = min(int(getattr(base_cfg, 'max_tokens', 4096) or 4096), 1024)
            try:
                llm_config_from_msg = _dc_replace(base_cfg, **overrides)
            except TypeError:
                llm_config_from_msg = base_cfg
            self.logger.info(
                f"本轮模型={chosen_model} 推理强度={reasoning_effort or '默认'} 快速模式={fast_mode}"
            )

        if llm_config_from_msg is None:
            from ..core import providers_store

            try:
                active = providers_store.active_provider(self._workdir())
                if active and active.get('has_key'):
                    llm_config_from_msg = providers_store.build_llm_config(
                        active['id'], self._workdir()
                    )
                    self.logger.info(
                        f"使用默认 provider: {active['id']} / {active['model'] or '(默认模型)'}"
                    )
                elif active:
                    self.logger.warning(
                        f"默认 provider {active['id']} 没有可用密钥，回退全局配置"
                    )
            except Exception as exc:  # noqa: BLE001 — provider 配置有问题不能挡住对话
                self.logger.warning(f"默认 provider 不可用，回退全局配置: {exc}")

        # 项目：消息里带 workdir 就用它（客户端选中的项目），否则用 Host 默认
        run_workdir = message.get('workdir')
        try:
            engine = engine_factory.create(
                llm_config=llm_config_from_msg,
                workdir=Path(str(run_workdir)) if run_workdir else None,
            )
        except TypeError:
            engine = engine_factory.create(llm_config=llm_config_from_msg)

        # 续聊：客户端带上会话 id，则本轮结果追加到该会话（而不是每轮新开一条）
        sid_hint = str(message.get('session_id') or '').strip()
        if sid_hint:
            try:
                engine.session_id_hint = sid_hint
            except AttributeError as exc:
                # 引擎不支持续聊 id（老实现/测试桩）→ 退回"每轮新开"，但要留痕
                self.logger.debug(f'引擎不接受 session_id_hint，本轮将新开会话: {exc}')

        # 角色（personas/*.md）：用户不用自己写提示词，选一个即可
        persona_name = str(message.get('persona') or '').strip()
        if persona_name:
            from ..agent.personas import load_persona

            try:
                engine.apply_persona(load_persona(persona_name))
            except KeyError as exc:
                return build_error(message.get('id'), 'E_PERSONA_UNKNOWN', str(exc))

        self.event_bus.publish(Event(
            type=EventType.AGENT_TASK_STARTED,
            data={
                'goal': goal,
                'client': str(ws.remote_address),
                'stream': stream,
            },
            source='websocket_server',
        ))

        if llm_config_from_msg and engine.llm_provider is None:
            # 如果传入的 llm_config 还未创建 provider，手动初始化
            from ..llm import create_llm_provider
            try:
                engine.llm_provider = create_llm_provider(llm_config_from_msg)
            except Exception as exc:
                return build_error(
                    message.get('id'),
                    'E_LLM_INIT_FAILED',
                    f'LLM 提供商初始化失败: {exc}',
                )

        # 图片附件：客户端把图片以 data URL 塞进 run 消息（HTTP 侧只有 GET，不做 multipart）
        # 我们把它落盘到 .clawd/uploads/ 并把路径写进 goal —— **不假装视觉能力**：
        # 模型能用 FileReadTool 读到文件；读不出图就如实说看不到，而不是编造图片内容。
        attachments: list[str] = []
        use_vision = False  # 无附件 / 模型不支持视觉时保持 False（走纯文本 + 路径告知）
        raw_images = message.get('images')
        if isinstance(raw_images, list) and raw_images:
            import base64
            import hashlib

            from ..core.data_dir import data_path

            upload_dir = data_path('uploads', create_dir=True)
            try:
                upload_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.logger.warning(f"创建上传目录失败: {exc}")
            for item in raw_images[:4]:
                data_url = ''
                if isinstance(item, dict):
                    data_url = str(item.get('data_url') or item.get('dataUrl') or '')
                elif isinstance(item, str):
                    data_url = item
                if not data_url.startswith('data:image/'):
                    continue
                try:
                    head, _, payload = data_url.partition(',')
                    ext = 'png'
                    if ';' in head:
                        mime = head[5:].split(';')[0]
                        ext = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif',
                               'image/webp': 'webp', 'image/bmp': 'bmp'}.get(mime, 'png')
                    raw = base64.b64decode(payload, validate=False)
                    if len(raw) > 8 * 1024 * 1024:
                        self.logger.warning("附件超过 8MB，已忽略")
                        continue
                    digest = hashlib.sha256(raw).hexdigest()[:12]
                    target = upload_dir / f"img-{digest}.{ext}"
                    target.write_bytes(raw)
                    # **写绝对路径**：上传目录在数据目录（userData/data/uploads），
                    # 与工作目录不在同一棵树里，`relative_to(workdir)` 会抛 ValueError
                    # 把附件整条吞掉 —— 模型于是完全不知道有图（真实发现：
                    # 落了盘但 goal 里没路径，用户以为"图片没传上去"）。
                    attachments.append(str(target))
                except Exception as exc:  # noqa: BLE001 — 坏图片不能挡住消息
                    self.logger.warning(f"附件解析失败（已忽略）: {exc}")
            if attachments:
                # 模型能看图 → 图片以 image_url 内容块随消息发出（真多模态）；
                # 否则回退成"路径告知 + 如实说看不到"，绝不让模型猜图里有什么。
                from ..llm.vision import supports_vision

                model_name = str(getattr(llm_config_from_msg, 'model', '') or '')
                if not model_name:
                    cfg_obj = getattr(getattr(engine, 'llm_provider', None), 'config', None)
                    model_name = str(getattr(cfg_obj, 'model', '') or '')
                use_vision = supports_vision(model_name)
                if use_vision:
                    goal = goal + (
                        "\n\n[随消息附图 " + str(len(attachments))
                        + " 张，已作为图像内容一并提供，请直接看图回答。]"
                    )
                else:
                    goal = goal + (
                        "\n\n[随消息附图 " + str(len(attachments)) + " 张，已保存到本机: "
                        + ", ".join(attachments)
                        + "。若你的模型不支持视觉输入，请直接说明看不到图片，不要猜内容。]"
                    )
                self.logger.info(
                    f"附件 {len(attachments)} 张，模型={model_name or '(未知)'} "
                    f"视觉={'开' if use_vision else '关'}"
                )

        # 续聊：客户端可带上一段历史（点开旧会话后继续对话）
        prior_messages: list[dict[str, Any]] = []
        raw_prior = message.get('prior_messages')
        if isinstance(raw_prior, list):
            for item in raw_prior[-40:]:
                if isinstance(item, dict) and item.get('role') in ('user', 'assistant'):
                    content = str(item.get('content') or '').strip()
                    if content:
                        prior_messages.append({'role': item['role'], 'content': content[:8000]})

        try:
            start_time = time.time()
            if stream:
                # 真流式：把增量文本发给客户端。
                # 之前这里只把 chunk 收进本地 list 就扔了 —— 客户端全程只看到工具事件，
                # 模型说的话要等整段结束才出现（"只汇报工具调用、没有正常回复"的根因）。
                self.event_bus.publish(Event(
                    type=EventType.AGENT_STREAM_STARTED,
                    data={'goal': goal},
                    source='websocket_server',
                ))
                buf: list[str] = []
                state = {'chars': 0, 'last': time.monotonic()}

                def _flush() -> None:
                    if not buf:
                        return
                    text = ''.join(buf)
                    buf.clear()
                    state['last'] = time.monotonic()
                    self.event_bus.publish(Event(
                        type=EventType.AGENT_STREAM_DELTA,
                        data={'text': text, 'chars': state['chars']},
                        source='websocket_server',
                    ))

                def _on_chunk(text: str) -> None:
                    if not text:
                        return
                    buf.append(text)
                    state['chars'] += len(text)
                    # 合并发送：≥40 字符或距上次 ≥120ms，避免 token 级事件打爆 WS
                    if len(''.join(buf)) >= 12 or (time.monotonic() - state['last']) >= 0.06:
                        _flush()

                session = await engine.run_stream(
                    goal=goal,
                    on_chunk=_on_chunk,
                    prior_messages=prior_messages,
                    images=attachments if use_vision else None,
                )
                _flush()
                # 事件总线 → WS 的投递是排队进行的：让出一次循环，
                # 保证增量文本先于最终 response 到达客户端（否则前端会看到"先出完整答案、后补流式"）
                await asyncio.sleep(0.08)
                self.event_bus.publish(Event(
                    type=EventType.AGENT_STREAM_COMPLETED,
                    data={'chars': state['chars']},
                    source='websocket_server',
                ))
            else:
                session = await engine.run(
                    goal=goal, prior_messages=prior_messages,
                    images=attachments if use_vision else None,
                )

            elapsed = time.time() - start_time

            # 发送完成事件
            self.event_bus.publish(Event(
                type=EventType.AGENT_TASK_COMPLETED,
                data={
                    'goal': goal,
                    'result': session.final_result or '',
                    'steps': len(session.steps),
                    'elapsed': round(elapsed, 3),
                },
                source='websocket_server',
            ))

            # 获取性能指标
            metrics = engine.get_perf_summary() if hasattr(engine, 'get_perf_summary') else ''

            return build_response(
                message.get('id'),
                {
                    'status': 'completed',
                    'session_id': str(getattr(engine, 'last_session_id', '') or ''),
                    'attachments': attachments,
                    'result': session.final_result or '',
                    'steps': len(session.steps),
                    'elapsed_seconds': round(elapsed, 3),
                    'perf_summary': metrics,
                },
            )

        except Exception as exc:
            self.logger.error(
                f'执行目标时出错: {goal} | 错误: {exc}',
                goal=goal,
                exc_info=True,
            )
            self.event_bus.publish(Event(
                type=EventType.AGENT_TASK_ERROR,
                data={
                    'goal': goal,
                    'error': str(exc),
                },
                source='websocket_server',
            ))
            return build_error(
                message.get('id'),
                'E_RUN_FAILED',
                f'任务执行失败: {exc}',
            )

    # ------------------------------------------------------------------
    # 项目（工作区）
    # ------------------------------------------------------------------
    async def _handle_projects_list(self, ws, message, engine_factory=None):
        from ..core import projects_store

        try:
            items = projects_store.list_projects()
            active = projects_store.active_project()
        except Exception as exc:  # noqa: BLE001
            return build_error(message.get('id'), 'E_PROJECTS_FAILED', f'读取项目失败: {exc}')
        return build_response(message.get('id'), {'projects': items, 'count': len(items), 'active': active})

    async def _handle_projects_add(self, ws, message, engine_factory=None):
        from ..core import projects_store

        path = str(message.get('path') or '').strip()
        name = str(message.get('name') or '').strip()
        if not path:
            return build_error(message.get('id'), 'E_INVALID_MESSAGE', '缺少 path')
        try:
            project = projects_store.add_project(path, name)
        except ValueError as exc:
            return build_error(message.get('id'), 'E_PROJECT_INVALID', str(exc))
        return build_response(message.get('id'), {'project': project})

    async def _handle_projects_remove(self, ws, message, engine_factory=None):
        from ..core import projects_store

        project_id = str(message.get('project_id') or message.get('id_value') or '').strip()
        if not project_id:
            return build_error(message.get('id'), 'E_INVALID_MESSAGE', '缺少 project_id')
        return build_response(message.get('id'), {'removed': projects_store.remove_project(project_id)})

    async def _handle_projects_set_active(self, ws, message, engine_factory=None):
        from ..core import projects_store

        project_id = str(message.get('project_id') or message.get('id_value') or '').strip()
        if not project_id:
            return build_error(message.get('id'), 'E_INVALID_MESSAGE', '缺少 project_id')
        if not projects_store.set_active(project_id):
            return build_error(message.get('id'), 'E_PROJECT_NOT_FOUND', f'项目不存在: {project_id}')
        return build_response(message.get('id'), {'active': projects_store.active_project()})

    async def _handle_projects_clone(self, ws, message, engine_factory=None):
        """从 URL 克隆仓库并加入项目列表（真实调用 git clone）"""
        from ..core import data_dir as data_dir_mod
        from ..core import projects_store

        url = str(message.get('url') or '').strip()
        if not url:
            return build_error(message.get('id'), 'E_INVALID_MESSAGE', '缺少 url')
        if not (url.startswith('http://') or url.startswith('https://') or url.startswith('git@')):
            return build_error(message.get('id'), 'E_INVALID_MESSAGE', '只支持 http(s):// 或 git@ 的仓库地址')

        name = url.rstrip('/').split('/')[-1]
        if name.endswith('.git'):
            name = name[:-4]
        name = name or 'repo'
        target_root = data_dir_mod.data_path('clones', create_dir=True)
        target = target_root / name

        import asyncio
        import subprocess

        def _clone() -> tuple[int, str]:
            try:
                proc = subprocess.run(
                    ['git', 'clone', '--depth', '1', url, str(target)],
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600,
                )
                return proc.returncode, (proc.stderr or proc.stdout or '').strip()[:600]
            except (OSError, subprocess.SubprocessError) as exc:
                return 1, f'{type(exc).__name__}: {exc}'

        code, detail = await asyncio.get_running_loop().run_in_executor(None, _clone)
        if code != 0:
            return build_error(message.get('id'), 'E_CLONE_FAILED', f'git clone 失败: {detail}')

        try:
            project = projects_store.add_project(str(target), name)
        except ValueError as exc:
            return build_error(message.get('id'), 'E_PROJECT_INVALID', str(exc))
        return build_response(message.get('id'), {'project': project, 'detail': detail})

    # ------------------------------------------------------------------
    # 模型清单（客户端模型选择器）
    # ------------------------------------------------------------------
    async def _handle_models_list(self, ws, message, engine_factory=None):
        from ..core import providers_store

        models: list[dict[str, Any]] = []
        try:
            from ..core.config.models import get_settings

            settings = get_settings()
            default_model = str(getattr(settings, 'llm_model', '') or '')
            if default_model:
                models.append({
                    'id': default_model,
                    'label': default_model,
                    'source': 'global',
                    'provider': str(getattr(settings, 'llm_provider', '') or ''),
                })
        except Exception as exc:  # noqa: BLE001 — 设置读不到只是少一个模型来源
            self.logger.debug(f'模型列表：全局设置来源不可用: {exc}')

        try:
            for item in providers_store.list_providers():
                if item.get('model'):
                    models.append({
                        'id': item['model'],
                        'label': item['name'] + ' · ' + item['model'],
                        'source': 'provider',
                        'provider': item['id'],
                    })
        except Exception as exc:  # noqa: BLE001 — provider 列表坏了不影响内置模型
            self.logger.debug(f'模型列表：provider 来源不可用: {exc}')

        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in models:
            if item['id'] in seen:
                continue
            seen.add(item['id'])
            # 标出"这个模型能不能看图"——UI 据此提示，用户才知道为什么模型看不到图
            try:
                from ..llm.vision import supports_vision

                item['vision'] = supports_vision(item.get('id', ''))
            except Exception as exc:  # noqa: BLE001 — 能力标注失败不影响模型列表
                self.logger.debug(f'模型视觉标注失败（{item.get("id")}）: {exc}')
                item['vision'] = False
            unique.append(item)
        return build_response(message.get('id'), {
            'models': unique,
            'count': len(unique),
            'reasoning_efforts': ['低', '中', '高', '极高', '最大'],
        })

    async def _handle_personas(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        engine_factory: EngineFactoryProtocol | None = None,  # dispatch 统一传三参
    ) -> dict[str, Any]:
        """列出可用角色（personas/*.md）—— 前端角色选择器用"""
        from ..agent.personas import personas_report

        try:
            items = personas_report()
        except Exception as exc:  # noqa: BLE001 — 角色库坏了不能拖垮会话
            self.logger.warning(f'读取角色库失败: {exc}')
            return build_error(message.get('id'), 'E_PERSONAS_FAILED', f'读取角色库失败: {exc}')
        return build_response(message.get('id'), {'personas': items, 'count': len(items)})

    # ------------------------------------------------------------------
    # 多 provider 配置（本地 SQLite；密钥只返回掩码）
    # ------------------------------------------------------------------

    def _workdir(self) -> Path:
        """当前工作目录（provider/用量都存 <workdir>/.clawd/clawd.db）"""
        return Path.cwd()

    async def _handle_providers_list(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        from ..core import providers_store

        try:
            items = providers_store.list_providers(self._workdir())
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f'读取 provider 列表失败: {exc}')
            return build_error(message.get('id'), 'E_PROVIDERS_FAILED', f'读取 provider 失败: {exc}')
        active = next((i for i in items if i['is_default']), None)
        return build_response(
            message.get('id'),
            {'providers': items, 'count': len(items), 'active': active, 'kinds': list(providers_store.KINDS)},
        )

    async def _handle_providers_save(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        from ..core import providers_store

        payload = message.get('provider') or {}
        if not isinstance(payload, dict):
            return build_error(message.get('id'), 'E_INVALID_MESSAGE', 'provider 必须是对象')
        try:
            saved = providers_store.save_provider(payload, self._workdir())
        except ValueError as exc:
            return build_error(message.get('id'), 'E_PROVIDER_INVALID', str(exc))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f'保存 provider 失败: {exc}')
            return build_error(message.get('id'), 'E_PROVIDERS_FAILED', f'保存 provider 失败: {exc}')
        return build_response(message.get('id'), {'provider': saved})

    async def _handle_providers_delete(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        from ..core import providers_store

        provider_id = str(message.get('id_value') or message.get('provider_id') or '').strip()
        if not provider_id:
            return build_error(message.get('id'), 'E_INVALID_MESSAGE', '缺少 provider_id')
        ok = providers_store.delete_provider(provider_id, self._workdir())
        return build_response(message.get('id'), {'deleted': ok, 'provider_id': provider_id})

    async def _handle_providers_set_default(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        from ..core import providers_store

        provider_id = str(message.get('id_value') or message.get('provider_id') or '').strip()
        if not provider_id:
            return build_error(message.get('id'), 'E_INVALID_MESSAGE', '缺少 provider_id')
        ok = providers_store.set_default(provider_id, self._workdir())
        if not ok:
            return build_error(message.get('id'), 'E_PROVIDER_NOT_FOUND', f'provider 不存在: {provider_id}')
        return build_response(message.get('id'), {'default': provider_id})

    # ------------------------------------------------------------------
    # 用量统计
    # ------------------------------------------------------------------

    async def _handle_usage_summary(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        from ..core import usage_store

        range_key = str(message.get('range') or 'today')
        try:
            data = usage_store.summary(range_key, self._workdir())
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f'读取用量汇总失败: {exc}')
            return build_error(message.get('id'), 'E_USAGE_FAILED', f'读取用量失败: {exc}')
        return build_response(message.get('id'), data)

    async def _handle_usage_recent(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        from ..core import usage_store

        try:
            rows = usage_store.recent(int(message.get('limit') or 50), self._workdir())
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f'读取请求日志失败: {exc}')
            return build_error(message.get('id'), 'E_USAGE_FAILED', f'读取日志失败: {exc}')
        return build_response(message.get('id'), {'rows': rows, 'count': len(rows)})

    async def _handle_status(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        _engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        """处理服务器状态查询请求。

        返回已认证客户端数、运行时间等。
        """
        router = message.get('_router_context')
        uptime = time.time() - (router.get('start_time') if isinstance(router, dict) and 'start_time' in router else time.time())

        return build_response(
            message.get('id'),
            {
                'status': 'running',
                'authenticated_clients': self.auth_manager.authenticated_count,
                'uptime_seconds': round(uptime, 2),
            },
        )

    async def _handle_file_read(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        _engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        """处理文件读取请求。

        期望消息格式:
            {"type": "file_read", "path": "相对路径", "limit": 100}

        参数:
            path: 相对于工作目录的路径。
            limit: 最大读取行数（可选，默认不限制）。

        返回:
            文件内容及其元数据。
        """
        path_str = message.get('path', '')
        if not path_str:
            return build_error(
                message.get('id'),
                'E_MISSING_PATH',
                'file_read 请求缺少 path 字段',
            )

        limit = message.get('limit')
        base_path = message.get('base_path', Path.cwd())

        target = Path(base_path) / path_str
        try:
            target = target.resolve()
            base = Path(base_path).resolve()
            # 路径遍历检查
            if not _is_under_base(target, base):
                return build_error(
                    message.get('id'),
                    ErrorCode.SECURITY_PATH_TRAVERSAL.value,
                    '路径遍历攻击被阻止',
                    {'path': path_str},
                )
        except (OSError, ValueError) as exc:
            return build_error(
                message.get('id'),
                'E_INVALID_PATH',
                f'无效的路径: {exc}',
            )

        if not target.exists():
            return build_error(
                message.get('id'),
                'E_FILE_NOT_FOUND',
                f'文件不存在: {path_str}',
            )

        if not target.is_file():
            return build_error(
                message.get('id'),
                'E_NOT_A_FILE',
                f'路径不是文件: {path_str}',
            )

        try:
            if limit:
                import itertools
                lines = list(itertools.islice(target.open(encoding='utf-8'), limit))
                content = ''.join(lines)
            else:
                content = target.read_text(encoding='utf-8')

            return build_response(
                message.get('id'),
                {
                    'path': str(path_str),
                    'content': content,
                    'encoding': 'utf-8',
                },
            )
        except UnicodeDecodeError as exc:
            return build_error(
                message.get('id'),
                'E_ENCODING_ERROR',
                f'文件编码错误: {exc}',
            )
        except PermissionError:
            return build_error(
                message.get('id'),
                'E_PERMISSION_DENIED',
                f'没有读取权限: {path_str}',
            )
        except Exception as exc:
            return build_error(
                message.get('id'),
                ErrorCode.INTERNAL_ERROR.value,
                f'读取文件失败: {exc}',
            )

    async def _handle_file_write(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        _engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        """处理文件写入请求。

        期望消息格式:
            {"type": "file_write", "path": "相对路径", "content": "...", "mode": "w"}

        参数:
            path: 相对于工作目录的路径。
            content: 要写入的内容。
            mode: 写入模式，``w`` 或 ``a``（默认 ``w``）。

        返回:
            写入操作的结果。
        """
        path_str = message.get('path', '')
        if not path_str:
            return build_error(
                message.get('id'),
                'E_MISSING_PATH',
                'file_write 请求缺少 path 字段',
            )

        content = message.get('content')
        if content is None:
            return build_error(
                message.get('id'),
                'E_MISSING_CONTENT',
                'file_write 请求缺少 content 字段',
            )

        mode = message.get('mode', 'w')
        if mode not in ('w', 'a'):
            return build_error(
                message.get('id'),
                'E_INVALID_MODE',
                f'无效的写入模式: {mode}，仅支持 w 或 a',
            )

        base_path = message.get('base_path', Path.cwd())

        target = Path(base_path) / path_str
        try:
            target = target.resolve()
            base = Path(base_path).resolve()
            if not _is_under_base(target, base):
                return build_error(
                    message.get('id'),
                    ErrorCode.SECURITY_PATH_TRAVERSAL.value,
                    '路径遍历攻击被阻止',
                    {'path': path_str},
                )
        except (OSError, ValueError) as exc:
            return build_error(
                message.get('id'),
                'E_INVALID_PATH',
                f'无效的路径: {exc}',
            )

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding='utf-8', mode=mode)

            return build_response(
                message.get('id'),
                {
                    'path': str(path_str),
                    'operation': 'write' if mode == 'w' else 'append',
                    'bytes_written': len(str(content).encode('utf-8')),
                },
            )
        except PermissionError:
            return build_error(
                message.get('id'),
                'E_PERMISSION_DENIED',
                f'没有写入权限: {path_str}',
            )
        except Exception as exc:
            return build_error(
                message.get('id'),
                ErrorCode.INTERNAL_ERROR.value,
                f'写入文件失败: {exc}',
            )

    async def _handle_ping(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        _engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        """处理心跳/健康检查请求。

        期望消息格式: {"type": "ping"}

        返回: {"type": "response", "data": {"pong": true, "timestamp": ...}}
        """
        return build_response(
            message.get('id'),
            {
                'pong': True,
                'timestamp': time.time(),
            },
        )

    # ------------------------------------------------------------------
    # 设置读写（UI 设置面板数据源）
    # ------------------------------------------------------------------

    #: 允许 UI 修改的键（白名单；api_key 刻意排除，只能经 .env / 环境变量设置）
    UI_SETTABLE_KEYS = ('provider', 'model', 'base_url', 'enable_rag', 'native_tools')

    def _settings_snapshot(self) -> dict[str, Any]:
        """当前设置快照（不含任何密钥）"""
        import sys as _sys

        from ..core.settings import get_settings

        settings = get_settings()
        version = 'unknown'
        try:
            from .. import __version__

            version = __version__
        except Exception as exc:  # noqa: BLE001 — 包元数据缺失时回落到 'unknown'
            self.logger.debug(f'读取 __version__ 失败，回落 unknown: {exc}')

        def _flag(name: str, default: str) -> bool:
            return os.environ.get(name, default).lower() in ('1', 'true', 'yes')

        # 运行期覆盖优先（用户在设置面板刚保存的值要立刻可见），否则回落 .env/settings
        try:
            from ..core.config.injector import get_config_injector

            injector = get_config_injector()
            provider = injector.get_runtime_override('llm_provider', None)
            model = injector.get_runtime_override('llm_model', None)
            base_url = injector.get_runtime_override('llm_base_url', None)
        except Exception:
            provider = model = base_url = None

        def _pick(override, attr):
            if override is not None:
                return str(override)
            value = getattr(settings, attr, '') or ''
            # pydantic 枚举转成纯字符串（避免 UI 显示 LLMProviderEnum.OPENAI）
            return str(getattr(value, 'value', value))

        return {
            'version': version,
            'python': _sys.version.split()[0],
            'workdir': str(Path.cwd()),
            'provider': _pick(provider, 'llm_provider'),
            'model': _pick(model, 'llm_model'),
            'base_url': _pick(base_url, 'llm_base_url'),
            'api_key_set': bool(getattr(settings, 'llm_api_key', None)),
            'enable_rag': _flag('CLAWD_ENABLE_RAG', ''),
            'native_tools': _flag('CLAWD_NATIVE_TOOLS', '1'),
            'editable_keys': list(self.UI_SETTABLE_KEYS),
        }

    async def _handle_settings_get(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        _engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        """读取当前设置。

        期望消息格式: {"type": "settings_get"}
        """
        return build_response(message.get('id'), self._settings_snapshot())

    async def _handle_settings_set(
        self,
        ws: ServerProtocol,
        message: dict[str, Any],
        _engine_factory: EngineFactoryProtocol | None = None,
    ) -> dict[str, Any]:
        """更新设置（白名单键 + 持久化到 .clawd/ui_settings.json）。

        期望消息格式: {"type": "settings_set", "settings": {"model": "...", ...}}

        安全:
            - 仅接受白名单键，未知键返回错误（不静默忽略）
            - api_key 不在白名单内（禁止经 WS 传输密钥）
        """
        payload = message.get('settings') or {}
        if not isinstance(payload, dict) or not payload:
            return build_error(
                message.get('id'),
                'E_INVALID_MESSAGE',
                'settings 必须是非空对象',
            )

        unknown = [k for k in payload if k not in self.UI_SETTABLE_KEYS]
        if unknown:
            return build_error(
                message.get('id'),
                'E_INVALID_PARAMETER',
                f'不支持修改的设置项: {unknown}',
                {'editable_keys': list(self.UI_SETTABLE_KEYS)},
            )

        # 逐项应用：进程内生效（环境变量），并落盘以便重启后保持
        persisted: dict[str, Any] = {}
        try:
            for key, value in payload.items():
                if key in ('enable_rag', 'native_tools'):
                    env_name = 'CLAWD_ENABLE_RAG' if key == 'enable_rag' else 'CLAWD_NATIVE_TOOLS'
                    os.environ[env_name] = '1' if value else '0'
                    persisted[key] = bool(value)
                else:
                    env_name = {
                        'provider': 'LLM_PROVIDER',
                        'model': 'LLM_MODEL',
                        'base_url': 'LLM_BASE_URL',
                    }[key]
                    text = str(value or '').strip()
                    if text:
                        os.environ[env_name] = text
                    persisted[key] = text
                    # 同步写入运行期覆盖：否则 UI 显示新值但引擎仍用旧配置（假保存）
                    try:
                        from ..core.config.injector import set_config

                        cfg_key = {
                            'provider': 'llm_provider',
                            'model': 'llm_model',
                            'base_url': 'llm_base_url',
                        }[key]
                        set_config(cfg_key, text)
                    except Exception as exc:
                        self.logger.warning(f'写入运行期配置失败 {key}: {exc}')

            settings_file = Path.cwd() / '.clawd' / 'ui_settings.json'
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            existing: dict[str, Any] = {}
            if settings_file.is_file():
                try:
                    existing = json.loads(settings_file.read_text(encoding='utf-8'))
                except (OSError, json.JSONDecodeError):
                    existing = {}
            existing.update(persisted)
            settings_file.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except Exception as exc:
            return build_error(
                message.get('id'),
                'E_SETTINGS_WRITE_FAILED',
                f'设置应用失败: {exc}',
            )

        self.logger.info(f'设置已更新: {sorted(persisted)}')
        snapshot = self._settings_snapshot()
        snapshot['applied'] = persisted
        snapshot['restart_required'] = any(
            k in persisted for k in ('provider', 'model', 'base_url')
        )
        return build_response(message.get('id'), snapshot)


# ------------------------------------------------------------------
# AgentEngine 工厂协议
# ------------------------------------------------------------------

class EngineFactoryProtocol:
    """AgentEngine 工厂协议接口。"""

    def create(
        self,
        llm_config: Any | None = None,
    ) -> Any:  # returns AgentEngine
        """创建一个 AgentEngine 实例。

        参数:
            llm_config: 可选的 LLM 配置。若为 None，则使用默认配置。
        """
        raise NotImplementedError


# ------------------------------------------------------------------
# 路径安全检查工具
# ------------------------------------------------------------------

def _is_under_base(target: Path, base: Path) -> bool:
    """检查 ``target`` 是否位于 ``base`` 目录之下，防止路径遍历攻击。

    参数:
        target: 解析后的目标路径。
        base: 允许的基础目录。

    返回:
        安全返回 True，否则返回 False。
    """
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False

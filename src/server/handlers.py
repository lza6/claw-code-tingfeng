"""WebSocket 消息处理器模块

负责解析和路由来自客户端的 JSON-RPC 风格消息，
执行对应的业务逻辑（目标执行、状态查询、文件操作等），
并返回标准化的响应或错误消息。
"""
from __future__ import annotations

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
            'status': self._handle_status,
            'file_read': self._handle_file_read,
            'file_write': self._handle_file_write,
            'ping': self._handle_ping,
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
        llm_config_from_msg: LLMConfig | None = message.get('llm_config')  # type: ignore[assignment]
        message.get('max_iterations')

        engine = engine_factory.create(llm_config=llm_config_from_msg)

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

        try:
            start_time = time.time()
            if stream:
                chunks: list[str] = []

                def _on_chunk(text: str) -> None:
                    chunks.append(text)

                session = await engine.run_stream(
                    goal=goal,
                    on_chunk=_on_chunk,
                )
            else:
                session = await engine.run(goal=goal)

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

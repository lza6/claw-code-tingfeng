"""AgentEngine 核心模块 - 定义 AgentEngine 类及核心生命周期
从 engine.py 拆分，保持高内聚低耦合。
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.events import EventBus
from ..core.events import get_event_bus as get_bus
from ..core.patch.atomic_patcher import AtomicPatcher
from ..llm import (
    BaseLLMProvider,
    LLMConfig,
    create_llm_provider,
)
from ..llm.weak_model_router import WeakModelRouter, auto_detect_weak_model
from ..tools_runtime import (
    BashTool,
    FileEditTool,
    FileReadTool,
    GlobTool,
    GrepTool,
    HotFilesTool,
)
from ..utils import debug, get_logger, warn
from ._system_prompt import build_system_prompt
from .engine_events import EventPublisher
from .engine_lifecycle import LifecycleManager
from .engine_metrics import EngineMetrics
from .engine_session import SessionManager
from .engine_stream import StreamExecutor
from .message_truncator import MessageTruncator
from .tool_manager import ToolManager

if TYPE_CHECKING:
    from ..tools_runtime.base import BaseTool
    from .engine_session_data import AgentSession

class AgentEngine:
    """代理循环引擎

    v0.38.0 重构: 使用组合模式替代 Mixin 多重继承
    - EventPublisher: 事件发布
    - LifecycleManager: 生命周期管理
    - StreamExecutor: 流式执行

    v0.61.x 模块化拆分:
    - engine_core.py: 核心类定义
    - engine_loop.py: 统一执行循环 (_run_agent_loop)
    - engine_session_data.py: 数据模型 (AgentSession, AgentStep)
    """

    DEFAULT_MAX_CONTEXT_TOKENS = 8000
    DEFAULT_MAX_MESSAGE_LENGTH = 32000

    def publish_task_started(self, goal: str, max_iterations: int) -> None:
        """[Proxy] 发布任务开始事件"""
        self.events.publish_task_started(goal, max_iterations)

    def publish_task_completed(self, goal: str, result: str, tokens: int, steps: int) -> None:
        """[Proxy] 发布任务完成事件"""
        self.events.publish_task_completed(goal, result, tokens, steps)

    def publish_task_error(self, goal: str, error: str, error_code: str | None, tokens: int) -> None:
        """[Proxy] 发布任务错误事件"""
        self.events.publish_task_error(goal, error, error_code, tokens)
        self.logger = get_logger('agent.engine')
        self.workdir = self.workdir or Path.cwd()

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        workdir: Path | None = None,
        max_iterations: int = 10,
        enable_cost_tracking: bool = True,
        rag_index: Any | None = None,
        world_model: Any | None = None,
        max_repeat_calls: int = 3,
        max_message_length: int = DEFAULT_MAX_MESSAGE_LENGTH,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        enable_events: bool = True,
        event_bus: EventBus | None = None,
        audit_mode: bool = False,
        auditor: Any | None = None,
        max_audit_retries: int = 2,
        max_reflections: int = 3,
        transcript_path: str | None = None,
        metrics_collector: Any | None = None,
        enable_output_compression: bool = True,
        enable_tee_mode: bool = True,
        enable_token_tracking: bool = True,
        developer_mode: bool = False,
        intent: str = "deliver",  # 新增: 意图标识 (deliver/explore/evolve/debate/implement)
    ) -> None:
        self.logger = get_logger('agent.engine')
        self.workdir = workdir or Path.cwd()
        self.intent = intent  # 保存意图

        # Initialize ClawGod-style configuration systems
        self._init_config_systems()

        # 事件发布器
        self._event_publisher = EventPublisher(
            event_bus=event_bus or get_bus(),
            enabled=enable_events
        )

        self.max_iterations = max_iterations
        self.developer_mode = developer_mode
        self.enable_cost_tracking = enable_cost_tracking
        self._shutdown_requested = False
        self._is_running = False
        self._llm_config = llm_config
        self.max_repeat_calls = max_repeat_calls
        self.max_reflections = max_reflections
        self.max_message_length = max_message_length
        self.max_context_tokens = max_context_tokens
        self._encoding: Any = None
        self._init_tokenizer()

        # RTK 集成
        self.enable_output_compression = enable_output_compression
        self.enable_tee_mode = enable_tee_mode
        self.enable_token_tracking = enable_token_tracking

        self.audit_mode = audit_mode
        self.auditor = auditor
        self.max_audit_retries = max_audit_retries
        self._audit_retry_count = 0

        # 初始化 LLM Provider 和相关的辅助组件
        self._init_llm_provider(llm_config)

        # Session & Persistence
        self.session_manager = SessionManager(
            workdir=self.workdir,
            transcript_path=transcript_path
        )
        self.transcript = self.session_manager.transcript

        # RecencyTracker
        self._init_recency_tracker()

        # 工具池
        self.tools: dict[str, BaseTool] = {
            'BashTool': BashTool(
                workdir=self.workdir,
                compress_output=self.enable_output_compression,
                tee_mode=self.enable_tee_mode,
                track_tokens=self.enable_token_tracking,
                bypass_security=self.developer_mode,
            ),
            'FileReadTool': FileReadTool(base_path=self.workdir),
            'FileEditTool': FileEditTool(base_path=self.workdir),
            'GlobTool': GlobTool(base_path=self.workdir),
            'GrepTool': GrepTool(base_path=self.workdir),
            'HotFilesTool': HotFilesTool(tracker=self.recency_tracker),
        }
        self.system_prompt = build_system_prompt(self.tools, developer_mode=self.developer_mode)

        # 原子补丁引擎
        self.patcher = AtomicPatcher(base_path=self.workdir)

        # 性能指标统计
        self.metrics = EngineMetrics(collector=metrics_collector)
        self._perf_metrics = self.metrics._perf_metrics
        self._metrics_lock = self.metrics._lock
        self._metrics_collector = metrics_collector

        # 编辑格式
        self.edit_format = "editblock"
        self._edit_format_switcher = None
        self._init_edit_format()

        # 初始化核心组件 (EventPublisher, LifecycleManager, etc.)
        self._init_components(rag_index=rag_index, world_model=world_model, enable_events=enable_events, event_bus=event_bus)

    def _init_config_systems(self) -> None:
        """初始化配置系统"""
        try:
            from ..utils.provider_manager import provider_manager
            provider_manager.initialize(workdir=self.workdir)
        except Exception:
            pass
        try:
            from ..utils.features import features
            features.initialize(workdir=self.workdir)
        except Exception:
            pass

    def _init_llm_provider(self, llm_config: LLMConfig | None) -> None:
        """初始化 LLM 提供商和弱模型路由"""
        if not llm_config:
            self.llm_provider = None
            self._truncator = MessageTruncator(
                max_context_tokens=self.max_context_tokens,
                encoding=self._encoding,
            )
            return

        self.llm_provider = create_llm_provider(llm_config)
        self._init_weak_model(llm_config)

        # 注入 LLM Provider 以支持智能总结
        self._truncator = MessageTruncator(
            max_context_tokens=self.max_context_tokens,
            encoding=self._encoding,
            llm_provider=self.llm_provider,
        )

    def _init_weak_model(self, llm_config: LLMConfig) -> None:
        """初始化弱模型路由器"""
        self._weak_model_router = None
        try:
            from ..core.settings import get_settings
            settings = get_settings()
            weak_model_name = settings.weak_model or auto_detect_weak_model(llm_config.model or '')

            weak_config = LLMConfig(
                provider=llm_config.provider,
                api_key=llm_config.api_key,
                base_url=llm_config.base_url,
                api_path_suffix=llm_config.api_path_suffix,
                model=weak_model_name,
                max_tokens=1024,
                temperature=0.3,
                timeout=llm_config.timeout,
                max_retries=3,
            )
            self._weak_model_router = WeakModelRouter(
                main_provider=self.llm_provider,
                weak_provider=create_llm_provider(weak_config),
                main_model_name=llm_config.model or '',
                weak_model_name=weak_model_name,
            )
        except Exception as e:
            self.logger.warning(f'弱模型初始化失败: {e}')

    def _init_recency_tracker(self) -> None:
        """初始化 RecencyTracker"""
        from ..utils.recency import RecencyTracker
        self.recency_tracker = RecencyTracker(root_dir=self.workdir)
        try:
            import threading
            threading.Thread(
                target=lambda: self.recency_tracker.scan(),
                daemon=True,
                name='recency-scan'
            ).start()
        except Exception as e:
            warn(f'RecencyTracker 扫描启动失败: {e}')

    def _init_edit_format(self) -> None:
        """初始化编辑格式系统"""
        try:
            from ..tools_runtime.edit_format_switcher import get_edit_format_switcher
            self._edit_format_switcher = get_edit_format_switcher(self.edit_format)
            if self._llm_config and self._llm_config.model:
                from ..llm.model_manager import get_model_manager
                self.edit_format = get_model_manager().get_edit_format(self._llm_config.model)
                self._edit_format_switcher.set_format(self.edit_format)
        except Exception:
            pass

    def _init_components(self, rag_index: Any, world_model: Any, enable_events: bool, event_bus: EventBus | None) -> None:
        """初始化辅助组件"""
        self.tool_manager = ToolManager(self.tools)
        self.rag_index = rag_index
        self.world_model = world_model
        self.enable_events = enable_events
        self._event_bus = event_bus or get_bus()

        if not self.world_model and self.workdir:
            self._init_world_model_async()

        # 缺少信息错误模式
        self._missing_info_patterns = [
            'file not found', 'no such file', 'not found',
            'undefined', 'not defined', 'no module',
            'missing', 'cannot find', 'unknown',
            '没有这个文件', '找不到', '未找到',
            '缺少', '不存在', '未定义',
        ]

        # 组合模式组件
        self._event_publisher = EventPublisher(event_bus=self._event_bus, enabled=self.enable_events)
        self._lifecycle = LifecycleManager(
            event_bus=self._event_bus,
            events_enabled=self.enable_events,
            shutdown_getter=lambda: self._shutdown_requested,
            shutdown_setter=lambda v: setattr(self, '_shutdown_requested', v),
            shutdown_reason_setter=lambda v: setattr(self, '_shutdown_reason', v),
            shutdown_time_setter=lambda v: setattr(self, '_shutdown_time', v),
            is_running_setter=lambda v: setattr(self, '_is_running', v),
            tools_clear=lambda: self.tools.clear(),
            cost_estimator_reset=lambda: self._cost_estimator.reset() if hasattr(self, '_cost_estimator') and self._cost_estimator else None,
        )
        self._stream_executor = StreamExecutor(llm_provider=self.llm_provider, run_coroutine=self.run)
        self._lifecycle.register_signal_handlers()

        # 自愈引擎
        from ..self_healing.engine import SelfHealingEngine
        self.healing_engine = SelfHealingEngine(workdir=self.workdir, llm_config=self._llm_config, event_bus=self._event_bus)

        if self.enable_cost_tracking:
            from ..core.cost_estimator import CostEstimator
            self._cost_estimator = CostEstimator()

    def _init_world_model_async(self) -> None:
        """异步初始化 WorldModel"""
        try:
            from ..brain import RepositoryWorldModel
            from ..rag import TextIndexer
            ti = self.rag_index if isinstance(self.rag_index, TextIndexer) else None
            self.world_model = RepositoryWorldModel(root_dir=self.workdir, text_indexer=ti)

            import asyncio
            import threading
            def _bg():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.world_model.initialize())
            threading.Thread(target=_bg, daemon=True, name='world-model-init').start()
        except Exception as e:
            debug(f'WorldModel 初始化失败: {e}')

    def _init_tokenizer(self) -> None:
        """初始化 tokenizer"""
        try:
            import tiktoken
            model = self._llm_config.model if self._llm_config else ''
            try:
                self._encoding = tiktoken.encoding_for_model(model)
            except KeyError:
                self._encoding = tiktoken.get_encoding('cl100k_base')
        except ImportError:
            pass

    # --- 代理方法保持向后兼容 ---

    @property
    def is_running(self) -> bool:
        return self._is_running

    def set_llm_provider(self, provider: BaseLLMProvider) -> None:
        self.llm_provider = provider
        self.system_prompt = build_system_prompt(self.tools)

    def add_tool(self, name: str, tool: BaseTool) -> None:
        self.tool_manager.add_tool(name, tool)
        self.system_prompt = build_system_prompt(self.tools)

    def remove_tool(self, name: str) -> None:
        self.tool_manager.remove_tool(name)
        self.system_prompt = build_system_prompt(self.tools)

    async def run(self, goal: str, on_step: Callable | None = None) -> AgentSession:
        result = await self._run_agent_core(goal=goal, is_stream=False, on_step=on_step)
        return result['session']

    async def run_stream(self, goal: str, on_chunk: Callable | None = None, on_step: Callable | None = None) -> AgentSession:
        result = await self._run_agent_core(goal=goal, is_stream=True, on_chunk=on_chunk, on_step=on_step)
        return result['session']

    async def _run_agent_core(self, goal: str, **kwargs) -> dict[str, Any]:
        """统一入口，调用 engine_loop 中的 _run_agent_loop"""
        from .engine_loop import AgentLoopConfig, _run_agent_loop
        from .engine_session_data import AgentSession

        self.session_manager.record_user_goal(goal)
        session = AgentSession(goal=goal)

        config = AgentLoopConfig(
            goal=goal,
            llm_provider=self.llm_provider,
            messages=[],
            max_iterations=self.max_iterations,
            system_prompt=self.system_prompt,
            tools=self.tools,
            rag_index=self.rag_index,
            world_model=self.world_model,
            _llm_config=self._llm_config,
            enable_cost_tracking=self.enable_cost_tracking,
            _cost_estimator=getattr(self, '_cost_estimator', None),
            _perf_metrics=self._perf_metrics,
            _metrics_lock=self._metrics_lock,
            _truncator=self._truncator,
            _parse_tool_calls=self.tool_manager.parse_tool_calls,
            _execute_tool=self.tool_manager.execute_tool,
            _count_tokens=self._truncator.count_tokens,
            _missing_info_patterns=self._missing_info_patterns,
            _deep_rag_patch=self._deep_rag_patch,
            max_repeat_calls=self.max_repeat_calls,
            auditor=self.auditor,
            audit_mode=self.audit_mode,
            max_audit_retries=self.max_audit_retries,
            max_reflections=self.max_reflections,
            session=session,
            publish_llm_started=self._event_publisher.publish_llm_call_started,
            publish_llm_completed=self._event_publisher.publish_llm_call_completed,
            publish_tool_started=self._event_publisher.publish_tool_exec_started,
            publish_tool_completed=self._event_publisher.publish_tool_exec_completed,
            publish_task_started=self._event_publisher.publish_task_started,
            publish_task_completed=self._event_publisher.publish_task_completed,
            publish_task_error=self._event_publisher.publish_task_error,
            publish_token_and_cost=self._event_publisher.publish_token_and_cost_update,
            _metrics_collector=self._metrics_collector,
            patcher=self.patcher,
            healing_engine=self.healing_engine,
            **kwargs
        )

        result = await _run_agent_loop(config=config)
        self.session_manager.record_assistant_result(result['session'])
        return result

    async def _deep_rag_patch(self, messages: list[dict[str, Any]]) -> str | None:
        from .engine_rag import deep_rag_patch as _patch
        return await _patch(self.rag_index, messages)

    def get_available_tools(self) -> dict[str, str]:
        return self.tool_manager.get_available_tools()

    def get_cost_report(self) -> str | None:
        return self._cost_estimator.get_report() if self.enable_cost_tracking and hasattr(self, '_cost_estimator') else None

    def get_perf_metrics(self) -> dict[str, Any]:
        return self.metrics.get_metrics_copy()

    def get_perf_summary(self) -> str:
        return self.metrics.get_summary()

    @property
    def events(self) -> EventPublisher:
        return self._event_publisher

    async def graceful_shutdown(self, timeout: float = 5.0) -> None:
        await self._lifecycle.shutdown(timeout)

    def is_shutting_down(self) -> bool:
        return self._lifecycle.is_shutting_down()

    async def generate_commit_message(self, diff_text: str) -> str:
        if self._weak_model_router:
            return await self._weak_model_router.generate_commit_message(diff_text)
        return f'update: {diff_text[:50]}...'

    def save_checkpoint(self, **kwargs) -> Path:
        return self.session_manager.save_checkpoint(
            max_iterations=self.max_iterations,
            model=self._llm_config.model if self._llm_config else '',
            **kwargs
        )

    def load_checkpoint(self, path: str | Path) -> dict[str, Any]:
        return self.session_manager.load_checkpoint(path)

    def get_cost_summary(self) -> dict[str, Any] | None:
        """获取成本摘要"""
        if self.enable_cost_tracking and hasattr(self, '_cost_estimator'):
            return self._cost_estimator.get_summary()
        return None

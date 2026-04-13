"""事件总线模块 - 事件驱动架构核心

提供发布/订阅模式的事件总线，支持同步和异步事件处理。
用于解耦组件间通信，替代直接的信号/回调依赖。

增强功能 (v0.15.0):
- 事件节流 (throttle): 限制某事件类型的发布频率
- 事件采样 (sample): 每 N 个事件只发布 1 个
- 背压控制: 事件队列满时丢弃最旧事件
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(Enum):
    """事件类型枚举

    增强功能 (v0.19.0):
    - 添加 GUI 事件类型
    - 添加 CLI 事件类型
    - 添加 Session 事件类型
    - 添加 RAG 事件类型
    - 添加 Server 事件类型
    """
    # ============================================
    # 代理引擎事件
    # ============================================
    AGENT_TASK_STARTED = 'agent.task_started'  # 新增
    AGENT_TASK_COMPLETED = 'agent.task_completed'
    AGENT_TASK_ERROR = 'agent.task_error'
    AGENT_STEP_STARTED = 'agent.step_started'
    AGENT_STEP_COMPLETED = 'agent.step_completed'
    AGENT_LLM_CALL_STARTED = 'agent.llm_call_started'  # 新增
    AGENT_LLM_CALL_COMPLETED = 'agent.llm_call_completed'  # 新增
    AGENT_TOKEN_USAGE = 'agent.token_usage'
    AGENT_COST_UPDATE = 'agent.cost_update'
    AGENT_STREAM_STARTED = 'agent.stream_started'
    AGENT_STREAM_COMPLETED = 'agent.stream_completed'
    AGENT_SHUTDOWN_REQUESTED = 'agent.shutdown_requested'
    AGENT_SHUTDOWN_COMPLETED = 'agent.shutdown_completed'
    AGENT_TOOL_CALL_STARTED = 'agent.tool_call_started'
    AGENT_TOOL_CALL_COMPLETED = 'agent.tool_call_completed'

    # ============================================
    # LLM 事件
    # ============================================
    LLM_CALL_STARTED = 'llm.call_started'
    LLM_CALL_COMPLETED = 'llm.call_completed'
    LLM_CALL_ERROR = 'llm.call_error'
    LLM_STREAM_CHUNK = 'llm.stream_chunk'
    LLM_STREAM_STARTED = 'llm.stream_started'
    LLM_STREAM_COMPLETED = 'llm.stream_completed'
    LLM_RATE_LIMITED = 'llm.rate_limited'

    # ============================================
    # 工具事件
    # ============================================
    AGENT_TOOL_EXEC_STARTED = 'agent.tool_exec_started'  # 新增
    AGENT_TOOL_EXEC_COMPLETED = 'agent.tool_exec_completed'  # 新增
    AGENT_TOOL_EXEC_ERROR = 'agent.tool_exec_error'  # 新增
    TOOL_EXEC_STARTED = 'tool.exec_started'
    TOOL_EXEC_COMPLETED = 'tool.exec_completed'
    TOOL_EXEC_ERROR = 'tool.exec_error'

    # ============================================
    # GUI 事件 (v0.19.0 新增)
    # ============================================
    GUI_WINDOW_READY = 'gui.window_ready'
    GUI_THEME_CHANGED = 'gui.theme_changed'
    GUI_SETTINGS_UPDATED = 'gui.settings_updated'
    GUI_MESSAGE_SENT = 'gui.message_sent'
    GUI_MESSAGE_RECEIVED = 'gui.message_received'
    GUI_CONTEXT_PANEL_UPDATE = 'gui.context_panel_update'
    GUI_TERMINAL_OUTPUT = 'gui.terminal_output'
    GUI_FILE_OPENED = 'gui.file_opened'
    GUI_WORKDIR_CHANGED = 'gui.workdir_changed'

    # ============================================
    # CLI 事件 (v0.19.0 新增)
    # ============================================
    CLI_COMMAND_STARTED = 'cli.command_started'
    CLI_COMMAND_COMPLETED = 'cli.command_completed'
    CLI_COMMAND_ERROR = 'cli.command_error'
    CLI_OUTPUT_CHUNK = 'cli.output_chunk'

    # ============================================
    # Session 事件 (v0.19.0 新增)
    # ============================================
    SESSION_CREATED = 'session.created'
    SESSION_LOADED = 'session.loaded'
    SESSION_SAVED = 'session.saved'
    SESSION_CLOSED = 'session.closed'
    SESSION_FLUSHED = 'session.flushed'
    SESSION_COMPRESSED = 'session.compressed'

    # ============================================
    # RAG 事件 (v0.19.0 新增)
    # ============================================
    RAG_INDEX_CREATED = 'rag.index_created'
    RAG_INDEX_UPDATED = 'rag.index_updated'
    RAG_SEARCH_STARTED = 'rag.search_started'
    RAG_SEARCH_COMPLETED = 'rag.search_completed'

    # ============================================
    # Server 事件 (v0.19.0 新增)
    # ============================================
    SERVER_STARTED = 'server.started'
    SERVER_STOPPED = 'server.stopped'
    SERVER_CLIENT_CONNECTED = 'server.client_connected'
    SERVER_CLIENT_DISCONNECTED = 'server.client_disconnected'
    SERVER_AUTH_SUCCESS = 'server.auth_success'
    SERVER_AUTH_FAILURE = 'server.auth_failure'
    SERVER_HEALTH_CHECK = 'server.health_check'

    # ============================================
    # 系统事件
    # ============================================
    SYSTEM_SHUTDOWN = 'system.shutdown'
    SYSTEM_CONFIG_CHANGED = 'system.config_changed'
    SYSTEM_STARTUP = 'system.startup'

    # ============================================
    # Workflow 工作流引擎事件
    # ============================================
    WORKFLOW_STARTED = 'workflow.started'
    WORKFLOW_PHASE_STARTED = 'workflow.phase_started'
    WORKFLOW_PHASE_COMPLETED = 'workflow.phase_completed'
    WORKFLOW_TASK_STARTED = 'workflow.task_started'
    WORKFLOW_TASK_COMPLETED = 'workflow.task_completed'
    WORKFLOW_HOTFIX_ENABLED = 'workflow.hotfix_enabled'
    WORKFLOW_HOTFIX_DISABLED = 'workflow.hotfix_disabled'
    WORKFLOW_VERSION_BUMPED = 'workflow.version_bumped'
    WORKFLOW_TECH_DEBT_RECORDED = 'workflow.tech_debt_recorded'
    WORKFLOW_COMPLETED = 'workflow.completed'
    WORKFLOW_ERROR = 'workflow.error'
    WORKFLOW_ITERATION_LOOP = 'workflow.iteration_loop'
    WORKFLOW_TASK_ERROR = 'workflow.task_error'
    WORKFLOW_HEAL_STARTED = 'workflow.heal_started'
    WORKFLOW_HEAL_COMPLETED = 'workflow.heal_completed'
    WORKFLOW_HEAL_FAILED = 'workflow.heal_failed'
    WORKFLOW_INTERVENTION = 'workflow.intervention'

    # ============================================
    # 自愈事件
    # ============================================
    HEALING_EVENT = 'healing.event'
    HEALING_STATS_UPDATE = 'healing.stats_update'

    # ============================================
    # 预算与成本事件 (v0.52.0 新增)
    # ============================================
    COST_RECORDED = 'budget.cost_recorded'
    BUDGET_EXHAUSTED = 'budget.exhausted'


@dataclass(frozen=True)
class Event:
    """不可变事件对象"""
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ''  # 事件来源标识
    timestamp: float = 0.0  # 时间戳（由发布者设置）


# 事件处理器类型
SyncHandler = Callable[[Event], None]
AsyncHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """事件总线 - 发布/订阅模式

    功能:
    - 支持同步和异步事件处理器
    - 支持事件过滤（按类型订阅）
    - 支持一次性订阅（subscribe_once）
    - 线程安全（threading.Lock 保护共享状态）
    - 背压控制：节流/采样/自动清理/溢出检测

    使用示例:
        bus = EventBus()

        # 订阅事件
        @bus.on(EventType.AGENT_STEP_COMPLETED)
        def on_step(event: Event):
            print(f'步骤完成: {event.data}')

        # 发布事件
        bus.publish(Event(
            type=EventType.AGENT_STEP_COMPLETED,
            data={'step': 'execute', 'result': 'success'},
            source='agent_engine',
        ))
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        auto_cleanup: bool = True,
        cleanup_threshold: int | None = None,
        cleanup_target: int | None = None,
    ) -> None:
        self._sync_handlers: dict[EventType, list[SyncHandler]] = defaultdict(list)
        self._async_handlers: dict[EventType, list[AsyncHandler]] = defaultdict(list)
        self._once_handlers: dict[EventType, list[SyncHandler]] = defaultdict(list)

        # 线程安全锁
        self._lock = threading.Lock()

        # 背压控制
        self._max_queue_size = max_queue_size
        self._event_queue: deque[Event] = deque(maxlen=max_queue_size)

        # 自动清理配置 (v0.18.0 新增)
        # cleanup_threshold 默认为 max_queue_size 的 80%，确保不会超过 deque maxlen
        self._auto_cleanup = auto_cleanup
        self._cleanup_threshold = cleanup_threshold if cleanup_threshold is not None else int(max_queue_size * 0.8)
        self._cleanup_target = cleanup_target if cleanup_target is not None else int(max_queue_size * 0.5)

        # 溢出计数器：deque maxlen 满时静默丢弃的事件数
        self._total_dropped = 0

        # 节流控制: event_type -> (last_timestamp, min_interval_seconds)
        self._throttle_config: dict[EventType, float] = {}
        self._throttle_state: dict[EventType, float] = {}

        # 采样控制: event_type -> sample_rate (每 N 个发布 1 个)
        self._sample_config: dict[EventType, int] = {}
        self._sample_counters: dict[EventType, int] = defaultdict(int)

        # 统计信息
        self._total_published = 0
        self._total_throttled = 0
        self._total_sampled = 0
        self._total_cleaned = 0  # 清理的事件数

    def on(self, event_type: EventType) -> Callable[[SyncHandler], SyncHandler]:
        """装饰器：订阅事件（持久订阅）

        用法:
            @bus.on(EventType.AGENT_STEP_COMPLETED)
            def handler(event: Event):
                ...
        """
        def decorator(handler: SyncHandler) -> SyncHandler:
            self.subscribe(event_type, handler)
            return handler
        return decorator

    def on_async(self, event_type: EventType) -> Callable[[AsyncHandler], AsyncHandler]:
        """装饰器：订阅异步事件"""
        def decorator(handler: AsyncHandler) -> AsyncHandler:
            self.subscribe_async(event_type, handler)
            return handler
        return decorator

    def subscribe(self, event_type: EventType, handler: SyncHandler) -> None:
        """订阅同步事件"""
        with self._lock:
            self._sync_handlers[event_type].append(handler)

    def subscribe_async(self, event_type: EventType, handler: AsyncHandler) -> None:
        """订阅异步事件"""
        with self._lock:
            self._async_handlers[event_type].append(handler)

    def subscribe_once(self, event_type: EventType, handler: SyncHandler) -> None:
        """订阅一次性事件（触发后自动取消订阅）"""
        with self._lock:
            self._once_handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: SyncHandler | AsyncHandler) -> None:
        """取消订阅"""
        with self._lock:
            if handler in self._sync_handlers[event_type]:
                self._sync_handlers[event_type].remove(handler)
            if handler in self._async_handlers[event_type]:
                self._async_handlers[event_type].remove(handler)
            if handler in self._once_handlers[event_type]:
                self._once_handlers[event_type].remove(handler)

    def _prepare_event(self, event: Event) -> Event | None:
        """事件预处理：节流/采样/清理/入队

        返回带时间戳的新 Event，如果被节流/采样则返回 None。
        使用锁保护共享状态。
        """
        with self._lock:
            return self._prepare_event_unlocked(event)

    def _prepare_event_unlocked(self, event: Event) -> Event | None:
        """_prepare_event 的无锁内部实现"""
        if self._should_throttle(event.type):
            self._total_throttled += 1
            return None
        if self._should_sample(event.type):
            self._total_sampled += 1
            return None

        event = Event(
            type=event.type,
            data=event.data,
            source=event.source,
            timestamp=time.time(),
        )

        if self._auto_cleanup and len(self._event_queue) >= self._cleanup_threshold:
            self._auto_cleanup_events()

        # 检测 deque maxlen 溢出：append 前记录大小，append 后比较
        queue_size_before = len(self._event_queue)
        self._event_queue.append(event)
        if len(self._event_queue) == queue_size_before and queue_size_before == self._max_queue_size:
            # deque 已满，最旧事件被静默丢弃
            self._total_dropped += 1

        self._total_published += 1
        return event

    def _dispatch_sync(self, event: Event) -> None:
        """调用同步处理器和一次性处理器"""
        import logging
        logger = logging.getLogger('eventbus')

        # 快照同步处理器列表（锁保护）
        with self._lock:
            sync_handlers = list(self._sync_handlers[event.type])
            once_handlers = list(self._once_handlers[event.type])
            self._once_handlers[event.type].clear()

        for handler in sync_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f'同步事件处理器异常: {e}')

        for handler in once_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f'一次性事件处理器异常: {e}')

    def publish(self, event: Event) -> None:
        """发布事件（同步）

        按顺序调用所有同步处理器和一次性处理器。
        异步处理器需要通过 publish_async 处理。

        背压控制:
        - 节流: 如果配置了节流间隔，跳过频率过高的事件
        - 采样: 如果配置了采样率，只发布每第 N 个事件
        - 队列: 事件被记录到环形缓冲区，溢出时丢弃最旧事件
        - 自动清理: 队列超过阈值时自动清理旧事件（v0.18.0 新增）
        """
        event = self._prepare_event(event)
        if event is None:
            return
        self._dispatch_sync(event)

    async def publish_async(self, event: Event) -> None:
        """发布事件（同步 + 异步）

        复用 _prepare_event 进行背压控制，然后调用同步+异步处理器。
        """
        event = self._prepare_event(event)
        if event is None:
            return

        self._dispatch_sync(event)

        # 异步处理器（快照列表，锁保护）
        with self._lock:
            async_handlers = list(self._async_handlers[event.type])
        for handler in async_handlers:
            try:
                await handler(event)
            except Exception as e:
                logging.getLogger('eventbus').error(f'异步事件处理器异常: {e}')

    def clear(self) -> None:
        """清除所有订阅和事件队列"""
        with self._lock:
            self._sync_handlers.clear()
            self._async_handlers.clear()
            self._once_handlers.clear()
            self._event_queue.clear()
            self._sample_counters.clear()
            self._throttle_state.clear()
            self._total_dropped = 0

    # ==================== 背压控制 ====================

    def set_throttle(self, event_type: EventType, min_interval: float) -> None:
        """设置事件节流间隔（秒）

        同一事件类型在 min_interval 秒内只发布一次。
        适用于高频事件（如 token 用量更新、成本更新）。

        参数:
            event_type: 事件类型
            min_interval: 最小发布间隔（秒）
        """
        self._throttle_config[event_type] = min_interval

    def set_sample(self, event_type: EventType, sample_rate: int) -> None:
        """设置事件采样率

        每 sample_rate 个事件只发布 1 个。
        例如 sample_rate=10 表示每 10 个事件发布 1 个。

        参数:
            event_type: 事件类型
            sample_rate: 采样率（>= 1）
        """
        if sample_rate < 1:
            raise ValueError('采样率必须 >= 1')
        self._sample_config[event_type] = sample_rate

    def get_stats(self) -> dict[str, Any]:
        """获取事件总线统计信息

        新增 (v0.18.0):
        - total_cleaned: 已清理的事件数
        - estimated_memory_bytes: 估算内存占用（字节）
        - auto_cleanup_enabled: 是否启用自动清理
        """
        return {
            'total_published': self._total_published,
            'total_throttled': self._total_throttled,
            'total_sampled': self._total_sampled,
            'total_cleaned': self._total_cleaned,
            'total_dropped': self._total_dropped,
            'queue_size': len(self._event_queue),
            'max_queue_size': self._max_queue_size,
            'queue_usage_percent': round(len(self._event_queue) / max(self._max_queue_size, 1) * 100, 1),
            'estimated_memory_bytes': self._estimate_memory_usage(),
            'auto_cleanup_enabled': self._auto_cleanup,
            'cleanup_threshold': self._cleanup_threshold,
            'throttle_config': {e.value: v for e, v in self._throttle_config.items()},
            'sample_config': {e.value: v for e, v in self._sample_config.items()},
        }

    def get_recent_events(self, count: int = 10) -> list[Event]:
        """获取最近的事件（从环形缓冲区）"""
        return list(self._event_queue)[-count:]

    def _should_throttle(self, event_type: EventType) -> bool:
        """检查是否应该节流"""
        if event_type not in self._throttle_config:
            return False

        min_interval = self._throttle_config[event_type]
        now = time.time()
        last_time = self._throttle_state.get(event_type, 0)

        if now - last_time < min_interval:
            return True

        self._throttle_state[event_type] = now
        return False

    def _should_sample(self, event_type: EventType) -> bool:
        """检查是否应该采样跳过"""
        if event_type not in self._sample_config:
            return False

        sample_rate = self._sample_config[event_type]
        self._sample_counters[event_type] += 1

        # 每 sample_rate 个事件发布一次
        return self._sample_counters[event_type] % sample_rate != 0

    def handler_count(self, event_type: EventType) -> int:
        """获取某事件类型的处理器数量"""
        return (
            len(self._sync_handlers[event_type]) +
            len(self._async_handlers[event_type]) +
            len(self._once_handlers[event_type])
        )

    # ==================== 内存管理 (v0.18.0 新增) ====================

    def _auto_cleanup_events(self) -> None:
        """自动清理旧事件

        当事件队列超过 cleanup_threshold 时触发，
        保留最近的 cleanup_target 个事件，清除其余旧事件。
        """
        current_size = len(self._event_queue)
        if current_size <= self._cleanup_threshold:
            return

        # 转换为列表以便操作
        events_list = list(self._event_queue)
        # 保留最近的事件
        events_to_keep = events_list[-self._cleanup_target:]
        # 清除并重新添加
        self._event_queue.clear()
        for event in events_to_keep:
            self._event_queue.append(event)

        cleaned_count = current_size - len(events_to_keep)
        self._total_cleaned += cleaned_count

    def _estimate_memory_usage(self) -> int:
        """估算事件队列内存占用（字节）

        估算方法:
        - 每个 Event 对象约 200 字节基础开销
        - data 字典平均约 100 字节
        - 总计约 300 字节/事件
        """
        estimated_per_event = 300  # 字节
        return len(self._event_queue) * estimated_per_event

    def clear_events(self) -> int:
        """清空事件队列

        返回:
            清空的事件数量
        """
        count = len(self._event_queue)
        self._event_queue.clear()
        self._total_cleaned += count
        return count

    def set_auto_cleanup(self, enabled: bool, threshold: int = 5000, target: int = 2000) -> None:
        """配置自动清理策略

        参数:
            enabled: 是否启用自动清理
            threshold: 触发清理的队列大小
            target: 清理后保留的事件数
        """
        self._auto_cleanup = enabled
        self._cleanup_threshold = threshold
        self._cleanup_target = target


# 全局事件总线实例
_global_bus: EventBus | None = None
_global_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """获取全局事件总线（线程安全单例）"""
    global _global_bus
    if _global_bus is None:
        with _global_bus_lock:
            if _global_bus is None:
                _global_bus = EventBus()
    return _global_bus


def reset_event_bus() -> None:
    """重置全局事件总线（主要用于测试）"""
    global _global_bus
    with _global_bus_lock:
        if _global_bus:
            _global_bus.clear()
            _global_bus = None

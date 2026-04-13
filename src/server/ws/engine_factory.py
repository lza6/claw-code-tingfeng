"""AgentEngine 实例工厂"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...agent.engine import AgentEngine
from ...core.events import EventBus
from ...llm import LLMConfig
from ...utils import get_logger
from ..handlers import EngineFactoryProtocol

logger = logging.getLogger('server.ws.engine_factory')


class EngineFactory(EngineFactoryProtocol):
    """按需创建 AgentEngine 实例的工厂。

    每个会话拥有独立的 AgentEngine，避免共享状态导致的竞态条件。
    """

    def __init__(
        self,
        default_llm_config: LLMConfig | None = None,
        workdir: Path | None = None,
        max_iterations: int = 10,
        developer_mode: bool = False,
        enable_events: bool = True,
        event_bus: EventBus | None = None,
        enable_cost_tracking: bool = True,
    ) -> None:
        self.default_llm_config = default_llm_config
        self.workdir = workdir or Path.cwd()
        self.max_iterations = max_iterations
        self.developer_mode = developer_mode
        self.enable_events = enable_events
        self.event_bus = event_bus
        self.enable_cost_tracking = enable_cost_tracking
        self._logger = get_logger('server.engine_factory')

    def create(
        self,
        llm_config: LLMConfig | None = None,
    ) -> AgentEngine:
        """创建一个新的 AgentEngine 实例。

        参数:
            llm_config: 可选的 LLM 配置。若 None 则使用默认配置。

        返回:
            配置好的 AgentEngine 实例。
        """
        effective_config = llm_config or self.default_llm_config

        engine_args: dict[str, Any] = {
            'workdir': self.workdir,
            'max_iterations': self.max_iterations,
            'enable_cost_tracking': self.enable_cost_tracking,
            'enable_events': self.enable_events,
            'developer_mode': self.developer_mode,
        }

        if self.event_bus is not None:
            engine_args['event_bus'] = self.event_bus

        if effective_config:
            engine_args['llm_config'] = effective_config

        engine = AgentEngine(**engine_args)
        self._logger.debug(
            '已创建新的 AgentEngine 实例',
            provider=effective_config.provider.value if effective_config else 'default',
        )
        return engine

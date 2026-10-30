"""AgentEngine 核心模块 - 定义 AgentEngine 类及核心生命周期
从 engine.py 拆分，保持高内聚低耦合。
"""
from __future__ import annotations

import time
import os
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
    SkillTool,
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

def _session_dir() -> Path:
    """会话落盘目录（跟随数据目录；桌面端在 userData 下，升级不丢）"""
    try:
        from ..core.data_dir import data_path

        return data_path('sessions', create_dir=True)
    except Exception:  # noqa: BLE001
        return Path.cwd() / '.clawd' / 'sessions'



def _normalize_prior_messages(raw: Any) -> list[Any] | None:
    """把 {role, content} 字典或已是 LLMMessage 的列表统一成 LLMMessage 列表

    会话存储里是字典（便于 JSON 持久化），循环里要 LLMMessage，这里做转换。
    无效项直接跳过（不因为一条脏历史炸掉整轮续跑）。
    """
    if not raw:
        return None
    from ..llm.config import LLMMessage

    out = []
    for item in raw:
        if item is None:
            continue
        if hasattr(item, 'role') and hasattr(item, 'content'):
            out.append(item)
            continue
        if isinstance(item, dict):
            role = str(item.get('role') or 'user')
            if role not in ('system', 'user', 'assistant', 'tool'):
                role = 'user'  # 旧格式的 'unknown' 等一律按用户输入对待
            content = str(item.get('content') or '')
            if not content:
                continue
            out.append(LLMMessage(role=role, content=content))
    return out or None


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
            'SkillTool': SkillTool(workdir=self.workdir),
        }
        from .skill_loader import discover_skills

        self.skills = discover_skills(self.workdir)
        self.system_prompt = build_system_prompt(
            self.tools,
            developer_mode=self.developer_mode,
            skills=self.skills,
        )
        # 异步装配扩展工具（MCP 桥接 + 逆向工具），不阻断引擎启动
        self._extended_tools_loaded = False

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

    async def _load_extended_tools(self) -> None:
        """惰性装配扩展工具池：逆向原生工具 + 外部 MCP server 桥接

        失败降级：单个来源失败只告警，不阻断 agent 启动。
        幂等：重复调用无副作用。
        """
        if self._extended_tools_loaded:
            return
        self._extended_tools_loaded = True

        # 0. 领域原生工具（世界模型 / 项目图谱）+ 世界模型后台自动预热
        #    注意：我们自己的 agent 走原生调用，不绕 MCP（MCP 只用于外部引擎跨进程对接）
        try:
            from ..brain.warmup import ensure_warm
            from ..tools_runtime.domain_tools import get_domain_tools
            from ..tools_runtime.lsp_tool import get_lsp_tool
            from ..tools_runtime.notebook_tool import get_notebook_tool

            count_before = len(self.tools)
            for tool in get_domain_tools(self.workdir):
                self.tools[tool.name] = tool
            # LSP 代码智能（懒启动：首次调用才拉语言服务器）
            lsp_tool = get_lsp_tool(self.workdir)
            self.tools[lsp_tool.name] = lsp_tool
            # 会话笔记本（长会话持久记忆）
            notebook_tool = get_notebook_tool(self.workdir)
            self.tools[notebook_tool.name] = notebook_tool
            self.logger.info(f"领域工具已装配: {len(self.tools) - count_before} 个")

            # 后台预热：非阻塞；索引在小仓库上秒级就绪，大仓库期间工具会如实返回 indexing
            ensure_warm(self.workdir)
        except Exception as e:
            self.logger.warning(f"领域工具装配失败（降级运行）: {e}")

        # 1. 逆向原生工具（纯本地，无外部依赖）
        try:
            from ..reverse_tools import get_all_tools

            count_before = len(self.tools)
            for tool_def in get_all_tools():
                self.tools[tool_def.name] = tool_def
            self.logger.info(
                f"逆向工具已装配: {len(self.tools) - count_before} 个"
            )
        except Exception as e:
            self.logger.warning(f"逆向工具装配失败（降级运行）: {e}")

        # 2. 外部 MCP server 桥接（配置驱动，未配置则跳过）
        mcp_servers_cfg = self.workdir / ".clawd" / "mcp_servers.json"
        if not mcp_servers_cfg.exists():
            return
        try:
            import json as _json

            from ..mcp.client import MCPClientConfig, get_mcp_manager
            from ..mcp.governance import ToolGovernor
            from ..mcp.tool_bridge import bridge_server_tools

            data = _json.loads(mcp_servers_cfg.read_text(encoding="utf-8"))
            manager = get_mcp_manager()
            governor = ToolGovernor()
            bridged_total = 0
            for item in data.get("servers", []):
                cfg = MCPClientConfig.from_dict(item)
                # 治理门禁：检疫期/被拒绝的 server 不桥接
                if governor.status_of(cfg.name) != "approved":
                    self.logger.info(
                        f"MCP server {cfg.name} 未通过治理审批，跳过桥接"
                        f"（状态: {governor.status_of(cfg.name)}）"
                    )
                    continue
                manager.register(cfg)
                tools = await bridge_server_tools(
                    manager, cfg.name, registry=None
                )
                for t in tools:
                    self.tools[t.name] = t
                bridged_total += len(tools)
            self.logger.info(f"MCP 桥接工具已装配: {bridged_total} 个")
        except Exception as e:
            self.logger.warning(f"MCP 桥接装配失败（降级运行）: {e}")

    def _init_config_systems(self) -> None:
        """初始化配置系统。

        这两步失败时工作流仍可运行（使用默认值），但**必须留下痕迹**：
        此前是 `except Exception: pass`，用户把配置写错时既没有报错也没有提示，
        只会看到"配置没生效"这种无从排查的现象。
        """
        try:
            from ..utils.provider_manager import provider_manager
            provider_manager.initialize(workdir=self.workdir)
        except Exception as e:
            self.logger.warning(
                "provider_manager 初始化失败，将使用默认 provider 配置: %s: %s",
                type(e).__name__, e,
            )
        try:
            from ..utils.features import features
            features.initialize(workdir=self.workdir)
        except Exception as e:
            self.logger.warning(
                "features 初始化失败，将使用默认特性开关: %s: %s",
                type(e).__name__, e,
            )

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
        # 挂机自主决策：默认 supervised（有人盯）→ 行为与之前完全一致；
        # CLAWD_AUTONOMY=semi|unattended 时启用自决（详见 src/agent/autonomy.py）
        try:
            from .autonomy import AutonomyEngine, level_from_env

            autonomy_engine = AutonomyEngine(level_from_env(), workdir=self.workdir)
        except Exception as e:
            self.logger.warning(f'挂机自决引擎初始化失败（回退为有人盯模式）: {e}')
            autonomy_engine = None
        self.autonomy = autonomy_engine
        self.tool_manager = ToolManager(self.tools, autonomy=autonomy_engine)
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

    def _build_tool_schemas(self) -> list[dict[str, Any]] | None:
        """为原生 function calling 生成工具 schema。

        默认**开启**（原生 tools 协议是现代 OpenAI 兼容模型的正确姿势：
        文本 <tool> 协议对部分模型会被无视，实测 step-5-preview 直接声称
        "没有工具"。设 `CLAWD_NATIVE_TOOLS=0` 可显式回退文本协议。
        """
        if os.environ.get('CLAWD_NATIVE_TOOLS', '1').lower() in ('0', 'false', 'no'):
            return None

        type_map = {
            'str': 'string',
            'int': 'integer',
            'float': 'number',
            'bool': 'boolean',
            'dict': 'object',
            'list': 'array',
        }

        schemas: list[dict[str, Any]] = []
        for name, tool in self.tools.items():
            properties: dict[str, Any] = {}
            required: list[str] = []
            for param in getattr(tool, 'parameter_schemas', ()) or ():
                prop: dict[str, Any] = {
                    'type': type_map.get(getattr(param, 'param_type', 'str'), 'string')
                }
                if getattr(param, 'description', ''):
                    prop['description'] = param.description
                if getattr(param, 'allowed_values', None):
                    prop['enum'] = list(param.allowed_values)
                properties[param.name] = prop
                if getattr(param, 'required', False):
                    required.append(param.name)

            schemas.append({
                'type': 'function',
                'function': {
                    'name': name,
                    'description': getattr(tool, 'description', ''),
                    'parameters': {
                        'type': 'object',
                        'properties': properties,
                        'required': required,
                    },
                },
            })

        return schemas or None

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

    async def run(
        self,
        goal: str,
        on_step: Callable | None = None,
        prior_messages: list[Any] | None = None,
        images: list[str] | None = None,
    ) -> AgentSession:
        """执行一次 agent 任务

        Args:
            goal: 本次目标
            on_step: 步骤回调
            prior_messages: 续跑时注入的历史消息（LLMMessage 或 {role, content} 字典）
            images: 随消息发送的本地图片绝对路径（模型支持视觉时变成图像内容块）
        """
        # 装配扩展工具（幂等，失败降级）
        await self._load_extended_tools()
        self._execute_hook_point("session_start", {"goal": goal, "stream": False})
        try:
            result = await self._run_agent_core(
                goal=goal, is_stream=False, on_step=on_step, prior_messages=prior_messages,
                images=images,
            )
        except Exception as e:
            self._execute_hook_point(
                "session_end", {"goal": goal, "ok": False, "error": f"{type(e).__name__}: {e}"}
            )
            raise
        self._persist_session(result['session'])
        self._execute_hook_point("session_end", {"goal": goal, "ok": True, "stream": False})
        return result['session']

    async def run_stream(
        self,
        goal: str,
        on_chunk: Callable | None = None,
        on_step: Callable | None = None,
        prior_messages: list[Any] | None = None,
        images: list[str] | None = None,
    ) -> AgentSession:
        self._execute_hook_point("session_start", {"goal": goal, "stream": True})
        try:
            result = await self._run_agent_core(
                goal=goal, is_stream=True, on_chunk=on_chunk, on_step=on_step,
                prior_messages=prior_messages, images=images,
            )
        except Exception as e:
            self._execute_hook_point(
                "session_end", {"goal": goal, "ok": False, "error": f"{type(e).__name__}: {e}"}
            )
            raise
        self._persist_session(result['session'])
        self._execute_hook_point("session_end", {"goal": goal, "ok": True, "stream": True})
        return result['session']

    def apply_persona(self, persona: Any) -> None:
        """装载角色（系统提示词模板）

        `persona` 是 `src.agent.personas.Persona`（或任意带 system/title 的对象）；
        传 None 表示清空。角色只影响系统提示词，不改工具集与权限边界。
        """
        if persona is None:
            self.persona_prompt = ""
            self.persona_name = ""
            return
        from .personas import build_system_prefix

        self.persona_prompt = build_system_prefix(persona)
        self.persona_name = getattr(persona, "name", "")
        self.logger.info(f"已装载角色: {self.persona_name or '?'}")

    # ---------- Hook 接线（hook_registry 此前在引擎里零调用点）----------
    def _execute_hook_point(self, point_name: str, data: dict[str, Any]):
        """执行一个 Hook 点

        返回 `HookExecutionResult`；**未注册任何 hook 时返回 None 且几乎零开销**
        （只是一次 dict 查表）。这样既能真的把 hooks 接上，又不会给默认路径
        增加可感知成本。

        接线背景（审计 P1-4）：`src/hooks/` + `src/core/hook_registry/` 共 2.5k 行
        造好却没人调用 —— 配置里写 hook 等于写了不生效的配置。
        """
        try:
            from ..core.hook_registry import enums as hook_enums
            from ..core.hook_registry.registry import execute_hook, get_hook_point_specs
            from ..core.hook_registry.specs import HookContext
        except ImportError:  # 精简安装/裁剪环境：hook 系统可能不存在
            return None

        try:
            point = hook_enums.HookPoint(point_name)
        except ValueError:
            return None
        try:
            specs = get_hook_point_specs(point)
        except Exception as e:  # noqa: BLE001
            self.logger.debug(f"读取 hook 规格失败: {e}")
            return None
        if not specs:
            return None
        try:
            return execute_hook(point, HookContext(hook_point=point, data=dict(data)))
        except Exception as e:  # noqa: BLE001 — hook 出错不能打断主流程
            self.logger.warning(f"Hook {point_name} 执行异常（已忽略）: {e}")
            return None

    async def _execute_tool_with_hooks(self, tool_name: str, tool_args: dict[str, Any]):
        """工具执行的三点接线：PRE_TOOL_USE → 执行 → POST_TOOL_USE / TOOL_ERROR

        PRE_TOOL_USE 返回 DENY 时**不执行工具**，直接把拒绝原因作为失败结果返回
        （而不是抛异常打断整轮）。
        """
        from ..tools_runtime.base import ToolResult

        pre = self._execute_hook_point(
            "pre_tool_use", {"tool": tool_name, "args": dict(tool_args or {})}
        )
        denied = pre is not None and str(getattr(pre.result, "value", pre.result)) == "deny"
        if denied:
            message = str(getattr(pre, "message", "") or "被 hook 拒绝")
            self.logger.warning(f"PRE_TOOL_USE 拒绝执行 {tool_name}: {message}")
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Hook 拒绝执行 {tool_name}: {message}"
                    "（该工具已被策略拒绝，不要用相同参数重试；请换方案或直接说明被拒绝的原因）"
                ),
            )

        try:
            result = await self.tool_manager.execute_tool(tool_name, tool_args)
        except Exception as e:
            self._execute_hook_point(
                "tool_error",
                {"tool": tool_name, "args": dict(tool_args or {}),
                 "error": f"{type(e).__name__}: {e}"},
            )
            raise

        self._execute_hook_point(
            "post_tool_use",
            {
                "tool": tool_name,
                "args": dict(tool_args or {}),
                "success": bool(getattr(result, "success", False)),
                "output": str(getattr(result, "output", "") or "")[:500],
                "error": str(getattr(result, "error", "") or "")[:500],
            },
        )
        return result

    def _system_prompt_with_autonomy_hint(self) -> str:
        """挂机模式下把"能用什么命令"的清单塞进系统提示

        真实 E2E 教训：不告诉模型可用清单，它会不断尝试复合/管道命令，
        这些在挂机时会被保守跳过，白烧迭代且任务完不成。
        """
        base = self.system_prompt or ''
        persona = getattr(self, 'persona_prompt', '')
        if persona:
            # 角色（personas/*.md）放最前面：它是"怎么说话/怎么做事"的总体设定
            base = (persona.strip() + chr(10) + chr(10) + '---' + chr(10) + chr(10) + base).strip()
        autonomy = getattr(self, 'autonomy', None)
        if autonomy is None:
            return base
        try:
            hint = autonomy.allowed_command_hint()
        except Exception:
            return base
        return f'{base}{hint}' if hint else base

    def _persist_session(self, session: Any) -> None:
        """把本次运行落盘到 .clawd/sessions/（此前两套会话存储都没人写，CLI 永远是空的）

        失败只告警不阻断：会话留痕是增强项，不能影响主流程返回。

        **测试环境不落盘**：pytest 运行时引擎会被大量实例化，此前把
        `<MagicMock name='mock.goal'>` 之类脏数据写进了真实 `.clawd/sessions/`
        （实测 37 个会话里 17 个是 MagicMock），`clawd session list` 直接展示脏数据
        （2026-10-29 审计 P1-3）。可用 CLAWD_DISABLE_SESSION_PERSIST=1 显式关闭。
        """
        import os as _os

        # 显式开关优先级最高：测试要验证落盘链路时设 CLAWD_FORCE_SESSION_PERSIST=1
        if _os.environ.get("CLAWD_FORCE_SESSION_PERSIST", "").lower() in ("1", "true", "yes"):
            pass  # 强制落盘
        elif _os.environ.get("PYTEST_CURRENT_TEST") or _os.environ.get(
            "CLAWD_DISABLE_SESSION_PERSIST", ""
        ).lower() in ("1", "true", "yes"):
            return
        try:
            from ..core.session_bridge import persist_agent_session

            steps = []
            for step in getattr(session, 'steps', []) or []:
                content = getattr(step, 'content', None) or getattr(step, 'result', None)
                if not content:
                    continue
                step_type = str(getattr(step, 'step_type', '') or '')
                if step_type == 'execute':
                    # 工具步骤保留结构：action 形如 `FileReadTool({'file_path': ...})`
                    action = str(getattr(step, 'action', '') or '')
                    tool_name = action.split('(', 1)[0].strip() or 'tool'
                    steps.append({
                        'role': 'tool',
                        'name': tool_name,
                        'content': str(content)[:4000],
                        'ok': bool(getattr(step, 'success', False)),
                    })
                else:
                    steps.append({'role': 'assistant', 'content': str(content)[:4000]})

            llm_config = getattr(self, '_llm_config', None)
            model = str(getattr(llm_config, 'model', '') or '')
            provider = getattr(llm_config, 'provider', '')
            provider = str(getattr(provider, 'value', provider) or '')

            # 用量优先取成本估算器（它同时有输入/输出/费用）；没有就退回 session 的总量
            estimator = getattr(self, '_cost_estimator', None)
            usage: dict[str, Any] = {}
            if estimator is not None and hasattr(estimator, 'get_summary'):
                try:
                    usage = estimator.get_summary() or {}
                except Exception as e:  # noqa: BLE001 — 估算失败不能挡住落盘
                    self.logger.debug(f'成本摘要不可用: {e}')
            input_tokens = int(usage.get('total_input_tokens')
                               or getattr(session, 'total_tokens', 0) or 0)
            output_tokens = int(usage.get('total_output_tokens') or 0)
            total_cost = float(usage.get('total_cost') or 0.0)

            stamp = time.strftime('%Y%m%d_%H%M%S')
            persist_agent_session(
                session_id=f'sess-{stamp}',
                goal=str(getattr(session, 'goal', '') or ''),
                steps=steps,
                final_result=str(getattr(session, 'final_result', '') or ''),
                total_tokens=input_tokens,
                output_tokens=output_tokens,
                total_cost=total_cost,
                persona=str(getattr(self, 'persona_name', '') or ''),
                model=model,
                provider=provider,
                directory=_session_dir(),
                workdir=str(getattr(self, "workdir", "") or ""),
            )

            # 用量记账（CLI 与桌面端共用这条路径）：用户面板里的成本/请求数/缓存命中率就靠它
            try:
                from ..core import usage_store

                usage_store.record(
                    provider=provider,
                    model=model,
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                    cache_read_tokens=int(usage.get('total_cache_read_tokens') or 0),
                    cost=total_cost,
                    steps=len(getattr(session, 'steps', []) or []),
                    status='completed' if getattr(session, 'is_complete', True) else 'incomplete',
                    session_id=f'sess-{stamp}',
                    goal_chars=len(str(getattr(session, 'goal', '') or '')),
                    client=str(getattr(self, 'client_tag', 'cli') or 'cli'),
                    workdir=self.workdir,
                )
            except Exception as e:  # noqa: BLE001 — 记账失败不影响主流程
                self.logger.debug(f'用量记账跳过: {e}')
        except Exception as e:
            self.logger.warning(f'会话落盘失败（不影响本次结果）: {e}')

    async def _run_agent_core(self, goal: str, **kwargs) -> dict[str, Any]:
        """统一入口，调用 engine_loop 中的 _run_agent_loop"""
        from .engine_loop import AgentLoopConfig, _run_agent_loop
        from .engine_session_data import AgentSession

        # kwargs 末尾会 **展开进 AgentLoopConfig，先取出 prior_messages 避免重复传参
        prior_raw = kwargs.pop('prior_messages', None)

        self.session_manager.record_user_goal(goal)
        session = AgentSession(goal=goal)

        # 原生 function calling 只在非流式路径可用：流式分支无法可靠收集
        # tool_calls（各 provider 的 delta 事件实现不一致）。启用开关但走流式时
        # 必须显式告警，不能静默地"开关无效"。
        tool_schemas = self._build_tool_schemas()
        if tool_schemas and kwargs.get('is_stream'):
            warn('流式模式暂不支持原生 function calling，已回退文本工具协议')
            tool_schemas = None

        config = AgentLoopConfig(
            goal=goal,
            llm_provider=self.llm_provider,
            messages=[],
            prior_messages=_normalize_prior_messages(prior_raw),
            autonomy=getattr(self, 'autonomy', None),
            max_iterations=self.max_iterations,
            system_prompt=self._system_prompt_with_autonomy_hint(),
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
            _execute_tool=self._execute_tool_with_hooks,
            tool_schemas=tool_schemas,
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

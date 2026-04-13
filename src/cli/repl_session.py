"""REPL 会话核心 — ReplSession 类核心逻辑

从 repl.py 拆分出来
包含: 会话初始化、引擎延迟加载、HUD 管理、主循环
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Any

from ..utils.colors import (
    bold_green,
    dim,
    green,
)
from .banner import render_banner
from .command_registry import command_registry
from .hud import HudContext, render_hud
from .streaming_markdown import StreamingMarkdownRenderer


class ReplSession:
    """交互式 REPL 会话"""

    def __init__(
        self,
        workdir: Path | None = None,
        max_iterations: int = 10,
        use_rich_hud: bool = True,
        project_ctx: Any = None,
    ) -> None:
        from ..core.project_context import ProjectContext

        self.workdir = workdir or Path(os.environ.get('WORK_DIR', os.getcwd()))
        self.max_iterations = max_iterations
        self.use_rich_hud = use_rich_hud

        # RTK 集成配置 (v0.40.0)
        self.enable_output_compression = True
        self.enable_tee_mode = True
        self.enable_token_tracking = True
        try:
            from ..core.settings import get_settings
            _s = get_settings()
            self.enable_output_compression = getattr(_s, 'enable_output_compression', True)
            self.enable_tee_mode = getattr(_s, 'enable_tee_mode', True)
            self.enable_token_tracking = getattr(_s, 'enable_token_tracking', True)
        except Exception:
            pass  # 优雅降级

        # 初始化项目上下文（如果未提供）
        if project_ctx is not None:
            self.project_ctx = project_ctx
        else:
            self.project_ctx = ProjectContext(workdir=self.workdir)
            self.project_ctx.ensure_dirs()  # 自动创建 .clawd 目录结构

        self.engine = None
        self.hud_ctx = HudContext()
        self._interrupted = False
        self._turn_count = 0
        self._last_session: Any = None
        self._memory_guard: Any = None
        # 持久化事件循环（避免每次任务 asyncio.run() 创建/销毁循环）
        self._loop = asyncio.new_event_loop()
        # Initialize command registry (ClawGod integration)
        command_registry.initialize_builtin_commands()
        # 注册 Aider 风格命令 (整合自 Aider-main)
        command_registry.register_aider_commands()
        # 注入 session 引用，供需要 session 上下文的命令使用
        command_registry.set_session_ref(self)
        # Rich HUD
        self._rich_hud: Any = None
        self._md_renderer: StreamingMarkdownRenderer | None = None

    def _init_engine(self) -> None:
        """延迟初始化 AgentEngine，并挂载 MemoryGuard + Evolution。"""
        if self.engine is not None:
            return
        from ..agent.factory import create_agent_engine
        self.engine = create_agent_engine(
            workdir=self.workdir,
            max_iterations=self.max_iterations,
            enable_output_compression=self.enable_output_compression,
            enable_tee_mode=self.enable_tee_mode,
            enable_token_tracking=self.enable_token_tracking,
        )
        # 自动挂载 MemoryGuard
        try:
            from ..core.memory_guard import MemoryGuard
            guard = MemoryGuard()
            guard.enable_for_engine(self.engine)
            self._memory_guard = guard
        except Exception:
            pass  # 优雅降级

        # 更新 command registry 的 engine 引用
        command_registry.refresh_engine(self.engine)

    def _post_task_hook(self, session: Any) -> None:
        """任务完成后自动执行：内存检查 + 进化审查。"""
        if session is None:
            return
        self._last_session = session

        # 1. MemoryGuard 检查
        guard = getattr(self, '_memory_guard', None)
        if guard:
            guard.on_turn_complete()

        # 2. 低质量自动审查 (score < 70 时触发)
        if session.is_complete and session.steps and len(session.steps) > 3:
            try:
                from ..core.evolution import EvolutionEngine
                evo = EvolutionEngine(workdir=self.workdir)

                report = self._loop.run_until_complete(
                    evo.review(session, auto_apply=True)
                )
                if report.score < 70 and report.issues:
                    dim_msg = dim(f'[进化] 代码评分 {report.grade} ({report.score}/100)，已自动记录改进建议')
                    self._safe_print(f'  {dim_msg}')
            except Exception:
                pass  # 不应阻塞主流程

    def _update_hud(self) -> None:
        """更新 HUD 上下文"""
        if self.engine is None:
            return
        provider = os.environ.get('LLM_PROVIDER', 'openai')
        model_key = {
            'openai': 'OPENAI_MODEL', 'anthropic': 'ANTHROPIC_MODEL',
            'google': 'GOOGLE_MODEL',
            'groq': 'GROQ_MODEL',
        }.get(provider, 'OPENAI_MODEL')

        self.hud_ctx.provider = provider
        self.hud_ctx.model = os.environ.get(model_key, '')
        self.hud_ctx.session_turns = self._turn_count
        self.hud_ctx.max_iterations = self.max_iterations

        summary = self.engine.get_cost_summary()
        if summary:
            self.hud_ctx.total_cost = summary.get('total_cost', 0)
            self.hud_ctx.total_tokens = summary.get('total_tokens', 0)

    def _get_prompt(self) -> str:
        """生成输入提示符"""
        self._update_hud()
        render_hud(self.hud_ctx, 'focused')  # triggers HUD render side-effect
        is_god = False
        if self.engine:
            is_god = getattr(self.engine, 'developer_mode', False)

        if is_god:
            return f'{bold_green("[GOD MODE]")} {green(">")} '
        return f'{dim(">")} '

    def _get_status_line(self) -> str:
        """生成状态行（显示在提示符上方）"""
        self._update_hud()
        hud = render_hud(self.hud_ctx, 'focused')
        return hud

    @staticmethod
    def _safe_print(text: str = '') -> None:
        """安全打印（处理 Windows GBK 等编码问题）"""
        try:
            print(text)
        except UnicodeEncodeError:
            cleaned = text.encode('ascii', errors='replace').decode('ascii')
            print(cleaned)

    def run(self) -> int:
        """启动 REPL 主循环

        返回:
            退出码 (0=正常)
        """
        # 设置 readline 历史（如果可用）- 使用项目级 .clawd 目录
        try:
            import readline
            history_file = self.project_ctx.readline_history_path
            history_file.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(FileNotFoundError):
                readline.read_history_file(str(history_file))
            readline.set_history_length(1000)
        except ImportError:
            readline = None
            history_file = None

        # 显示欢迎横幅
        self._safe_print(render_banner())

        consecutive_interrupts = 0

        while True:
            try:
                prompt = self._get_prompt()
                user_input = input(prompt)
                consecutive_interrupts = 0

                # 空输入
                stripped = user_input.strip()
                if not stripped:
                    continue

                # 多行输入支持（以 \ 结尾续行）
                while stripped.endswith('\\'):
                    stripped = stripped[:-1]
                    try:
                        more = input(f'{dim("...")} ')
                        stripped += '\n' + more.strip()
                    except (EOFError, KeyboardInterrupt):
                        break

                # 内置命令
                if stripped.startswith('/'):
                    should_continue = self._handle_builtin(stripped)
                    if not should_continue:
                        break
                    continue

                # 执行 Agent 任务
                self._run_task(stripped)

            except KeyboardInterrupt:
                consecutive_interrupts += 1
                if consecutive_interrupts >= 2:
                    self._safe_print(f'\n  {dim("再见！")}\n')
                    break
                self._safe_print(f'\n  {dim("再次 Ctrl+C 退出")}')
                continue

            except EOFError:
                self._safe_print(f'\n  {dim("再见！")}\n')
                break

        # 保存历史
        if readline is not None and history_file is not None:
            with contextlib.suppress(Exception):
                readline.write_history_file(str(history_file))

        # 关闭持久化事件循环
        with contextlib.suppress(Exception):
            self._loop.close()

        return 0


# ─── 延迟绑定外部函数到类方法 ───────────────────────
# 在类定义之后进行方法绑定，避免循环导入问题
from .repl_handlers import (
    _handle_builtin,
    _handle_diff,
    _handle_evolve_direct,
    _handle_internal_toggle,
    _handle_provider_switch,
    _handle_undo,
)
from .repl_task import _run_task, _run_task_plain, _run_task_rich

ReplSession._run_task = _run_task
ReplSession._run_task_rich = _run_task_rich
ReplSession._run_task_plain = _run_task_plain
ReplSession._handle_builtin = _handle_builtin
ReplSession._handle_undo = _handle_undo
ReplSession._handle_diff = _handle_diff
ReplSession._handle_provider_switch = _handle_provider_switch
ReplSession._handle_internal_toggle = _handle_internal_toggle
ReplSession._handle_evolve_direct = _handle_evolve_direct

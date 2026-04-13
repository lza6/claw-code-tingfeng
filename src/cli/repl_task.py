"""REPL 任务执行逻辑 — Agent 任务运行

从 repl.py 拆分出来
包含: _run_task, _run_task_rich, _run_task_plain
"""
from __future__ import annotations

from typing import Any

from ..utils.colors import (
    cyan,
    dim,
    status_fail,
    status_warn,
)
from .rich_hud import RichLiveHud
from .streaming_markdown import StreamingMarkdownRenderer


def _run_task(self, goal: str) -> None:
    """运行一次 Agent 任务"""
    self._init_engine()
    self._turn_count += 1

    if self.use_rich_hud:
        self._run_task_rich(goal)
    else:
        self._run_task_plain(goal)


def _run_task_rich(self, goal: str) -> None:
    """使用 Rich HUD 运行任务"""
    from rich.live import Live

    self._rich_hud = RichLiveHud()
    self._md_renderer = StreamingMarkdownRenderer()
    self._rich_hud.renderer.state.model = self.hud_ctx.model or 'unknown'
    self._rich_hud.set_max_iterations(self.max_iterations)

    def on_chunk(chunk: str) -> None:
        """流式 chunk 回调"""
        self._md_renderer.append(chunk)
        self._rich_hud.stream_content(chunk)

    def on_step(step: Any, session: Any) -> None:
        """步骤回调"""
        iteration = getattr(step, 'iteration', 0)
        self._rich_hud.update_iteration(iteration)

        step_type = getattr(step, 'step_type', '')
        action = getattr(step, 'action', '')
        success = getattr(step, 'success', True)

        if step_type == 'llm':
            self._rich_hud.update_status('thinking', action)
        elif step_type == 'execute':
            self._rich_hud.add_step(step_type, action, success)
        elif step_type == 'report':
            if success:
                self._rich_hud.update_status('done', '任务完成')
            else:
                self._rich_hud.update_status('error', action)

        # 更新 token
        summary = self.engine.get_cost_summary()
        if summary:
            self._rich_hud.update_tokens(
                summary.get('total_tokens', 0),
                summary.get('total_cost', 0),
            )

    last_session = None
    try:
        with Live(
            self._rich_hud.renderer.render_full_layout(),
            console=self._rich_hud.console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            session = self._loop.run_until_complete(
                self.engine.run_stream(goal, on_chunk=on_chunk, on_step=on_step)
            )
            last_session = session
            live.update(self._rich_hud.renderer.render_full_layout())
    except KeyboardInterrupt:
        self._safe_print(f'\n  {status_warn("任务已中止")}')
    except Exception as e:
        self._safe_print(f'\n  {status_fail(f"错误: {e}")}')

    # 自动进化和内存护栏
    self._post_task_hook(last_session)


def _run_task_plain(self, goal: str) -> None:
    """使用原始 HUD 运行任务"""
    self._safe_print()

    def on_step(step: Any, session: Any) -> None:
        """进度回调"""
        iteration = getattr(step, 'iteration', 0)
        self.hud_ctx.iteration = iteration

        # 显示工具调用信息
        tool_calls = getattr(step, 'tool_calls', [])
        if tool_calls:
            for tc in tool_calls:
                tool_name = tc.get('name', '') if isinstance(tc, dict) else getattr(tc, 'name', '')
                if tool_name:
                    self._safe_print(f'  {dim("���")} {cyan(tool_name)}')

    last_session = None
    try:
        # 运行 Agent 循环
        session = self._loop.run_until_complete(self.engine.run(goal, on_step=on_step))
        last_session = session

        # 显示结果
        if hasattr(session, 'final_answer') and session.final_answer:
            self._safe_print(f'\n{session.final_answer}')
        elif hasattr(session, 'steps') and session.steps:
            last_step = session.steps[-1]
            content = getattr(last_step, 'content', '') or getattr(last_step, 'response', '')
            if content:
                self._safe_print(f'\n{content}')

        # 更新 HUD 状态
        self._update_hud()
        status = self._get_status_line()
        if status:
            self._safe_print(f'\n  {status}')

    except KeyboardInterrupt:
        self._safe_print(f'\n  {status_warn("任务已中止")}')
    except Exception as e:
        self._safe_print(f'\n  {status_fail(f"错误: {e}")}')

    # 自动进化和内存护栏
    self._post_task_hook(last_session)

    self._safe_print()

"""REPL 任务执行逻辑 — Agent 任务运行

从 repl.py 拆分出来
包含: _run_task, _run_task_rich, _run_task_plain
"""
from __future__ import annotations

from typing import Any

from ..utils.colors import cyan, dim, status_fail, status_warn
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
                self.engine.run_stream(
                    goal, on_chunk=on_chunk, on_step=on_step,
                    prior_messages=self._context_messages(),
                )
            )
            last_session = session
            self._record_turn(goal, session)
            live.update(self._rich_hud.renderer.render_full_layout())

        # Live(screen=True) 退出时会清屏 —— 最终答案必须在退出之后单独打印，
        # 否则用户在富 HUD 模式下看不到任务结果（旧实现确实什么都没打印）。
        self._print_final_answer(last_session)
    except KeyboardInterrupt:
        self._safe_print(f'\n  {status_warn("任务已中止")}')
    except Exception as e:
        self._safe_print(f'\n  {status_fail(f"错误: {e}")}')

    # 自动进化和内存护栏
    self._post_task_hook(last_session)


def _print_final_answer(self, session: Any) -> None:
    """打印任务最终输出（富 HUD 退出后调用）"""
    if session is None:
        self._safe_print(f'\n  {status_warn("本轮没有产生结果会话")}')
        return

    answer = (
        getattr(session, 'final_result', '')
        or getattr(session, 'final_answer', '')
        or ''
    )
    if not str(answer).strip():
        self._safe_print(f'\n  {dim("（模型没有给出最终文本，可看上面的步骤）")}')
        return

    self._safe_print()
    md = getattr(self, '_md_renderer', None)
    if md is not None:
        try:
            md.reset()
            md.append(str(answer))
            self._rich_hud.console.print(md.render_current())
            return
        except Exception as e:  # noqa: BLE001 — 渲染失败必须降级到纯文本，不能吞掉答案
            self._safe_print(f'  {dim(f"Markdown 渲染失败，改用纯文本: {e}")}')
    self._safe_print(str(answer))


def _print_markdown(text: str, repl: Any) -> bool:
    """用 rich 渲染 Markdown（CLI 也要有标题/列表/表格/代码块）；失败返回 False 由调用方降级"""
    try:
        from rich.console import Console
        from rich.markdown import Markdown

        console = getattr(getattr(repl, '_rich_hud', None), 'console', None) or Console()
        console.print(Markdown(str(text)))
        return True
    except Exception:  # noqa: BLE001 — 渲染失败不该吃掉答案
        return False


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
        session = self._loop.run_until_complete(
            self.engine.run(goal, on_step=on_step, prior_messages=self._context_messages())
        )
        self._record_turn(goal, session)
        last_session = session

        # 显示结果（Markdown 渲染；rich 不可用则降级纯文本）
        answer = ''
        if hasattr(session, 'final_answer') and session.final_answer:
            answer = session.final_answer
        elif hasattr(session, 'steps') and session.steps:
            last_step = session.steps[-1]
            answer = getattr(last_step, 'content', '') or getattr(last_step, 'response', '')
        if answer:
            self._safe_print()
            if not _print_markdown(answer, self):
                self._safe_print(str(answer))

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

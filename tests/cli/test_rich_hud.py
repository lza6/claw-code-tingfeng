"""RichLiveHud 真实渲染测试（回归：曾全是 `pass` 的空壳）

旧实现里所有方法都是 `pass`，`render_full_layout()` 返回常量 `""`，
于是 `rich.Live` 包着一个空字符串 —— 用户在富 HUD 模式下什么都看不到，
任务结束也没有最终答案输出（`_run_task_rich` 从未打印结果）。

这里断言：状态改变必须真的反映到渲染结果上，且最终答案必须被打印。
"""

from __future__ import annotations

import io

from rich.console import Console

from src.cli.repl_task import _print_final_answer
from src.cli.rich_hud import RichLiveHud


def _render(hud: RichLiveHud) -> str:
    console = Console(file=io.StringIO(), width=100, force_terminal=False)
    console.print(hud.render_full_layout())
    return console.file.getvalue()


class TestRichLiveHudRenders:
    def test_initial_render_is_not_empty(self):
        assert _render(RichLiveHud()).strip() != ""

    def test_iteration_and_tokens_appear(self):
        hud = RichLiveHud()
        hud.set_max_iterations(8)
        hud.update_iteration(3)
        hud.update_tokens(4321, 0.5)
        out = _render(hud)
        assert "iter:3/8" in out
        assert "4.3k" in out or "4321" in out

    def test_status_and_message_appear(self):
        hud = RichLiveHud()
        hud.update_status("running", "读取 config.yaml")
        out = _render(hud)
        assert "running" in out
        assert "读取 config.yaml" in out

    def test_steps_are_rendered_with_success_marker(self):
        hud = RichLiveHud()
        hud.add_step("execute", "跑测试", True)
        hud.add_step("execute", "点按钮", False)
        out = _render(hud)
        assert "ok" in out
        assert "err" in out
        assert "跑测试" in out
        assert "点按钮" in out

    def test_stream_tail_is_visible_and_bounded(self):
        hud = RichLiveHud()
        hud.stream_content("x" * 5000 + "TAIL")
        out = _render(hud)
        assert "TAIL" in out
        assert len(out) < 5000  # 只保留尾部，不把整段输出塞进 HUD

    def test_render_reflects_later_state_without_new_object(self):
        """Live 会复用同一个 renderable，所以状态更新必须自动体现"""
        hud = RichLiveHud()
        layout = hud.render_full_layout()
        hud.update_iteration(5)
        hud.set_max_iterations(9)
        console = Console(file=io.StringIO(), width=100, force_terminal=False)
        console.print(layout)
        assert "iter:5/9" in console.file.getvalue()

    def test_renderer_surface_is_backward_compatible(self):
        hud = RichLiveHud()
        hud.renderer.state.model = "gpt-5"
        assert hud.state.model == "gpt-5"
        assert hud.renderer.render_full_layout() is hud


class _FakeRepl:
    def __init__(self) -> None:
        self.printed: list[str] = []
        self._rich_hud = RichLiveHud(console=Console(file=io.StringIO(), width=100))
        self._md_renderer = None

    def _safe_print(self, *args, **kwargs) -> None:
        self.printed.append(" ".join(str(a) for a in args))


class _FakeSession:
    def __init__(self, final_result: str) -> None:
        self.final_result = final_result


class TestFinalAnswerPrinting:
    def test_prints_final_result(self):
        repl = _FakeRepl()
        _print_final_answer(repl, _FakeSession("任务完成：已修复按钮间距"))
        assert any("任务完成" in line for line in repl.printed)

    def test_missing_session_reports_honestly(self):
        repl = _FakeRepl()
        _print_final_answer(repl, None)
        assert any("没有产生结果会话" in line for line in repl.printed)

    def test_empty_answer_is_reported_not_silent(self):
        repl = _FakeRepl()
        _print_final_answer(repl, _FakeSession("   "))
        assert repl.printed, "空答案必须给出提示，不能什么都不打印"

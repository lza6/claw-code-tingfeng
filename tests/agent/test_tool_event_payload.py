"""工具完成事件的 payload 必须是**真实的成功标志**（安装版 E2E 抓到的显示缺陷）

真实现象：桌面版里 `FileReadTool` 明明读到了文件（会话里 `ok: true`、模型也用了文件内容），
但界面上工具那一行显示「工具完成: FileReadTool (失败)」。

根因：`engine_loop` 里 `result` 可能是被包了一层的 `(name, args, ToolResult)`，
而 `publish_tool_completed(tool_name, tool_args, result)` 直接把这个元组发了出去；
`EventPublisher` 用 `result.success if hasattr(result, 'success') else False`
→ 元组没有 `.success` → 一律上报 False。

这个缺陷只影响"显示"，但属于同一类问题：**界面在说假话**。所以钉住。
"""

from __future__ import annotations

import pytest

from unittest.mock import MagicMock

from src.agent.engine_loop import AgentLoopConfig, _run_agent_loop
from src.llm.config import LLMResponse
from src.tools_runtime.base import ToolResult


class _OneToolProvider:
    """第一轮返回一个工具调用，第二轮收尾"""

    def __init__(self) -> None:
        self.turn = 0

    async def chat(self, messages):
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(content='<tool>{"name": "TestTool", "args": {}}</tool>', model="mock", usage={})
        return LLMResponse(content="完成", model="mock", usage={})


def _config(events: list, tool_result: ToolResult) -> AgentLoopConfig:
    async def fake_execute(name, args):
        return tool_result

    return AgentLoopConfig(
        goal="读文件",
        llm_provider=_OneToolProvider(),
        messages=[],
        max_iterations=3,
        system_prompt="sys",
        tools={"TestTool": MagicMock()},
        _parse_tool_calls=lambda c: [("TestTool", {})] if "<tool>" in c else [],
        _execute_tool=fake_execute,
        publish_tool_completed=lambda name, args, result: events.append((name, result)),
    )


class TestToolCompletedEventPayload:
    @pytest.mark.asyncio
    async def test_successful_tool_reports_success_true(self):
        events: list = []
        await _run_agent_loop(config=_config(events, ToolResult(success=True, output="文件内容")))
        assert events, "应当发出工具完成事件"
        name, payload = events[0]
        assert name == "TestTool"
        assert getattr(payload, "success", None) is True, (
            f"事件里的 result 必须是 ToolResult 而不是元组，实际: {type(payload)}"
        )
        assert payload.output == "文件内容"

    @pytest.mark.asyncio
    async def test_failed_tool_reports_success_false(self):
        events: list = []
        await _run_agent_loop(
            config=_config(events, ToolResult(success=False, output="", error="boom"))
        )
        assert events
        _, payload = events[0]
        assert getattr(payload, "success", None) is False

    @pytest.mark.asyncio
    async def test_event_publisher_maps_success_field(self):
        """再确认 EventPublisher 的映射语义：没有 .success 就只能是 False"""
        from src.agent._event_publisher import EventPublisher
        from src.core.events import EventBus, EventType

        published: list = []
        bus = EventBus()
        bus.subscribe(EventType.AGENT_TOOL_EXEC_COMPLETED, lambda e: published.append(e))
        publisher = EventPublisher(bus, enabled=True)

        publisher.publish_tool_exec_completed("T", {}, ToolResult(success=True, output="ok"))
        publisher.publish_tool_exec_completed("T", {}, ("T", {}, ToolResult(success=True, output="ok")))

        assert published[0].data["success"] is True
        assert published[1].data["success"] is False, "元组形态必然被误判，正是本缺陷的来源"


class TestLenientToolCallParsing:
    """模型输出格式漂移时必须能宽松解析，否则工具不执行、原始标记还会被当答案

    真实踩坑（安装版 E2E）：模型写出 `<tool>{"name": ...}}>`（多一个 `>`、漏 `</tool>`），
    严格正则匹配不到 → 工具没执行，界面把 `<tool>...` 原文当成最终回答。
    """

    def _parse(self, text: str):
        from src.agent.tool_executor import parse_tool_calls

        return parse_tool_calls(text)

    def test_standard_format_still_works(self):
        calls = self._parse('<tool>{"name": "FileReadTool", "args": {"file_path": "a.txt"}}</tool>')
        assert calls == [("FileReadTool", {"file_path": "a.txt"})]

    def test_extra_angle_bracket_tolerated(self):
        calls = self._parse('<tool>{"name": "FileReadTool", "args": {"file_path": "a.txt"}}>')
        assert calls == [("FileReadTool", {"file_path": "a.txt"})]

    def test_missing_closing_tag_tolerated(self):
        broken = (
            '<tool>{"name": "FileReadTool", "args": {"file_path": "a.txt"}}>'
            "\n</function>\n</tool_call>"
        )
        assert self._parse(broken) == [("FileReadTool", {"file_path": "a.txt"})]

    def test_args_alias_supported(self):
        calls = self._parse('<tool>{"name": "GrepTool", "arguments": {"pattern": "x"}}')
        assert calls == [("GrepTool", {"pattern": "x"})]

    def test_plain_text_has_no_calls(self):
        assert self._parse("就是一句普通回答，没有工具调用。") == []

    def test_unbalanced_json_is_ignored(self):
        assert self._parse('<tool>{"name": "FileReadTool", "args": {"file_path"') == []

    def test_braces_inside_strings_do_not_break_balance(self):
        calls = self._parse('<tool>{"name": "BashTool", "args": {"command": "echo {x}"}}')
        assert calls == [("BashTool", {"command": "echo {x}"})]


class TestXmlStyleToolCalls:
    """预览版模型会在同一任务里换着花样写工具调用（实测三种）

    第三种：`<tool_call><file_read>{"file_path": "x"}</file_read></tool_call>` ——
    只认 `<tool>{json}</tool>` 的解析器会漏掉，工具不执行、原文还被当答案。
    同时模型会把工具名写成 `file_read` / `shell` 这类别名，需要映射到真实类名。
    """

    def _parse(self, text: str):
        from src.agent.tool_executor import parse_tool_calls

        return parse_tool_calls(text)

    def test_xml_style_tag_parsed_with_alias(self):
        text = '<tool_call><file_read>{"file_path": "final_probe.txt"}</file_read></tool_call>'
        assert self._parse(text) == [("FileReadTool", {"file_path": "final_probe.txt"})]

    def test_alias_in_json_name_field(self):
        text = '<tool>{"name": "file_read", "args": {"file_path": "a.txt"}}>'
        assert self._parse(text) == [("FileReadTool", {"file_path": "a.txt"})]

    def test_shell_alias_maps_to_bash_tool(self):
        text = '<tool_call><shell>{"command": "echo hi"}</shell></tool_call>'
        assert self._parse(text) == [("BashTool", {"command": "echo hi"})]

    def test_unknown_tag_becomes_camelcase_tool(self):
        from src.agent.tool_executor import resolve_tool_alias

        assert resolve_tool_alias("web_search") == "Web_searchTool"
        assert resolve_tool_alias("GrepTool") == "GrepTool"

    def test_wrapper_tags_are_not_treated_as_tools(self):
        """`tool_call` / `function_call` 这类包装标签不能被当成工具名"""
        calls = self._parse('<tool_call>{"name": "FileReadTool", "args": {}}</tool_call>')
        names = [name for name, _ in calls]
        assert "tool_call" not in names
        assert "Tool_callTool" not in names

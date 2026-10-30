"""内置能力工具测试（状态 / 记忆 / 追踪 / 团队）—— 证明"不用 MCP 也能用"

对应你的问题："MCP 工具能不能直接内置进智能体？"
答案：**这些能力本来就是进程内的**，所以内置版直接调 `src/core/mcp/*_server.py` 的
Server 类，不需要起 MCP 进程、不需要端口/token 握手。MCP 只留给外部引擎跨进程用。

这里逐条验证 4 个工具的主路径与错误路径。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tools_runtime.domain_tools import get_domain_tools


@pytest.fixture
def tools(tmp_path: Path) -> dict:
    return {t.name: t for t in get_domain_tools(tmp_path)}


class TestAssembly:
    def test_all_capability_tools_assembled(self, tools):
        assert {"WorldModelTool", "ProjectMapTool", "MemoryTool", "StateTool", "TraceTool", "TeamTool"} <= set(tools)

    def test_tools_do_not_require_mcp_process(self, tools):
        """能力工具必须能直接跑（同进程），不依赖任何 MCP server 启动"""
        for name in ("MemoryTool", "StateTool", "TraceTool", "TeamTool"):
            tool = tools[name]
            result = tool.execute(action="stats" if name == "MemoryTool" else "list_sessions" if name == "StateTool" else "recent" if name == "TraceTool" else "list_tasks")
            assert result.success is True, f"{name} 失败: {result.error}"


class TestMemoryTool:
    def test_create_then_search(self, tools):
        mem = tools["MemoryTool"]
        created = mem.execute(action="create", id="e1", name="登录模块", entity_type="module", description="OAuth2")
        assert created.success
        found = mem.execute(action="search", query="登录")
        assert found.success and "e1" in found.output

    def test_observe_records_note(self, tools):
        mem = tools["MemoryTool"]
        mem.execute(action="create", id="e2", name="缓存")
        obs = mem.execute(action="observe", entity_id="e2", content="命中率 92%")
        assert obs.success and "观察已记录" in obs.output

    def test_missing_query_is_failure(self, tools):
        assert tools["MemoryTool"].execute(action="search").success is False

    def test_create_requires_id_and_name(self, tools):
        assert tools["MemoryTool"].execute(action="create", id="x").success is False


class TestStateTool:
    def test_surface_roundtrip(self, tools):
        state = tools["StateTool"]
        assert state.execute(action="surface_set", name="plan", data='{"step": 2}').success
        got = state.execute(action="surface_get", name="plan")
        assert got.success and json.loads(got.output) == {"step": 2}

    def test_bad_json_is_reported_not_crashed(self, tools):
        result = tools["StateTool"].execute(action="surface_set", name="x", data="{not json")
        assert result.success is False and "JSON" in result.error

    def test_session_state_roundtrip(self, tools):
        state = tools["StateTool"]
        assert state.execute(action="session_set", session_id="s1", state='{"a": 1}').success
        got = state.execute(action="session_get", session_id="s1")
        assert got.success and "a" in got.output

    def test_list_sessions(self, tools):
        assert tools["StateTool"].execute(action="list_sessions").success


class TestTraceTool:
    def test_recent_and_unknown_action(self, tools):
        trace = tools["TraceTool"]
        assert trace.execute(action="recent").success
        assert trace.execute(action="get").success is False  # 缺 trace_id

    def test_summarize_requires_trace_id(self, tools):
        result = tools["TraceTool"].execute(action="summarize")
        assert result.success is False and "trace_id" in result.error


class TestTeamTool:
    def test_create_assign_and_mailbox(self, tools):
        team = tools["TeamTool"]
        created = team.execute(action="create_task", description="补测试")
        assert created.success
        task_id = created.output.split(":")[-1].strip()
        assigned = team.execute(action="assign", task_id=task_id, assignee="worker-1")
        assert assigned.success
        sent = team.execute(action="send", to="worker-1", content="开始吧")
        assert sent.success
        mailbox = team.execute(action="mailbox", agent="worker-1")
        assert mailbox.success and "开始吧" in mailbox.output

    def test_assign_nonexistent_task_fails_honestly(self, tools):
        result = tools["TeamTool"].execute(action="assign", task_id="nope", assignee="w")
        assert result.success is False and "不存在" in result.error

    def test_workers_list(self, tools):
        assert tools["TeamTool"].execute(action="workers").success


class TestSchemaValidation:
    def test_invalid_action_rejected_by_schema(self, tools):
        ok, msg = tools["MemoryTool"].validate(action="nope")
        assert ok is False and "action" in msg

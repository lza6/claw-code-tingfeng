"""内置能力工具 —— 把"状态 / 记忆 / 追踪 / 团队"直接装进 agent，不经 MCP

为什么要这三个前提（写在最前面，避免以后又退回"什么都走 MCP"）：

1. **我们自己的 agent 在同一进程里**：直接调 `src/core/mcp/*_server.py` 的 Server 类即可，
   零进程、零 JSON-RPC 序列化、零端口、零 token 握手。
2. **MCP 只是跨进程桥**：外部引擎（Codex/OpenCode 跑在别的进程）才需要 MCP；
   给自家 agent 也绕一圈 MCP，等于给自己加一层会坏的网络边界
   （审计 P1-2 就是这么坏的：server 没 `__main__`，整条链路静默 EOF）。
3. **能力单一来源**：这里不重写存储逻辑，直接复用 core/mcp 的 Server 类 ——
   MCP 工具与内置工具**共用同一份实现**，不会漂移。

每个工具用 `action` 参数做子命令（与 `WorldModelTool` 的风格一致），
参数校验走 `parameter_schemas`，失败返回 `ToolResult(success=False, error=...)`。
"""
from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from .base import BaseTool, ParameterSchema, ToolCategory, ToolResult

MAX_OUTPUT_CHARS = 8000


def _dump(value: Any, limit: int = MAX_OUTPUT_CHARS) -> str:
    """把返回值转成可读文本（JSON 优先，超长截断并标注）"""
    if value is None:
        return "(空)"
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            text = str(value)
    if len(text) > limit:
        return text[:limit] + f"\n…（已截断，原文 {len(text)} 字符）"
    return text


def _fail(message: str) -> ToolResult:
    return ToolResult(success=False, output="", error=message)


class MemoryTool(BaseTool):
    """项目长期记忆：实体/观察/关系（进程内直连，不走 MCP）"""

    name = "MemoryTool"
    description = "项目长期记忆：search 检索 / create 建实体 / observe 加观察 / stats 统计"
    category = ToolCategory.MEMORY
    risk_kind = "read"

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name="action",
            param_type="str",
            required=True,
            description="search | create | observe | stats",
            allowed_values=("search", "create", "observe", "stats"),
        ),
        ParameterSchema(name="query", param_type="str", description="search 的查询词", max_length=500),
        ParameterSchema(name="id", param_type="str", description="create 的实体 id", max_length=200),
        ParameterSchema(name="entity_type", param_type="str", description="create 的实体类型（如 note/service/module）", max_length=100),
        ParameterSchema(name="name", param_type="str", description="create 的实体名", max_length=200),
        ParameterSchema(name="description", param_type="str", description="create 的实体描述", max_length=2000),
        ParameterSchema(name="entity_id", param_type="str", description="observe 的目标实体 id", max_length=200),
        ParameterSchema(name="content", param_type="str", description="observe 的内容", max_length=4000),
    )

    def __init__(self, workdir: Path | str = ".") -> None:
        self.workdir = Path(workdir)
        self._server = None

    def _get(self):
        if self._server is None:
            from ..core.mcp.memory_server import MemoryEntity, create_memory_server

            self._server = create_memory_server(self.workdir)
            self._entity_cls = MemoryEntity
        return self._server

    def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        self._get()
        if action == "stats":
            return ToolResult(success=True, output=_dump(self._server.get_stats()))
        if action == "search":
            query = str(kwargs.get("query") or "").strip()
            if not query:
                return _fail("search 需要 query")
            return ToolResult(success=True, output=_dump(self._server.search(query)))
        if action == "create":
            missing = [k for k in ("id", "name") if not str(kwargs.get(k) or "").strip()]
            if missing:
                return _fail(f"create 缺少参数: {missing}")
            entity = self._entity_cls(
                id=str(kwargs["id"]).strip(),
                type=str(kwargs.get("entity_type") or "note").strip() or "note",
                name=str(kwargs["name"]).strip(),
                description=str(kwargs.get("description") or "").strip(),
            )
            return ToolResult(success=True, output=f"实体已创建: {self._server.create_entity(entity)}")
        if action == "observe":
            entity_id = str(kwargs.get("entity_id") or "").strip()
            content = str(kwargs.get("content") or "").strip()
            if not entity_id or not content:
                return _fail("observe 需要 entity_id 与 content")
            return ToolResult(
                success=True,
                output=f"观察已记录: {self._server.add_observation(entity_id, content)}",
            )
        return _fail(f"未知 action: {action}")


class StateTool(BaseTool):
    """项目状态/表面（surfaces）：会话状态与持久化表面读写"""

    name = "StateTool"
    description = "项目状态：surface_get/surface_set 持久化表面、session_get/session_set、list_sessions"
    category = ToolCategory.UTILITY
    risk_kind = "write"

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name="action",
            param_type="str",
            required=True,
            description="surface_get | surface_set | session_get | session_set | list_sessions",
            allowed_values=("surface_get", "surface_set", "session_get", "session_set", "list_sessions"),
        ),
        ParameterSchema(name="name", param_type="str", description="surface 名（surface_* 用）", max_length=200),
        ParameterSchema(name="data", param_type="str", description="surface_set 的 JSON 文本", max_length=8000),
        ParameterSchema(name="session_id", param_type="str", description="session_* 用", max_length=200),
        ParameterSchema(name="state", param_type="str", description="session_set 的 JSON 文本", max_length=8000),
    )

    def __init__(self, workdir: Path | str = ".") -> None:
        self.workdir = Path(workdir)
        self._server = None

    def _get(self):
        if self._server is None:
            from ..core.mcp.state_server import create_state_server

            self._server = create_state_server(self.workdir)
        return self._server

    @staticmethod
    def _loads(raw: Any) -> dict:
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败: {e}") from e
        if not isinstance(value, dict):
            raise ValueError("必须是 JSON 对象")
        return value

    def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        self._get()
        try:
            if action == "list_sessions":
                return ToolResult(success=True, output=_dump(self._server.list_sessions()))
            if action == "surface_get":
                name = str(kwargs.get("name") or "").strip()
                if not name:
                    return _fail("surface_get 需要 name")
                return ToolResult(success=True, output=_dump(self._server.get_surface(name)))
            if action == "surface_set":
                name = str(kwargs.get("name") or "").strip()
                if not name:
                    return _fail("surface_set 需要 name")
                self._server.set_surface(name, self._loads(kwargs.get("data")))
                return ToolResult(success=True, output=f"surface 已写入: {name}")
            if action == "session_get":
                sid = str(kwargs.get("session_id") or "").strip()
                if not sid:
                    return _fail("session_get 需要 session_id")
                return ToolResult(success=True, output=_dump(self._server.get_session_state(sid)))
            if action == "session_set":
                sid = str(kwargs.get("session_id") or "").strip()
                if not sid:
                    return _fail("session_set 需要 session_id")
                self._server.set_session_state(sid, self._loads(kwargs.get("state")))
                return ToolResult(success=True, output=f"会话状态已写入: {sid}")
            return _fail(f"未知 action: {action}")
        except ValueError as e:
            return _fail(str(e))


class TraceTool(BaseTool):
    """执行追踪读取：review 之后用来讲清"到底发生了什么" """

    name = "TraceTool"
    description = "读取执行追踪：recent 最近列表 / get 详情 / summarize 汇总 / export 导出"
    category = ToolCategory.UTILITY
    risk_kind = "read"

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name="action",
            param_type="str",
            required=True,
            description="recent | get | summarize | export",
            allowed_values=("recent", "get", "summarize", "export"),
        ),
        ParameterSchema(name="trace_id", param_type="str", description="get/summarize/export 用", max_length=200),
        ParameterSchema(name="limit", param_type="int", description="recent 的条数（默认 10）", min_value=1, max_value=100),
        ParameterSchema(name="format", param_type="str", description="export 的格式", allowed_values=("json", "text")),
    )

    def __init__(self, workdir: Path | str = ".") -> None:
        self.workdir = Path(workdir)
        self._server = None

    def _get(self):
        if self._server is None:
            from ..core.mcp.trace_server import create_trace_server

            self._server = create_trace_server(self.workdir)
        return self._server

    def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        self._get()
        if action == "recent":
            return ToolResult(success=True, output=_dump(self._server.get_recent_traces(limit=int(kwargs.get("limit") or 10))))
        trace_id = str(kwargs.get("trace_id") or "").strip()
        if not trace_id:
            return _fail(f"{action} 需要 trace_id")
        if action == "get":
            return ToolResult(success=True, output=_dump(self._server.get_trace(trace_id)))
        if action == "summarize":
            return ToolResult(success=True, output=_dump(self._server.summarize_trace(trace_id)))
        if action == "export":
            fmt = str(kwargs.get("format") or "json")
            return ToolResult(success=True, output=_dump(self._server.export_trace(trace_id, fmt)))
        return _fail(f"未知 action: {action}")


class TeamTool(BaseTool):
    """团队任务/邮箱/worker：多 agent 协作的共享账本"""

    name = "TeamTool"
    description = "团队协作：create_task/list_tasks/assign/send/mailbox/workers"
    category = ToolCategory.UTILITY
    risk_kind = "write"

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name="action",
            param_type="str",
            required=True,
            description="create_task | list_tasks | assign | send | mailbox | workers",
            allowed_values=("create_task", "list_tasks", "assign", "send", "mailbox", "workers"),
        ),
        ParameterSchema(name="description", param_type="str", description="create_task 的任务描述", max_length=2000),
        ParameterSchema(name="task_id", param_type="str", description="assign 的任务 id", max_length=200),
        ParameterSchema(name="assignee", param_type="str", description="assign 的目标 agent", max_length=200),
        ParameterSchema(name="to", param_type="str", description="send 的收件 agent", max_length=200),
        ParameterSchema(name="from_agent", param_type="str", description="send 的发件 agent（默认 agent）", max_length=200),
        ParameterSchema(name="subject", param_type="str", description="send 的主题（默认取内容前 40 字）", max_length=200),
        ParameterSchema(name="content", param_type="str", description="send 的消息正文", max_length=4000),
        ParameterSchema(name="agent", param_type="str", description="mailbox 的 agent 名", max_length=200),
    )

    def __init__(self, workdir: Path | str = ".") -> None:
        self.workdir = Path(workdir)
        self._server = None

    def _get(self):
        if self._server is None:
            from ..core.mcp.team_server import create_team_server

            self._server = create_team_server(self.workdir)
        return self._server

    def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        self._get()
        if action == "list_tasks":
            return ToolResult(success=True, output=_dump(self._server.list_tasks()))
        if action == "workers":
            return ToolResult(success=True, output=_dump(self._server.list_workers()))
        if action == "create_task":
            desc = str(kwargs.get("description") or "").strip()
            if not desc:
                return _fail("create_task 需要 description")
            return ToolResult(success=True, output=f"任务已创建: {self._server.create_task(desc)}")
        if action == "assign":
            task_id = str(kwargs.get("task_id") or "").strip()
            assignee = str(kwargs.get("assignee") or "").strip()
            if not task_id or not assignee:
                return _fail("assign 需要 task_id 与 assignee")
            ok = self._server.assign_task(task_id, assignee)
            return ToolResult(success=bool(ok), output=("已分配" if ok else "分配失败"), error="" if ok else f"任务不存在: {task_id}")
        if action == "send":
            to = str(kwargs.get("to") or "").strip()
            content = str(kwargs.get("content") or "").strip()
            if not to or not content:
                return _fail("send 需要 to 与 content")
            sender = str(kwargs.get("from_agent") or "agent").strip() or "agent"
            subject = str(kwargs.get("subject") or content[:40]).strip() or "无主题"
            # 真实签名是 send_message(from_agent, to_agent, subject, body)
            return ToolResult(
                success=True,
                output=f"消息已发送: {self._server.send_message(sender, to, subject, content)}",
            )
        if action == "mailbox":
            agent = str(kwargs.get("agent") or "").strip()
            if not agent:
                return _fail("mailbox 需要 agent")
            return ToolResult(success=True, output=_dump(self._server.get_mailbox(agent)))
        return _fail(f"未知 action: {action}")


def get_builtin_capability_tools(workdir: Path | str | None = None) -> list[BaseTool]:
    """内置能力工具（引擎装配用，和 MCP 工具共用同一份 Server 实现）"""
    wd = Path(workdir or Path.cwd()).resolve()
    return [MemoryTool(wd), StateTool(wd), TraceTool(wd), TeamTool(wd)]


__all__ = [
    "MemoryTool",
    "StateTool",
    "TeamTool",
    "TraceTool",
    "get_builtin_capability_tools",
]

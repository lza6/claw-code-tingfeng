from __future__ import annotations

import logging
from typing import Any

from ..core.approval_mode import ApprovalMode
from ..core.exceptions import ToolApprovalDeniedError
from ..llm.parsers import HeuristicToolParser
from ..tools_runtime.base import BaseTool, ToolResult
from .tool_executor import execute_tool, execute_tools_parallel, parse_tool_calls

logger = logging.getLogger('agent.tool_manager')


# 会修改磁盘的工具（名称含 Edit / Write / Patch）
_WRITE_TOOL_MARKERS: tuple[str, ...] = ('edit', 'write', 'patch')
# 会执行外部命令的工具
_EXEC_TOOL_MARKERS: tuple[str, ...] = ('bash', 'shell', 'command', 'exec')


def classify_tool(tool_name: str) -> str:
    """把工具分成 read / write / exec 三类。

    门禁按类别判定，而不是硬编码工具名 —— 这样新增工具只要命名符合约定
    就会被自动纳入管控，不需要再改门禁代码。
    """
    lower = tool_name.lower()
    if any(m in lower for m in _EXEC_TOOL_MARKERS):
        return 'exec'
    if any(m in lower for m in _WRITE_TOOL_MARKERS):
        return 'write'
    return 'read'


class ToolManager:
    """工具管理器 - 负责工具的生命周期、解析与执行"""

    def __init__(
        self,
        tools: dict[str, BaseTool],
        approval_mode: ApprovalMode | None = None,
    ) -> None:
        self.tools = tools
        self._heuristic_parser = HeuristicToolParser()
        self.approval_mode = approval_mode if approval_mode is not None else self._load_approval_mode()
        self._warn_if_approval_unenforceable()

    def _warn_if_approval_unenforceable(self) -> None:
        """当配置声明的审批语义**无法被实施**时，一次性说明清楚。

        `DEFAULT` / `AUTO_EDIT` 在 `ApprovalMode` 里声明了不同的审批语义，
        但本版本**没有交互式审批设施**，它们之间实际上没有差别。

        不说明的后果：用户读到 "DEFAULT: 编辑文件或执行 shell 需要审批"，
        会以为有保护 —— 这是**静默的虚假安全感**，比明说不支持更危险。

        只在构造时告警一次，避免每个工具调用都刷屏。
        """
        if self.approval_mode in (ApprovalMode.DEFAULT, ApprovalMode.AUTO_EDIT):
            logger.warning(
                "approval_mode=%s 声明%s，但本版本未实现交互式审批，"
                "写/执行类工具**不会被拦截**。如需强制只读，请设为 plan。",
                self.approval_mode.value,
                "需要审批" if self.approval_mode == ApprovalMode.DEFAULT else "自动批准文件编辑",
            )

    @staticmethod
    def _load_approval_mode() -> ApprovalMode:
        """从配置读取审批模式；读不到时退回 DEFAULT（不放大权限）。

        失败时**不能**默认成 YOLO —— 那等于"配置读取失败就放开全部管控"，
        是最危险的降级方向。
        """
        try:
            from ..core.config.models import AgentSettings

            raw = AgentSettings().approval_mode
            return raw if isinstance(raw, ApprovalMode) else ApprovalMode(str(raw))
        except Exception as e:
            logger.warning(f"读取 approval_mode 失败，按 DEFAULT 处理: {e}")
            return ApprovalMode.DEFAULT

    def _enforce_approval(self, tool_name: str) -> None:
        """按审批模式拦截工具调用。

        当前实现范围（重要，勿误读）:
            本函数**只实施 PLAN 模式的硬性只读门禁**。PLAN 的文档语义是
            "仅分析，不修改文件"，判定结果是明确的"拒绝"，因此无需交互 UI。

        DEFAULT / AUTO_EDIT / YOLO 不做拦截 —— 因为本仓库**没有任何交互式
        审批设施**（全仓库搜不到 approval 请求/回调），DEFAULT 语义中的
        "需要审批"无法落地。强行拦截会让开箱即用的默认配置直接不可用。
        补齐交互式审批属于**新功能**，不在本次缺陷修复范围内。

        修复的缺陷：此前 approval_mode 只在配置层被读写，
        **没有任何运行时消费者** —— 用户设成 plan 后 Agent 照样写盘。
        """
        if self.approval_mode != ApprovalMode.PLAN:
            return

        kind = classify_tool(tool_name)
        if kind == 'read':
            return

        raise ToolApprovalDeniedError(
            tool_name=tool_name,
            tool_kind=kind,
            approval_mode=self.approval_mode.value,
        )

    def add_tool(self, name: str, tool: BaseTool) -> None:
        self.tools[name] = tool

    def remove_tool(self, name: str) -> None:
        if name in self.tools:
            del self.tools[name]

    def get_available_tools(self) -> dict[str, str]:
        return {name: tool.description for name, tool in self.tools.items()}

    def parse_tool_calls(self, content: str) -> list[tuple[str, dict[str, Any]]]:
        """解析工具调用，支持标准解析与启发式解析"""
        standard_calls = parse_tool_calls(content)
        if standard_calls:
            return standard_calls

        _, heuristic_calls = self._heuristic_parser.feed(content)
        if heuristic_calls:
            return [(c['name'], c['input']) for c in heuristic_calls if c['type'] == 'tool_use']

        return []

    async def execute_tool(self, tool_name: str, tool_args: dict[str, Any]) -> ToolResult:
        self._enforce_approval(tool_name)
        return await execute_tool(self.tools, tool_name, tool_args)

    async def execute_tools_parallel(self, tool_calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
        # 并行路径同样要过门禁：它的调用方是 engine_loop 的并行分支，
        # 绕过这里等于门禁只挡住了一半请求。
        for tool_name, _args in tool_calls:
            self._enforce_approval(tool_name)
        return await execute_tools_parallel(self.tools, tool_calls)

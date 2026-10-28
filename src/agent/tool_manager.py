from __future__ import annotations

import logging
from pathlib import Path
from collections.abc import Callable
from typing import Any

from ..core.approval_mode import ApprovalMode
from ..core.exec_policy import ExecPolicy
from ..core.permissions import (
    Effect,
    PermissionEngine,
    PermissionRequest,
    current_session_id,
    extract_command,
    extract_target_path,
)
from ..core.exceptions import ToolApprovalDeniedError
from ..llm.parsers import HeuristicToolParser
from ..tools_runtime.base import BaseTool, ToolResult
from .tool_executor import execute_tool, execute_tools_parallel, parse_tool_calls

logger = logging.getLogger('agent.tool_manager')


# 会修改磁盘的工具（名称含 Edit / Write / Patch）
_WRITE_TOOL_MARKERS: tuple[str, ...] = ('edit', 'write', 'patch')
# 会执行外部命令的工具
_EXEC_TOOL_MARKERS: tuple[str, ...] = ('bash', 'shell', 'command', 'exec')


def classify_tool(tool_name: str, tool: BaseTool | None = None) -> str:
    """把工具分成 read / write / exec 三类。

    优先使用工具**显式声明**的 `risk_kind`；未声明时才回退到名称约定。
    这样新增工具只要声明了风险类别，就无需再改门禁代码，也不会因为
    命名不合约定而绕过审批。
    """
    declared = getattr(tool, 'risk_kind', None)
    if declared in ('read', 'write', 'exec'):
        return declared

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
        confirm_callback: Callable[[str, str, dict[str, Any]], bool] | None = None,
        autonomy: Any = None,
    ) -> None:
        """
        Args:
            tools: 工具池
            approval_mode: 审批模式；None 表示从配置读取
            confirm_callback: 交互式确认回调 `(tool_name, kind, tool_args) -> bool`。
                提供时 `DEFAULT` / `AUTO_EDIT` 会在写/执行类工具上向用户提问；
                未提供时这两者不做拦截（保证脚本 / CI 等非交互场景行为不变）。
        """
        self.tools = tools
        self._heuristic_parser = HeuristicToolParser()
        self.approval_mode = approval_mode if approval_mode is not None else self._load_approval_mode()
        self._confirm_callback = confirm_callback
        # 权限引擎：保护路径 + 会话级授权（见 src/core/permissions.py 的借鉴说明）
        self.permissions = PermissionEngine(
            exec_policy=ExecPolicy.load(
                Path.cwd() / ".clawd" / "exec_policy.json"
            )
        )
        # 挂机自主决策引擎（None = 不启用，保持原有交互语义）
        self.autonomy = autonomy
        self._warn_if_approval_unenforceable()

    def _warn_if_approval_unenforceable(self) -> None:
        """当配置声明的审批语义**无法被实施**时，一次性说明清楚。

        本版本只在**提供了交互式确认回调**时才能实施 `DEFAULT` / `AUTO_EDIT`
        的审批语义。未提供回调（脚本、CI、库调用）时这两者与 `YOLO` 无差别。

        不说明的后果：用户读到 "DEFAULT: 编辑文件或执行 shell 需要审批"，
        会以为有保护 —— 这是**静默的虚假安全感**，比明说不支持更危险。

        只在构造时告警一次，避免每个工具调用都刷屏。
        """
        if self._confirm_callback is not None:
            return
        if self.approval_mode in (ApprovalMode.DEFAULT, ApprovalMode.AUTO_EDIT):
            logger.warning(
                "approval_mode=%s 声明%s，但当前未提供交互式确认回调，"
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

    def _enforce_approval(self, tool_name: str, tool_args: dict[str, Any] | None = None) -> None:
        """按审批模式决定是否放行工具调用。

        完整实施 `ApprovalMode` 的文档语义：

        | 模式 | read | write | exec |
        |:---|:---|:---|:---|
        | plan       | 放行 | 拒绝 | 拒绝 |
        | default    | 放行 | 询问 | 询问 |
        | auto-edit  | 放行 | 放行 | 询问 |
        | yolo       | 放行 | 放行 | 放行 |

        "询问"依赖 `confirm_callback`。**未提供回调时按放行处理** ——
        脚本 / CI / 库调用等非交互场景不能因为没人应答就卡死，也不能
        因此改变既有行为。构造时会对此告警一次（见
        `_warn_if_approval_unenforceable`）。

        修复的缺陷：此前 approval_mode 只在配置层被读写，
        **没有任何运行时消费者** —— 用户设成 plan 后 Agent 照样写盘。
        """
        kind = classify_tool(tool_name, self.tools.get(tool_name))
        if kind == 'read':
            return

        mode = self.approval_mode

        # 先过权限引擎：保护路径 / 会话级授权（借鉴 Pi 的边界 + OpenCode 的会话授权）
        req = PermissionRequest(
            tool=tool_name,
            action=kind,
            path=extract_target_path(tool_args),
            session_id=current_session_id(),
            command=extract_command(tool_args),
        )
        decision = self.permissions.decide(req, approval_mode=mode.value)

        if decision.effect is Effect.DENY:
            # 拒绝必须带理由（Codex 风格），模型据此换方案而不是原地重试
            raise ToolApprovalDeniedError(
                tool_name, kind, mode.value,
                reason=PermissionEngine.denial_message(req, decision.reason),
            )
        if decision.effect is Effect.ALLOW:
            return

        if mode == ApprovalMode.PLAN:
            # 仅分析，不修改文件 —— 硬性拒绝，无需询问
            raise ToolApprovalDeniedError(tool_name, kind, mode.value)

        if mode == ApprovalMode.YOLO:
            return

        if mode == ApprovalMode.AUTO_EDIT and kind == 'write':
            return

        # 剩余情形：DEFAULT 的 write/exec，AUTO_EDIT 的 exec —— 需要审批
        # 挂机模式：由自主决策引擎按规则自决（没人可批时不能默认放行，也不能卡死）
        if self.autonomy is not None:
            from ..agent.autonomy import Action as _AutoAction

            auto = self.autonomy.decide_permission(
                req, decision.effect, decision.reason,
                approval_mode=mode.value,
                policy=getattr(decision, 'policy', '') or '',
            )
            if auto.action is _AutoAction.PROCEED:
                self.permissions.grant_session(req)
                return
            if auto.action in (_AutoAction.SKIP, _AutoAction.ABORT):
                raise ToolApprovalDeniedError(
                    tool_name, kind, mode.value, reason=auto.reason
                )
            # ASK → 继续走人工确认（若没有回调则按原有语义处理）

        if self._confirm_callback is None:
            return  # 非交互场景：放行（既有行为不变）

        if self._confirm_callback(tool_name, kind, tool_args or {}):
            # 批准后记入会话授权：同 (tool, action, 目录) 不再重复询问
            self.permissions.grant_session(req)
            return

        raise ToolApprovalDeniedError(
            tool_name, kind, mode.value, reason="用户拒绝了本次调用"
        )

    def set_confirm_callback(
        self,
        callback: Callable[[str, str, dict[str, Any]], bool] | None,
    ) -> None:
        """挂载/卸载交互式确认回调。

        交互式前端（REPL）在初始化后调用此方法，使 `DEFAULT` / `AUTO_EDIT`
        的审批语义真正生效。非交互场景不调用，行为保持不变。
        """
        self._confirm_callback = callback

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
        self._enforce_approval(tool_name, tool_args)
        return await execute_tool(self.tools, tool_name, tool_args)

    async def execute_tools_parallel(self, tool_calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
        # 并行路径同样要过门禁：它的调用方是 engine_loop 的并行分支，
        # 绕过这里等于门禁只挡住了一半请求。
        for tool_name, args in tool_calls:
            self._enforce_approval(tool_name, args)
        return await execute_tools_parallel(self.tools, tool_calls)

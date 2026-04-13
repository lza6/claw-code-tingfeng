"""REPL 命令处理器 — 内置命令分发逻辑

从 repl.py 拆分出来
包含: _handle_builtin, _handle_undo, _handle_diff, _handle_provider_switch, _handle_internal_toggle
"""
from __future__ import annotations

from ..utils.colors import (
    bold_cyan,
    dim,
    green,
    status_fail,
    status_pass,
    status_warn,
)
from ..utils.features import features
from .command_registry import command_registry


def _handle_builtin(self, cmd: str) -> bool:
    """处理内置命令（统一通过 command_registry 分发）

    返回:
        True = 继续循环, False = 退出
    """
    cmd_lower = cmd.strip().lower()
    handler = command_registry.find(cmd_lower)

    if handler:
        # /exit 和 /quit 特殊处理
        if cmd_lower in ('/exit', '/quit'):
            self._safe_print(f'\n  {dim("再见！")}\n')
            return False

        # /clear 特殊处理（需要重建引擎）
        if cmd_lower == '/clear':
            self.engine = None
            self._turn_count = 0
            command_registry.refresh_engine(None)
            self._safe_print(f'  {status_pass("对话已清除")}')
            return True

        # 如果命令需要引擎，先初始化
        if handler.requires_engine:
            self._init_engine()

        # 执行命令
        try:
            # 优先使用 _engine_handler（延迟绑定）
            if handler._engine_handler is not None and self.engine is not None:
                result = handler._engine_handler(self.engine)
            elif handler.handler is not None:
                result = handler.handler(self.engine if handler.requires_engine else None)
            else:
                result = None

            # 处理返回值
            if isinstance(result, bool):
                return result  # False means exit
            return True
        except Exception as e:
            self._safe_print(f"  {status_fail(f'命令执行失败: {e}')}")
            return True

    # /undo 和 /diff — Git 操作（不需要 engine，但需要 git）
    if cmd_lower == '/undo':
        self._handle_undo()
        return True

    if cmd_lower == '/diff':
        self._handle_diff()
        return True

    # /provider 和 /internal 支持带参数调用（需要 session 上下文）
    if cmd_lower.startswith('/provider') and len(cmd.strip().split()) > 1:
        self._handle_provider_switch(cmd)
        return True

    if cmd_lower.startswith('/internal') and len(cmd.strip().split()) > 1:
        self._handle_internal_toggle(cmd)
        return True

    self._safe_print(f'  {status_warn(f"未知命令: {cmd}")}\n  输入 /help 查看可用命令')
    return True


def _handle_provider_switch(self, cmd: str) -> None:
    """Handle /provider <name> — Switch API providers."""
    from ..utils.provider_manager import provider_manager
    parts = cmd.strip().split()
    if len(parts) < 2:
        return
    provider_name = parts[1]
    provider_manager.initialize(self.workdir)
    success = provider_manager.switch_provider(provider_name)
    if success:
        self._safe_print(f'  {status_pass(f"已切换到 provider: {provider_name}")}')
        # Reinitialize engine to pick up new config
        self.engine = None
        command_registry.refresh_engine(None)
        self._safe_print(f'  {dim("引擎将在下次任务时重新初始化")}')
    else:
        msg = f"Provider '{provider_name}' 未找到"
        self._safe_print(f'  {status_fail(msg)}')
    self._safe_print()


def _handle_undo(self) -> None:
    """Handle /undo — 撤销上一次 AI commit (借鉴 Aider)"""
    try:
        from ..core.git_integration import get_git_manager
        git = get_git_manager(self.workdir)
        success, message = git.undo_last_aider_commit()
        if success:
            self._safe_print(f'  {status_pass(message)}')
        else:
            self._safe_print(f'  {status_warn(message)}')
        self._safe_print()
    except Exception as e:
        self._safe_print(f'  {status_fail(f"Undo 失败: {e}")}\n')


def _handle_diff(self) -> None:
    """Handle /diff — 显示当前变更 (借鉴 Aider)"""
    try:
        from ..core.git_integration import get_git_manager
        git = get_git_manager(self.workdir)
        result = git.get_diff_since_last_message()
        if result is None:
            self._safe_print(f'  {dim("没有变更")}\n')
            return
        self._safe_print(f'  {bold_cyan("变更概览")}')
        self._safe_print(f'  文件: {len(result.files_changed)}  +{result.additions} -{result.deletions}')
        for f in result.files_changed[:20]:
            self._safe_print(f'    {green(f)}')
        if len(result.files_changed) > 20:
            self._safe_print(f'    {dim(f"... 还有 {len(result.files_changed) - 20} 个文件")}')
        self._safe_print()
    except Exception as e:
        self._safe_print(f'  {status_fail(f"Diff 失败: {e}")}\n')


def _handle_internal_toggle(self, cmd: str) -> None:
    """Handle /internal on|off — Toggle internal user mode."""
    parts = cmd.strip().split()
    if len(parts) < 2:
        return
    action = parts[1].lower()
    if action in ('on', 'enable', '开启'):
        features.set_feature("tengu_harbor", True)
        features.set_feature("tengu_session_memory", True)
        features.set_feature("tengu_auto_background_agents", True)
        features.set_feature("tengu_immediate_model_command", True)
        self._safe_print(f'  {status_pass("内部用户模式已开启")}')
    elif action in ('off', 'disable', '关闭'):
        features.set_feature("tengu_harbor", False)
        features.set_feature("tengu_session_memory", False)
        features.set_feature("tengu_auto_background_agents", False)
        features.set_feature("tengu_immediate_model_command", False)
        self._safe_print(f'  {status_pass("内部用户模式已关闭")}')
    else:
        self._safe_print(f'  {status_warn("用法: /internal on|off")}')
    self._safe_print()


def _handle_evolve_direct(self) -> None:
    """Handle /evolve — Direct dispatch from command_registry."""
    self._init_engine()
    from ..core.evolution import EvolutionEngine
    evo = EvolutionEngine(workdir=self.workdir)
    last_session = getattr(self, '_last_session', None)
    if last_session and last_session.steps:
        report = self._loop.run_until_complete(
            evo.review(last_session, auto_apply=True)
        )
        self._safe_print(f'\n  {bold_cyan("进化审查报告")}')
        self._safe_print(f'  评分: {report.grade} ({report.score}/100)')
        for issue in report.issues:
            self._safe_print(f'  - [{issue.get("severity", "?")}] {issue.get("detail", "")}')
        for sug in report.suggestions:
            self._safe_print(f'  * {sug}')
        self._safe_print(f'  {evo.get_evolution_report()}\n')
    else:
        self._safe_print(f'\n  {status_warn("尚无任务历史，无法审查")}\n')

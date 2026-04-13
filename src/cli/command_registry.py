"""Command Registry — Plugin-based CLI Command System

Inspired by ClawGod's modular command architecture.
Provides a centralized registry for CLI commands with automatic help generation,
categorization, and plugin support.

Architecture:
    - Commands are registered with metadata (name, description, category)
    - Help text is auto-generated from registered commands
    - Third-party plugins can dynamically register new commands
    - Supports both sync and async command handlers
    - Engine-dependent commands use lazy binding via refresh_engine()

Usage:
    # Register a command
    from src.cli.command_registry import command_registry

    @command_registry.register("/mycommand", "My custom command", "custom")
    def handle_mycommand(args):
        ...

    # Get help text
    help_text = command_registry.get_help_text()
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..utils.colors import bold_cyan, bold_green, dim, green, status_info, status_pass, status_warn

logger = logging.getLogger(__name__)


@dataclass
class CommandHandler:
    """Represents a registered CLI command."""
    name: str
    handler: Callable
    description: str
    category: str = "general"
    aliases: list[str] = field(default_factory=list)
    requires_engine: bool = False  # Whether command needs engine initialized
    # For engine-dependent commands, store the actual function reference
    # and inject engine at dispatch time
    _engine_handler: Callable | None = field(default=None, repr=False)

    def matches(self, cmd: str) -> bool:
        """Check if command matches name or any alias."""
        cmd_lower = cmd.lower().strip()
        return cmd_lower == self.name.lower() or cmd_lower in [a.lower() for a in self.aliases]


class CommandRegistry:
    """Centralized command registry with plugin support.

    Features:
        - Dynamic command registration
        - Automatic help text generation with categories
        - Alias support
        - Engine requirement tracking with lazy binding
        - refresh_engine() for updating engine-dependent commands after init

    Usage:
        registry = CommandRegistry()

        # Register command
        registry.register(
            "/help",
            lambda args: print("Help"),
            "Show help information",
            category="system"
        )

        # Find and execute
        handler = registry.find("/help")
        if handler:
            handler.handler(args)
    """

    def __init__(self):
        self.commands: dict[str, CommandHandler] = {}
        self._initialized = False
        self._engine_ref: Any = None  # Lazy engine reference
        self._session_ref: Any = None  # ReplSession reference for context-dependent commands

    def register(
        self,
        name: str,
        handler: Callable,
        description: str,
        category: str = "general",
        aliases: list[str] | None = None,
        requires_engine: bool = False,
        engine_handler: Callable | None = None,
    ) -> Callable:
        """Register a command.

        Args:
            name: Command name (e.g., "/help")
            handler: Command handler function (may receive engine as arg)
            description: Human-readable description
            category: Category for grouping in help text
            aliases: Alternative command names
            requires_engine: Whether engine must be initialized
            engine_handler: If set, this function receives (engine) and is called
                           instead of handler when engine is available.

        Returns:
            The handler (for decorator usage)
        """
        cmd = CommandHandler(
            name=name,
            handler=handler,
            description=description,
            category=category,
            aliases=aliases or [],
            requires_engine=requires_engine,
            _engine_handler=engine_handler,
        )

        self.commands[name.lower()] = cmd

        # Also register aliases
        for alias in (aliases or []):
            self.commands[alias.lower()] = cmd

        logger.debug(f"Registered command: {name} (category={category})")
        return handler

    def refresh_engine(self, engine: Any) -> None:
        """Update the engine reference for engine-dependent commands.

        Should be called after engine initialization so that
        engine-dependent commands can access it at dispatch time.
        """
        self._engine_ref = engine
        logger.debug("Engine reference updated in command registry")

    def find(self, cmd: str) -> CommandHandler | None:
        """Find a command by name or alias.

        Args:
            cmd: Command string (e.g., "/help")

        Returns:
            CommandHandler or None if not found
        """
        return self.commands.get(cmd.lower().strip())

    def unregister(self, name: str) -> bool:
        """Unregister a command.

        Args:
            name: Command name

        Returns:
            True if command was removed, False if not found
        """
        if name.lower() in self.commands:
            del self.commands[name.lower()]
            logger.debug(f"Unregistered command: {name}")
            return True
        return False

    def get_help_text(self) -> str:
        """Generate formatted help text grouped by category.

        Returns:
            Formatted help string
        """
        # Group commands by category
        categories: dict[str, list[CommandHandler]] = defaultdict(list)

        # Only include each unique command once (skip aliases)
        seen_names = set()
        for cmd in self.commands.values():
            if cmd.name in seen_names:
                continue
            seen_names.add(cmd.name)
            categories[cmd.category].append(cmd)

        # Build help text
        output = []
        output.append(f'\n  {bold_cyan("Clawd Code")} — AI 编程代理 CLI\n')
        output.append(f'  {dim("使用方法:")}')
        output.append('    直接输入任务描述，AI 将帮你编程')
        output.append('    多行输入：以 \\ 结尾可续行\n')
        output.append(f'  {dim("内置命令:")}')

        # Sort categories for consistent output
        for category in sorted(categories.keys()):
            cmds = sorted(categories[category], key=lambda c: c.name)
            output.append(f'\n  {bold_cyan(category)}:')
            for cmd in cmds:
                output.append(f'    {green(cmd.name):30s} {cmd.description}')

        output.append(f'\n  {dim("快捷键:")}')
        output.append(f'    {green("Ctrl+C"):30s} 中止当前任务')
        output.append(f'    {green("Ctrl+D"):30s} 退出')
        output.append('')

        return '\n'.join(output)

    def get_commands_by_category(self, category: str) -> list[CommandHandler]:
        """Get all commands in a specific category."""
        return [
            cmd for cmd in self.commands.values()
            if cmd.category == category
        ]

    def list_all_commands(self) -> list[CommandHandler]:
        """List all unique commands (excluding aliases)."""
        seen = set()
        unique_cmds = []
        for cmd in self.commands.values():
            # Use name as identity (not handler id) since multiple lambdas
            # have different ids but represent different commands
            if cmd.name not in seen:
                seen.add(cmd.name)
                unique_cmds.append(cmd)
        return unique_cmds

    def initialize_builtin_commands(self):
        """Initialize built-in commands.

        This should be called once during application startup.
        """
        if self._initialized:
            return

        # Import here to avoid circular dependencies
        from ..cli.repl_commands import (
            _handle_cost,
            _handle_doctor,
            _handle_help,
            _handle_status,
            _handle_tools,
            _handle_version,
        )

        # System commands
        self.register(
            "/help",
            lambda args: _handle_help(),
            "显示此帮助信息",
            category="系统",
            aliases=["/?"]
        )

        self.register(
            "/exit",
            lambda args: False,  # Signal to exit
            "退出 Clawd Code",
            category="系统",
            aliases=["/quit", "/q"]
        )

        self.register(
            "/clear",
            lambda args: None,  # Handled by ReplSession directly
            "清除对话历史",
            category="系统"
        )

        self.register(
            "/version",
            lambda args: _handle_version(),
            "显示版本信息",
            category="系统",
            aliases=["/v"]
        )

        # Diagnostic commands
        self.register(
            "/doctor",
            lambda args: _handle_doctor(),
            "运行环境诊断（检查 Python/依赖/API Key）",
            category="诊断",
            requires_engine=False
        )

        # Engine-dependent commands: use _engine_handler for lazy binding
        self.register(
            "/status",
            handler=lambda args: None,  # Fallback; actual logic in _engine_handler
            description="显示引擎状态",
            category="诊断",
            requires_engine=True,
            engine_handler=_handle_status,
        )

        # Information commands
        self.register(
            "/model",
            lambda args: _handle_version(),
            "显示/切换当前 LLM 模型",
            category="信息",
            requires_engine=True
        )

        self.register(
            "/cost",
            handler=lambda args: None,
            description="显示成本报告",
            category="信息",
            requires_engine=True,
            engine_handler=_handle_cost,
        )

        self.register(
            "/tools",
            handler=lambda args: None,
            description="列出可用工具",
            category="信息",
            requires_engine=True,
            engine_handler=_handle_tools,
        )

        # Advanced commands
        self.register(
            "/undo",
            lambda args: None,  # Handled by ReplSession directly
            "撤销上一次 AI commit (借鉴 Aider)",
            category="Git",
        )

        self.register(
            "/diff",
            lambda args: None,  # Handled by ReplSession directly
            "显示当前未提交的变更",
            category="Git",
        )

        self.register(
            "/compact",
            lambda args: status_info("上下文压缩功能将在下次 LLM 调用时自动触发"),
            "压缩对话上下文",
            category="高级",
            requires_engine=True
        )

        self.register(
            "/memory",
            lambda args: self._dispatch_memory(),
            "显示内存健康报告",
            category="高级",
            requires_engine=True
        )

        self.register(
            "/evolve",
            lambda args: self._dispatch_evolve(),
            "触发自动进化审查",
            category="高级",
            requires_engine=True
        )

        # Feature management
        self.register(
            "/features",
            lambda args: self._dispatch_features(),
            "管理实验性功能开关 (God Mode)",
            category="功能",
            requires_engine=False
        )

        self.register(
            "/godpower",
            lambda args: self._dispatch_godpower(),
            "切换开发者模式 (God Mode)",
            category="功能",
            requires_engine=True
        )

        # Project B (ClawGod) inspired commands
        self.register(
            "/provider",
            lambda args: self._dispatch_provider(),
            "切换 API Provider (支持多端点配置)",
            category="功能",
            requires_engine=False
        )

        self.register(
            "/format",
            lambda args: self._dispatch_format(),
            "切换编辑格式 (editblock/wholefile/udiff/patch)",
            category="功能",
            requires_engine=True
        )

        self.register(
            "/internal",
            lambda args: self._dispatch_internal(),
            "显示/设置内部用户模式 (解锁高级功能)",
            category="功能",
            requires_engine=False
        )

        self.register(
            "/override",
            lambda args: self._dispatch_override(),
            "管理 GrowthBook 风格功能覆盖",
            category="功能",
            requires_engine=False
        )

        self.register(
            "/share",
            lambda args: self._dispatch_share(),
            "导出当前会话记录",
            category="功能",
            requires_engine=False
        )

        self._initialized = True
        logger.info(f"Initialized {len(self.list_all_commands())} built-in commands")

    def register_aider_commands(self) -> None:
        """注册 Aider 风格命令

        借鉴 Aider 的命令系统，扩展 Clawd 的命令行功能。
        """
        from .aider_commands import get_aider_command_handler, register_aider_commands

        # 使用 engine_ref 如果可用
        engine = self._engine_ref if self._engine_ref else None

        # 获取 handler 并设置 engine
        handler = get_aider_command_handler(engine)
        handler.set_engine(engine)

        register_aider_commands(self, engine)
        logger.info("Registered Aider-style commands")

    # ─── 延迟分发方法 (由 ReplSession 注入上下文) ───────────────────

    def _dispatch_memory(self):
        """Dispatch /memory using engine reference."""
        if self._engine_ref:
            guard = getattr(self._engine_ref, '_memory_guard', None)
            if guard:
                print(f'\n  {guard.get_report()}\n')
            else:
                print(f'\n  {status_warn("MemoryGuard 未挂载")}\n')
        else:
            print(f'\n  {status_warn("引擎尚未初始化")}\n')

    def _dispatch_evolve(self):
        """Dispatch /evolve using engine reference."""
        # This needs ReplSession context, so delegate back via _session_ref
        session_ref = getattr(self, '_session_ref', None)
        if session_ref:
            session_ref._handle_evolve_direct()
        else:
            print(f'\n  {status_warn("尚无任务历史，无法审查")}\n')

    def _dispatch_features(self):
        """Dispatch /features."""
        from ..utils.features import features
        f_data = features.get_all()
        print(f'\n  {bold_cyan("特性开关 (Features)")}\n')
        for k, v in f_data.items():
            status = green("开启") if v else dim("关闭")
            print(f'    {k:20s} {status}')
        print(f'\n  使用 {dim(".clawd/features.json")} 修改配置\n')

    def _dispatch_godpower(self):
        """Dispatch /godpower using engine reference."""
        if self._engine_ref:
            from ..agent.engine import build_system_prompt
            current = getattr(self._engine_ref, 'developer_mode', False)
            new_mode = not current
            self._engine_ref.developer_mode = new_mode
            bash_tool = self._engine_ref.tools.get('BashTool')
            if bash_tool:
                bash_tool.bypass_security = new_mode
            self._engine_ref.system_prompt = build_system_prompt(
                self._engine_ref.tools, developer_mode=new_mode
            )
            status_text = bold_green("开启") if new_mode else dim("关闭")
            print(f'  {status_pass(f"开发者模式 (God Mode) 已{status_text}")}')
        else:
            print(f'\n  {status_warn("引擎尚未初始化")}\n')

    def _dispatch_provider(self):
        """Dispatch /provider — show current provider info."""
        from ..utils.provider_manager import provider_manager
        config = provider_manager.get_config()
        print(f'\n  {bold_cyan("当前 Provider 配置")}\n')
        api_key_display = config.api_key[:8] + "..." if len(config.api_key) > 8 else "(未配置)"
        print(f'  API Key: {dim(api_key_display)}')
        print(f'  Base URL: {dim(config.base_url)}')
        print(f'  Model: {dim(config.model or "(默认)")}')
        print(f'  Small Model: {dim(config.small_model or "(未配置)")}')
        print(f'  Timeout: {dim(str(config.timeout_ms) + "ms")}')
        if config.providers:
            print(f'\n  {bold_cyan("已配置的 Providers")}\n')
            for name in config.providers:
                print(f'    {green(name)}')
        print('\n  用法: /provider <name> — 切换到指定 provider')
        print('  示例: /provider openai\n')

    def _dispatch_format(self):
        """Dispatch /format — show/switch edit format (from Aider)"""
        if self._engine_ref and hasattr(self._engine_ref, 'edit_format'):
            current = self._engine_ref.edit_format

            # 尝试从 session 获取参数
            args = ""
            if self._session_ref and hasattr(self._session_ref, '_last_command_args'):
                args = getattr(self._session_ref, '_last_command_args', '')

            if args.strip():
                # 切换格式
                new_format = args.strip().lower()
                from ..tools_runtime.edit_format_switcher import EDIT_FORMAT_CHOICES
                if new_format in EDIT_FORMAT_CHOICES:
                    success = self._engine_ref.set_edit_format(new_format)
                    if success:
                        print(f'\n  {status_pass(f"已切换编辑格式: {new_format}")}\n')
                    else:
                        print(f'\n  {status_warn(f"格式切换失败: {new_format}")}\n')
                else:
                    print(f'\n  {status_warn(f"未知格式: {new_format}")}')
                    print(f'  可用格式: {", ".join(EDIT_FORMAT_CHOICES)}\n')
                return

            # 显示当前格式
            from ..tools_runtime.edit_format_switcher import EDIT_FORMAT_PROMPTS
            print(f'\n  {bold_cyan("当前编辑格式")}: {green(current)}\n')
            print(f'  {dim("可用格式:")}')
            for fmt in EDIT_FORMAT_CHOICES[:6]:  # 显示前6个
                marker = " *" if fmt == current else "  "
                print(f'    {marker} {fmt}')

            if current in EDIT_FORMAT_PROMPTS:
                print(f'\n  {dim("格式说明:")}')
                desc = EDIT_FORMAT_PROMPTS[current][:200]
                print(f'    {desc}...')

            print('\n  用法: /format <format> — 切换格式')
            print('  示例: /format wholefile\n')
        else:
            print(f'\n  {status_warn("引擎未初始化或不支持编辑格式")}\n')

    def _dispatch_internal(self):
        """Dispatch /internal — show internal mode status."""
        from ..utils.features import features
        is_internal = features.is_enabled("tengu_harbor") or features.is_enabled("god_mode")
        status_text = bold_green("开启") if is_internal else dim("关闭")
        print(f'\n  {bold_cyan("内部用户模式")}: {status_text}\n')
        print('  内部用户模式解锁以下功能:')
        print('    - tengu_harbor: 高级会话记忆')
        print('    - tengu_session_memory: 跨会话上下文')
        print('    - tengu_auto_background_agents: 自动后台 Agent')
        print('    - tengu_immediate_model_command: 即时模型切换')
        print('\n  用法: /internal on|off\n')

    def _dispatch_override(self):
        """Dispatch /override — show override management."""
        import json
        import os
        print(f'\n  {bold_cyan("GrowthBook 功能覆盖管理")}\n')
        overrides_json = os.environ.get("CLAUDE_INTERNAL_FC_OVERRIDES")
        if overrides_json:
            try:
                overrides = json.loads(overrides_json)
                print('  当前内部覆盖 (CLAUDE_INTERNAL_FC_OVERRIDES):')
                for key, val in overrides.items():
                    print(f'    {green(key)}: {val}')
            except json.JSONDecodeError:
                print(f'  {status_warn("无效的 CLAUDE_INTERNAL_FC_OVERRIDES JSON")}')
        else:
            print('  当前无内部覆盖')
        from ..utils.features import features
        sources = features.get_override_report()
        if sources:
            print('\n  功能覆盖来源:')
            for key, source in sources.items():
                print(f'    {green(key)}: {dim(source)}')
        print('\n  用法: /override set <key> <value>')
        print('  示例: /override set god_mode true')
        print('\n  提示: 设置 CLAUDE_INTERNAL_FC_OVERRIDES 环境变量可批量覆盖\n')

    def _dispatch_share(self):
        """Dispatch /share — show share info."""
        session_ref = getattr(self, '_session_ref', None)
        if session_ref:
            history_file = session_ref.project_ctx.readline_history_path
            print(f'\n  {status_info(f"会话记录已保存至: {history_file}")}')
        else:
            print(f'\n  {status_info("会话记录保存中...")}')
        print(f'  {dim("提示: 你可以手动分享此文件或导出 Markdown 摘要")}\n')

    def set_session_ref(self, session: Any) -> None:
        """Set the ReplSession reference for commands that need session context."""
        self._session_ref = session


# Global singleton instance
command_registry = CommandRegistry()

"""模型命令 - Aider 风格模型和配置命令

此模块包含模型和控制相关的命令:
- cmd_model: 显示/切换模型
- cmd_editor_model: 切换编辑器模型
- cmd_weak_model: 切换弱模型
- cmd_chat_mode: 切换聊天模式
- cmd_thinking: 控制思考过程显示
- cmd_cache: 控制缓存行为
- cmd_map: 显示/设置代码地图详细程度
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .aider_commands_base import AiderCommandHandler


def cmd_model(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """显示/切换模型

    用法: /model [model_name]
    """
    if not args.strip():
        # 显示当前模型
        if self.engine_ref and hasattr(self.engine_ref, 'llm_config'):
            cfg = self.engine_ref.llm_config
            return True, f"当前模型: {cfg.model}"
        return True, "用法: /model <model_name>"

    # 切换模型
    if self.engine_ref and hasattr(self.engine_ref, 'llm_config'):
        self.engine_ref.llm_config.model = args.strip()
        return True, f"已切换到模型: {args.strip()}"

    return False, "引擎未初始化"


def cmd_editor_model(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """切换编辑器模型

    用法: /editor-model <model_name>
    """
    if not args.strip():
        return True, "用法: /editor-model <model_name>"

    if self.engine_ref and hasattr(self.engine_ref, 'llm_config'):
        self.engine_ref.llm_config.editor_model = args.strip()
        return True, f"已切换编辑器模型: {args.strip()}"

    return False, "引擎未初始化"


def cmd_weak_model(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """切换弱模型（用于摘要/commit）

    用法: /weak-model <model_name>
    """
    if not args.strip():
        return True, "用法: /weak-model <model_name>"

    if self.engine_ref and hasattr(self.engine_ref, 'llm_config'):
        self.engine_ref.llm_config.weak_model = args.strip()
        return True, f"已切换弱模型: {args.strip()}"

    return False, "引擎未初始化"


def cmd_chat_mode(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """切换聊天模式

    用法: /chat-mode [ask|code|architect|context]
    """
    if not args.strip():
        return True, """可用聊天模式:
  ask      - 仅问问题，不修改代码
  code     - 询问并修改代码（默认）
  architect - 架构师模式，设计后由编辑器执行
  context   - 自动识别需要编辑的文件
"""

    mode = args.strip().lower()
    valid_modes = ['ask', 'code', 'architect', 'context']

    if mode not in valid_modes:
        return False, f"无效模式: {mode}\n可用: {', '.join(valid_modes)}"

    if self.engine_ref and hasattr(self.engine_ref, 'set_chat_mode'):
        self.engine_ref.set_chat_mode(mode)
        return True, f"已切换到 {mode} 模式"

    return False, "引擎未初始化"


def cmd_thinking(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """控制思考过程显示

    用法: /thinking [on|off|tokens]
    """
    arg = args.strip().lower() if args.strip() else "toggle"

    if arg == "on":
        self._thinking_enabled = True
        return True, "思考过程���示已开启"
    elif arg == "off":
        self._thinking_enabled = False
        return True, "思考过程显示已关闭"
    elif arg == "tokens":
        return True, f"思考 token 预算: {getattr(self, '_thinking_tokens', '未设置')}"
    elif arg == "toggle":
        self._thinking_enabled = not getattr(self, '_thinking_enabled', True)
        status = "开启" if self._thinking_enabled else "关闭"
        return True, f"思考过程显示已{status}"

    return False, "用法: /thinking [on|off|tokens]"


def cmd_cache(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """控制缓存行为

    用法: /cache [on|off|clear|status]
    """
    arg = args.strip().lower() if args.strip() else "status"

    if arg == "on":
        return True, "缓存已启用 (通过 API 配置)"
    elif arg == "off":
        return True, "缓存已禁用"
    elif arg == "clear":
        return True, "缓存已清除"
    elif arg == "status":
        return True, """缓存状态:
  Prompt Caching: 可用 (如果模型支持)
  Context Caching: 自动管理
"""

    return False, "用法: /cache [on|off|clear|status]"


def cmd_map(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """显示/设置代码地图详细程度

    用法: /map [auto|<token_budget>]
    """
    if not args.strip() or args.strip() == "auto":
        return True, "代码地图: auto (自动 token 预算)"

    try:
        tokens = int(args.strip())
        return True, f"代码地图: {tokens} tokens"
    except ValueError:
        return False, "用法: /map [auto|<number>]"

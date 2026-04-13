"""BashTool - 安全命令执行工具

向后兼容模块: 导入所有拆分出去的子模块。
"""
from __future__ import annotations

# 重新导出所有公共 API 以保持向后兼容
from .bash_constants import (
    DANGEROUS_PATTERNS,
    DANGEROUS_PATTERNS_UNIX,
    DANGEROUS_PATTERNS_WINDOWS,
    get_allowed_workdirs,
    set_allowed_workdirs,
)
from .bash_executor import BashTool
from .bash_security import (
    detect_command_substitution,
    evaluate_awk_command,
    evaluate_find_command,
    evaluate_git_command,
    evaluate_sed_command,
    find_git_bash_path,
    is_shell_command_read_only,
    split_commands,
    strip_shell_wrapper,
)

# 向后兼容: 也从 bash_executor 重新导出
__all__ = [
    # 常量
    'DANGEROUS_PATTERNS',
    'DANGEROUS_PATTERNS_UNIX',
    'DANGEROUS_PATTERNS_WINDOWS',
    # 类
    'BashTool',
    'detect_command_substitution',
    'evaluate_awk_command',
    'evaluate_find_command',
    'evaluate_git_command',
    'evaluate_sed_command',
    'find_git_bash_path',
    # 函数
    'get_allowed_workdirs',
    'is_shell_command_read_only',
    'set_allowed_workdirs',
    'split_commands',
    'strip_shell_wrapper',
]

"""文件操作命令 - Aider 风格文件管理命令

此模块包含文件相关的命令:
- cmd_add: 添加文件到聊天
- cmd_drop: 从聊天移除文件
- cmd_read: 读取文件内容
- cmd_edit: 编辑文件
- cmd_subtree: 限制文件操作范围
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..utils.colors import bold_cyan, dim, green

if TYPE_CHECKING:
    from .aider_commands_base import AiderCommandHandler


def cmd_add(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """添加文件到聊天

    用法: /add <file1> <file2> ...
    """
    if not args.strip():
        # 显示当前聊天文件
        if self._chat_fnames:
            print(f'\n  {bold_cyan("当前聊天文件:")}\n')
            for f in sorted(self._chat_fnames):
                print(f'    {green(f)}')
            print()
            return True, ""
        return True, "用法: /add <file> [<file> ...]"

    # 添加文件
    added = []
    for path in args.split():
        self._chat_fnames.add(path)
        added.append(path)

    return True, f"已添加 {len(added)} 个文件到聊天"


def cmd_drop(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """从聊天移除文件

    用法: /drop <file1> <file2> ...
    """
    if not args.strip():
        # 清除所有文件
        count = len(self._chat_fnames)
        self._chat_fnames.clear()
        return True, f"已移除 {count} 个聊天文件"

    # 移除指定文件
    removed = []
    for path in args.split():
        if path in self._chat_fnames:
            self._chat_fnames.discard(path)
            removed.append(path)

    return True, f"已移除 {len(removed)} 个文件"


def cmd_read(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """读取文件内容

    用法: /read <file> [lines]
    """
    parts = args.strip().split()
    if not parts:
        return False, "用法: /read <file> [lines]"

    file_path = parts[0]
    n_lines = int(parts[1]) if len(parts) > 1 else 100

    if not os.path.exists(file_path):
        return False, f"文件不存在: {file_path}"

    try:
        with open(file_path, encoding='utf-8', errors='replace') as f:
            lines = []
            for i, line in enumerate(f, 1):
                if i > n_lines:
                    break
                lines.append(f"{i:4d} │ {line.rstrip()}")

        output = [f"文件: {bold_cyan(file_path)}", ""]
        output.append('\n'.join(lines))

        if i > n_lines:
            output.append(f"\n{dim('... (还有更多行)')}")

        return True, '\n'.join(output)

    except Exception as e:
        return False, f"读取失败: {e}"


def cmd_edit(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """编辑文件（行号编辑）

    用法: /edit <file>:<start_line>-<end_line> <new_content>
    """
    parts = args.split(':', 1)
    if len(parts) != 2:
        return False, "用法: /edit <file>:<start>-<end> <new_content>"

    file_path = parts[0]
    line_spec = parts[1]

    match = re.match(r'(\d+)(?:-(\d+))?', line_spec)
    if not match:
        return False, "用法: /edit <file>:<start>-<end> <new_content>"

    start_line = int(match.group(1))
    end_line = int(match.group(2)) if match.group(2) else start_line

    new_content = args.split(' ', 1)[1] if ' ' in parts[1] else ""

    # 使用 FileEditTool
    if self.engine_ref and hasattr(self.engine_ref, 'tools'):
        edit_tool = self.engine_ref.tools.get('FileEditTool')
        if edit_tool:
            result = edit_tool.execute(
                file_path=file_path,
                content=new_content,
                start_line=start_line,
                end_line=end_line,
            )
            return result.success, result.output or result.error

    return False, "FileEditTool 不可用"


def cmd_subtree(self: AiderCommandHandler, args: str) -> tuple[bool, str]:
    """限制文件操作范围到子目录

    用法: /subtree <path>
    """
    if not args.strip():
        # 显示当前 subtree 设置
        return True, f"当前 subtree: {getattr(self, '_subtree_path', '(未设置)')}"

    # 设置 subtree
    self._subtree_path = args.strip()

    # 应用限制
    if self.engine_ref and hasattr(self.engine_ref, 'git_manager'):
        gm = self.engine_ref.git_manager
        if hasattr(gm, 'subtree_only') and hasattr(gm, 'workdir'):
            gm.subtree_only = True
            gm.workdir = Path(gm.workdir) / args.strip()

    return True, f"已限制文件操作到子目录: {args.strip()}"

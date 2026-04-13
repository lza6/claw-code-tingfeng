"""Editor 模块 — 系统文本编辑器交互（移植自 Aider editor.py）

功能:
- 自动发现系统默认编辑器（VISUAL/EDITOR 环境变量）
- 跨平台支持（Windows/macOS/Linux）
- 临时文件编辑（pipe_editor 模式）
- 编辑器偏好配置

用法:
    from src.utils.editor import pipe_editor, discover_editor

    # 发现编辑器
    editor = discover_editor()  # e.g. 'vim' or 'notepad'

    # 管道编辑
    edited = pipe_editor(input_data="原始内容", suffix="py")
"""
from __future__ import annotations

import os
import platform
import subprocess
import tempfile

from rich.console import Console

console = Console()

DEFAULT_EDITOR_NIX = "vi"
DEFAULT_EDITOR_OS_X = "vim"
DEFAULT_EDITOR_WINDOWS = "notepad"


def print_status_message(success: bool, message: str, style: str | None = None) -> None:
    """打印状态消息"""
    if style is None:
        style = "bold green" if success else "bold red"
    console.print(message, style=style)
    print()


def write_temp_file(
    input_data: str = "",
    suffix: str | None = None,
    prefix: str | None = None,
    dir: str | None = None,
) -> str:
    """创建临时文件并写入内容

    参数:
        input_data: 文件内容
        suffix: 文件后缀（不含点）
        prefix: 文件名前缀
        dir: 目标目录

    返回:
        临时文件路径
    """
    kwargs: dict[str, Any] = {"prefix": prefix, "dir": dir}
    if suffix:
        kwargs["suffix"] = f".{suffix}"
    fd, filepath = tempfile.mkstemp(**kwargs)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(input_data)
    except Exception:
        os.close(fd)
        raise
    return filepath


def get_environment_editor(default: str | None = None) -> str | None:
    """从环境变量获取首选编辑器

    检查顺序: VISUAL → EDITOR → default

    参数:
        default: 默认编辑器

    返回:
        编辑器命令
    """
    return os.environ.get("VISUAL", os.environ.get("EDITOR", default))


def discover_editor(editor_override: str | None = None) -> str:
    """发现系统编辑器

    支持编辑器命令中包含参数的情况（如 'vim -c "set noswapfile"'）。

    参数:
        editor_override: 强制指定的编辑器

    返回:
        编辑器命令字符串
    """
    system = platform.system()
    if system == "Windows":
        default_editor = DEFAULT_EDITOR_WINDOWS
    elif system == "Darwin":
        default_editor = DEFAULT_EDITOR_OS_X
    else:
        default_editor = DEFAULT_EDITOR_NIX

    if editor_override:
        return editor_override

    return get_environment_editor(default_editor) or default_editor


def pipe_editor(
    input_data: str = "",
    suffix: str | None = None,
    editor: str | None = None,
) -> str:
    """打开系统编辑器编辑内容并返回结果

    创建临时文件 → 打开编辑器 → 等待用户编辑 → 读取结果 → 删除临时文件

    参数:
        input_data: 初始内容
        suffix: 文件后缀（如 'py', 'md'）
        editor: 指定编辑器（None 则自动发现）

    返回:
        编辑后的内容
    """
    filepath = write_temp_file(input_data, suffix)
    command_str = discover_editor(editor)
    command_str += " " + filepath

    subprocess.call(command_str, shell=True)

    with open(filepath, encoding="utf-8", errors="replace") as f:
        output_data = f.read()

    try:
        os.remove(filepath)
    except PermissionError:
        print_status_message(
            False,
            f"WARNING: 无法删除临时文件 {filepath!r}，请手动删除。",
        )

    return output_data

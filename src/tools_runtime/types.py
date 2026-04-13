"""工具类型注解 - TypedDict 定义"""
from __future__ import annotations

from typing import TypedDict


class BashToolArgs(TypedDict, total=False):
    """BashTool 参数类型"""
    command: str  # 要执行的命令


class FileReadToolArgs(TypedDict, total=False):
    """FileReadTool 参数类型"""
    file_path: str  # 文件路径（相对于 base_path）
    offset: int  # 起始行号（1-based，默认 1）
    limit: int  # 读取行数（默认全部）


class FileEditToolArgs(TypedDict, total=False):
    """FileEditTool 参数类型"""
    file_path: str  # 文件路径（相对于 base_path）
    content: str  # 文件内容
    append: bool  # 是否追加模式（默认 False，覆盖写入）


class GlobToolArgs(TypedDict, total=False):
    """GlobTool 参数类型"""
    pattern: str  # 文件匹配模式（如 *.py）
    max_results: int  # 最大结果数量


class GrepToolArgs(TypedDict, total=False):
    """GrepTool 参数类型"""
    pattern: str  # 正则表达式
    case_sensitive: bool  # 是否区分大小写（默认 False）
    file_pattern: str  # 文件匹配模式（默认 *.py）
    max_results: int  # 最大结果数量（默认 50）


# 联合类型：所有工具参数的联合
ToolArgs = BashToolArgs | FileReadToolArgs | FileEditToolArgs | GlobToolArgs | GrepToolArgs

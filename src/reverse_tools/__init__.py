"""
逆向原生工具模块

提供:
- GhidraTool: GhidraMCP 插件 HTTP 桥接（反编译/符号/导入导出/交叉引用）
- StringsTool / EntropyTool / HexDumpTool: 纯 Python 静态分析
- ObjdumpTool / FileTool / BinwalkTool / ReadelfTool: 外部 CLI 包装

register_all(registry) 将全部工具注册到指定 ToolRegistry。
"""
from __future__ import annotations

import logging

from src.reverse_tools.binary_cli import BinwalkTool, FileTool, ObjdumpTool, ReadelfTool
from src.reverse_tools.ghidra_bridge import GhidraTool
from src.reverse_tools.static_analysis import EntropyTool, HexDumpTool, StringsTool
from src.tools_runtime.tool_interface import BaseTool, ToolRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "GhidraTool",
    "StringsTool",
    "EntropyTool",
    "HexDumpTool",
    "ObjdumpTool",
    "FileTool",
    "BinwalkTool",
    "ReadelfTool",
    "get_all_tools",
    "register_all",
]


def get_all_tools() -> list[BaseTool]:
    """创建全部逆向工具实例（每次返回新实例）"""
    return [
        GhidraTool(),
        StringsTool(),
        EntropyTool(),
        HexDumpTool(),
        ObjdumpTool(),
        FileTool(),
        BinwalkTool(),
        ReadelfTool(),
    ]


def register_all(registry: ToolRegistry) -> None:
    """将全部逆向工具注册到指定 ToolRegistry"""
    for tool in get_all_tools():
        registry.register(tool)
    logger.info(f"逆向工具注册完成: {len(get_all_tools())} 个")

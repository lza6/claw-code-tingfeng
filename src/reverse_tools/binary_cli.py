"""
外部 CLI 包装工具 - 通过 subprocess 调用逆向分析命令行工具

提供:
- ObjdumpTool  (objdump -d)
- FileTool     (file)
- BinwalkTool  (binwalk)
- ReadelfTool  (readelf -a)

全部在 execute 前用 shutil.which 检查 CLI 是否存在，不存在返回明确错误。
subprocess 异常统一转 ToolResult 错误，绝不静默吞掉。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

from src.tools_runtime.tool_interface import BaseTool, ToolCallStatus, ToolResult

logger = logging.getLogger(__name__)

CLI_TIMEOUT = 120


def _run_cli(tool_name: str, cli: str, args: list[str], timeout: int = CLI_TIMEOUT) -> ToolResult:
    """执行外部 CLI，统一异常转 ToolResult 错误"""
    exe = shutil.which(cli)
    if exe is None:
        msg = f"工具未安装: {cli}"
        logger.error(f"{tool_name}: {msg}")
        return ToolResult(tool_name=tool_name, status=ToolCallStatus.ERROR, error=msg)

    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        msg = f"命令超时（>{timeout}s）: {cli} {' '.join(args)}"
        logger.error(f"{tool_name}: {msg}")
        return ToolResult(
            tool_name=tool_name,
            status=ToolCallStatus.TIMEOUT,
            error=msg,
        )
    except OSError as e:
        msg = f"执行命令失败: {e}"
        logger.error(f"{tool_name}: {msg}")
        return ToolResult(tool_name=tool_name, status=ToolCallStatus.ERROR, error=msg)
    except Exception as e:
        msg = f"执行命令出现未知错误: {e}"
        logger.error(f"{tool_name}: {msg}")
        return ToolResult(tool_name=tool_name, status=ToolCallStatus.ERROR, error=msg)

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        msg = f"命令退出码 {proc.returncode}: {cli} {' '.join(args)}\nstderr: {stderr}"
        logger.error(f"{tool_name}: {msg}")
        return ToolResult(
            tool_name=tool_name,
            status=ToolCallStatus.ERROR,
            error=msg,
            metadata={"returncode": proc.returncode},
        )

    return ToolResult(
        tool_name=tool_name,
        status=ToolCallStatus.SUCCESS,
        output=proc.stdout,
        metadata={"returncode": 0, "command": f"{cli} {' '.join(args)}"},
    )


def _reverse_definition(tool: BaseTool, description: str) -> None:
    """统一设置 reverse 分类与标签"""
    tool._definition.category = "reverse"
    tool._definition.tags = ["reverse", "cli", tool.name]
    tool._definition.description = description


class ObjdumpTool(BaseTool):
    """objdump -d 反汇编工具"""

    def __init__(self):
        super().__init__(name="objdump", description="使用 objdump -d 反汇编二进制文件")
        _reverse_definition(self, "使用 objdump -d 反汇编二进制文件（参数: path）")

    def execute(self, path: str, **_: Any) -> ToolResult:
        return _run_cli(self.name, "objdump", ["-d", path])


class FileTool(BaseTool):
    """file 命令文件类型识别"""

    def __init__(self):
        super().__init__(name="file", description="使用 file 命令识别文件类型")
        _reverse_definition(self, "使用 file 命令识别文件类型（参数: path）")

    def execute(self, path: str, **_: Any) -> ToolResult:
        return _run_cli(self.name, "file", [path])


class BinwalkTool(BaseTool):
    """binwalk 固件/嵌入内容分析"""

    def __init__(self):
        super().__init__(name="binwalk", description="使用 binwalk 扫描文件中的嵌入内容与签名")
        _reverse_definition(self, "使用 binwalk 扫描文件中的嵌入内容与签名（参数: path）")

    def execute(self, path: str, **_: Any) -> ToolResult:
        return _run_cli(self.name, "binwalk", [path])


class ReadelfTool(BaseTool):
    """readelf -a ELF 完整信息"""

    def __init__(self):
        super().__init__(name="readelf", description="使用 readelf -a 输出 ELF 文件完整信息")
        _reverse_definition(self, "使用 readelf -a 输出 ELF 文件完整信息（参数: path）")

    def execute(self, path: str, **_: Any) -> ToolResult:
        return _run_cli(self.name, "readelf", ["-a", path])

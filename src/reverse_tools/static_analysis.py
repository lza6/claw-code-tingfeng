"""
静态分析工具 - 纯 Python 实现，无外部 CLI 依赖

提供:
- StringsTool: 提取二进制可打印字符串（ascii）
- EntropyTool: 计算文件/内存块熵（0-8 bit/byte），加壳检测线索
- HexDumpTool: 十六进制转储
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from pathlib import Path

from src.tools_runtime.tool_interface import BaseTool, ToolCallStatus, ToolResult

logger = logging.getLogger(__name__)

# 可打印 ASCII 序列（默认最短 4 字符）
_PRINTABLE_RE = re.compile(rb"[\x20-\x7e]{4,}")


def _read_bytes(source: str, max_bytes: int | None = None) -> bytes:
    """从文件路径读取字节；路径不存在时抛 FileNotFoundError（由调用方转错误）"""
    p = Path(source)
    data = p.read_bytes()
    if max_bytes is not None:
        data = data[:max_bytes]
    return data


class StringsTool(BaseTool):
    """提取二进制中的可打印 ASCII 字符串"""

    def __init__(self):
        super().__init__(
            name="strings",
            description="提取二进制文件中的可打印 ASCII 字符串（参数: path, min_length）",
        )
        self._definition.category = "reverse"
        self._definition.tags = ["reverse", "static-analysis", "strings"]

    def execute(self, path: str, min_length: int = 4, **_) -> ToolResult:
        """提取字符串，返回换行分隔的字符串列表"""
        try:
            if min_length < 1:
                return self._err("min_length 必须 >= 1")
            data = _read_bytes(path)
            pattern = re.compile(rb"[\x20-\x7e]{%d,}" % min_length)
            found = [m.decode("ascii") for m in pattern.findall(data)]
            return ToolResult(
                tool_name=self.name,
                status=ToolCallStatus.SUCCESS,
                output="\n".join(found),
                metadata={"count": len(found), "min_length": min_length},
            )
        except OSError as e:
            return self._err(f"读取文件失败: {e}")
        except Exception as e:
            return self._err(str(e))

    def _err(self, msg: str) -> ToolResult:
        logger.error(f"StringsTool: {msg}")
        return ToolResult(tool_name=self.name, status=ToolCallStatus.ERROR, error=msg)


class EntropyTool(BaseTool):
    """计算文件或字节块的香农熵（0-8 bit/byte），熵 > 7.5 常见于加密/加壳"""

    PACKING_THRESHOLD = 7.5

    def __init__(self):
        super().__init__(
            name="entropy",
            description="计算文件/内存块的香农熵（0-8 bit/byte），高熵提示加密或加壳"
            "（参数: path 或 data，limit 限制读取字节数）",
        )
        self._definition.category = "reverse"
        self._definition.tags = ["reverse", "static-analysis", "entropy", "packing"]

    @staticmethod
    def shannon_entropy(data: bytes) -> float:
        """香农熵，单位 bit/byte，范围 [0, 8]"""
        if not data:
            return 0.0
        counts = Counter(data)
        total = len(data)
        ent = 0.0
        for c in counts.values():
            p = c / total
            ent -= p * math.log2(p)
        return ent

    def execute(self, path: str | None = None, data: bytes | None = None,
                limit: int | None = None, **_) -> ToolResult:
        try:
            if data is not None:
                raw = data[:limit] if limit else data
                src = "memory"
            elif path:
                raw = _read_bytes(path, max_bytes=limit)
                src = str(path)
            else:
                return self._err("需要提供 path 或 data 参数")

            ent = self.shannon_entropy(raw)
            hint = "高熵，疑似加密/加壳" if ent > self.PACKING_THRESHOLD else "正常"
            return ToolResult(
                tool_name=self.name,
                status=ToolCallStatus.SUCCESS,
                output=f"{ent:.4f}",
                metadata={
                    "entropy": ent,
                    "source": src,
                    "bytes": len(raw),
                    "packing_suspect": ent > self.PACKING_THRESHOLD,
                    "hint": hint,
                },
            )
        except OSError as e:
            return self._err(f"读取文件失败: {e}")
        except Exception as e:
            return self._err(str(e))

    def _err(self, msg: str) -> ToolResult:
        logger.error(f"EntropyTool: {msg}")
        return ToolResult(tool_name=self.name, status=ToolCallStatus.ERROR, error=msg)


class HexDumpTool(BaseTool):
    """十六进制转储（hexdump 风格: 偏移 + hex + ascii）"""

    def __init__(self):
        super().__init__(
            name="hexdump",
            description="十六进制转储文件内容（参数: path, offset, limit；每行 16 字节）",
        )
        self._definition.category = "reverse"
        self._definition.tags = ["reverse", "static-analysis", "hexdump"]

    @staticmethod
    def format_hexdump(data: bytes, base_offset: int = 0) -> str:
        """格式化为 'offset  hex  |ascii|' 行，每行 16 字节"""
        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i : i + 16]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            hex_part = hex_part.ljust(16 * 3 - 1)
            ascii_part = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in chunk)
            lines.append(f"{base_offset + i:08x}  {hex_part}  |{ascii_part}|")
        return "\n".join(lines)

    def execute(self, path: str, offset: int = 0, limit: int = 256, **_) -> ToolResult:
        try:
            if offset < 0 or limit <= 0:
                return self._err("offset 必须 >= 0 且 limit 必须 > 0")
            full = _read_bytes(path)
            chunk = full[offset : offset + limit]
            if not chunk:
                return self._err(f"偏移 {offset} 超出文件大小 {len(full)}")
            return ToolResult(
                tool_name=self.name,
                status=ToolCallStatus.SUCCESS,
                output=self.format_hexdump(chunk, base_offset=offset),
                metadata={"offset": offset, "bytes": len(chunk), "file_size": len(full)},
            )
        except OSError as e:
            return self._err(f"读取文件失败: {e}")
        except Exception as e:
            return self._err(str(e))

    def _err(self, msg: str) -> ToolResult:
        logger.error(f"HexDumpTool: {msg}")
        return ToolResult(tool_name=self.name, status=ToolCallStatus.ERROR, error=msg)

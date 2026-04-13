"""Base Tool Implementation — 工具基类"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    result: Any = None
    error: str | None = None
    execution_time_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
        }


class ToolImplementation(ABC):
    """工具实现基类"""

    name: str = ""
    description: str = ""
    input_schema: dict = {}

    def __init__(self):
        self._execution_count = 0
        self._total_time_ms = 0

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        pass

    async def validate(self, **kwargs) -> tuple[bool, str | None]:
        """验证输入参数"""
        required = self.input_schema.get("required", [])
        for field in required:
            if field not in kwargs:
                return False, f"Missing required field: {field}"
        return True, None

    def get_stats(self) -> dict:
        """获取统计信息"""
        avg_time = self._total_time_ms / max(self._execution_count, 1)
        return {
            "name": self.name,
            "executions": self._execution_count,
            "total_time_ms": self._total_time_ms,
            "average_time_ms": avg_time,
        }

    def _record_execution(self, time_ms: int):
        """记录执行统计"""
        self._execution_count += 1
        self._total_time_ms += time_ms


class ReadFileTool(ToolImplementation):
    """读取文件工具"""

    name = "read_file"
    description = "Read contents of a file"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read"},
            "offset": {"type": "integer", "description": "Line offset to start from"},
            "limit": {"type": "integer", "description": "Number of lines to read"},
        },
        "required": ["path"],
    }

    async def execute(self, path: str, offset: int = 0, limit: int | None = None, **kwargs) -> ToolResult:
        import time
        start = time.perf_counter()

        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()

            content = "".join(lines[offset:offset + limit] if limit else lines[offset:])

            return ToolResult(
                success=True,
                result={"content": content, "lines": len(lines)},
                execution_time_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                execution_time_ms=int((time.perf_counter() - start) * 1000),
            )


class WriteFileTool(ToolImplementation):
    """写入文件工具"""

    name = "write_file"
    description = "Write content to a file"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write"},
            "content": {"type": "string", "description": "Content to write"},
            "append": {"type": "boolean", "description": "Append to file instead of overwrite"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, path: str, content: str, append: bool = False, **kwargs) -> ToolResult:
        import time
        start = time.perf_counter()

        try:
            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)

            return ToolResult(
                success=True,
                result={"path": path, "bytes_written": len(content.encode())},
                execution_time_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                execution_time_ms=int((time.perf_counter() - start) * 1000),
            )


class RunCommandTool(ToolImplementation):
    """运行命令工具"""

    name = "run_command"
    description = "Run a shell command"
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to run"},
            "cwd": {"type": "string", "description": "Working directory"},
            "timeout": {"type": "integer", "description": "Timeout in seconds"},
        },
        "required": ["command"],
    }

    async def execute(self, command: str, cwd: str | None = None, timeout: int = 60, **kwargs) -> ToolResult:
        import subprocess
        import time
        start = time.perf_counter()

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return ToolResult(
                success=result.returncode == 0,
                result={
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
                execution_time_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                execution_time_ms=int((time.perf_counter() - start) * 1000),
            )


class SearchTool(ToolImplementation):
    """搜索工具"""

    name = "search"
    description = "Search for content in files"
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Search pattern"},
            "path": {"type": "string", "description": "Path to search in"},
            "glob": {"type": "string", "description": "File glob pattern"},
            "ignore_case": {"type": "boolean", "description": "Case insensitive"},
        },
        "required": ["pattern", "path"],
    }

    async def execute(self, pattern: str, path: str, glob: str | None = None, ignore_case: bool = False, **kwargs) -> ToolResult:
        import subprocess
        import time
        start = time.perf_counter()

        try:
            cmd = ["grep", "-n"]
            if ignore_case:
                cmd.append("-i")
            if glob:
                cmd.extend(["--include", glob])
            cmd.extend([pattern, path])

            result = subprocess.run(cmd, capture_output=True, text=True)

            return ToolResult(
                success=True,
                result={"matches": result.stdout.splitlines(), "count": len(result.stdout.splitlines())},
                execution_time_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                execution_time_ms=int((time.perf_counter() - start) * 1000),
            )


class GlobTool(ToolImplementation):
    """文件查找工具"""

    name = "glob"
    description = "Find files by pattern"
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern"},
            "path": {"type": "string", "description": "Base path to search"},
        },
        "required": ["pattern"],
    }

    async def execute(self, pattern: str, path: str = ".", **kwargs) -> ToolResult:
        import glob as glob_module
        import time
        start = time.perf_counter()

        try:
            matches = glob_module.glob(f"{path}/{pattern}", recursive=True)

            return ToolResult(
                success=True,
                result={"files": matches, "count": len(matches)},
                execution_time_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                execution_time_ms=int((time.perf_counter() - start) * 1000),
            )


# 工具注册表
class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: dict[str, type[ToolImplementation]] = {}

    def register(self, tool_class: type[ToolImplementation]):
        """注册工具"""
        instance = tool_class()
        self._tools[instance.name] = tool_class
        logger.info(f"Registered tool: {instance.name}")

    def get(self, name: str) -> type[ToolImplementation] | None:
        """获取工具类"""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """列出所有工具"""
        return list(self._tools.keys())

    def create_instance(self, name: str) -> ToolImplementation | None:
        """创建工具实例"""
        tool_class = self._tools.get(name)
        return tool_class() if tool_class else None


# 全局注册表
_tool_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """获取全局工具注册表"""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
        # 注册默认工具
        _tool_registry.register(ReadFileTool)
        _tool_registry.register(WriteFileTool)
        _tool_registry.register(RunCommandTool)
        _tool_registry.register(SearchTool)
        _tool_registry.register(GlobTool)
    return _tool_registry


__all__ = [
    "GlobTool",
    "ReadFileTool",
    "RunCommandTool",
    "SearchTool",
    "ToolImplementation",
    "ToolRegistry",
    "ToolResult",
    "WriteFileTool",
    "get_tool_registry",
]

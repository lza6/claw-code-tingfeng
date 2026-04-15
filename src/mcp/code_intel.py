"""
MCP Code Intelligence Server

提供代码理解 MCP 工具:
- tsc 诊断包装
- ast-grep/sg 集成
- 符号搜索
- 项目文件索引

汲取自 oh-my-codex-main/src/mcp/code-intel-server.ts
"""

import asyncio
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ==== 工具响应格式 =====

def text_content(data: dict | list | str) -> dict:
    """创建文本内容响应"""
    return {
        "content": [{"type": "text", "text": json.dumps(data, indent=2)}]
    }


def error_content(msg: str) -> dict:
    """创建错误响应"""
    return {
        "content": [{"type": "text", "text": json.dumps({"error": msg})}],
        "isError": True
    }


# ==== 诊断数据结构 =====

@dataclass
class Diagnostic:
    """单条诊断信息"""
    file: str
    line: int
    character: int
    severity: str  # 'error' | 'warning'
    code: str
    message: str


@dataclass
class DiagnosticsResult:
    """诊断结果"""
    diagnostics: list[Diagnostic] = field(default_factory=list)
    command: str = ""
    project_dir: str = ""
    severity_filter: str = ""


# ==== 执行辅助 =====

async def run_command(
    cmd: str,
    args: list[str],
    cwd: str = ".",
    timeout: int = 60,
    check: bool = False
) -> tuple[str, str, int]:
    """运行命令并返回 stdout, stderr, returncode"""
    try:
        result = await asyncio.create_subprocess_exec(
            cmd,
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate(timeout=timeout)
        return (
            stdout.decode() if stdout else "",
            stderr.decode() if stderr else "",
            result.returncode
        )
    except FileNotFoundError:
        return "", f"Command not found: {cmd}", 127
    except asyncio.TimeoutError:
        return "", f"Timeout after {timeout}s", 124
    except Exception as e:
        return "", str(e), 1


# ==== 诊断功能 =====

def parse_tsc_output(output: str, project_dir: str) -> list[Diagnostic]:
    """解析 tsc 输出

    格式: src/foo.ts(10,5): error TS2304: Cannot find name 'x'.
    """
    diagnostics: list[Diagnostic] = []
    pattern = re.compile(
        r"^(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.+)$",
        re.MULTILINE
    )

    for match in pattern.finditer(output):
        diagnostics.append(Diagnostic(
            file=str(Path(project_dir) / match.group(1)),
            line=int(match.group(2)),
            character=int(match.group(3)),
            severity=match.group(4),
            code=match.group(5),
            message=match.group(6)
        ))

    return diagnostics


async def find_tsconfig(dir: str) -> Optional[str]:
    """查找 tsconfig"""
    candidates = ["tsconfig.json", "tsconfig.build.json"]
    for candidate in candidates:
        path = Path(dir) / candidate
        if path.exists():
            return str(path)
    return None


async def run_tsc_diagnostics(
    target: str,
    project_dir: str,
    severity: Optional[str] = None
) -> DiagnosticsResult:
    """运行 tsc 诊断

    Args:
        target: 目标文件/目录
        project_dir: 项目目录
        severity: 可选的 severity 过滤 ('error' | 'warning')
    """
    tsconfig = await find_tsconfig(project_dir)
    args = ["--noEmit", "--pretty", "false"]

    if tsconfig:
        args.extend(["--project", tsconfig])

    # 尝试找到 target
    target_path = Path(target)
    if not target_path.is_absolute():
        target_path = Path(project_dir) / target

    args.append(str(target_path))

    stdout, stderr, code = await run_command(
        "npx", ["tsc", *args],
        cwd=project_dir,
        timeout=60
    )

    output = stdout + "\n" + stderr
    diagnostics = parse_tsc_output(output, project_dir)

    # 按 severity 过滤
    if severity:
        diagnostics = [d for d in diagnostics if d.severity == severity]

    return DiagnosticsResult(
        diagnostics=diagnostics,
        command=f"npx tsc {' '.join(args)}",
        project_dir=project_dir,
        severity_filter=severity or ""
    )


# ==== ast-grep 集成 =====

@dataclass
class SearchResult:
    """搜索结果"""
    file: str
    line: int
    symbol: str
    context: str


async def run_ast_grep(
    pattern: str,
    cwd: str = ".",
    language: str = "python",
    timeout: int = 30
) -> list[SearchResult]:
    """运行 ast-grep 搜索

    Args:
        pattern: 搜索模式
        cwd: 工作目录
        language: 语言 (python, typescript, etc.)
        timeout: 超时秒数
    """
    args = ["sg", "scan", pattern, "--language", language, "--json"]

    stdout, stderr, code = await run_command(
        "npx", args,
        cwd=cwd,
        timeout=timeout
    )

    if code != 0:
        return []

    results: list[SearchResult] = []

    try:
        data = json.loads(stdout)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    results.append(SearchResult(
                        file=item.get("file", ""),
                        line=item.get("line", 0),
                        symbol=item.get("symbol", item.get("text", "")),
                        context=item.get("context", item.get("snippet", ""))
                    ))
    except json.JSONDecodeError:
        pass

    return results


# ==== 符号搜索 =====

@dataclass
class Symbol:
    """代码符号"""
    name: str
    kind: str  # 'function' | 'class' | 'variable' | 'constant'
    file: str
    line: int
    signature: str = ""


async def find_symbols(
    cwd: str,
    pattern: str,
    language: str = "python"
) -> list[Symbol]:
    """查找代码符号

    使用 ast-grep 或简化搜索
    """
    results = await run_ast_grep(pattern, cwd, language)

    symbols: list[Symbol] = []
    kind_map = {
        "def": "function",
        "class": "class",
        "const": "constant",
        "let": "variable",
        "var": "variable",
    }

    for r in results:
        # 简单推断 kind
        kind = "variable"
        for k, v in kind_map.items():
            if k in r.symbol:
                kind = v
                break

        symbols.append(Symbol(
            name=r.symbol.split("(")[0].split("=")[0].strip(),
            kind=kind,
            file=r.file,
            line=r.line,
            signature=r.symbol
        ))

    return symbols


# ==== 文件索引 =====

@dataclass
class FileIndex:
    """项目文件索引"""
    path: str
    size: int
    modified: float
    extension: str


async def index_project(
    cwd: str,
    extensions: Optional[list[str]] = None,
    exclude_dirs: Optional[list[str]] = None
) -> list[FileIndex]:
    """索引项目文件

    Args:
        cwd: 工作目录
        extensions: 要包含的扩展名 (如 [".py", ".ts"])
        exclude_dirs: 要排除的目录
    """
    if extensions is None:
        extensions = [".py", ".ts", ".tsx", ".js", ".jsx"]

    if exclude_dirs is None:
        exclude_dirs = ["node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build"]

    indexes: list[FileIndex] = []
    cwd_path = Path(cwd)

    for pattern in ["**/*" + ext for ext in extensions]:
        for file_path in cwd_path.glob(pattern):
            # 排除目录检查
            if any(excl in file_path.parts for excl in exclude_dirs):
                continue

            try:
                stat = file_path.stat()
                indexes.append(FileIndex(
                    path=str(file_path.relative_to(cwd_path)),
                    size=stat.st_size,
                    modified=stat.st_mtime,
                    extension=file_path.suffix
                ))
            except OSError:
                continue

    # 按修改时间排序
    indexes.sort(key=lambda x: x.modified, reverse=True)

    return indexes[:500]  # 限制数量


# ==== MCP 工具处理 =====

class CodeIntelTool:
    """Code Intelligence 工具集"""

    def __init__(self, cwd: str = "."):
        self.cwd = cwd

    async def diagnose(self, target: str = ".", severity: Optional[str] = None) -> dict:
        """运行 tsc 诊断

        MCP 工具: mcp-code-intel-diagnose
        """
        result = await run_tsc_diagnostics(target, self.cwd, severity)

        return text_content({
            "diagnostics": [
                {
                    "file": d.file,
                    "line": d.line,
                    "character": d.character,
                    "severity": d.severity,
                    "code": d.code,
                    "message": d.message
                }
                for d in result.diagnostics
            ],
            "count": len(result.diagnostics),
            "command": result.command,
            "severity_filter": result.severity_filter
        })

    async def search(self, pattern: str, language: str = "python") -> dict:
        """搜索符号

        MCP 工具: mcp-code-intel-search
        """
        results = await run_ast_grep(pattern, self.cwd, language)

        return text_content({
            "results": [
                {
                    "file": r.file,
                    "line": r.line,
                    "symbol": r.symbol,
                    "context": r.context
                }
                for r in results[:50]  # 限制数量
            ],
            "count": len(results)
        })

    async def find_symbol(self, name: str, language: str = "python") -> dict:
        """查找符号定义

        MCP 工具: mcp-code-intel-find-symbol
        """
        symbols = await find_symbols(self.cwd, name, language)

        return text_content({
            "symbols": [
                {
                    "name": s.name,
                    "kind": s.kind,
                    "file": s.file,
                    "line": s.line,
                    "signature": s.signature
                }
                for s in symbols[:20]
            ],
            "count": len(symbols)
        })

    async def index(self, extensions: Optional[list[str]] = None) -> dict:
        """索引项目文件

        MCP 工具: mcp-code-intel-index
        """
        indexes = await index_project(self.cwd, extensions)

        return text_content({
            "files": [
                {
                    "path": i.path,
                    "size": i.size,
                    "modified": i.modified,
                    "extension": i.extension
                }
                for i in indexes[:100]
            ],
            "count": len(indexes)
        })


# ==== 工具注册表 =====

MCP_TOOLS = [
    {
        "name": "mcp-code-intel-diagnose",
        "description": "Run tsc type diagnostics on project files",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target file or directory (default: '.')"
                },
                "severity": {
                    "type": "string",
                    "enum": ["error", "warning"],
                    "description": "Filter by severity"
                }
            }
        }
    },
    {
        "name": "mcp-code-intel-search",
        "description": "Search code using ast-grep pattern",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Ast-grep pattern"
                },
                "language": {
                    "type": "string",
                    "default": "python"
                }
            }
        }
    },
    {
        "name": "mcp-code-intel-find-symbol",
        "description": "Find symbol definitions in codebase",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Symbol name to find"
                },
                "language": {
                    "type": "string",
                    "default": "python"
                }
            }
        }
    },
    {
        "name": "mcp-code-intel-index",
        "description": "Index project files for fast lookup",
        "inputSchema": {
            "type": "object",
            "properties": {
                "extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File extensions to include"
                }
            }
        }
    }
]


# ==== 主入口 =====

async def get_code_intel_tools(cwd: str = ".") -> list[dict]:
    """获取 Code Intelligence 工具列表"""
    return MCP_TOOLS


async def handle_code_intel_tool(
    tool_name: str,
    arguments: dict,
    cwd: str = "."
) -> dict:
    """处理 Code Intelligence 工具调用

    Args:
        tool_name: 工具名称
        arguments: 工具参数
        cwd: 工作目录
    """
    tools = CodeIntelTool(cwd)

    if tool_name == "mcp-code-intel-diagnose":
        return await tools.diagnose(
            arguments.get("target", "."),
            arguments.get("severity")
        )
    elif tool_name == "mcp-code-intel-search":
        return await tools.search(
            arguments.get("pattern", ""),
            arguments.get("language", "python")
        )
    elif tool_name == "mcp-code-intel-find-symbol":
        return await tools.find_symbol(
            arguments.get("name", ""),
            arguments.get("language", "python")
        )
    elif tool_name == "mcp-code-intel-index":
        return await tools.index(arguments.get("extensions"))
    else:
        return error_content(f"Unknown tool: {tool_name}")


# ==== 使用示例 =====

"""
# 集成到现有 MCP Server

from .code_intel import (
    get_code_intel_tools,
    handle_code_intel_tool
)

async def handle_mcp_tool(method, params):
    if method == "tools/call":
        tool = params.get("name")
        args = params.get("arguments", {})

        # Code Intelligence 工具
        if tool.startswith("mcp-code-intel-"):
            return await handle_code_intel_tool(tool, args, cwd=params.get("cwd", "."))

        # 其他工具...
"""
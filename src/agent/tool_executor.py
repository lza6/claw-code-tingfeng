"""工具执行器 - AgentEngine 的工具执行和异常处理模块

从 agent/engine.py 拆分，负责：
- 工具查找和执行
- 结构化异常转换
- 循环检测

增强功能 (v0.19.0):
- 可配置超时（从环境变量或参数获取）
- 工具执行计时
- 更详细的错误信息
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from ..core.exceptions import (
    ToolExecutionError,
    ToolInvalidArgsError,
    ToolNotFoundError,
)
from ..tools_runtime.base import BaseTool, ToolResult
from ..utils import debug, error, warn

# P1 优化: 工具超时配置集中化
# 默认超时配置（秒）
DEFAULT_TIMEOUTS: dict[str, int] = {
    'default': 30,       # 默认工具执行超时
    'bash': 60,          # Bash 命令执行超时
    'file': 30,          # 文件操作超时
    'search': 45,        # 搜索操作超时 (grep/glob)
}

# 工具类型到超时类型的映射
_TOOL_TYPE_MAP: dict[str, str] = {
    'bash': 'bash',
    'powershell': 'bash',
    'file_read': 'file',
    'file_edit': 'file',
    'file_write': 'file',
    'grep': 'search',
    'glob': 'search',
}


def get_tool_timeout(tool_name: str) -> int:
    """获取工具超时配置

    P1 优化 - 配置优先级:
    1. 环境变量 TOOL_TIMEOUTS (JSON 格式，如 '{"BashTool": 120, "FileReadTool": 60}')
    2. 环境变量 TOOL_TIMEOUT_<TOOL_NAME> (如 TOOL_TIMEOUT_BASH=120)
    3. 环境变量 COMMAND_TIMEOUT (通用命令超时)
    4. 内置默认值（按工具类型）

    参数:
        tool_name: 工具名称

    返回:
        超时时间（秒）
    """
    # 优先级 1: 检查集中式 JSON 配置
    tool_timeouts_str = os.environ.get('TOOL_TIMEOUTS')
    if tool_timeouts_str:
        try:
            tool_timeouts = json.loads(tool_timeouts_str)
            if tool_name in tool_timeouts:
                return int(tool_timeouts[tool_name])
            # 也尝试匹配不带 Tool 后缀的名称
            short_name = tool_name.replace('Tool', '')
            if short_name in tool_timeouts:
                return int(tool_timeouts[short_name])
        except (json.JSONDecodeError, ValueError):
            warn(f'环境变量 TOOL_TIMEOUTS 格式错误，请使用有效 JSON: {tool_timeouts_str[:50]}')

    # 优先级 2: 工具专用环境变量
    env_key = f'TOOL_TIMEOUT_{tool_name.upper().replace("TOOL", "")}'
    env_timeout = os.environ.get(env_key)
    if env_timeout:
        try:
            return int(env_timeout)
        except ValueError:
            pass

    # 优先级 3: 通用命令超时
    command_timeout = os.environ.get('COMMAND_TIMEOUT')
    if command_timeout:
        try:
            return int(command_timeout)
        except ValueError:
            pass

    # 优先级 4: 内置默认值（按工具类型）
    tool_name_lower = tool_name.lower()
    for keyword, timeout_type in _TOOL_TYPE_MAP.items():
        if keyword in tool_name_lower:
            return DEFAULT_TIMEOUTS[timeout_type]
    return DEFAULT_TIMEOUTS['default']


def parse_tool_calls(content: str) -> list[tuple[str, dict[str, Any]]]:
    """从 LLM 回复中解析工具调用

    支持格式：
    - JSON 格式：<tool>{"name": "BashTool", "args": {"command": "ls -la"}}</tool>

    注意：XML 格式（<tool>BashTool</tool><args>...</args>）已在 v0.11.0 中废弃。
    """
    tool_calls: list[tuple[str, dict[str, Any]]] = []

    # JSON 格式解析
    json_pattern = r'<tool>\s*(\{.*?\})\s*</tool>'
    json_matches = re.findall(json_pattern, content, re.DOTALL)

    for json_str in json_matches:
        try:
            data = json.loads(json_str.strip())
            tool_name = data.get('name', '')
            tool_args = data.get('args', {})
            if tool_name:
                tool_calls.append((tool_name, tool_args))
                debug(f'解析到工具调用: {tool_name}')
            else:
                warn(f'JSON 格式缺少 name 字段: {json_str[:50]}')
        except json.JSONDecodeError as e:
            warn(f'JSON 解析失败: {e}')

    return tool_calls


async def execute_tool(
    tools: dict[str, BaseTool],
    tool_name: str,
    tool_args: dict[str, Any],
    timeout: int | None = None,
) -> Any:
    """执行工具（集成结构化异常）

    增强功能 (v0.19.0):
    - 可配置超时（默认从环境变量或工具类型推断）
    - 执行计时
    - 更详细的错误信息
    - 有界线程池（防止高并发时耗尽系统资源）
    """
    # 查找工具
    tool = tools.get(tool_name)
    if tool is None:
        raise ToolNotFoundError(tool_name=tool_name)

    # 验证参数
    is_valid, error_msg = tool.validate(**tool_args)
    if not is_valid:
        raise ToolInvalidArgsError(tool_name=tool_name, reason=error_msg)

    # 获取超时配置
    if timeout is None:
        timeout = get_tool_timeout(tool_name)

    start_time = time.monotonic()
    try:
        # 使用有界线程池执行同步工具，配合 asyncio.wait_for 强制超时
        loop = asyncio.get_running_loop()
        executor = await _get_bounded_executor()
        result = await asyncio.wait_for(
            loop.run_in_executor(executor, lambda t=tool: t.execute(**tool_args)),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start_time
        debug(f'工具 {tool_name} 执行完成，耗时: {elapsed:.2f}s')
        return result
    except (ToolNotFoundError, ToolExecutionError):
        raise
    except TimeoutError as e:
        elapsed = time.monotonic() - start_time
        raise ToolExecutionError(
            message=f'工具 {tool_name} 执行超时 ({timeout}s)',
            details={
                'tool_name': tool_name,
                'timeout': timeout,
                'elapsed': round(elapsed, 2),
            },
        ) from e
    except Exception as e:
        elapsed = time.monotonic() - start_time
        error(f'工具 {tool_name} 执行异常: {e} (耗时: {elapsed:.2f}s)')
        raise ToolExecutionError(
            message=f'工具 {tool_name} 执行异常: {e}',
            details={
                'tool_name': tool_name,
                'exception_type': type(e).__name__,
                'elapsed': round(elapsed, 2),
            },
        ) from e


# 有界线程池（全局单例，防止高并发时耗尽系统资源）
_BOUNDED_EXECUTOR: ThreadPoolExecutor | None = None
_BOUNDED_EXECUTOR_MAX_WORKERS = 10  # 最大工作线程数
_EXECUTOR_LOCK = asyncio.Lock()


async def _get_bounded_executor() -> ThreadPoolExecutor:
    """获取有界线程池（全局单例，异步安全初始化）

    防止高并发时无限制创建线程导致系统资源耗尽。
    """
    global _BOUNDED_EXECUTOR
    if _BOUNDED_EXECUTOR is None:
        async with _EXECUTOR_LOCK:
            if _BOUNDED_EXECUTOR is None:
                _BOUNDED_EXECUTOR = ThreadPoolExecutor(max_workers=_BOUNDED_EXECUTOR_MAX_WORKERS)
    return _BOUNDED_EXECUTOR


def check_tool_call_loop(
    tool_call_history: list[tuple[str, str]],
    tool_name: str,
    tool_args: dict[str, Any],
    max_repeat_calls: int,
) -> tuple[bool, str]:
    """检查是否存在重复工具调用循环

    参数:
        tool_call_history: 工具调用历史
        tool_name: 工具名称
        tool_args: 工具参数
        max_repeat_calls: 最大重复调用次数

    返回:
        (is_loop, warning_message) 元组
    """
    call_signature = (tool_name, json.dumps(tool_args, sort_keys=True))
    repeat_count = tool_call_history.count(call_signature)
    if repeat_count >= max_repeat_calls:
        warning = (
            f'你已重复调用 {tool_name} 相同参数 {repeat_count + 1} 次。'
            f'请换一种方法或直接给出最终答案。'
        )
        return True, warning
    return False, ''


# ---------------------------------------------------------------------------
# 异步并行化执行引擎
# ---------------------------------------------------------------------------

@dataclass
class ParallelToolResult:
    """并行工具执行结果"""
    tool_name: str
    tool_args: dict[str, Any]
    result: Any
    is_error: bool = False
    elapsed: float = 0.0


async def execute_tools_parallel(
    tools: dict[str, BaseTool],
    tool_calls: list[tuple[str, dict[str, Any]]],
    timeout: int | None = None,
) -> list[ParallelToolResult]:
    """异步并行执行多个工具

    核心技术点:
    - 使用 ``asyncio.TaskGroup`` (Python 3.11+) 进行结构化并发管理
    - 不支持 TaskGroup 时自动回退到 ``asyncio.gather`` + `return_exceptions=True`
    - 每个工具保持独立超时、独立异常、独立计时
    - 单工具失败不影响其他工具执行

    参数:
        tools: 可用工具字典
        tool_calls: 工具调用列表 ``[(name, args), ...]``
        timeout: 统一超时（秒），为 None 时按各工具类型自动获取

    返回:
        ``ParallelToolResult`` 列表，顺序与输入一致
    """
    if not tool_calls:
        return []

    results: list[ParallelToolResult | None] = [None] * len(tool_calls)
    errors: dict[int, tuple[Exception, float]] = {}

    async def _run_one(
        idx: int, name: str, args: dict[str, Any],
    ) -> None:
        start = time.monotonic()
        try:
            t = timeout if timeout is not None else get_tool_timeout(name)
            result = await execute_tool(tools, name, args, timeout=t)
            elapsed = time.monotonic() - start
            results[idx] = ParallelToolResult(
                tool_name=name, tool_args=args,
                result=result, elapsed=elapsed,
            )
        except Exception as e:
            elapsed = time.monotonic() - start
            errors[idx] = (e, elapsed)

    tasks = [_run_one(i, name, args) for i, (name, args) in enumerate(tool_calls)]

    # Python 3.11+: 优先使用 TaskGroup（结构化并发，支持 cancel scope）
    # Fallback: asyncio.gather (Python 3.10 compatibility)
    try:
        async with asyncio.TaskGroup() as tg:
            for t in tasks:
                tg.create_task(t)
    except AttributeError:
        await asyncio.gather(*tasks, return_exceptions=True)

    # 组装结果
    out: list[ParallelToolResult] = []
    for i in range(len(tool_calls)):
        if i in errors:
            exc, elapsed = errors[i]
            name, args = tool_calls[i]
            out.append(ParallelToolResult(
                tool_name=name, tool_args=args,
                result=ToolResult(success=False, output='', error=str(exc)),
                is_error=True, elapsed=elapsed,
            ))
        elif results[i] is not None:
            out.append(results[i])  # type: ignore[arg-type]

    return out


def shutdown_executor() -> None:
    """关闭全局线程池，释放资源（应在进程退出前调用）"""
    global _BOUNDED_EXECUTOR
    if _BOUNDED_EXECUTOR is not None:
        _BOUNDED_EXECUTOR.shutdown(wait=False)
        _BOUNDED_EXECUTOR = None

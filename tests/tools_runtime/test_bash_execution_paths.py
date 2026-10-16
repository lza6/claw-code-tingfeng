"""BashTool 执行路径回归测试。

## 为什么需要这个文件

仓库里已有的 bash 测试都在**主线程直调** `BashTool.execute()`：

    # tests/test_manual_god_mode.py
    tool = BashTool(workdir=Path.cwd())
    tool.execute(command='...')

主线程有自动创建的事件循环，所以那条路径永远绿。但**生产环境不走那条路**：

    src/agent/engine.py:391  注入 _execute_tool = tool_manager.execute_tool
      -> src/agent/tool_executor.py:170
         loop.run_in_executor(executor, lambda: tool.execute(**args))

工具被丢进 `ThreadPoolExecutor` 工作线程执行。**工作线程没有事件循环**，
`asyncio.get_event_loop()` 在 Python 3.10 直接抛
`RuntimeError: There is no current event loop in thread ...`，
被外层 `except` 吞成一句"执行失败"。

后果：Agent 的**每一次** bash 调用都失败 —— 跑测试、git、构建、
任何命令全部不可用，而这个缺陷对既有测试完全不可见。

本文件锁定三种执行上下文都要工作。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from src.agent.tool_executor import execute_tool
from src.tools_runtime.bash_tool import BashTool
from src.tools_runtime.file_read_tool import FileReadTool


@pytest.fixture
def workdir() -> Path:
    return Path.cwd()


@pytest.fixture
def tools(workdir: Path) -> dict:
    """按生产 engine.py 的方式构造工具池"""
    return {
        "BashTool": BashTool(workdir=workdir),
        "FileReadTool": FileReadTool(base_path=workdir),
    }


# ---------------------------------------------------------------------------
# 生产路径：execute_tool（ThreadPoolExecutor 工作线程）
# ---------------------------------------------------------------------------


class TestProductionPath:
    """经 execute_tool 调用 —— 这是 Agent 真实走的路径"""

    @pytest.mark.asyncio
    async def test_bash_runs_in_worker_thread(self, tools):
        """回归核心：工作线程无事件循环时也必须能跑 bash

        修复前此处返回 success=False，error 含
        "There is no current event loop in thread 'ThreadPoolExecutor-0_0'"。
        """
        result = await execute_tool(tools, "BashTool", {"command": "echo hello-from-agent"})

        assert result.success is True, f"bash 在 Agent 路径失败: {result.error}"
        assert "hello-from-agent" in result.output
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_error_message_does_not_mention_event_loop(self, tools):
        """失败原因不应是事件循环问题 —— 那是框架缺陷而非命令问题"""
        result = await execute_tool(tools, "BashTool", {"command": "echo probe"})

        assert "event loop" not in (result.error or "").lower(), (
            f"仍受事件循环缺陷影响: {result.error}"
        )

    @pytest.mark.asyncio
    async def test_production_path_works_while_inside_event_loop(self, tools):
        """在生产路径里调用时，当前协程运行于事件循环中。

        注意不要把「主线程直调」当对照组：pytest-asyncio 的 auto 模式下
        测试函数本身跑在事件循环里，此时直调会正确地落入"嵌套循环"分支
        并提示改用 async 入口 —— 那是**正确行为**，不是缺陷。
        真正的对照是：有循环时 `execute_tool` 仍要能跑通（它把工具丢进
        工作线程，从而绕开当前循环）。
        """
        result = await execute_tool(tools, "BashTool", {"command": "echo parity"})

        assert result.success is True, result.error
        assert result.output.strip() == "parity"


# ---------------------------------------------------------------------------
# 三种执行上下文
# ---------------------------------------------------------------------------


class TestExecutionContexts:
    """execute() 必须覆盖三种调用上下文，缺一即该上下文下 BashTool 全废"""

    def test_main_thread_without_running_loop(self, workdir):
        """上下文 A：主线程且无运行中的循环（脚本 / 既有测试）"""
        result = BashTool(workdir=workdir).execute(command="echo main-thread")
        assert result.success is True, result.error
        assert "main-thread" in result.output

    def test_bare_worker_thread(self, workdir):
        """上下文 B：无事件循环的裸线程（这是生产实际情形）"""
        box: dict = {}

        def _run() -> None:
            box["result"] = BashTool(workdir=workdir).execute(command="echo worker-thread")

        thread = threading.Thread(target=_run)
        thread.start()
        thread.join(timeout=30)

        assert "result" in box, "线程未在超时内完成"
        assert box["result"].success is True, box["result"].error
        assert "worker-thread" in box["result"].output

    def test_running_loop_rejects_sync_call(self, workdir):
        """上下文 C：已有运行中的循环 —— 应给出明确指引而非静默失败"""
        async def _attempt():
            return BashTool(workdir=workdir).execute(command="echo nested")

        result = asyncio.run(_attempt())

        assert result.success is False
        assert "async_execute" in (result.error or ""), (
            f"嵌套循环场景应提示改用异步入口: {result.error}"
        )


# ---------------------------------------------------------------------------
# 与其它工具的对比（证明不是执行器整体坏）
# ---------------------------------------------------------------------------


class TestNotAUniversalFailure:
    @pytest.mark.asyncio
    async def test_file_tool_still_works(self, tools):
        """同期 FileReadTool 一直正常 —— 佐证问题是 bash 独有的桥接缺陷"""
        result = await execute_tool(tools, "FileReadTool", {"file_path": "README.md"})

        assert result.success is True, result.error
        assert result.output


# ---------------------------------------------------------------------------
# 工具描述如实声明能力边界
# ---------------------------------------------------------------------------


class TestCapabilityDisclosure:
    """描述里必须声明不支持 shell 特性。

    实现走 shlex.split + 参数列表执行（无 shell），管道/重定向/命令串联
    天然不可用。不声明的后果：模型会自然写 `ls | wc -l`，
    拿到一句 `ls: cannot access '|'` 的困惑报错，白白浪费迭代。
    """

    def test_description_mentions_pipe_limitation(self):
        desc = BashTool.description
        assert "|" in desc or "管道" in desc, "描述未声明不支持管道符"
        assert "重定向" in desc or ">" in desc, "描述未声明不支持重定向"

    def test_description_mentions_command_chaining(self):
        desc = BashTool.description
        assert "&&" in desc or "串联" in desc, "描述未声明不支持命令串联"


# ---------------------------------------------------------------------------
# 安全边界仍然生效（修复不得削弱防护）
# ---------------------------------------------------------------------------


class TestSecurityStillEnforced:
    @pytest.mark.asyncio
    async def test_dangerous_command_still_blocked(self, tools):
        """桥接修复不得绕过危险命令拦截"""
        with pytest.raises(Exception):  # noqa: B017 - ToolInvalidArgsError
            await execute_tool(tools, "BashTool", {"command": "rm -rf /"})

    @pytest.mark.asyncio
    async def test_readonly_command_allowed_in_normal_mode(self, tools):
        """正常模式下的只读命令应放行 —— 回归"全部命令都被拦"的误伤"""
        result = await execute_tool(tools, "BashTool", {"command": "echo readonly-ok"})
        assert result.success is True, result.error

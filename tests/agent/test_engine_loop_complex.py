"""src/agent/engine_loop.py 的复杂路径测试 - 事务、自愈、并行协作"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.engine_loop import AgentLoopConfig, _run_agent_loop
from src.llm import LLMMessage, LLMResponse
from src.tools_runtime.base import ToolResult


@pytest.mark.asyncio
async def test_tool_transaction_commit():
    """测试文件编辑工具成功时提交事务"""
    patcher = MagicMock()
    patcher.begin_transaction = AsyncMock()
    patcher.commit = MagicMock()
    patcher.rollback = MagicMock()

    class FileToolProvider:
        async def chat(self, messages):
            return LLMResponse(
                content='调用工具',
                model="mock",
                usage={"total_tokens": 0},
            )

    execute_tool_fn = AsyncMock(return_value=ToolResult(success=True, output="edit ok"))

    config = AgentLoopConfig(
        goal="edit file",
        llm_provider=FileToolProvider(),
        messages=[],
        max_iterations=1,
        system_prompt="sys",
        tools={},
        _parse_tool_calls=lambda c: [("FileEdit", {"file_path": "test.py", "content": "new"})],
        _execute_tool=execute_tool_fn,
        patcher=patcher
    )

    await _run_agent_loop(config=config)

    # 验证事务流程
    patcher.begin_transaction.assert_called_once()
    patcher.commit.assert_called_once()
    patcher.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_tool_transaction_rollback_and_heal():
    """测试文件编辑工具失败时回滚并触发自愈"""
    patcher = MagicMock()
    patcher.begin_transaction = AsyncMock()
    patcher.commit = MagicMock()
    patcher.rollback = MagicMock()

    healing_engine = MagicMock()
    healing_engine.heal = AsyncMock()

    class FileToolProvider:
        async def chat(self, messages):
            return LLMResponse(
                content='调用工具',
                model="mock",
                usage={"total_tokens": 0},
            )

    execute_tool_fn = AsyncMock(return_value=ToolResult(success=False, output="", error="syntax error"))

    config = AgentLoopConfig(
        goal="edit file",
        llm_provider=FileToolProvider(),
        messages=[],
        max_iterations=1,
        system_prompt="sys",
        tools={},
        _parse_tool_calls=lambda c: [("FileEdit", {"file_path": "test.py", "content": "bad code"})],
        _execute_tool=execute_tool_fn,
        patcher=patcher,
        healing_engine=healing_engine
    )

    await _run_agent_loop(config=config)

    # 验证事务回滚
    patcher.rollback.assert_called_once()
    patcher.commit.assert_not_called()
    # 验证触发自愈
    healing_engine.heal.assert_called_once()


@pytest.mark.asyncio
async def test_parallel_tools_transaction():
    """测试多个并行文件工具的事务处理"""
    patcher = MagicMock()
    patcher.begin_transaction = AsyncMock()
    patcher.commit = MagicMock()
    patcher.rollback = MagicMock()

    class ParallelToolProvider:
        async def chat(self, messages):
            return LLMResponse(
                content='两个工具',
                model="mock",
                usage={"total_tokens": 0},
            )

    execute_tool_fn = AsyncMock(return_value=ToolResult(success=True, output="ok"))

    config = AgentLoopConfig(
        goal="edit files",
        llm_provider=ParallelToolProvider(),
        messages=[],
        max_iterations=1,
        system_prompt="sys",
        tools={},
        _parse_tool_calls=lambda c: [
            ("FileEdit", {"file_path": "a.py"}),
            ("FileEdit", {"file_path": "b.py"})
        ],
        _execute_tool=execute_tool_fn,
        patcher=patcher
    )

    await _run_agent_loop(config=config)

    # 验证事务包含多个文件
    args, _ = patcher.begin_transaction.call_args
    paths = args[0]
    assert len(paths) == 2
    assert Path("a.py") in paths
    assert Path("b.py") in paths
    patcher.commit.assert_called_once()


@pytest.mark.asyncio
async def test_world_model_prefetch_trigger():
    """测试工具执行成功后触发 WorldModel 预取"""
    world_model = MagicMock()
    world_model.prefetch_context = AsyncMock()

    class ReadToolProvider:
        async def chat(self, messages):
            return LLMResponse(
                content='读取文件',
                model="mock",
                usage={"total_tokens": 0},
            )

    execute_tool_fn = AsyncMock(return_value=ToolResult(success=True, output="file content"))

    config = AgentLoopConfig(
        goal="read file",
        llm_provider=ReadToolProvider(),
        messages=[],
        max_iterations=1,
        system_prompt="sys",
        tools={},
        _parse_tool_calls=lambda c: [("ReadFile", {"file_path": "src/main.py"})],
        _execute_tool=execute_tool_fn,
        world_model=world_model
    )

    await _run_agent_loop(config=config)

    # 等待背景任务完成 (如果有的话)
    if config._background_tasks:
        await asyncio.gather(*config._background_tasks)

    # 验证预取被调用
    world_model.prefetch_context.assert_called_once_with("src/main.py")


@pytest.mark.asyncio
async def test_deep_rag_patch_trigger():
    """测试检测到信息缺失时触发 Deep RAG 补丁"""
    deep_rag_patch = AsyncMock(return_value="found info")

    class MissingInfoProvider:
        async def chat(self, messages):
            return LLMResponse(
                content='尝试查找',
                model="mock",
                usage={"total_tokens": 0},
            )

    execute_tool_fn = AsyncMock(return_value=ToolResult(success=False, output="Error: symbol not found"))

    config = AgentLoopConfig(
        goal="find symbol",
        llm_provider=MissingInfoProvider(),
        messages=[],
        max_iterations=1,
        system_prompt="sys",
        tools={},
        _parse_tool_calls=lambda c: [("Grep", {"pattern": "foo"})],
        _execute_tool=execute_tool_fn,
        _missing_info_patterns=["not found"],
        _deep_rag_patch=deep_rag_patch
    )

    await _run_agent_loop(config=config)

    # 验证 RAG 补丁被触发
    deep_rag_patch.assert_called_once()
    # 验证补丁内容进入了消息列表
    last_msg = config.messages[-1]
    assert "found info" in last_msg.content
    assert "补充参考资料" in last_msg.content

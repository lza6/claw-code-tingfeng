"""Integration tests for WorldModel prefetching in Agent Engine"""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from src.agent.engine_loop import _run_agent_loop, AgentLoopConfig
from src.llm import LLMMessage, LLMResponse
from src.tools_runtime.base import ToolResult

@pytest.mark.asyncio
async def test_world_model_prefetch_integration():
    """Verify that WorldModel.prefetch_context is triggered after successful file tool execution."""

    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=LLMResponse(
        content='<tool>{"name": "FileReadTool", "args": {"file_path": "test.py"}}</tool>',
        model='test-model',
        usage={'total_tokens': 10, 'prompt_tokens': 5, 'completion_tokens': 5}
    ))

    mock_world_model = MagicMock()
    mock_world_model.prefetch_context = AsyncMock(return_value={})

    mock_execute = AsyncMock(return_value=ToolResult(success=True, output='test content'))

    config = AgentLoopConfig(
        goal='Read test.py',
        llm_provider=mock_llm,
        messages=[],
        max_iterations=1,
        system_prompt='You are a helper',
        tools={'FileReadTool': MagicMock()},
        world_model=mock_world_model,
        _execute_tool=mock_execute,
        _parse_tool_calls=lambda x: [("FileReadTool", {"file_path": "test.py"})]
    )

    # Run the loop
    await _run_agent_loop(config=config)

    # Wait a bit for the async task to be scheduled/executed
    await asyncio.sleep(0.1)

    # Verify prefetch_context was called with the correct file path
    mock_world_model.prefetch_context.assert_called_with("test.py")

@pytest.mark.asyncio
async def test_world_model_no_prefetch_on_failure():
    """Verify that WorldModel.prefetch_context is NOT triggered after failed tool execution."""

    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=LLMResponse(
        content='<tool>{"name": "FileReadTool", "args": {"file_path": "test.py"}}</tool>',
        model='test-model',
        usage={'total_tokens': 10, 'prompt_tokens': 5, 'completion_tokens': 5}
    ))

    mock_world_model = MagicMock()
    mock_world_model.prefetch_context = AsyncMock()

    mock_execute = AsyncMock(return_value=ToolResult(success=False, output='', error='File not found'))

    config = AgentLoopConfig(
        goal='Read test.py',
        llm_provider=mock_llm,
        messages=[],
        max_iterations=1,
        system_prompt='You are a helper',
        tools={'FileReadTool': MagicMock()},
        world_model=mock_world_model,
        _execute_tool=mock_execute,
        _parse_tool_calls=lambda x: [("FileReadTool", {"file_path": "test.py"})]
    )

    await _run_agent_loop(config=config)
    await asyncio.sleep(0.1)

    # Should NOT be called
    mock_world_model.prefetch_context.assert_not_called()

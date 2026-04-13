import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from src.agent.engine import AgentEngine
from src.llm import LLMConfig, LLMProviderType

@pytest.mark.asyncio
async def test_agent_engine_run_integration():
    # Mock LLM provider
    mock_provider = MagicMock()
    mock_provider.generate_response = AsyncMock(return_value=MagicMock(
        content="Final result",
        usage={"total_tokens": 100},
        model="gpt-4o",
        tool_calls=[]
    ))

    config = LLMConfig(provider=LLMProviderType.OPENAI, api_key="test", model="gpt-4o")

    # 使用 Patch 掉内部耗时或复杂的初始化
    with patch('src.agent.engine.create_llm_provider', return_value=mock_provider), \
         patch('src.agent.engine_loop._run_agent_loop', new_callable=AsyncMock) as mock_loop, \
         patch('src.core.config.get_settings') as mock_get_settings:

        mock_loop.return_value = {'session': MagicMock(final_result="Final result")}
        mock_get_settings.return_value = MagicMock()

        engine = AgentEngine(llm_config=config)
        # 修复传参错误，kwargs 不应包含 stream
        result = await engine.run("test goal")

        assert result is not None
        mock_loop.assert_called_once()

@pytest.mark.asyncio
async def test_agent_engine_generate_commit_message():
    # Mock LLM provider for weak model
    mock_provider = MagicMock()
    mock_provider.chat = AsyncMock(return_value=MagicMock(
        content="update: fixed something",
        usage={"total_tokens": 10},
        model="gpt-4o-mini"
    ))

    config = LLMConfig(provider=LLMProviderType.OPENAI, api_key="test", model="gpt-4o")
    with patch('src.core.config.get_settings', return_value=MagicMock()), \
         patch('src.agent.engine.create_llm_provider', return_value=mock_provider):
        engine = AgentEngine(llm_config=config)

        msg = await engine.generate_commit_message("diff data")
        assert "update:" in msg

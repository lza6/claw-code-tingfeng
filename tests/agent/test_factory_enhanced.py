import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.agent.factory import create_agent_engine
from src.llm import LLMProviderType

def test_create_agent_engine_default():
    """测试默认参数创建引擎"""
    with patch('src.agent.engine.AgentEngine.__init__', return_value=None) as mock_init:
        engine = create_agent_engine(api_key="test_key")
        assert engine is not None
        mock_init.assert_called_once()
        args, kwargs = mock_init.call_args
        assert kwargs['llm_config'].provider == LLMProviderType.OPENAI
        assert kwargs['llm_config'].api_key == "test_key"
        assert kwargs['llm_config'].model == "gpt-4o"

def test_create_agent_engine_anthropic():
    """测试 Anthropic 提供商"""
    with patch('src.agent.engine.AgentEngine.__init__', return_value=None) as mock_init:
        engine = create_agent_engine(provider_type="anthropic", api_key="test_key")
        args, kwargs = mock_init.call_args
        assert kwargs['llm_config'].provider == LLMProviderType.ANTHROPIC
        assert kwargs['llm_config'].model == "claude-3-5-sonnet-20241022"

def test_create_agent_engine_from_env():
    """测试从环境变量加载"""
    mock_config = MagicMock()
    mock_config.provider = LLMProviderType.DEEPSEEK

    with patch('src.llm.LLMConfig.from_env', return_value=mock_config), \
         patch('src.core.config.get_settings', return_value=MagicMock(developer_mode=True)), \
         patch('src.agent.engine.AgentEngine.__init__', return_value=None) as mock_init:

        engine = create_agent_engine(api_key=None)
        assert engine is not None
        args, kwargs = mock_init.call_args
        assert kwargs['llm_config'] == mock_config
        assert kwargs['developer_mode'] is True

def test_create_agent_engine_custom_workdir():
    """测试自定义工作目录"""
    custom_dir = Path("/tmp/test_clawd")
    with patch('src.agent.engine.AgentEngine.__init__', return_value=None) as mock_init:
        create_agent_engine(api_key="test", workdir=custom_dir)
        args, kwargs = mock_init.call_args
        assert kwargs['workdir'] == custom_dir

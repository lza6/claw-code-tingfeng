import pytest
from pathlib import Path
from src.agent.engine import AgentEngine
from src.llm import LLMConfig, LLMProviderType

@pytest.fixture
def agent_engine():
    config = LLMConfig(
        provider=LLMProviderType.ANTHROPIC,
        model="claude-3-haiku-20240307",
        api_key="test-key"
    )
    return AgentEngine(llm_config=config, workdir=Path("/tmp"))

def test_engine_initialization(agent_engine):
    """验证引擎初始化是否正常"""
    assert agent_engine is not None
    assert agent_engine.edit_format == "editblock"
    assert "BashTool" in agent_engine.tools

def test_engine_metrics_delegation(agent_engine):
    """验证性能指标是否正确代理"""
    metrics = agent_engine.get_perf_metrics()
    assert isinstance(metrics, dict)
    assert "llm_call_count" in metrics

def test_engine_events_delegation(agent_engine):
    """验证事件发布接口是否可用"""
    # 只要不抛出 AttributeError 即可
    agent_engine.publish_task_started("test goal", 10)
    assert agent_engine.events is not None

def test_engine_tool_access(agent_engine):
    """验证工具访问接口"""
    tools = agent_engine.get_available_tools()
    assert "BashTool" in tools
    assert "FileEditTool" in tools

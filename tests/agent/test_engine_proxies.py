"""Engine Proxies 测试 - 覆盖 src/agent/_engine_proxies.py"""

import pytest
from src.agent._engine_proxies import (
    setup_event_proxies,
    setup_lifecycle_proxies,
    setup_stream_proxies,
)


class TestSetupProxies:
    """代理设置测试"""

    def test_setup_event_proxies(self):
        """测试事件代理设置"""
        from src.agent.engine import AgentEngine
        engine = AgentEngine()
        # Should not raise
        setup_event_proxies(engine)

    def test_setup_lifecycle_proxies(self):
        """测试生命周期代理设置"""
        from src.agent.engine import AgentEngine
        engine = AgentEngine()
        setup_lifecycle_proxies(engine)

    def test_setup_stream_proxies(self):
        """测试流代理设置"""
        from src.agent.engine import AgentEngine
        engine = AgentEngine()
        setup_stream_proxies(engine)
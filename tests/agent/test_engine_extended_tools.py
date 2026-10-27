"""AgentEngine 扩展工具装配测试（MCP 桥接 + 逆向工具，mock 外部依赖）"""
import asyncio
import json

import pytest

from src.agent.engine import AgentEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """构造最小可用的 AgentEngine（mock 重依赖初始化）"""
    eng = object.__new__(AgentEngine)
    eng.workdir = tmp_path
    eng.tools = {}
    eng._extended_tools_loaded = False

    import logging

    eng.logger = logging.getLogger("test.engine")
    return eng


class TestReverseToolsAssembly:
    def test_assembles_reverse_tools(self, engine):
        asyncio.run(engine._load_extended_tools())
        names = set(engine.tools)
        # 逆向工具 name 属性为小写
        assert any("ghidra" in n for n in names)
        assert any("strings" in n for n in names)
        assert any("entropy" in n for n in names)
        assert any("hexdump" in n for n in names)
        assert engine._extended_tools_loaded is True

    def test_idempotent(self, engine):
        asyncio.run(engine._load_extended_tools())
        count = len(engine.tools)
        asyncio.run(engine._load_extended_tools())
        assert len(engine.tools) == count

    def test_degrades_on_failure(self, engine, monkeypatch):
        import src.reverse_tools as rt

        def boom():
            raise RuntimeError("导入失败模拟")

        monkeypatch.setattr(rt, "get_all_tools", boom)
        # 不应抛异常
        asyncio.run(engine._load_extended_tools())
        assert engine._extended_tools_loaded is True


class TestMCPBridgeAssembly:
    def test_skips_when_no_config(self, engine, tmp_path):
        asyncio.run(engine._load_extended_tools())
        # 无 mcp_servers.json 时只有逆向工具
        assert any("ghidra" in n for n in engine.tools)
        assert not any(n.startswith("mcp__") for n in engine.tools)

    def test_quarantined_server_not_bridged(self, engine, tmp_path, monkeypatch):
        # 配置一个 server，但治理状态为检疫期 → 不桥接
        cfg_dir = tmp_path / ".clawd"
        cfg_dir.mkdir(exist_ok=True)
        (cfg_dir / "mcp_servers.json").write_text(
            json.dumps({"servers": [
                {"name": "ghidra", "transport": "http", "url": "http://localhost:8080"}
            ]}),
            encoding="utf-8",
        )
        # 治理状态文件：检疫期（默认，不 approve）
        asyncio.run(engine._load_extended_tools())
        assert not any(n.startswith("mcp__ghidra") for n in engine.tools)

    def test_approved_server_bridged(self, engine, tmp_path, monkeypatch):
        cfg_dir = tmp_path / ".clawd"
        cfg_dir.mkdir(exist_ok=True)
        (cfg_dir / "mcp_servers.json").write_text(
            json.dumps({"servers": [
                {"name": "ghidra", "transport": "http", "url": "http://localhost:8080"}
            ]}),
            encoding="utf-8",
        )
        # 预先 approve 该 server
        from src.mcp.governance import ToolGovernor

        gov = ToolGovernor(state_path=tmp_path / ".clawd" / "mcp_governance.json")
        gov.approve("ghidra", "测试放行")

        # mock 桥接：返回一个假工具
        from src.mcp.client import MCPToolInfo
        from src.mcp.tool_bridge import MCPExternalTool

        class _FakeManager:
            def register(self, cfg):
                pass

            async def discover_tools(self, server):
                return [MCPToolInfo(
                    server=server, name="decompile",
                    description="d", input_schema={},
                )]

            async def call(self, server, tool, args=None):
                return "ok"

        import src.mcp.client as client_mod

        monkeypatch.setattr(client_mod, "get_mcp_manager", lambda: _FakeManager())

        # ToolGovernor 单例路径: engine 用默认 state_path —— 需要 monkeypatch
        import src.mcp.governance as gov_mod

        real_gov = ToolGovernor(state_path=tmp_path / ".clawd" / "mcp_governance.json")
        real_gov.approve("ghidra")
        monkeypatch.setattr(gov_mod, "ToolGovernor", lambda *a, **kw: real_gov)

        # bridge_server_tools 里 registry=None 会用全局 ToolRegistry（副作用可接受）
        asyncio.run(engine._load_extended_tools())
        assert "mcp__ghidra__decompile" in engine.tools

"""Clawd 领域能力 MCP Server 启动器

外部引擎（Codex / OpenCode / OpenClaw …）以 `command + args` 方式拉起 MCP server。
直接用 `python -m src.mcp.domain_server` 在某些客户端的精简环境下会因包初始化
（日志/遥测等写 stdout）污染协议流或直接退出，故提供这个无副作用的薄启动器：
只做 sys.path 修补 + 调 DomainServer.serve()，不 import 项目其它模块。

用法: python scripts/mcp_domain_launcher.py [--root <项目根>]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mcp.domain_server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

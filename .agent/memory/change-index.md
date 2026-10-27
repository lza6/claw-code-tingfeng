# 变更索引（change-index）

## 2026-10-27 超级智能体增强
| 类型 | 路径 | 说明 |
|------|------|------|
| 新增 | src/mcp/client.py | MCP Client stdio+HTTP |
| 新增 | src/mcp/tool_bridge.py | 外部工具→BaseTool 适配 |
| 新增 | src/mcp/governance.py | 工具签名+检疫审批 |
| 新增 | src/reasoning/patterns.py | 4 推理模式 |
| 新增 | src/reasoning/context_engineering.py | 截断+历史压缩 |
| 新增 | src/security/catalog.py + catalog/recon.yaml | 安全工具目录 |
| 新增 | src/reverse_tools/* | 8 个逆向工具 |
| 新增 | src/cli_handlers/reason_handler.py | reason 处理器 |
| 修改 | src/cli_handlers/__init__.py | 注册 reason 命令 |
| 修改 | src/cli/entrypoint.py | Typer reason 命令 |
| 修改 | src/main.py | argparse reason subparser + 命令分组 |
| 修改 | src/agent/engine.py | +62 行：_load_extended_tools 装配 |
| 新增 | skills/reverse/ | 51 个 SKILL.md + ghidra 脚本 + 路由表 |
| 新增 | tests/{mcp,reasoning,security,reverse_tools,agent/test_engine_extended_tools.py,cli_handlers/test_reason_handler.py} | 116 测试 |
| 新增 | docs/ENHANCEMENT_GUIDE.md | 使用与运维指南 |
| 新增 | .agent/skills/clawd-extension-sop.md | 扩展开发 SOP |
| 新增 | .agent/memory/{audit-history,verified-scope,known-issues}.md | 记忆文件 |
| 新增 | reports/change-report-2026-10-27.html | HTML 变更报告 |
| 修改 | workflow_status.md | 收口台账 |

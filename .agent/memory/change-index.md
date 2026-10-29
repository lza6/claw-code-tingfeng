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

## 2026-10-29 v0.76.5~v0.76.6 审计 P0/P1 清零 + 功能面补缺
| 类型 | 路径 | 说明 |
|------|------|------|
| 新增 | src/core/mcp/stdio_server.py | 通用 stdio JSON-RPC 骨架（4 个 server 此前无入口） |
| 新增 | src/agent/review_team.py | 多角色并行评审（确定性裁决，可注入 provider） |
| 新增 | src/cli/explain.py | `clawd explain` 中文解释器（零 LLM 调用） |
| 新增 | docs/adr/0018-mcp-servers-single-source.md | core/mcp 为唯一真相源 |
| 新增 | docs/adr/0019-hooks-package-is-reference-only.md | src/hooks 参考快照不接线 |
| 新增 | src/eval/datasets/honesty.json | 三态评测样例（pass/fail/unknown） |
| 改写 | docs/getting-started.md | 产品上手教程（原内容移入 docs/skills-distribution.md） |
| 修改 | src/agent/swarm/roles.py | 补 `AgentRole.CRITIC`（ralplan 默认路径崩溃） |
| 修改 | src/agent/swarm/worktree_manager.py | integrator 合并从假成功改为真实文件级合并 |
| 修改 | src/agent/engine.py | hook 接线（SESSION/PRE_TOOL_USE/POST_TOOL_USE/TOOL_ERROR） |
| 修改 | src/agent/skill_loader.py | 递归发现（63→113）+ 正文上限 26k + 截断告警 |
| 修改 | src/eval/* | 三态 + 基线缺失不再"通过" |
| 修改 | src/cli/rich_hud.py + repl_task.py | 真实 rich 渲染 + 最终答案打印 |
| 修改 | src/core/quality_gate.py / workflow/task_planner.py | 聚合判定 / 悬空依赖抛错 |
| 修改 | pyproject.toml | 打包包含 prompts/ |

# 变更索引（change-index）

## 2026-10-30 v0.88.0 客户端去垃圾（7 个观感缺陷 + 停止生成）
| 类型 | 路径 | 说明 |
|------|------|------|
| 修改 | desktop/web/index.html | 布局兜底（main 限高 + view 内滚 + 侧栏分区滚动）；空态/摘要/停止态样式；设置页与用量页过时文案（SQLite→providers.json、`.clawd/clawd.db`→`<数据目录>`) |
| 修改 | desktop/web/app.js | `stripToolProtocol()` 剥 3 种工具协议（括号平衡取 JSON）；`stripAttachmentNote()` 气泡/标题去提示词；`humanizeError()` + 3s 去重；`setBusy()` 忙时变停止；`resetChatArea()` 重置流式状态；迟到事件丢弃；空态欢迎区；会话列表折叠；`currentSessionId` 续聊 |
| 修改 | src/server/ws/manager.py | run 起独立 task（不再阻塞消息循环）；新增 `cancel` 处理；`E_BUSY` 防并发；`_run_and_reply` 兜底回包 |
| 修改 | src/server/ws/sessions.py | `ConnectionSession.run_task` 槽 |
| 修改 | src/server/handlers.py | 透传 `session_id` 给引擎；响应带 `session_id` |
| 修改 | src/agent/engine.py | `session_id_hint` + `append=True` + `last_session_id` |
| 修改 | src/core/session_bridge.py | `persist_agent_session(append=)`：追加到同一会话并保留 title/created_at |
| 新增 | tests/core/test_session_append.py | 5 条（追加不覆盖/保留 title/created_at/无 append 覆盖/文件不存在） |
| 新增 | tests/server/test_cancel.py | 3 条（run 不阻塞循环+真打断/E_BUSY/空 cancel 无害） |
| 修改 | desktop/ui_console_e2e.mjs | 28 → 31 项；忙判定改 `stop-mode`（按钮不再 disabled）；分组断言随折叠调整；等待流式收尾 2.2s |
| 修改 | desktop/{final_verify,ui_snapshot,ui_e2e_real}.mjs | 忙判定同步改 `stop-mode` |

## 2026-10-30 v0.87.0 真多模态视觉输入

| 类型 | 路径 | 说明 |
|------|------|------|
| 新增 | src/llm/vision.py | `supports_vision()`（模型白名单 + CLAWD_VISION 双向强制）+ `build_image_blocks()`（路径→image_url 内容块，≤2MB/≤4 张） |
| 修改 | src/llm/config.py | `LLMMessage.content: str \| list[dict]`（无图仍是 str） |
| 修改 | src/agent/engine_loop.py | `AgentLoopConfig.images` + `build_initial_messages` 拼内容块 |
| 修改 | src/agent/engine.py | `run/run_stream(images=)` 透传 |
| 修改 | src/server/handlers.py | `/run` 按 `supports_vision(模型)` 分流（视觉→内容块；否则路径告知）；`models_list` 带 `vision` 字段 |
| 修改 | src/server/websocket_server.py | `/api/models` 带 `vision` 字段 |
| 修改 | desktop/web/app.js + index.html | 模型列表标「👁 可看图」；不支持视觉时附件 chip 加 `👁✕` 虚线角标 |
| 新增 | tests/llm/test_vision_blocks.py（13）+ tests/server/test_vision_pass_through.py（6） | 能力判定/块构造/回退/透传 |
| 修改 | desktop/ui_console_e2e.mjs | 27 → 28 项（模型视觉标注与后端一致） |
| 修改 | scripts/diag_restart*.ps1、%TEMP%/clawd-install-e2e.ps1 | 安装包改为动态查找最新 Setup（不再写死版本号） |

## 2026-10-30 v0.86.0 桌面端收口（会话分组 / toast / 两个启动级 bug）
| 类型 | 路径 | 说明 |
|------|------|------|
| 修改 | src/core/session_bridge.py | `persist_agent_session(..., workdir=)` → metadata.workdir（侧栏分组依据） |
| 修改 | src/agent/engine.py | 落盘时传 `workdir=self.workdir` |
| 修改 | src/server/websocket_server.py | `/api/sessions`、`/api/session` 由 `cwd/.clawd/sessions` 改 `data_path('sessions')`；列表带 workdir/model/provider |
| 修改 | desktop/web/app.js | 会话按项目分组渲染；右下角 toast（`window.__clawdToast`）；更新状态接 toast；删除"设置占位"过期注释 |
| 修改 | desktop/web/index.html | `#toastHost` 容器 + `.toast*` / `.session-group*` 样式 |
| 修改 | desktop/electron/main.js | 删 `registerIpcHandlers` 内重复解构（TDZ 启动崩溃）；新增 `clawd:quit-and-install` |
| 修改 | desktop/electron/preload.js | 暴露 `quitAndInstall()` |
| 修改 | desktop/ui_console_e2e.mjs | 20→24 项，扩到 27 项（分组数/ workdir 字段 / toast 位置） |
| 新增 | tests/server/test_sessions_api.py | 4 条真 HTTP：数据目录跟随、workdir 字段、详情、404 |
| 新增 | tests/test_electron_main_static.py | 7 条静态检查（含 TDZ 先用后声明，反向验证过） |
| 修改 | tests/core/test_session_persist_structure.py | +3 条 workdir metadata |
| 修改 | CHANGELOG.md / workflow_status.md / .agent/memory/change-index.md | 记录 |
| 修改 | scripts/prepare_host_bundle.py | 依赖闭包改为空格分隔+分批；dist-info 随包复制；顶层 DLL 全量；禁止复制 .pth；[5/5] 真实 import 自检 + 缺依赖自动补齐 + 打包后清脏数据 |
| 修改 | docs/MAINTENANCE.md | 新增 3.5 桌面端接口 SOP；发布检查单补"桌面端出包三步" |
| 修改 | docs/getting-started.md | 4.6 改为 JSON 存储与数据目录表；新增 4.7 项目/会话分组/更新提示 |
| 新增 | docs/adr/0022-desktop-data-dir-and-storage.md | 数据目录分离 + JSON vs SQLite 选型决策 |
| 新增 | scripts/diag_desktop_start.ps1 | 装机启动排错（抓 stderr / shell.log / 数据目录 / 端口文件） |
| 新增 | scripts/diag_restart.ps1 | 装机重启排错（装→启动→杀→再启动并逐秒观察，分清产品问题 vs E2E 脚本问题） |
| 修改 | desktop/electron/main.js | 加 uncaughtException/unhandledRejection 落盘 + 启动流程 try/catch（闪退留痕） |
| 修改 | tests/core/test_packaging_contract.py | +6 条打包契约（pip 参数/自检/dist-info/禁 .pth/DLL/自动补齐） |
| 修改 | %TEMP%/clawd-install-e2e.ps1 | 控制台 E2E 输出扩到 40 行；新增 STEP2f（重启后 /api/sessions + workdir 字段，带重试） |
| 修改 | README.md | 桌面章节重写（工作台能力/架构/存储/E2E 清单）；指标改实测值 |

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

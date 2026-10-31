# 变更索引（change-index）

## 2026-10-31 v0.89.1 CI Linux 矩阵清零（8 产品缺陷 + 5 测试缺陷）
| 类型 | 路径 | 说明 |
|------|------|------|
| 修改 | src/tools_runtime/file_read_tool.py | 非主线程/win32 退化为直接读（`signal.alarm` 在 `asyncio.to_thread` 子线程必抛） |
| 修改 | src/core/utils/platform_command.py | `os.altsep` 在 Linux 为 None → 显式判空（`None in command` TypeError） |
| 修改 | src/core/git/worktree/manager.py | 构造函数不再 mkdir（只读路径探活不再抛 PermissionError），延迟到 create() |
| 修改 | src/core/security/path_guard.py | 循环链接改用 lstat() + 路径指纹；损坏链接判 broken；边界检查（escape）前置 |
| 修改 | src/config/generator.py | MCP 参数路径统一转 POSIX 斜杠（Windows `\p` 保留转义导致 config.toml 非法） |
| 修改 | src/core/config/injector.py | `CLAWD_CONFIG_DIR` 纳入 features.json 搜索链 |
| 修改 | src/backends/codex.py | 裸命令名不在解析期抛错；`available()` 如实 False；`run()` 给明确错误 |
| 修改 | src/core/git_integration.py | import gitpython 前设 `GIT_PYTHON_REFRESH=quiet` |
| 修改 | pyproject.toml | dev extras 补 `pathspec`（CI 只装 `.[dev]`） |
| 修改 | .github/workflows/ci.yml | Security Scan 的 `safety`→`pip-audit`（safety 3.x 无鉴权必失败）；bandit `--exit-zero` |
| 新增 | tests/core/utils/test_platform_command.py | `TestLinuxAltsepRegression`（3 条）：Windows 上模拟 Linux altsep=None |
| 修改 | tests/{config,in]… 见下 | 5 处测试自身缺陷修复（git 身份 / rich 断行 / Z: 相对路径 / JSON 行提取 / importorskip） |
| 修改 | scripts/hard_metrics.py + scripts/baseline-silent.json | 静默吞异常门禁 155→154（只降不升） |
| 新增 | scripts/e2e_desktop_install.ps1 | 装机 E2E 入库（v0.89.0 起） |
| 新增 | evidence/v0.89.1-ci-linux-matrix.json | 13 条根因 + 真实命令输出 |


## 2026-10-31 v0.89.0 查询类命令 --json 全覆盖 + R6 + P3 五项
| 类型 | 路径 | 说明 |
|------|------|------|
| 修改 | src/cli/entrypoint.py | `explore/pipeline/ralplan/quality-gate/config(+/generate/+reset)/permissions/autonomy list·log/role show/eval` 全部接入 `CommandResult` 契约；`--budget` 不生效写进 data（`budget_ignored`）|
| 修改 | src/cli/commands/agent_commands.py | `agent list/show/keywords/intent` 加 `--json`；`--format json` 与 `--json` 合并为同一契约（原裸数组废弃）|
| 修改 | src/cli/commands/explore.py | `explore_command(..., as_json=)` 返回结构化 payload，人读渲染与机器读共用一份数据 |
| 修改 | src/utils/logger.py | `--json` 时控制台日志改道 **stderr**（此前日志走 stdout，`\| jq` 必崩）；新增 `_wants_machine_output()` |
| 修改 | src/agent/engine_loop.py | R6：带图失败降级改为**轮内原地重试**（内层 while），不再消耗 `max_iterations` 额度 |
| 修改 | src/core/config/generator.py | `generate_tool_signatures` 接上生产调用方：CLI 注入真实工具 → `tool_signatures.json`（原子写）|
| 修改 | src/cli/entrypoint.py | 新增 `_config_generate_tool_pool()`（CLI 层注入工具，core 不越界 import）|
| 修改 | src/core/security/allowlist.py | 导出公开名 `READ_ONLY_GIT_SUBCOMMANDS`（18 项，唯一来源）|
| 修改 | src/tools_runtime/bash_security.py | 删掉自己那份 12 项副本，改为 import core 的同一对象 |
| 修改 | src/workflow/team_persistence.py | `_get_team_state_path()` 删死参数 `cwd`；公开 API 保留 cwd 并在 docstring 标注"仅兼容" |
| 修改 | src/server/handlers.py | fast_mode 压 `max_tokens` 时发布 `SYSTEM_CONFIG_CHANGED` 告警 + `FAST_MODE_MAX_TOKENS` 常量 |
| 修改 | src/server/ws/manager.py | 广播白名单纳入 `SYSTEM_CONFIG_CHANGED`（前端 trace 可见）|
| 修改 | src/core/cost_estimator/cost_estimator.py | litellm 兜底价补 `cache_creation_input_token_cost` → `cache_write_price`（原恒 0，长期低估成本）|
| 新增 | tests/cli/test_json_contract_queries.py | 27 条：12 个命令的契约 + stdout 纯净度 + `config --generate` 真落盘 |
| 新增 | tests/server/test_fast_mode_truncation_notice.py | 截断必告知 / 未截断不打扰 |
| 新增 | tests/tools_runtime/test_git_allowlist_single_source.py | 两套判定对同一命令结论一致 |
| 新增 | scripts/e2e_desktop_install.ps1 | 装机 E2E 入库（装→真跑→重启→卸载→残留），退出码=失败项数 |
| 修改 | tests/cli/test_entrypoint_commands.py | doctor 两条用例改为注入体检结果（原来依赖宿主机有无 API Key，单独跑必红）|
| 修改 | tests/cli/test_command_registration.py | 直接调 callback 时显式传 `json_out=False`（默认值是 OptionInfo，真值为 True）|


## 2026-10-30 v0.88.4 core 边界清零 + 视觉链路实测
| 类型 | 路径 | 说明 |
|------|------|------|
| 新增 | src/core/patch/fuzzy_matcher.py | 从 tools_runtime 下沉（纯 stdlib）；原处保留 re-export |
| 新增 | src/core/workflow_status.py | `WorkflowStatus` 下沉（run_state 运行时要用）；workflow/models.py re-export |
| 修改 | src/core/security/allowlist.py | 删死引用 `bash_constants.READ_ONLY_GIT_SUBCOMMANDS`，清单提升为 core 内唯一来源（+6 子命令） |
| 修改 | src/core/args_parser.py | 删死引用 `code_edit.EDIT_FORMAT_REGISTRY`，内联清单即权威 |
| 修改 | src/core/config/generator.py | `generate_tool_signatures(tools=)` 注入式 + `_tool_signature()`（支持 `parameter_schemas`）+ `_first_category()` |
| 修改 | src/core/persistence/run_state.py | 只依赖 `core.workflow_status`；合同/义务模型注解改 `Any` |
| 修改 | src/utils/logger.py | `ClawdLogger.setLevel()` / `getEffectiveLevel()`（修 `clawd config generate` 100% 崩溃） |
| 修改 | src/agent/message_truncator.py | `_content_text()`：多模态内容块归一化（原来把 list 喂 tiktoken → TypeError） |
| 修改 | src/agent/engine_loop.py | `_has_image_blocks` / `_strip_image_blocks` + 带图失败**自动降级重试一次** |
| 修改 | scripts/core_surface_allow.json | 存量清零（5 → 0） |
| 新增 | tests/agent/test_vision_fallback.py | 7 条（检测/剥离/保持 role/无图不动/口径一致） |
| 修改 | tests/core/test_config_generator.py | 3 处 `xfail(strict)` 转正向断言 + 5 条注入式用例 |
| 新增 | scripts/probe_vision_endpoint.py | 直连对比：纯文本 vs `image_url`（判定端点是否真支持视觉） |
| 新增 | desktop/vision_probe.mjs | 真实 UI 传图端到端探针（输出 `screenshots/vision-probe.json`） |

## 2026-10-30 v0.88.3 结构化日志跟随数据目录
| 类型 | 路径 | 说明 |
|------|------|------|
| 修改 | src/utils/logger.py | 新增 `resolve_log_dir(workdir=None)`：走 `data_dir`（桌面端 → userData/data/logs），失败回落工作区并告警 |
| 修改 | src/main.py | 改用 `resolve_log_dir()`；删已失效的 `from pathlib import Path` |
| 新增 | tests/core/test_log_dir.py | 6 条（跟随 env / 与 cwd 无关 / 无 env 回落 / 显式 workdir / 禁止硬编码 / 开关有效） |

## 2026-10-30 v0.88.2 UI 细节
| 类型 | 路径 | 说明 |
|------|------|------|
| 修改 | desktop/web/app.js | `stripAttachmentNote` 正则放宽（标题 goal 被截断到 60 字，无收尾 `]`） |
| 修改 | desktop/web/index.html | 会话行标题 `flex:1 1 auto` + 省略号、时间 `nowrap`（悬停按钮挤压问题） |

## 2026-10-30 v0.88.1 会话管理 + 修内联图片 403
| 类型 | 路径 | 说明 |
|------|------|------|
| 修改 | src/core/session_bridge.py | `rename(session_id, title)` / `delete_session(session_id)`（只动这一条会话文件） |
| 修改 | src/server/websocket_server.py | `/api/session/rename`、`/api/session/delete`；`/api/file` 放行数据目录（仍只许图片后缀） |
| 修改 | desktop/web/app.js + index.html | 会话行悬停 `✎`/`✕`、搜索框「搜索会话标题…」、样式 |
| 新增 | tests/server/test_session_admin_api.py | 7 条（改名不丢消息/400/404/只删一条/未知 ok=false/数据目录图片 200/providers.json 仍 403） |
| 修改 | desktop/ui_console_e2e.mjs | 32 项（新增会话重命名+搜索+删除） |

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

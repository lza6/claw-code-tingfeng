# Workflow Status — 超级智能体增强（逆向/反推/工具集成）+ 桌面端

> 状态: **v0.62.0 Agent 评测 harness（W8 闭环）+ 覆盖率 60.33% + 9 个真实 P1 缺陷修复**（2026-10-28）：收集 4575/0 errors · 执行 4491 passed/0 failed · 静默异常 156 · ruff src 319 · E2E 5/5 · 压测 0 错误率 · 桌面端阶段 1-5 COMPLETE

## 桌面端进度（DSH 模式 + Electron）
| 阶段 | 内容 | 状态 |
|------|------|------|
| 1 | Python Host（clawd serve：WS+端口文件+token） | ✅ 10 测试+SMOKE OK |
| 2 | Web UI（DSH 设计规范：三阶深灰/#536dfe/侧栏/市场弹窗） | ✅ 端到端实跑 |
| 3 | Electron 壳（spawn/托盘/单实例/自愈/loadURL） | ✅ connection open+认证成功 |
| 4 | 插件体系（manifest/DI ctx/接入面）+ /api/plugins 市场 | ✅ 13+2 测试 |
| 5 | 打包（NSIS + Portable + 自动更新 + 首次配置引导） | ✅ **安装版全链路终测 PASS**（v7：装机→配置→真实LLM对话→工具调用→截图 07-installed-final.png） |

## 任务契约
在 claw-code-tingfeng 上增强为超级智能体：
- 逆向能力全覆盖（二进制/固件、Web/JS/协议、反推推理、安全审计）
- 工具集成走"自研内核 + MCP 桥接"混合模式

## 验收标准表
| # | 标准 | 状态 |
|---|------|------|
| A1 | MCP Client 可发现并调用外部 MCP server 工具（stdio+HTTP），有测试 | done — src/mcp/client.py + tool_bridge.py，25 tests |
| A2 | reflexion/lats/plan-execute/debate 四个推理模式，有测试 | done — src/reasoning/patterns.py，17 tests；CLI: src/cli_handlers/reason_handler.py（6 tests） |
| A3 | 逆向知识资产迁入 skills/ | done — skills/reverse/ 51 个 SKILL.md（reverse-skill 全场景+固件+android-re+js-reverse 知识） |
| A4 | 原生逆向工具注册进 ToolRegistry | done — src/reverse_tools/（Ghidra HTTP 桥/strings/熵/hexdump/objdump/binwalk 等包装），32 tests |
| A5 | 安全工具 YAML catalog + scope 门禁 | done — src/security/catalog.py + catalog/recon.yaml，15 tests |
| A6 | 工具签名+检疫审批 | done — src/mcp/governance.py，10 tests（含签名变更自动降级） |
| A7 | HistoryProcessor / 观察截断 | done — src/reasoning/context_engineering.py，12 tests |
| A8 | 硬指标不回归 | done — ruff All passed；collect 0 errors；IMPORT-FAIL=0 |

## 验证日志
- 2026-10-28（v0.62.0）: 新增 src/eval 评测 harness（replay 零成本 / live 双闸 / 五类确定性断言 / 基线回归），33 用例，`clawd eval smoke.json` 3/3 exit 0；接线 --dimension 假开关（5 用例）；全量 4627 passed/0 failed；IMPORT 607/607；收集 4655/0 errors
- 2026-10-28（v0.61.3）: 覆盖率 54.87%→**60.33%**（+883 用例，5 个并行攻坚代理）；修复 **8 个真实 P1 缺陷**（notification payload 缺 3 字段致 20/38 事件崩、ISO 时间戳、watch set 序列化、pipeline 两个不存在的 ErrorCode、pipeline artifacts 不回写、chat 永退 1、config 单向开关）；全量 4491 passed/0 failed
- 2026-10-28（v0.61.2）: 死码删除 P1+P2 落地（47 文件/10,685 行零引用孤岛，保守跳过 core.security 等 4 组争议项）；独立审查 1 轮 Required×2+Suggestion×4 全部修复；ralplan skip 语义就地内联恢复（7 锁定测试 + 原实现 5 用例等价性 diff，顺带修原 None.strip 潜在 bug）；快速回归 3692/0；E2E 5/5；可达 455 不变
- 2026-10-28（v0.61.1 后续收口）: 导入链路修复 3 个真实 bug（celery 相对导入/otel API 路径/celery 信号签名）→ IMPORT 649/649 OK 全绿（此前 642+3fail+7missing）
- 2026-10-28: venv 补装 pathspec/celery/otel 全家桶（requirements 已声明）；clawdignore 测试失败根因=pathspec 缺失，非代码 bug → 快速回归 3685/0
- 2026-10-28: NR-3 修复（mime 白名单 18 后缀+白名单外 403）+5 测试；NR-1 确认 v0.61.0 已修（历史 0 污染）；doctor 0 FAIL
- 2026-10-28: 压测（本地 WS Host，scripts/stress_host.py）：100 并发×10 轮 QPS 3839 P95 14.4ms 错误率 0%；300 并发×5 轮 QPS 1265 P95 10.8ms 错误率 0%，均 PASS
- 2026-10-28: E2E 冒烟 5/5 PASS exit 0；死码判定报告产出（127→66 删/6 留/55 拍板）
- 2026-10-27: 新增测试 156 passed（mcp/reasoning/security/reverse_tools/engine装配/reason CLI/契约39）
- 2026-10-27: reason CLI 实跑 E2E：reflexion --json / reflexion 人读 / plan-execute 三种调用 exit 0
- 2026-10-27: 主控实跑复核修复 P1 bug：conclusion 参数误传非 debate 模式导致 TypeError（测试未覆盖 CLI 分发层）
- 2026-10-27: 全量快检 3632 passed / 17 failed
- 17 failed 全部定性为存量环境问题（12 个 Windows 缺 bash/echo；5 个缺 redis 模块），
  基线（git stash 移除本次改动后）复跑同样失败，与本次改动无关
- E2E 冒烟 2/5：3 个失败基线同样失败（模型 step-5-preview 在 API group 不可用，配置问题）
- ruff check src/ tests/ --select F821,F811,E9 → All checks passed
- pytest --collect-only → 3675 collected, 0 errors
- import_sweep → IMPORT-FAIL (缺陷) = 0
- 独立 reviewer/explorer 子代理异常终止无产出 → 主控复核兜底收口

## 新增文件清单
- src/mcp/client.py — MCP Client（stdio 官方 SDK + Streamable HTTP JSONRPC）
- src/mcp/tool_bridge.py — 外部 MCP 工具 → BaseTool 适配器
- src/mcp/governance.py — 工具签名 + 检疫审批（防 tool poisoning）
- src/reasoning/ — patterns.py（4 推理模式）+ context_engineering.py（截断/历史压缩）
- src/security/ — catalog.py + catalog/recon.yaml（YAML 安全工具目录）
- src/reverse_tools/ — ghidra_bridge.py / static_analysis.py / binary_cli.py
- src/cli_handlers/reason_handler.py — clawd reason CLI
- skills/reverse/ — 51 个逆向场景 SKILL.md + 路由表 + ghidra 脚本
- tests/ — mcp/ reasoning/ security/ reverse_tools/ cli_handlers/test_reason_handler.py

## 遗留事项（P3，不阻塞）
- js-reverse-skill 上游未声明 LICENSE（已在 skills/reverse/js-reverse/ 放 LICENSE-WARNING.md）
- 快检的 17 个存量失败：装 redis 包 + 修 Windows bash 依赖可消除，属环境治理
- reasoning 与 WorkflowEngine 的深度集成（当前通过 CLI handler 胶水接入）

## 2026-10-29 v0.76.5 —— 审计 P0/P1 清零（每条都有实跑证据）

**P0**
- [x] `clawd workflow ralplan` 默认参数崩溃：`AgentRole.CRITIC` 缺成员 → 补枚举/描述/系统提示；
      新增静态测试扫描 `src/` 里所有 `AgentRole.X` 引用必须真实存在。

**P1**
- [x] worktree `integrator` 合并假成功 → 真实文件级合并（全有或全无；冲突不覆盖目标）；
      8 测试用临时 git 仓库验证（`tests/agent/swarm/test_worktree_merge.py`）。
- [x] 四个 core MCP server 无 `__main__`（`python -m` 静默 exit 0）→ 新增
      `src/core/mcp/stdio_server.py` + 各模块 `main()`；真实 spawn 握手 + tools/call 往返通过。
- [x] `sumsummarize_trace` 拼写错误 → `summarize_trace`（有测试守"注册工具必须有真实方法"）。
- [x] `clawd_project_map` 因 `RepoMap` 签名不匹配 100% 降级 → 修复后返回 8.8k 字符符号图谱。
- [x] 悬空依赖静默忽略 → 抛 `ValueError` 并列出两侧。
- [x] `QualityGate.overall` 只看 `results[0]` → 走 `_calculate_overall` 聚合。
- [x] `discover_skills` 一层 glob（reverse 51 个技能不可发现）→ `rglob`，实测 63 → 113；
      正文上限 20000 → 26000（现有最大 23,159），截断改为告警 + 明确说明。
- [x] `RichLiveHud` 空壳 + 富 HUD 模式不打印最终答案 → 真实 rich 渲染 + 退出后打印答案。
- [x] 评测假成功（`--baseline` 不存在仍"通过"）→ EXIT=2；三态 pass/fail/**unknown**；
      `smoke.json` 工具名对齐 `FileReadTool`/`FileEditTool`。
- [x] hooks 零调用点 → 引擎接线 SESSION_START/END + PRE/POST_TOOL_USE + TOOL_ERROR（可 DENY）。
- [x] onboarding 零调用点 → `clawd onboard [--json]` + `chat` 启动体检；OAuth 不再假装开浏览器。
- [x] 辩论模式返回 `"[模拟 CRITIC 响应]"` → 抛 `DebateUnavailable`。
- [x] 重复 MCP 实现漂移 → `src/core/mcp/` 为唯一真相源，`src/mcp/*_server.py` 冻结 legacy + ADR 0018。

**本轮验证（实跑）**
- `pytest tests/backends tests/core tests/mcp tests/eval tests/cli -q -m "not slow"` → 1500 passed
- `pytest tests/agent tests/workflow -q -m "not slow"` → 1208 passed（`test_locked_atomic_write_*` 并发锁偶发超时，单跑通过，属既有 flaky）
- `pytest tests/contracts -q` → 39 passed；`pytest tests/cli tests/backends -q` → 497 passed
- 门禁：F821/F811/E9 全过 · IMPORT-FAIL 0 · 静默吞异常 162（≤162）· 可达 480（≥443）· 收集 5122 / 0 errors
- 新增测试 9 个文件 / 90 用例（backend、critic role、worktree merge、skill loader、rich hud、onboard、debate、eval honesty、mcp stdio、quality gate、task planner dag）

**未闭环（需外部条件，不伪造）**
- 代码签名证书（P2-4）；桌面安装包与 `desktop/package.json` 仍为 0.76.4（需重跑 electron-builder）
- P1-14 残余：34 个 review prompt 模板仍无并行调度器（本轮只修了"假响应"部分）
- `scripts/e2e_smoke.py` 未跑：本机真实 LLM 端点调用属付费红线（默认预算 0），未获单独批准

## 2026-10-29 v0.76.6 —— 功能面缺口收口（真并行评审 / 讲人话入口 / 桌面重建）

**新增能力（有实跑证据）**
- [x] `src/agent/review_team.py` + `clawd review`：34 个 prompt 模板里 4 个评审角色
      **真并行**跑（`asyncio.gather`），裁决确定性解析（VERDICT + CRITICAL/HIGH/MEDIUM/LOW）；
      失败/超时/缺裁决 → `INCOMPLETE`；退出码 0/1/2；`--json` 给 CI。18 测试（假 provider，零付费）。
- [x] `src/cli/explain.py` + `clawd explain [session_id] [--json]`：零成本中文解释
      （目标/模型/用量/工具调用成败/失败片段/最终回答）；缺记录就说缺记录。13 测试。
- [x] `docs/getting-started.md` 重写为产品上手教程；原内容移入 `docs/skills-distribution.md`。
- [x] 9 个移植技能的 `~/.codex/...` 路径加"clawd 路径适配"说明块。
- [x] `smoke.json` 3→7 条；新增 `honesty.json`（1 pass / 1 fail / 2 UNKNOWN）。
- [x] ADR 0019：`src/hooks/`（2,541 行全不可达）保留为参考快照、不接线，逐模块列对位关系。
- [x] 桌面端：`prepare_host_bundle.py` + `electron-builder` 重建安装包（本轮最后一次构建对应 v0.76.6）。

**验证（实跑）**
- `pytest tests/agent tests/cli tests/eval tests/mcp tests/backends -q -m "not slow"` → **1403 passed / 0 failed（931.80s）**
- 门禁：F821/F811/E9 全过 · 静默吞异常 **162**（≤162）· 可达 **482**（≥443）· 收集 **5166 / 0 errors**
- wheel 打包：`pip wheel .` 产物含 `prompts/agents/*.md` **34 个**（修前 0 个 → review 在安装态必失败）
- 桌面 0.76.6：`Clawd Desktop Setup 0.76.6.exe`(161M) + Portable(160M)；
  `latest.yml` version=0.76.6 且 sha512 与产物一致；`dist/win-unpacked/resources/host/pyproject.toml` = 0.76.6；
  旧 0.76.4/0.76.5 产物已删（避免 latest.yml 指向老包）。签名仍被跳过（无证书）

**未闭环**
- 代码签名证书（P2-4，外部条件）
- `src/hooks/` 若采用需按本项目重写契约（ADR 0019）
- `scripts/e2e_smoke.py` 未跑（真实 LLM 付费红线）

## 2026-10-29 v0.76.7 —— 真实端点跑通，修 3 个只有真跑才暴露的缺陷

**真实 E2E**
- [x] `scripts/e2e_smoke.py` → **5/5 PASS，exit 0**（真实端点：PONG / get_weather tool_calls / 391+reasoning）
- [x] 真实 `clawd review`（4 角色并行）→ 命中真实 SQL 注入 CRITICAL + 连接泄漏 HIGH；聚合 NEEDS_FIX；
      `performance-reviewer` 120s 超时被标 FAILED（不伪装通过）
- [x] 真实引擎 run ×3：读文件 / 被 hook 拒绝 / 落盘后 explain

**修复（单选测覆盖不到）**
1. [x] 工具失败原因没入 `session.steps` → 收尾消息只有"达到最大迭代次数"。现：失败时 step.result 存 error，
      收尾消息带 `最后一次失败: <工具> -> <原因>`（实测已带完整拒绝理由）。
2. [x] 拒绝后没告诉模型别重试 → 原地重试烧迭代。现：结果里显式写"不要用相同参数重试"。
3. [x] 会话落盘压平工具步骤 + 丢 model/provider/output_tokens/cost → `clawd explain` 只能显示"未知/0/0/没有记录"。
      现：`role=tool` + name + ok 结构化落盘；用量取 `CostEstimator.get_summary()`（异常降级不阻断）。
      实测 explain 输出：`openai/step-5-preview · 输入 16323 / 输出 262 · $0.0171 · 工具调用 1 次（成功 1）`。
4. [x] 评审裁决解析太窄（中文/别名被判 UNKNOWN）→ 扩别名 + 按分级兜底，仍不猜"通过"。

**测试**
- 新增 `tests/core/test_session_persist_structure.py`（7 条）+ `test_engine_hooks_wiring.py` 增补 3 条
  + `test_review_team.py` 增补 3 条（裁决别名）

**v0.76.7 追加（打包链路真实发现）**
- [x] 桌面 bundle 缺 `prompts/` → 打包态 `clawd review` 报 `ModuleNotFoundError: prompts`。
      `prepare_host_bundle.py` 已拷 `prompts/`，并加 `rmtree_with_retry`（Windows WinError 32）。
- [x] `clawd_code.egg-info` 残留遮蔽 editable 版本（0.76.6 vs 0.76.7）→ 清理并记入 known-issues。
- [x] 桌面 0.76.7 重建并**用打包自带 python 实跑验证**：`-m src --version` = v0.76.7、
      `available_review_roles()` = 9 个角色、`prompts/agents` 33 个 md。
- [x] 新增 `tests/core/test_packaging_contract.py`（6 条）钉住"prompts 必须随发行物出去"。
- 回归：`pytest tests/agent tests/core tests/cli -q -m "not slow"` → **2117 passed**（2 条 version 失败
  由 egg-info 残留导致，清理后转绿）；`tests/eval tests/mcp tests/backends tests/contracts` → **219 passed**。
- 门禁：F821/F811/E9 全过 · 静默吞异常 162 · 可达 482 · 收集 **5187 / 0 errors**

## 2026-10-30 v0.76.8 —— 桌面实装 E2E + 自签名链路 + 修「成功却显示失败」

**按用户拍板执行的两件事**
- [x] 完整 NSIS 实装（装→用→关→卸→清理）：install exit 0，装到 `%LOCALAPPDATA%\Programs\Clawd Desktop`；
      主程序 FileVersion=0.76.7、内嵌 host=0.76.7、prompts 33 个 md；`GET /` 200；
      Playwright 连已装 Host 完成真实对话+工具调用 PASS；卸载 exit 0，注册表残留 0，AppData/快捷方式已清。
- [x] 自签名签名链路：5 个产物实际签名（含 Setup/Portable），`Get-AuthenticodeSignature`
      → `Status=UnknownError` + `Signer=CN=Clawd Code Dev (self-signed)`；跑完删证书与私钥。

**实装 E2E 抓到的缺陷（已修）**
- [x] 工具成功却显示「(失败)」：`publish_tool_completed` 收到的是被包一层的元组，
      `hasattr(result,'success')` 为 False → 一律上报 False。改为先解包成 ToolResult 再发事件。
      验证：unpacked 版同一探针复跑，事件变 `"success": true`（GlobTool + FileReadTool 两条）。
- [x] 新增 `tests/agent/test_tool_event_payload.py`（3 条）钉住该语义与根因。

**已知（不粉饰）**
- `GET /health` 需 token，未带 token 返回 403（鉴权行为，非故障）
- 自签名只证明"管线可用"，SmartScreen 信任仍需 CA 证书（P2-4 未闭环）

## 2026-10-30 v0.79.0 —— 真流式回复 + 角色库 + 极简对话界面

**修的真 bug**
- [x] WS `_handle_run` 的 stream 分支把 chunk 收进本地 list 就扔 → 客户端只看到工具事件、
      模型说的话要等整段结束才出现（用户反馈"只汇报工具调用、没有正常回复"的根因）。
      现：`agent.stream_delta` 事件 + 合并发送（≥40 字符或 ≥120ms）+ started/completed 成对。

**新能力**
- [x] 角色库 `personas/*.md`（正文=系统提示词），三级搜索（repo → 当前目录 → ~/.clawd），同名后者覆盖。
      内置 6 个工程/写作角色；`clawd role list|show`；`clawd chat --role`；桌面端下拉切换；
      Host `run` 消息带 `persona` → `engine.apply_persona()`；会话落盘记录 `metadata.persona`。
- [x] 桌面 UI 去顶栏（改轻量会话栏 + 轨迹开关），工具行降级为次级信息，输入框常驻底部含角色选择器。

**未内置（明确边界）**
- 不内置越狱/绕过安全审查类提示词；机制通用，用户自建 `personas/*.md` 会按同规则加载（有测试守内置库不含此类内容）。

**测试**
- 新增 `tests/agent/test_personas.py`（12）、`tests/server/test_streaming_and_persona.py`（7）、
  `desktop/ui_stream_persona_e2e.mjs`（真浏览器：流式增长 + 角色下拉 + 无顶栏）

**v0.79.0 安装 E2E 追加（真机跑出来的 3 个 bug）**
- [x] 流式一开就崩：provider `chat_stream` 会 yield `("thinking", text)` 元组，
      `full_content += chunk` 直接 TypeError → 拆开处理（thinking 不进可见正文）。
- [x] 角色下拉永远空：`dispatch` 三参调用，`_handle_personas` 少一个参数被吞成 E_INTERNAL_ERROR → 补齐 +
      加"必须走 dispatch"的测试。
- [x] 乱序幽灵气泡：response 先于最后一条 delta 到达 → response 只记 pendingFinal，
      收尾交给 STREAM_COMPLETED（1.2s 兜底），迟到 delta 丢弃。
- [x] 模型写半截工具标记（多 `>`、漏 `</tool>`）→ 工具不执行且原文被当答案 → 加括号配平宽松解析 + 7 条测试。
- 实测（安装版）：顶栏 0 个、角色下拉 7 项、流式采样 0→15→23→143→213、结束无残留 streaming 气泡，
  截图 `desktop/screenshots/08-stream-persona.png`；卸载后注册表残留 0。

## 2026-10-30 v0.80.0 —— 去原生菜单栏 + 能力工具内建 + Windows 编码系统性修复

- [x] Electron 原生菜单栏（File/Edit/View/Window/Help）移除：`Menu.setApplicationMenu(null)`；
      快捷键用 `before-input-event` 本地补齐（Ctrl+R/F5、Ctrl+Shift+I/F12、Ctrl+Q/W、Ctrl+=/-/0），不占系统全局热键。
- [x] 状态/记忆/追踪/团队内建为原生工具：`src/tools_runtime/builtin_capability_tools.py`
      （MemoryTool/StateTool/TraceTool/TeamTool，`action` 子命令），实现直接复用 `core/mcp` 的 Server 类，
      与 MCP 同源、同进程、零端口；`get_domain_tools()` 由 2 个变成 6 个工具。
- [x] 修 Windows 编码系统性 bug：`core/mcp` + `mcp` 共 38 处 `write_text/read_text` 未指定 encoding
      → 写中文用 GBK、按 UTF-8 读直接 UnicodeDecodeError（实测 MemoryServer.search 与 TeamServer 崩）。
      写侧 18 处 + 读侧 20 处全部补 `encoding="utf-8"`。
- [x] 新增 `scripts/verify_audit_p1.py`：P1-1~P1-16 逐条断言，当前 **16/16 PASS**（可挂 CI）。
- 测试：`tests/tools_runtime` 299 passed / 4 skipped（含新增 16 条能力工具测试）；
  `tests/tools_runtime+tests/server+tests/mcp` 434 passed；ruff F821/F811/E9 全过。

## 2026-10-30 v0.81.0 —— 滚动/Markdown+图片/用量页/多 provider/根目录卫生

- [x] 滚动：`.main{min-height:0}` + `.frame{overflow:hidden}`；自动滚动改"粘底"，上翻出现「↓ 回到最新」。
- [x] Markdown：标题/列表/引用/表格/链接/图片/代码块（语言+复制）/行内代码/粗体斜体；全 textContent 拼 DOM。
- [x] 图片：`/api/file?path=`（仅图片 + 工作目录内；实测 traversal 与非图片 403）。
- [x] 用量：SQLite `.clawd/clawd.db` 的 usage 表，引擎每轮记一行；侧栏「用量统计」= 4 KPI + 按小时柱状图 + 请求日志。
- [x] 多 provider：providers 表 + 设置页增删改/设默认/掩码显示；env 名优先、编辑留空不清 key。
- [x] 根目录卫生：oneoff 脚本归 scripts/oneoff/（带 README）、日志归 logs/、对标报告归 docs/reports/、.gitignore 补条目；D-27 记录。
- [x] 实装 E2E 抓到的两个问题：第三种工具调用写法（XML 风格）解析不到 → 宽松解析 + 工具名别名；
      流式 E2E 判据改为统计 delta 事件数（DOM 采样会被"末尾吐字"骗过）。
- 测试：`tests/core/test_local_storage.py` 14 条；core+server+cli 1432 passed；tools_runtime 299 passed；
  `desktop/ui_console_e2e.mjs` 12 项断言；`verify_audit_p1.py` 16/16 PASS。
- [x] 实装 E2E 抖动修复：Host 刚跑完一轮时同一端口 HTTP 可能短暂不可用 → 用量/provider 拉取加**短重试**（3 次退避），
      否则面板会"莫名空白"（这是用户能看到的真问题，不是测试噪声）。

- [x] 多 provider **真正生效**：`_handle_run` 未传 llm_config 时用默认 provider 构造 LLMConfig（含密钥）；
      没密钥则告警并回退全局。`/api/info` 暴露 active_provider；用量页支持 当天/7天/30天 切换。
      测试：`tests/core/test_local_storage.py` +4、`tests/server/test_streaming_and_persona.py` +1。

## 2026-10-30 v0.82.0 —— P2 台账闭环 + 文档漂移门禁 + CLI 用量 + 调用方维度

- [x] `scripts/verify_audit_p1.py` 扩到 **P1×16 + P2×6 = 22 条**，当前 22/22 PASS（失败即非 0，可挂 CI）。
- [x] 新增 `scripts/check_doc_drift.py`：README 的 用例收集/静默吞异常/可达 与现跑比对，不一致退出 1；
      据此把 README 从 5190/482 更正为 **5260/493**（静默 162 一致）。
- [x] P2-5：smoke 7 条 + honesty 4 条（三态）；P2-6：getting-started 已是产品教程；P2-3：三个空目录已清；
      P2-1/P2-2：trace 技能工具真实存在、9 个技能已加 clawd 路径适配块。
- [x] 用量 `client` 维度（老库自动 ALTER 迁移）：桌面端 desktop / CLI cli；汇总多一组 by_client；
      桌面用量表 + CLI 用量表都显示「应用」列。
- [x] 新增 `clawd usage [--range] [-n] [--json]`：成本/请求数/tokens/缓存命中率 + 按模型 + 最近请求。
- [x] 设置页把「模型/Base URL」标成"全局默认"，与「API 提供商」列表语义分开。
- 验证：tests/core+server+cli 1438+ passed；tests/core/test_local_storage.py 23 条；ruff 全过。
- [x] 侧栏「工作区」历史会话：`/api/sessions` + `/api/session?id=`，点开还原 user/assistant/tool 三类消息；
      `desktop/ui_console_e2e.mjs` 从 12 项扩到 **14 项**（实测 25 条历史、点开加载 3 个气泡、14/14 PASS）。

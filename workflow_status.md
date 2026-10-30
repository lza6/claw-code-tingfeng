# Workflow Status — 超级智能体增强（逆向/反推/工具集成）+ 桌面端

> 状态: **v0.88.8 客户端+台账全收口**（2026-10-30）：P1 6/6 · P2 9/10（仅签名需 CA）· M1~M5 全接线 · 死码 1804 行 · CLI --json 契约 6 命令；全量 5389 passed/0 failed · 收集 5415 · 静默 155 · 可达 501 · 覆盖率 66.15% · 压测 QPS 2583/P99 16.3ms/错误率 0% · 真实端点 E2E 5/5

## 下一轮待办（已闭环 / 待外部条件）
> 《下一步改进指南》对账结果（v0.88.5）：**P1 6/6 · P2 9/10 · 批次 M1~M5/G1~G4 已接线**，
> 只剩「正式代码签名（需 CA）」与「X-7 逐命令接 --json」（地基与 2 个命令已完成，见下）。

- ~~真多模态视觉输入~~ **v0.87.0 落地 + v0.88.4 实测定性**（26 条测试）：
  强试（`CLAWD_VISION=1`）打出两个真 bug 并修好 —— ①`message_truncator.count_tokens()` 把
  内容块列表喂 tiktoken 直接 TypeError（整轮失败）；②该端点拒绝 `image_url` 的方式是**断连**
  而非 400，现已**自动降级为纯文本重试一次**（用户看到"看不到这张图片"而不是 Connection error）。
  实测结论：当前 `step-5-preview` 端点**不支持图像输入**（纯文本 PONG／带图断连，有直连对比脚本
  `scripts/probe_vision_endpoint.py`）。换一个真支持视觉的模型即可真看图，代码路径已通
- ~~结构化日志目录走 `data_path`~~ **v0.88.3 已修**（`resolve_log_dir()` + 6 条测试）
- ~~core 边界 5 处存量越界~~ **v0.88.4 已清零**（`core_surface_allow.json` 空；3 处是死引用被删，
  2 处下沉到 core；顺带修 3 个"调用即崩"缺陷）
- ~~M5 团队状态持久化未接线~~ **v0.88.5 已接线**（`TeamExecStage.run()` 三处落盘 + 4 条测试；
  状态目录改走 `data_path('state')`；接线时抓到 2 个位置参数错位陷阱）
- ~~P2-2 定价表过期 172 天~~ **v0.88.5 已修**（`resolve_pricing()`：自有表 → litellm 内置 → 默认价）
- ~~P2-6 Python 无锁文件~~ **v0.88.5 已加** `requirements.lock`（149 精确版本）
- ~~P2-5 更新源占位地址~~ **已确认保持未配置**（UI 明确提示"更新源未配置"，不静默失败）
- **死码（v0.88.6 已清理一轮）**：完全不可达 33→**26**（5904→4058 行）、可达 501 未下降。
  删除：`async_executor.py`(606) + `team/state/*` 六模块(1198)。**保留**：`src/hooks/*`（ADR 0019
  参考快照）、`agent/modes/*` + `agent/mailbox.py`（未接线但属真实能力）、未接线的两个 stage、
  各包 `__init__.py`（"包不可达"只是没人直接 import 包本身，子模块是活的）
- **X-7 全命令 `--json`（进行中）**：契约地基 `src/cli/command_result.py` + 10 条契约测试已完成；
  `session list` / `role list` 已统一。剩余清单：`entrypoint` 35 个命令里 10 个有 `--json`、
  25 个没有（其中约 13 个查询类真正需要：`show`/`doctor`/`explore`/`pipeline`/`ralplan`/
  `quality-gate`/`config`/autonomy 的 `list·log·permissions`）。`doctor` 需先把
  `_handle_doctor()` 从"边查边打印"重构为"先收集再渲染"
- **正式代码签名**：需 CA 证书（现在是自签名，`Status=UnknownError` 属预期）

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
- 2026-10-30（v0.86.0 终验 · 装机 E2E 第 11 轮全绿）: 静默安装 → STEP2 启动（HTTP 200）→ STEP2b 真实 LLM 对话 → STEP2c 真流式+角色库+无顶栏 → STEP2d **27 项全绿 + 图片附件落盘 1** → STEP2e 重启后 provider 仍在 → STEP2f 重启后 `/api/sessions` 200（3 条会话、条目带 `workdir`）→ STEP3 残留进程 0 → STEP4 静默卸载 → STEP5 清理、注册表残留 0；数据目录实测含 `providers.json`/`projects.json`/`sessions/*.json`/`uploads/`（数据目录分离生效）。前 10 轮共修掉 5 个"只有装到机器上才暴露"的缺陷 + 3 处 E2E 自身假阴性（探针目录、userData 名字、脚本自杀 taskkill）
- 2026-10-30（v0.86.0 收口·打包五连）: 装机验证连带修 —— ①依赖闭包用逗号拼 pip 参数导致闭包永远为空（缺 annotated_doc）②元数据不可靠（anyio 无 Requires-Dist → 缺 exceptiongroup）③只拷包目录不拷 dist-info（anthropic 读自身版本 → PackageNotFoundError）④手写 DLL 清单漏 python3.dll（C 扩展 DLL load failed）⑤图片附件路径用 relative_to(workdir) 抛错被吞（goal 里没有附件路径 → 模型说看不到图）；bundle 增加 [5/5] 真实 import 自检 + 缺什么自动补齐（最多 30 轮）+ 打包后清脏数据；白名单纳入延迟 import 的 celery/redis/GitPython/otel/LSP（+27MB）
- 2026-10-30（v0.86.0 收口）: 桌面端 **10 个真实缺陷/缺口**闭环 —— ①数据目录分离（`CLAWD_DATA_DIR` 唯一入口 + 旧数据一次性迁移，修"重启后配置/用量/会话全丢"）②provider 改 JSON 可手改不丢 ③工具调用折叠成组（"运行 N 命令 和 编辑 M 文件"）④上下文面板 ⑤会话按项目分组（`workdir` 写入会话 metadata）⑥`/api/sessions`+`/api/session` 硬编码 `cwd/.clawd` 改走数据目录（**侧栏永远空着的根因**）⑦更新提示改右下角 toast + `quitAndInstall` 桥 ⑧三个启动级 bug：Electron 主进程 TDZ（函数内重复解构 `ipcMain`）；打包缺 `annotated_doc`（依赖闭包用逗号拼 pip 参数 → 闭包永远为空）；打包缺 `exceptiongroup`/`python3.dll`/dist-info（元数据不可靠 + 手写 DLL 清单漏项）→ bundle 加 [5/5] 真实 import 自检 + 缺什么自动补齐⑨世界模型索引排除 site-packages（11606→635）⑩签名构建管线（`-SelfSigned` 验证通过，Status=UnknownError 属自签名预期）；新增 `tests/server/test_sessions_api.py`（4 项真 HTTP）+ `tests/test_electron_main_static.py`（7 项静态检查，含"先用后声明"反向验证有效）+ 会话 workdir 3 项
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

## 2026-10-30 v0.83.0 —— UI 截图走查迭代 + 图片可粘贴上传 + 续聊 + CLI Markdown + 签名脚本

- [x] 截图走查（20~25 六张）发现并修：历史会话答案重复两遍（落盘去重 + 加载去重）、
      用量柱状图一根柱子糊满（柱宽上限 42px + Y 轴刻度/网格）、设置下拉是系统白色（统一深色）、
      「当前生效 Provider」显示错乱（拆只读行）。
- [x] 图片输入：粘贴/拖拽 → 缩略图 → data URL 随 run 发送 → Host 落盘 `.clawd/uploads/`；
      模型不支持视觉就如实说看不到（实测 `step-5-preview` 回"不支持视觉输入"），对话区无 base64 泄漏。
- [x] 续聊：点开历史会话记录 prior_messages，下一条消息带上下文；界面提示"已载入 N 条历史"。
- [x] CLI：plain 模式最终答案走 rich.markdown（失败降级纯文本）。
- [x] 签名脚本 `scripts/build_desktop_signed.ps1`（-Pfx 真证书 / -SelfSigned 验证管线；无证书退出 2 并说明）。
- [x] `hermes-agent-tmp/` 390MB 移出仓库（未删除）。
- 测试：console E2E 17 项全绿；core+server+cli+agent 全绿；ruff 全过。

### v0.83.0 追加：装到机器上最关键的 bug —— 索引把 UI 拖死
- 现象：安装版里用量/provider 面板一直"加载中…"；Host 日志 `检测到 11606 个文件发生语义变更`。
- 根因：打包版 cwd = `resources/host`（含内嵌 Python 运行时），`WorldModel.initialize()` 用
  `root.glob("**/*.py")` 把 `python/Lib/site-packages` 里 1.1 万个 .py 当源码索引，占满事件循环。
- 修法：新增 `src/core/source_scan.py`（排除 site-packages/node_modules/venv/dist/.git/.clawd…），
  `world_model` 与 `CodeGraph` 兜底扫描都改用它；超 `CLAWD_WM_MAX_FILES`（默认 5000）→ 跳过索引并如实告知。
- 实测：同一目录 11606 → **635**；`/api/usage` 响应 **83ms**；tests/brain+rag+core **1074 passed**。

## 2026-10-30 v0.84.0 —— P3 三项 + 风险表四条（28/28 机器可验）

- [x] P3-2 死码收敛：删 31 文件 / ~4.5k 行（background、core/journal、core/secrets、core/auth(+auth_module)、
      middleware、health_check、surface_viewer、version_check、history_compressor、task_analyzer、
      swarm/team_types、synthesized_agent、workflow/integration_*、pipeline_stages、code_simplifier）；
      不可达 141→110（29,933→25,441 行），可达 494→495（没降），IMPORT-FAIL 0；静默吞异常 162→159（门禁同步收紧）。
- [x] P3-1 core 边界：`scripts/core_surface.py` 禁止 core→上层 import；6 处存量登记 allow.json + 迁移方向；公开面 89 符号；153 文件/34,112 行。
- [x] P3-3 讲人话入口：`clawd explain --cross`（跨会话：成功率/成本/tokens/常见失败/失败最多工具）。
- [x] R1 假成功扫描：`scripts/scan_fake_success.py`（AST，排除能力谓词）→ 0 命中。
- [x] R2 MCP 可启动性：`scripts/check_mcp_startup.py` 真 spawn 4 台 → 4/4 PASS。
- [x] R3 两套账本：`src/workflow/run_ledger.py` + `clawd ledger`（ADR 0020），真实仓库抓到 1 条存量不一致。
- [x] R4 文档漂移门禁改用 hard_metrics 单一阈值。
- 验证：`verify_audit_p1.py` 28/28；tests/workflow+cli+core 1868 passed；brain+rag 1074 passed；ruff 全过。

## 2026-10-30 v0.85.0 —— 修「重启后数据丢」+ provider JSON + 工具折叠 + 上下文面板

- [x] 数据目录与程序目录分离：`src/core/data_dir.py`（`CLAWD_DATA_DIR` 优先），
      `local_db`/`session_bridge`/附件上传/引擎落盘全部改走它；Electron 传 `--data-dir <userData>/data`
      并设同名环境变量；**旧安装目录里的 .clawd 自动迁移一次**（不覆盖已有文件）。
- [x] provider 配置改 JSON（`<数据目录>/providers.json`，原子写；老 SQLite 自动迁移）；
      用量仍 SQLite（高频+聚合查询，理由写在模块 docstring）。
- [x] 工具调用折叠成一组：`命令 2 · 读取 1 · 执行中… ⌄`，展开逐条 ✓/✗ + 参数；
      LLM/token 噪音事件只进「轨迹」。E2E 断言：默认折叠、分类计数、展开 3 条。
- [x] 上下文用量面板（◎）：`已用/窗口(%)` + 进度条 + 分项（消息历史/技能清单/剩余空间），
      新端点 `/api/context`（`CLAWD_CONTEXT_WINDOW` 可覆盖，默认 200k）。
- [x] 安装 E2E 新增 STEP2e：重启应用后 `/api/providers` 仍有配置（直接验证用户头号投诉）。
- 测试：`tests/core/test_data_dir_and_providers_json.py` 13 条（含跨进程重启读取）；
      core+server+cli 1459 passed；console E2E 21 项全绿；ruff 全过。

## 2026-10-30 v0.86.0 —— 客户端照抄参考项目（项目/添加项目/模型选择器/计时）

- [x] 侧栏「项目」：列表 + 点击切换（active 高亮）+ ✕ 移除（不删文件）；存 `<数据目录>/projects.json`；
      **新会话工作目录 = 当前项目**（run 带 workdir → 引擎 create(workdir=...)）。
- [x] 「添加项目」对话框：主机下拉 / 浏览文件夹（Electron 原生 pickFolder，网页降级为粘贴路径）/
      从 URL 克隆（Host 真跑 `git clone --depth 1` 到 `<数据目录>/clones/<name>` 并自动加入）。
- [x] 模型选择器：搜索 + 模型列表（含来源）+ 推理强度 5 档 + 快速模式开关；
      run 带 model/reasoning_effort/fast_mode（推理强度→temperature 0.9→0.0，快速模式 max_tokens ≤1024）。
- [x] 会话栏「工作了 Ns / Nm Ns」计时（每轮开始/结束）。
- 验证：控制台 E2E **24 项全绿**；`tests/core/test_projects_store.py` 7 条；core+server+cli 1465 passed；
      走查截图 29-add-project / 30-model-picker / 26-tool-fold / 28-context-panel。
- 未做（下一步）：会话按项目分组、更新提示 toast 化、任务/自动化面板（参考项目专属功能，需另定）。

- [x] 修启动级 bug：0.86.0 首个安装包**打不开**（main.js 用 ipcMain 但没解构导入 →
      registerIpcHandlers 抛错 → 主进程在开窗前挂掉）。已补导入，并新增
      `tests/test_electron_main_static.py`（6 条）静态守住"electron 符号必须都导入 / 无默认菜单 / preload 不透 Node"。

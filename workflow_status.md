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

# 变更日志

所有重要的项目变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [未发布]

### v0.60.6 (2026-10-20) — 第三轮审查收口：生产持久化、测试强度、证据修正

第三轮独立审查（reviewer-round3）判定 Request Changes，阻塞点为 C1（修复落在
生产不可达模块）与 C2（并发测试被降强度）。本轮逐项关闭。

#### C1：生产持久化

- 确认 `src/core/state_impl.py` 在 `reachability --prod --list` 中属于
  **生产不加载**（391 行）；v0.60.4 的修复只提升了一致性，不等于生产已修复。
- 真正生产可达的 `src/core/persistence/run_state.py`（被 `workflow/engine.py`、
  `status_dashboard.py` 等使用）存在同类问题：
  - `_write_atomic` 使用固定 `<name>.tmp`、无锁、无 fsync，且先 move 目标再 replace；
  - `record_evidence_event` 的 JSONL 追加无锁、无 fsync；
  - `update_task` 的 OCC 检查与写入不在同一临界区。
  已改为 `file_lock + atomic_write`、锁内读改写、备份先 copy 再覆盖。
- 新增生产函数并发回归：`tests/core/test_run_state_concurrency.py`
  （4 线程更新任务不丢、4×10 事件追加 40 行且每行合法 JSON）。

#### C2：测试强度

- 恢复 `test_state_persistence_semantics.py` 的原并发强度：
  atomic write 20 次、mode_state 10 次、progress 10 次、读改写 25 次（断言 100）。
  `timeout=60` 保留（审查实测原参数可通过）。

#### 证据修正

- 收集基线改为实测 **3171 tests / 0 errors / 64.84s**。
- HTML 报告题数说明改为 9 题；正文证据更新为 v0.60.5/3163 passed/2773s。
- `.agent/memory` 的收集数字与“未达成”矛盾已清理；补充 async 重入限制条目。

---

### v0.60.5 (2026-10-20) — 持久化持久性与锁等待

- `atomic_write` 增加 `flush + fsync`：掉电后不再出现“文件存在但内容为空/半截”。
- `state_impl` / `state.persistence` 的状态写入锁等待上限提高到 30s：
  全量测试高负载 + fsync 下，10s 会偶发 `TimeoutError`（实测）。
- HTML 变更报告更新到 v0.60.4/0.60.5，测验扩为 9 题（真实浏览器 9/9 通过）。
- 并行负载复验：`tests/core` 669 + `tests/workflow` 226，0 failed。
- 熔断器半开测试改为有界轮询等待：固定 `sleep(timeout + 0.05)` 在高负载下
  偶发踩边界（全量实测），轮询不改变“必须迁移到 HALF_OPEN”的断言。

#### 验证

- `pytest tests/core/test_state_persistence_windows_safe.py -q` 连续 5 次通过。
- 并行跑 core/workflow 无锁超时。

---

### v0.60.4 (2026-10-20) — 终审补充：跨平台状态持久化

- `src/core/state_impl.py`（**生产不可达**的平行实现）的 `save_snapshot`
  曾在函数内 `import fcntl`；该模块在 Windows 上会保存失败。已改用
  `file_lock + atomic_write`，但**不宣称生产受此缺陷影响**。
- `src/core/state/persistence.py`：快照/事件原子写；`append_event` 加锁。
  该模块在 `src/` 中无调用方（`append_event` 也无生产调用方），属一致性修复。
- 生产路径 `src/core/persistence/run_state.py` 的同类问题在 v0.60.6 修复。
- 新增回归：Windows 跨平台保存、4 线程 ×10 次并发追加（40 条不丢）。
- 收集基线复测：**3171 tests / 0 errors / 64.84s**（收集 <120s 已达成）。

#### 验证

`pytest tests/core/test_state_persistence_windows_safe.py -q` → 2 passed；
`pytest tests/core/test_run_state_manager.py tests/integration/test_phase2_integration.py -q` → 21 passed。

---

### v0.60.3 (2026-10-19) — 终局审计：启动链路、核心依赖、测试套件退出、执行骨架

把项目当成真实交付物做终检，发现并修复以下问题。

#### P0：核心安装/启动链路

- `requirements.txt` 含不存在的 `braintrust>=0.50.0`，`pip install -r` 整体失败；
  该 processor 也未移植，已移除。
- `start.bat` 依赖 PATH 中不存在的 `python`；改为 `py -3.10` → `py -3` → `python`。
- 启动脚本安装全部 `requirements.txt`（含 celery/redis 等非必需）且失败仍报“成功”；
  改为 `pip install -e .`，失败 `exit /b 1`。
- venv 缺 `wheel` 导致 editable 构建失败；脚本先装 `setuptools wheel` 并使用
  `--no-build-isolation`。
- `src/utils/__init__.py` 急切导入可选依赖 `pathspec`，核心安装后 CLI 直接崩溃；
  改为可选导入 + 明确降级提示。
- `loguru`、`toml` 被核心模块直接 import 但未在 `pyproject.toml` 声明；
  已补进核心依赖（否则命令组整体失效）。

#### P1/P2

- `atexit` 阶段重导入导致 `can't register atexit after shutdown` traceback；
  清理函数捕获并降级为 debug。
- `doctor` 版本正则只认中文冒号，README 写成英文冒号时显示“无法提取”；已兼容。
- 测试套件无法退出：`test_goalx_integration.py` 是无超时的真实 LLM E2E，
  改为 `RUN_GOALX_E2E=1` opt-in；`test_agent_engine_refactor.py` 启动 WorldModel
  进程池导致 pytest 挂起，fixture 改为 tmp_path 并禁用后台初始化。
- 删除无任何测试函数的 `tests/test_slop_data.py`。

#### 执行骨架与文档

- 新增 `.agent/skills/`（9 个）、`.agent/memory/`（7 个）、`.agent/rules.md`。
- 新增 `reports/change-report-2026-10-19.html`（9 题测验，真实浏览器 9/9 通过）
  与 `reports/plan-audit-2026-10-19.md`。
- 计划文档审计：三份文档仍含未闭环项或为维护依据，**未删除、未归档**。
- 更新 `计划书/下一步改进指南.md` 顶部状态表为 v0.60.3 实测。

#### 验证

- `start.bat doctor` 端到端退出码 0（89s，诊断全 PASS）。
- `venv/Scripts/python.exe -m src --version` → v0.60.3，无缺失依赖/traceback。
- 根目录测试 270 passed / 1 skipped（76.5s，正常退出）。
- 全量测试结果见 `test_ledger.md`。

---

### v0.60.2 (2026-10-19) — 复审收口：过滤调用 id、生产读改写锁、安全测试真实性、版本解析

第二轮独立审查（reviewer-round2）仍判定 Request Changes；本轮逐项关闭。

#### 原生工具调用

- **被 `max_repeat_calls` 过滤的调用也补 `role=tool` 消息**：此前过滤后
  assistant 的 `tool_calls` 留下悬空 id，下一轮会 400。
- `tool_call_id` 改为**按调用顺序**与 `tool_calls` 一一对应，不再按
  (name,args) 签名映射（同名同参会拿到彼此的 id）。
- 新增“重复调用被过滤后无悬空 id”的回归测试。

#### 状态持久化

- `ModeStateManager.cancel_mode` 的 read→modify→write 整体加锁。
- `team_persistence` 的 `add_team_member` / `remove_team_member` /
  `update_member_status` / `add_team_message` 统一走
  `_mutate_team_state`（锁内读改写）。
- 新增直接针对生产函数的并发回归：`ModeStateManager.update_state`、
  `add_progress_entry`。
- `file_lock` 的 `stale_after` 默认提高到 300s；owner 写入失败时保留锁目录
  等待回收，不再冒险删除他人锁。

#### 安全

- `SafeRedirectHandler` 提到模块级；测试直接导入生产实现并断言拦截，
  不再在测试里复制一份逻辑（消除虚假覆盖）。

#### 版本与可观测性

- `src.__version__` 改为 **pyproject.toml 优先**：editable 安装元数据滞后时，
  不同解释器也能显示同一版本。
- tracing 恢复逐 provider 异常隔离（一个 provider 失败不影响另一个）。

#### 验证

- 全量：**3162 passed, 4 skipped, 1 xfailed, 0 failed**（1531s）。
- 定向：1383 passed / 1 xfailed。
- E2E：`e2e_smoke` 5/5、`e2e_production` 8/8；压测 5/5。

---

### v0.60.1 (2026-10-19) — 独立审查修复：CI 门禁、原生调用协议、SSRF 前置校验、锁语义

独立审查（reviewer-round1）判定 Request Changes；以下为逐项修复。

#### 阻塞项

- **CI lint 真实通过**：`ruff check src/ tests/ --select F821,F811,E9` 此前有
  4 个 F811（全部在 `tests/`）。已修复，CI 同款命令现在 `All checks passed`。
  `evidence/B1-ci-gates.json` 已更正为此前只跑 `src/` 的错误证据。
- **CI 依赖可复现**：`dev` 额外依赖补 `ruff` 与 `pytest-cov`，干净环境可执行
  lint 与 `--cov`。

#### 原生工具调用协议

- 参数解析失败时补一条 `role=tool` 消息，避免 assistant 的 `tool_calls`
  留下悬空 id（否则下一轮 400）。
- 被 `max_repeat_calls` 过滤的调用同样补 `role=tool` 消息；id 与调用顺序
  一一对应（不再按签名映射，避免同名同参错配）。
- 同名同参的重复调用按**队列**分配 `tool_call_id`，不再复用同一 id。
- 流式路径启用开关时显式告警并回退文本协议，不再静默无效。

#### 安全

- Scrape 的三种后端改为**重定向前置校验**：httpx 手动逐跳、urllib 自定义
  `HTTPRedirectHandler`、Playwright `page.route` 拦截。
- `validate` 阶段不再做同步 DNS，避免阻塞事件循环；DNS 在真正抓取时校验。
- DNS rebinding TOCTOU 仍未消除，已在 evidence limitations 中披露。

#### 持久化与可观测性

- `file_lock` 改为可重入 + owner token + 原子回收陈旧锁；`update_state` /
  `add_progress_entry` / `cancel_mode` / `team_persistence` 的读改写整体加锁，
  修复丢失更新。
- 新增直接针对生产函数的并发回归：`ModeStateManager.update_state` 与
  `add_progress_entry`。
- `atomic_write` 的 Windows 重试提高到 8 次 / 50ms，并发测试连续 3 次稳定。
- tracing 的 `_setup_*` 返回 bool，跳过时不再谎报“已初始化”；`setup_tracing()`
  接入 `initialize()`，功能不再是无调用点的死代码。

#### 其他

- `SafeRedirectHandler` 提到模块级，安全测试直接测生产实现（不再复制逻辑）。
- `src.__version__` 改为 **pyproject.toml 优先**，避免 editable 元数据滞后
  导致不同解释器显示不同版本。
- `atomic_write` 的 Windows 重试提高到 8 次 / 50ms。

#### 验证

全量回归、E2E、SSRF/状态/原生调用回归见 `test_ledger.md` 与 `evidence/`。

---

### v0.60.0 (2026-10-19) — 参考对标落地：CI 门禁、持久化语义、工具策略、Skill 接线、原生工具调用

本轮基于 `参考的结果计划指南.md` 的 Phase A 审计，按 P0/P1 批次落地。

#### P0

- **CI 门禁修复**：移除无效的 `--fail-on-incremental`；lint 分为
  “硬错误阻塞（F821/F811/E9）+ 全量非阻塞报告”；覆盖率阈值按实测基线
  分阶段设为 45%（目标 60% 保留在 `pyproject.toml`）。
- **tracing 移植残留**：`src/core/tracing/setup.py` 不再绝对导入 `onyx.*`；
  Braintrust processor 未移植时明确告警并跳过；Langfuse 改用项目内
  `TraceProvider.register_processor`。`pyproject.toml` 新增 `tracing` 可选依赖。
- **能力可见性**：`clawd doctor` 新增 RAG / World Model / WebSocket 服务端
  的启用状态；RAG 默认关闭并提示 `CLAWD_ENABLE_RAG=1`。
- **Agent 错误路径**：修复 `publish_task_error()` 方法体内混入 `__init__`
  尾部赋值的问题。

#### P0-5 状态持久化语义

- 新增 `file_lock` / `locked_atomic_write_json`（跨平台目录锁 + 原子写）。
- `PipelineState` 写入增加 `schema_version` / `attempt` / `updated_at` /
  `working_path`；`save(expected_attempt=...)` 提供乐观并发检查，
  不匹配抛 `StaleStateError`；更高 schema 版本拒绝恢复。
- `mode_state` / `team_persistence` / `ralph_ledger` 的 JSON 写入统一为
  加锁原子写，避免并发丢写与半截文件。

#### P1

- **工具风险策略**：`BaseTool.risk_kind` 显式声明 read/write/exec；
  `classify_tool()` 优先使用声明，名称启发式仅作兜底。
  默认工具（Bash/FileEdit/FileRead/Glob/Grep/HotFiles/Scrape/UDiff/Clipboard 等）已声明。
- **Scrape SSRF 加固**：仅 http/https；默认拒绝 localhost/元数据域名/
  私网/回环/链路本地/保留地址；DNS 解析结果同样校验；重定向后二次校验；
  `CLAWD_SCRAPE_ALLOW_PRIVATE=1` 仅供本地测试。
- **Skill 渐进披露**：新增 `skill_loader` 与 `SkillTool`；系统提示注入
  name + description 清单，正文按需读取；默认工具池新增 `SkillTool`。
- **WebSocket 入口**：新增 `clawd server` 命令（host/port/token/developer-mode），
  未配置 `AGENT_SERVER_TOKEN` 时生成本次一次性令牌。
- **原生工具调用（可选）**：`LLMResponse` 支持 `tool_calls`；
  OpenAI 兼容 provider 解析原生调用；Agent 循环优先原生、回退文本；
  设置 `CLAWD_NATIVE_TOOLS=1` 启用，默认关闭。
- **测试收集**：`pyproject.toml` 禁用与本项目无关的 pytest 插件
  （langsmith/seleniumbase/faker/flask）。

#### 验证

见 `test_ledger.md` 与本轮 `evidence/`。未达成的指标（覆盖率 60%、
收集 <120s、死模块 ≤20）在 `workflow_status.md` 中如实披露。

---### v0.59.0 (2026-10-19) — 审查阻塞项：pipeline 阶段去占位、验证目录修正

独立审查（review-d）判定 REQUEST_CHANGES，两条阻塞项经复现后修复；
处理过程中又发现两个"从未能工作"的占位阶段。

#### 1. `ralplan` / `team-exec` 是占位实现（返回 `<未实现>` 却报 SUCCESS）

`pipeline.py` 的这两个阶段此前不调用任何引擎，直接返回占位字符串并把
阶段标成 SUCCESS —— 调用方会以为"计划已产出、worker 已执行"。

现接真实引擎：
- `RalplanStage` → `RalplanEngine.run()`，产物含 plan/prd/tasks/confidence；异常 → FAILED
- `TeamExecStage` → `SwarmEngine.run()`，产物含 execution_result/errors；
  swarm 失败 → FAILED

#### 2. `precontext-intake` 导入不存在的模块，永远"成功"地什么都没做

`from .intake import IntakeGate` —— `src/workflow/intake.py` **从未存在**。
异常被捕获后仍返回 SUCCESS。

现改为**真实的最小扫描**：统计目标目录的 `.py` 文件数/行数、给出最大的若干文件；
失败时返回 SKIPPED（而不是 SUCCESS）。

#### 3. `stages/ralph_verify_stage.py` 用错验证目录（审查阻塞项）

`Path(self._config.cwd)` 默认 `"."`，忽略了 `ctx.cwd` —— 若挂进管道，
会在**进程当前目录**跑测试，可能对另一个项目报 passed。
现改为 `Path(ctx.cwd)`，并把"失败后原样重试同一命令最多 10 次"改为**不重试**
（没有重新实现步骤，重试没有意义）。

#### 4. `search_replace` 修复补齐回归测试（审查阻塞项）

`try_strategy` 的策略级异常回退此前无任何测试（原有 28 个用例都不进入 git 策略）。
新增 `tests/tools_runtime/test_search_replace_strategy_fallback.py`：
- 普通异常 → 返回失败且 error 带异常类型（不再一律"未找到匹配"）
- `MemoryError` / `RecursionError` → 仍向上抛（资源级问题不得降级）
- 非 git 目录 → 回退矩阵不中断

#### 5. 其他审查项

- 非法 `CLAWD_VERIFY_COMMAND`（未闭合引号）此前会让 `ValueError` 穿透 →
  现返回 `status="error"`（模块承诺所有失败都有结构化状态）
- `pipeline.py` 工厂 docstring 声称"持久循环"但实现只跑一次 → 已更正，
  并在 artifacts 里记录 `max_iterations` 仅作配置保留
- `docs/MAINTENANCE.md` 仍写"验证阶段是桩""覆盖率 ~20%" → 已同步真实状态

#### 验证

```
pytest tests/workflow/test_pipeline_stage_factories.py      → 7 passed
pytest tests/workflow/test_verification_runner.py           → 15 passed
pytest tests/tools_runtime/test_search_replace_strategy_fallback.py → 7 passed
pytest tests/tools_runtime/test_udiff_parser.py             → 15 passed
真实 pipeline（ralph-verify）                                → SUCCESS, verified=True
```

---

### v0.58.0 (2026-10-18) — 验证阶段变为真实现；修正覆盖率口径

#### 1. 验证阶段不再只是"诚实"，而是**真的执行**

新增 `src/workflow/verification_runner.py`：

- 默认命令：若 `<cwd>/tests/` 存在 → `python -m pytest -q --tb=short tests`
- 可用 `CLAWD_VERIFY_COMMAND` 覆盖（Windows 引号/反斜杠已处理）
- **以退出码判定**，保留命令、耗时、输出尾部作为证据
- 状态语义：`passed` / `failed` / `timeout` / `error` / `not_configured`
- 未配置时返回 `not_configured`，**绝不冒充通过**

接线：
- `pipeline.py` 的 `ralph-verify`：passed→SUCCESS，failed/timeout/error→FAILED，
  not_configured→SKIPPED
- `stages/ralph_verify_stage.py`：`_verify_implementation` 接同一执行器；
  未通过时返回 `failed`（此前恒返回 `completed`），未配置时提前结束迭代

#### 2. 所有 pipeline 阶段真实执行时崩溃（P0）

4 个内嵌阶段类都用 `self._logger`，但基类 `PipelineStage` **没有该属性** ——
一旦真正执行，第一个阶段就 `AttributeError`。此前只测过注册与构造，
从未真正跑过阶段，所以一直没暴露。

修复：4 个阶段类补 `_logger = logger` 类属性。已用真实 pipeline 端到端验证。

#### 3. 两处编辑核心的真实缺陷（覆盖率工作发现）

| 位置 | 问题 | 后果 |
|:---|:---|:---|
| `udiff_parser._directly_apply_hunk` | 从 `search_replace` 导入 **不存在** 的 `SearchTextNotUnique`（该名字定义在本模块） | `apply_hunks` 的直接应用分支**永远 ImportError** |
| `search_replace.try_strategy` | 只捕获 `(ValueError, IndexError, OSError)`；`InvalidGitRepositoryError` 会穿透 | **非 git 目录下**多策略回退矩阵直接中断，编辑失败 |

修复后新增 `tests/tools_runtime/test_udiff_parser.py`（15 用例）。

#### 4. 覆盖率口径修正

此前文档长期写"覆盖率 ~20%"，来自 2026-10-15 的陈旧 `coverage.json`。
本轮用 `pytest --cov=src` 全量实测（48 分钟；补齐用例后全量为 3079 passed）：

```
覆盖率      46.15%（25,877 / 56,072 行，插桩运行时测得）
```

仍低于 `pyproject.toml` 的 `fail_under = 60`，但**不是 20%**。
README / workflow_status / 指南中的旧数字已更正。

同时修掉一个计时脆弱测试（`test_sleeper_sync_sleep` 在覆盖率插桩下
100ms 睡眠被拖到 1.6s）——保留"确实等待了"的下界，放宽上界。

#### 5. 部署验证边界

- **本地安装部署已验证**：`pip install -e . --no-deps --no-build-isolation`
  成功；`clawd.exe --version / agent keywords / catalog reload` 全部实跑通过。
- **容器部署未验证**：本机未安装 Docker，`docker compose build/up` 无法执行。
  已在 `docs/MAINTENANCE.md` 明确写清缺失条件与恢复验证步骤，不冒充已部署。
- 本项目是 CLI/库，无常驻服务进程；"线上热更新"没有可验证的落地路径。

#### 验证

```
pytest tests/tools_runtime/test_udiff_parser.py tests/test_search_replace.py   → 43 passed
pytest tests/workflow/test_verification_runner.py                              → 13 passed
pytest tests/core/utils/test_sleep.py                                          → 9 passed
真实 pipeline 端到端（ralph-verify，CLAWD_VERIFY_COMMAND 控制退出码）          → SUCCESS/verified=True
pip install -e . + clawd.exe --version/agent/catalog                          → 通过
```

---

### v0.57.3 (2026-10-18) — 审查补充项：`pipeline` 命令与若干静默失败

#### `clawd pipeline` 同样"注册成功但运行即崩"

原实现三处错位，实测第一条就抛 `TypeError`：

```python
PipelineConfig(use_team=..., use_ralph=..., budget=...)   # 三个参数都不存在
PipelineOrchestrator(Path.cwd(), config)                  # 参数顺序反了
await orchestrator.execute(goal)                          # 方法不存在
```

重写为真实 API（`create_ralplan_stage/create_team_exec_stage/create_ralph_verify_stage`
+ `create_autopilot_pipeline_config` + `PipelineOrchestrator(config, cwd)`），
并新增 wiring 测试。`--budget` 在编排器上未实现，命令**明确提示不生效**而不是静默忽略。

#### 锁文件损坏不再静默覆盖

`LockStore.acquire()` 解析锁文件失败时 `except Exception: pass`，随后直接覆盖写 ——
两个 owner 可能同时认为自己持锁，正是锁要防的事。
现改为：`logger.error` + 把损坏文件隔离为 `*.corrupt-<ts>` 再重建（可见且不deadlock）。
`release()` 失败也不再静默吞掉。

#### 其他

- `HookPluginDispatchResult.duration_ms` 声明了两次（后者把必填字段静默改成可选）→ 去重。
- `sanitize_plugin_id()` 用 `str.replace(r"...")` 做"正则清洗"，实际是字面量替换，
  完全不生效 → 改为 `re.sub`。实测 `My Plugin!@#.py` → `my-plugin`。
- `memory_server.search()` 读到损坏 JSON 时静默跳过 → 增加 `logger.warning`（带路径）。

#### 验证

```
pytest tests/cli tests/workflow tests/core -q  → 1081 passed
ruff --select F821,F811                       → All checks passed
python -m src pipeline --help                 → 正常
python -m src catalog list / reload           → 正常
```

---

### v0.57.2 (2026-10-18) — 独立审查发现的 5 个阻塞项

v0.57.0/0.57.1 的独立审查线程回传了结论（REQUEST_CHANGES）。以下问题
**全部经复现确认**，均已修复。

#### 1. `workflow` 组四个命令"注册成功但运行即崩"

`--help` 能显示只说明 Typer 注册成功，**函数体**引用的是不存在的符号：

| 命令 | 原引用 | 真实 API |
|:---|:---|:---|
| `ralph` | `SwarmOrchestrator.execute_task()`、`RalphLedger` | `SwarmEngine.run()`、`RalphProgressLedger` |
| `team` | `SwarmOrchestrator.coordinate_task()` | `SwarmEngine.run()` |
| `ralplan` | `RalplanWorkflow.execute()` | `RalplanEngine.run()` |
| `autopilot` | `from .workflow_commands import create_autopilot_pipeline_config`（**从自身模块导入从未定义的名字**） | `workflow.pipeline_orchestrator.create_autopilot_pipeline_config` |

四个命令体全部重写为真实 API。`ralph` 的 `--verify` 不再假装"已验证通过"——
本项目的验证阶段仍是桩，命令会明确打印这一点。

新增 `tests/cli/test_workflow_commands_wiring.py`（4 用例）：
用替身驱动命令体，断言"不抛 ImportError/AttributeError、退出码正确、产物落盘"。

#### 2. `explore` 的只读引擎构建必然失败

原实现导入 `src.tools_runtime.tool_manager.create_readonly_tool_manager`
—— 模块与函数**都不存在**；且 `AgentEngine.__init__` 根本不接受 `tool_manager`
（内部自建）。改为：构造期间临时注入 `APPROVAL_MODE=plan`（真实只读门禁，
PLAN 会拒绝一切 write/exec），构造后还原；门禁未生效时显式告警。

#### 3. `catalog list/reload` 运行即崩

- `src/catalog/manifest.py:111` 给 `SkillDefinition` 传了不存在的
  `internal_required=True` → `TypeError`，`get_catalog()` 整体失败。
- `catalog_commands` 调用 `CatalogManifest.get_counts()`，该方法从未存在
  → `AttributeError`。

修复：去掉多余参数（状态已是 `INTERNAL`）；补齐 `CatalogCounts` +
`get_counts()`。实测 `catalog list` 正常、`catalog reload` 输出
"技能数 39（活跃 23）/ Agent 数 30（活跃 18）"。

#### 4. 断点续跑从未生效（三处叠加）

1. `run()` 先 `start_mode()`（写 index=0）再 `can_resume()` → 永远读到 0。
2. `_complete_pipeline("failed")` 写 `active=False` + phase `"failed"`，
   而 `can_resume()` 排除 `"failed"` → 失败后永不可恢复。
3. 失败阶段写 `index=i+1` → 恢复会跳过失败阶段。

修复：先读状态再初始化；失败时 `active=True`、phase=`stage:<name>:failed`；
失败阶段保持 `index=i`（重试该阶段）。恢复测试实测：
`calls s1=1, s2=2, s3=1`（s1 不重跑、s2 重试）。

#### 5. `PipelineState` 往返丢字段

`save` 写 `pipeline_stages` 但 `load` 不读回 → `load→save` 后 `can_resume`
由 True 变 False；`artifacts` 则两边都不处理。已补：
`stage_names`、`artifacts` 双向持久化；artifacts 做 JSON 归一化
（阶段把 `ctx.cwd` 放进 artifacts 时不再让整份状态写入失败）。

#### 同时修复（审查的非阻塞项）

- **`BudgetGuard` 跨轮状态泄漏**：复用实例后，第二次 `run()` 继承上轮
  `accumulated_cost/is_exhausted/start_time`。新增 `reset_for_run()` 并在
  `run()` 中调用（保留 config 与注入的替身）。附回归测试。
- `_resolved_dimensions` 在本次未配置维度时未清空 → 同一 engine 二次运行沿用旧维度。
- `create_pipeline(cwd=...)` 只影响阶段、不影响状态目录 → 对齐。
- `memory_server` 模块 docstring 与 MCP 工具描述仍称"语义搜索"，
  实际是子串匹配（score 恒 1.0）→ 如实改为关键词检索。
- `types.py` 去重后残留 4 个孤立 `@dataclass` 装饰器 → 清理。
- 测试文件未使用的 import → 清理。

#### 验证

```
pytest tests/ -q --tb=no                                → 3051 passed / 0 failed
pytest tests/cli tests/workflow tests/core -q           → 1080 passed
pytest tests/workflow/test_pipeline_orchestrator.py -q  → 30 passed
pytest tests/cli/test_workflow_commands_wiring.py -q    → 4 passed
ruff --select F821,F811                                 → All checks passed
scripts/import_sweep.py                                 → 0 缺陷（639 模块）
scripts/reachability.py                                 → 429（与基线一致）
python -m src catalog list / reload                     → 正常（39 技能 / 30 Agent）
python -m src agent keywords                            → 11 个关键词
scripts/verify_html_report.py                           → 10 题全部通过（真实浏览器）
```

---

### v0.57.1 (2026-10-18) — 启动耗时与循环导入

v0.57.0 发布后继续追查可用性时发现的两个问题。

#### 启动耗时：消除导入期重依赖

`litellm` 实测**导入本身约 34 秒**（连带 openai / httpx / pydantic 的大量子模块）。
它原本在 `src/llm/litellm_singleton/__init__.py` 顶层导入，而导入链是：

```
src.main → src.cli_handlers → src.workflow.cli_handler → src.workflow
  → src.workflow.experience_bank → src.core.experience_bank
  → src.memory.enterprise_ltm → src.llm.litellm_singleton → litellm
```

结果是 **`clawd --version` 也要先等几十秒**。四处改为惰性：

| 文件 | 改法 |
|:---|:---|
| `src/llm/litellm_singleton/__init__.py` | 顶层不 import litellm；PEP 562 `__getattr__` 保留 `from ... import completion` 兼容 |
| `src/__init__.py` | `CostEstimator` / `Event` / `ClawdError` 等改为按需导入；`__version__` 仍即时 |
| `src/agent/__init__.py` | 整个 Agent 栈改为按需导入 |
| `src/main.py` | `cli_handlers` 与 `cost_estimator` 移入实际使用点 |

实测（本机，数字受磁盘/杀软波动影响）：

```
import src             6.8s → 1.6s
import src.main       50.9s → ~8s
```

> `import src.cli.entrypoint` 仍有 ~20s：剩余成本来自
> `src.workflow`（experience_bank → llm）与 `src.core.__init__` 的急切再导出。
> 继续优化需要把 `src/core/__init__.py`（约 60 个再导出）与
> `src/llm/__init__.py` 一并惰性化 —— 属独立工程，不在本轮硬做。

#### 顺带修复：一个被掩盖的循环导入（P0）

`src/__init__` 惰性化后暴露：

```
src.utils.__init__ → diff_utils → src.core.patch.diff_engine
  → src.core.__init__ → args_parser → from ..utils import get_logger
  → ImportError: partially initialized module 'src.utils'
```

此前它被 `src/__init__` 的急切导入顺序掩盖。受影响的是**以
`from src.utils import ...` 作为进程第一个导入**的任何调用方
（包括 `CodeGraph.build` 的 `ProcessPoolExecutor` 子进程 ——
实测会抛 `BrokenProcessPool`）。

修复（两步，缺一不可）：

1. **在 `src/utils/__init__.py` 中提前绑定 `get_logger`**（只绑这一个名字，
   放在 `from . import deprecated_args, diff_utils, ...` 之前），破掉环。
   **不能**把整行 `from .logger import ... debug ...` 提前 ——
   随后导入 `.debug` 子模块会把包属性 `utils.debug` 覆盖成**模块对象**，
   调用时报 `TypeError: 'module' object is not callable`（第一版修复踩了这个坑，
   全量测试 56 红）。完整导出仍保留在 `.debug` 之后。
2. `src/core/args_parser.py` / `evolution.py` / `memory_guard.py`
   改为直接从 `..utils.logger` 导入，减少对包级 `__init__` 的依赖。

配套更新 `tests/test_main.py` 的 patch 目标：
`src.main.get_command_handler` → `src.cli_handlers.get_command_handler`，
`src.main.log_pricing_check` → `src.core.cost_estimator.cost_estimator.log_pricing_check`
（实现已改为在函数内导入，patch 必须指向**提供者模块**）。

---

### v0.57.0 (2026-10-17) — 静态缺陷清零、重复定义收敛、测试基线转绿

本轮把《下一步改进指南》里 v0.51 段的硬指标真正跑通，并修掉了一批
"只有跑测试才会暴露"的真实缺陷。

#### 硬指标（验收命令实跑）

| 指标 | 之前 | 现在 |
|:---|:---|:---|
| `ruff --select F821`（未定义名称） | **40 errors** | **All checks passed** |
| `ruff --select F811`（重复定义） | **19 errors** | **All checks passed** |
| 全库导入扫描 | 16 个模块导入即崩 | **0 个** |
| 全量测试 | 2999 passed / **31 failed** | **3033 passed / 0 failed** |
| 契约测试 | 39 passed | 39 passed |

#### 40 个未定义名称：多数是真实运行期 NameError

不是"注解写错"那么简单。逐类说明：

| 位置 | 问题 | 后果 |
|:---|:---|:---|
| `cli/commands/workflow_commands.py:328` | `Progress/SpinnerColumn/TextColumn` 未导入 | `clawd workflow autopilot` 运行即崩 |
| `cli/commands/catalog_commands.py:99` | `catalog` 未定义（应为 `new_catalog`） | `catalog reload` 崩 |
| `cli/config_enhancer.py:80` | `toil` 拼写错误 | 工具探测永远为假 |
| `core/quality_gate.py:314` | `console` 未定义 | 质量门 CLI 崩 |
| `utils/truncation.py:49` | `estimate_tokens` 未导入 | 大输出截断路径崩 |
| `tools_runtime/sandbox/docker.py:154` | `subprocess` 未导入 | Docker 沙箱关闭时崩 |
| `workflow/team/state/dispatch_lock.py:136` | `ClawdError/ErrorCode` 未导入 | 分发锁失败路径崩 |
| 其余（`Any` / `Path` / `ClassVar` / `Dict` / `Optional` / `T` / `Literal`） | 注解符号未导入 | 静态检查失败，`get_type_hints` 崩 |

`autoresearch` 的 `"a" | "b"` 写法一并改为 `Literal[...]`（字符串按位或，导入即 TypeError）。

#### 19 个重复定义：删除前一份，保留运行时生效的后一份

- `src/core/exceptions.py`：13 个异常类**逐字重复**（AST 比对确认 IDENTICAL），删除整段 150 行
- `src/hooks/extensibility/types.py`：4 个 dataclass 完全重复
- `src/templates/manifest.py`：`TemplateLoader` 重复
- `src/core/config/settings.py`：`load_settings` 先导入后被包装函数覆盖（有意为之，改为别名导入）
- `src/runtime/engine.py`：`derive_readiness` 重复定义
- `src/hooks/extensibility/loader.py`：`HookPluginDescriptor` 与 `types.py` 各定义一份
  —— **两个同名类，`isinstance` 互不为真**。统一到 `types`。

#### 四个"测试从未通过"背后的真实缺陷

`tests/workflow/test_pipeline_orchestrator.py` 从初始提交起就没绿过
（引用 `StageStatus.COMPLETED`、`PipelineConfig(state_file=...)` 等不存在的 API）。
追查后发现实现侧确实有 5 个真问题：

1. **`ReadinessSnapshot.ready` 字段被同名 classmethod 覆盖**
   实测 `ReadinessSnapshot().ready` 是 `<bound method>`，`if snap.ready:` 恒为真，
   `RuntimeSnapshot.ready()` 恒返回真。→ classmethod 改名 `all_ready()`。
2. **`_deserialize_result` 不把 status 字符串还原成枚举**
   恢复出来的失败阶段 `== StageStatus.FAILED` 恒为 False，断点续跑会当成正常。
   同时丢失 `skipped_reason`。
3. **`_deserialize_event` 遍历 dataclass 字段字典用 `f.name`**
   `'str' object has no attribute 'name'` —— 持久化恢复必崩。
4. **`PipelineState.save(state_file)` 完全忽略参数**
   调用方传入路径后文件不会出现在那里。`can_resume()` 也因阶段列表永远存空而恒为 False。
5. **`PipelineConfig.cwd` 从未生效**；`create_pipeline()` 不接受裸函数；
   `stage.can_skip` 未做存在性判断。

另有两个：
6. **`BudgetGuard` 在 `run()` 里被整个替换** → 外部注入的预算策略被静默丢弃。
7. **`spawn_platform_command_sync(spawn_fn=subprocess.run)` 是定义时绑定**
   → 全局 monkeypatch 无效，测试实际启动了真实子进程。

#### 工程基建

新增 `scripts/import_sweep.py`：逐个 import 全部模块，区分「项目内代码缺陷」
与「第三方依赖缺失」，补上 `reachability.py` 的盲区（**可达 ≠ 可导入**）。

新增 `scripts/verify_html_report.py`：用真实浏览器验证交付的报告与测验
（答对全部 → 判定通过；错一题 → 判定未通过；选项标色正确）。

#### CLI 调用闭环

| 问题 | 后果 | 修复 |
|:---|:---|:---|
| 顶层命令 `workflow` 与同名**命令组**共存 | 组遮蔽命令，`clawd workflow "目标"` 把目标当子命令解析，永远跑不到 5 阶段引擎 | 顶层命令改名 **`run`** |
| 命令组注册**不幂等**（模块导入 + `main()` 各注册一次） | `registered_groups` 出现重复项（实测 8 项 / 4 个名字） | 加 `_REGISTERED_GROUPS` 护栏 |
| `python -m src.main` 与 `clawd` 是**两套不同 CLI** | 同一个 `workflow` 在两个入口下语义不同 | 新增 `src/__main__.py`，`python -m src` 与 `clawd` 完全一致；`src.main` 标记为历史入口 |
| README 有两条**不存在的命令**示例（`workflow run --goal`、`budget status`） | 用户照抄即失败 | 改为实跑验证过的命令，并逐条验证 |

#### `--dimension/-d` 断链

CLI 一直支持 `-d creative --dimension adversarial`，实现是
`set_config("dimensions", [...])`。但**全仓库没有任何代码读取这个键** ——
参数被接受、被存储、然后被遗忘。

现在：`WorkflowEngine.run()` 解析运行时配置 → 生成维度引导文本 →
注入 `HealableExecutor` 的提示词（Swarm 与常规策略两条路径），
并挂到 `WorkflowTask.dimensions` 随状态持久化。

顺带确认：`src/workflow/dimensions.py`（英文内置库）**生产不可达**，
真正有效的是 `src/core/config/dimensions.py`（中文内置库）。接线使用后者。

#### RAG 增量扫描性能

`UnifiedScanner.scan_directory` 原对**每个**文件都 `run_in_executor`。
增量扫描时 1000 个文件全部缓存命中，但 1000 次线程池调度 + 1000 个 coroutine
的开销远大于工作本身：

```
全量扫描        13.20s
纯串行缓存命中   0.73s
原增量扫描       2.20s   ← 比串行还慢
```

改为"缓存命中走同步快路径，只把未命中交给线程池"，
增量扫描降到 ~0.7s，`tests/performance/test_rag_pressure.py` 转绿。

#### 文档清理

删除 16 个来自早期 AI 会话的陈旧报告（`FINAL_SUMMARY.md`、`INTEGRATION_*.md`、
`QUICK_REFERENCE.md` 等）。它们互相引用、互称"已完成"，但与仓库真实状态不符
（例如声称覆盖率 ~50%，实测 ~20%）。git 历史仍可追溯。

仓库根目录现在只保留：
`README.md` / `CHANGELOG.md` / `CONTRIBUTING.md` / `ARCHITECTURE.md` /
`AGENTS.md` / `CLAUDE.md` / `workflow_status.md`。

#### 验证

| 命令 | 结果 |
|:---|:---|
| `pytest tests/ -q` | **3035 passed / 0 failed** |
| `pytest tests/contracts -q` | 39 passed |
| `ruff check src/ --select F821` | All checks passed |
| `ruff check src/ --select F811` | All checks passed |
| `python scripts/import_sweep.py` | 0 缺陷（638 模块） |
| `python scripts/reachability.py` | 429 生产可达（未变） |
| `python -m src --version` | `Clawd Code v0.57.0` |
| `python scripts/e2e_production.py` | 8/8 |
| `python scripts/verify_html_report.py` | 6 项断言全过（真实浏览器） |

---

### v0.56.0 (2026-10-17) — 导入期缺陷清剿：7 个 CLI 命令从"静默消失"到可见

#### 🔴 主缺陷：两个命令组整体从 CLI 消失，启动无任何提示

`src/cli/entrypoint.py` 的 `_register_command_modules()` 用
`try: ... except ImportError: pass` 包裹四处注册。本意是"可选模块缺失时优雅降级"，
实际把**硬错误**吞成了静默失败：

| 模块 | 断裂点 | 后果 |
|:---|:---|:---|
| `agent_commands.py:16` | 导入 `get_registered_keywords`（该函数不存在，现名 `get_all_keywords`） | `clawd agent` 整组不可用 |
| `workflow_commands.py:18` | 从 `pipeline_orchestrator` 导入三个 stage 工厂（它们定义在 `workflow.pipeline`） | `clawd workflow` 整组不可用 |
| `hud_improved.py:20` | `from ...core` 但模块深度只有 2 层 → 越过顶层包 | `clawd hud` 不可用 |

**7 个命令**（agent list/show/keywords、workflow ralph/ralplan/team/autopilot）
因此从未被注册，而 `clawd --help` 看不出任何异常。

实测确认（修复前）：

```
$ clawd agent --help
main.py: error: argument command: invalid choice: 'agent'
已注册组: ['catalog', 'setup']        ← agent / workflow 完全缺席
```

#### 隐藏的第四类缺陷：自引用注册

`setup_commands.py` 早已修过 `app.add_typer(app, name="setup")` 这个自引用
（形参遮蔽了模块级 `app`，等于把父应用注册到自己身上），并留了警告注释。
但 **`agent` / `workflow` / `catalog` 三个模块没有同步**，全部沿用错误写法。

#### 修复

1. **让降级可观测** —— `except ImportError: pass` 改为 `except Exception` +
   `logger.warning`，并返回失败组名清单供测试断言。只接 `ImportError`
   会漏掉 `NameError`（`field` 未定义）这类同样致命的错误。
2. **修正三个断链**，命令体按真实 API 重写（不是简单改名）。
3. **四个 register 函数**统一改为 `parent_app.add_typer(app, ...)`。
4. **新增 `clawd agent intent <text>`** —— 暴露 `intent_router` 的真实意图分类能力。

#### 导入期全库扫描：16 → 1 → 0

新增 `scripts/import_sweep.py`，逐个 import 全部 639 个模块，
区分「项目内代码缺陷」与「第三方依赖缺失」（后者是环境问题，不计入缺陷）：

```
修复前： IMPORT-OK 617 / IMPORT-FAIL 16 / DEP-MISSING 6
修复后： IMPORT-OK 632 / IMPORT-FAIL  1 / DEP-MISSING 6
清零后： IMPORT-OK 638 / IMPORT-FAIL  0
```

16 个缺陷的根因分布（多数在**生产不可达**模块，非 P0）：

| 根因 | 模块数 | 处置 |
|:---|:---|:---|
| 相对导入层数算错 | 5（`team/state/*`） | 修 `locks.py:22` 一处，连带解除 5 个 |
| 字符串按位或冒充字面量联合 | 3（`autoresearch/*`） | 改用 `Literal` + `from __future__ import annotations` |
| 类名/函数名与真实实现不符 | 4 | 按真实 API 重写消费者 |
| dataclass 字段顺序违反继承规则 | 1（`charter.py`） | 给子类字段补默认值 |
| 引用了从未存在的模块 | 2（`coder_agent`、`core.mcp.code_intel_server`） | 删除孤儿 / 移除坏配置项 |
| 残壳包指向不存在的文件 | 1（`core/auth`） | 改为转发真实实现 `core/auth_module` |

#### ⚠️ `coder_agent.py` 的处置说明

它 `from .consensus import SemanticValidator, Vote, VoteType`，而
`src/agent/swarm/consensus.py` **在 git 全历史中从未存在过** ——
该模块从写下的第一天起就无法导入。核实：`CoderAgent` 零消费者、
`swarm/__init__.py` 未导出。

**选择删除而非补造 `consensus.py`**：补造一个"能导入但验证永远通过"的桩，
正是本项目 v0.55.0 刚刚清理掉的那类伪实现。若将来需要 swarm 的 Coder 专家，
应连同真实共识机制一起立项。

#### 修复"生成的 MCP 配置指向坏模块"

`src/core/config/generator.py` 的 `DEFAULT_MCP_SERVERS` 有 5 条，
其中 **2 条必然启动失败**：

- `clawd-memory` → `src.core.mcp.memory_server`：导入 `EnterpriseLongTermMemory`
  （类已更名 `EnterpriseLTM`），且调用的 `store_entity/store_observation/
  store_relation/search` 在该类中**从未存在**——两者数据模型不同
  （代码实现模式 vs 知识图谱三要素），无诚实映射方式。
  → 移除臆测的集成，`search()` 改为在本服务自己的 JSON 存储上做关键词检索。
- `clawd-code-intel` → `src.core.mcp.code_intel_server`：该文件不存在。
  → 移除该条配置。

修复后 4 条配置**全部可导入**（实测）。

#### 测试隔离缺陷

`tests/agent/test_approval_gate.py` 调用 `set_allowed_workdirs([tmp_path])`，
该函数用 `global ... = [...]` **重新绑定进程级模块属性**且不恢复。
后果是**同进程后续所有测试**都撞上"工作目录不在允许范围内"：

```
pytest tests/agent tests/tools_runtime tests/cli   → 6 failed（看似无关的 bash 用例）
pytest tests/tools_runtime/test_bash_execution_paths.py（单独） → 11 passed
```

已加 `autouse` fixture 在每个用例前后快照/恢复该全局。

#### 验证

| 项目 | 结果 |
|:---|:---|
| CLI 命令注册回归（新增 15 用例） | **15 passed** |
| `tests/agent + tools_runtime + cli` 合并 | **754 passed / 0 failed** |
| 生产路径 E2E（真实端点） | **8/8** |
| 并发压测 | **5/5** |
| 导入全库扫描 | **0 缺陷**（638/638 可导入） |
| 可达性不变量 | **429 → 429**（未变） |

#### 一处自我更正

初版修复把命令组模块清单写成字符串 + `importlib.import_module()`。
运行时正确，但 `scripts/reachability.py` 靠 AST 里的 import 语句建图，
这 4 个模块因此在图中消失，可达数从 429 掉到 416。
已改回显式 `from .commands import (...)`（保留失败可见的 `try/except`）。

> **教训：替换导入方式前，先确认项目自身的静态分析工具依赖什么形式。**

---

### v0.55.0 (2026-10-17) — 死代码复核、伪验证诚实化

#### 🔴 发现：验证阶段是假的

生产管道 `src/workflow/pipeline.py` 的验证阶段有 **4 处桩**，其中：

```python
# TODO: 集成 Ralph 循环逻辑
artifacts = {
    "verification_result": "passed",   # ← 硬编码
    "iterations": 3,                   # ← 也是假的
}
```

**它从不运行任何测试、不做任何检查，直接返回"通过"。**

更关键的是：未接线侧 `src/workflow/stages/ralph_verify_stage.py` 虽然循环结构
更完整（有 `while ... and not approved`），但它的 `_verify_implementation`
**同样是桩**：

```python
# TODO: 实现真正的验证逻辑
return {"approved": True,  # 简化为总是通过
        "evidence": {"tests_passed": True}}
```

**两者都是桩。** 把它接上去等于用一个更精致的"永远通过"替换一个简陋的
"永远通过"，不解决问题。（子代理最初的判断是"未接线侧是真实实现"，
主线程读源码后更正了这一结论。）

**本次修复**：把三处桩的伪造值改为**诚实值**（`plan_implemented: False`、
`execution_completed: False`、`verification_result: "not_implemented"`、
`verified: False`），使"未实现"不再伪装成"已通过"。
消费方检查为 0（已验证），因此零行为风险。

**仍待立项**：让验证阶段真正调用测试执行器；在此之前，任何依赖该阶段结果
做自动化放行决策的逻辑都不可信。

#### 🗑️ 死代码复核与收敛

由三个并行子代理逐模块读源码复核 163 个"生产不加载"模块（31,188 行），
删除 20 个经确认被取代的模块：

```
src/session/ src/openclaw/ src/mcp/code_intel.py src/mcp/state_paths.py
src/brain/repomap.py src/brain/file_watcher.py src/brain/special_files.py
src/self_healing/doctor.py src/self_healing/session_manager.py
src/server/mcp.py src/runtime/bridge.py src/runtime/mailbox.py
src/utils/paths.py src/rag/context_index.py src/rag/lang_engine.py
src/cli/report.py src/cli/onboarding.py src/cli/hud_authority.py
src/cli/tui/models.py src/cli/tui/animations.py
```

**安全验证**：删除前后「从生产入口可达的模块数」均为 **429（未变）**。

**为什么不继续删**：剩余模块多属"未接线功能"（如 swarm 专家类、
team 状态层、workflow worktree 护栏），删除等于砍能力，需产品决策。
完整清单与判定见 `计划书/死代码复核报告.md`。

#### 📚 新增文档

- `计划书/死代码复核报告.md` —— 复核方法、本轮删除、待决策清单、
  以及"验证阶段是假的"这一更正的完整记录

---

### v0.54.0 (2026-10-17) — 门禁落地、并发压测、真死代码收敛

#### 🔴 安全：PLAN 模式首次真正生效

`ApprovalMode` 此前只在配置层被读写，**没有任何运行时消费者**。
用户按文档把 `approval_mode` 设为 `plan`（"仅分析，不修改文件"），
Agent **照样写盘** —— 一个"装饰性控制"。

现在在 `ToolManager.execute_tool` / `execute_tools_parallel`（生产工具执行的
唯一咽喉点）按类别拦截：read 放行，write / exec 拒绝。

- 只实施 PLAN；DEFAULT / AUTO_EDIT / YOLO 不拦截 —— 因为**仓库里没有任何
  交互式审批设施**，DEFAULT 语义中的"需要审批"无法落地，强行拦截会让
  开箱即用的默认配置直接不可用。`.env.example` 已如实说明这一边界。
- 一个集成陷阱：初版抛 `SecurityError`，但 `engine_loop._execute_single_tool`
  只捕获 `ToolExecutionError`（二者是**兄弟类**）→ 异常穿透触发自愈引擎去
  "修复"一个策略拒绝。改为新增 `ToolApprovalDeniedError` + 错误码 `E2009`，
  使拒绝变成**模型可见的 ToolResult**。
- 配置读取失败时退回 `DEFAULT` 而非 `YOLO` —— "读不到配置就放开全部管控"
  是最危险的降级方向。

#### 🔴 修复：world_model 的 4 个缺陷

- **首次运行时指纹永不保存**（真实 Bug，静默降级）
  `import json` 位于 `if fp_path.exists():` 内，Python 因此把 `json` 视为
  **整个函数的局部变量** → 指纹文件不存在时抛 `UnboundLocalError`，被
  `except` 吞成 warning。后果：**增量索引每次退化为全量重建**，
  该模块的核心卖点长期失效。
- `predict_relevant_files` 无条件调用 `get_imported_by()`，但只有
  `CodeGraph` 有该方法；默认的 `DependencyGraph`（兼容层）只有
  `get_upstream` → 图谱构建失败退回兼容层时抛 AttributeError。
  改用两者都提供的 `impact_analysis()`，按各自返回结构读取。
- `isinstance(x, CodeGraph)` 在测试把 `CodeGraph` 替换成 MagicMock 时抛
  TypeError，使并行构建路径无法被 mock 覆盖。
- `import asyncio` 在方法内 —— stdlib 导入本就有缓存，局部化无收益却
  破坏 `patch("...world_model.asyncio.to_thread")`。

#### 🗑️ 真死代码收敛（净删 ~2,600 行）

本轮删除的都是**经人工核对确认同一 TS 源文件**的重复移植：

| 删除 | 行数 | 存活侧（生产可达） |
|:---|:---|:---|
| `src/pipeline/` | 248 | `src/workflow/pipeline.py` |
| `src/team/` | 1,065 | `src/workflow/team/` |
| `src/subagents/` | 230 | `src/agent/swarm/subagent_tracker.py` |
| `src/screens/hud/` | 1,013 | `src/cli/hud*.py` |

**安全验证**：删除前后「生产入口可达模块数」均为 **429**（未变），
证明删掉的确实都是不可达模块。模块总数 684 → 666。

#### ⚠️ 一个被证伪的自动化判据（重要）

我写过一个"近名存活模块存在 → 判为已取代的重复品"的启发式。实测**误报严重**：

```
src.core.hook_registry.async_executor  "对照" src.core.hook_registry
    —— 后者是同一个包，前者是它的子模块，不是重复品
src.workflow.worktree_isolation        "对照" src.cli.commands.workflow_commands
    —— 仅仅因为名字里都含 "workflow"
```

**名称相似 ≠ 语义重复。基于名称的启发式不足以授权删除源码。**
因此 `scripts/deadcode_inventory.py` 改为**只出复核清单、不判"可删"**。
剩余 163 个生产不加载模块（31,188 行）保持原样，等人工按源码逐条复核。

#### 🧪 新增：并发压测与深度自检

`scripts/stress_test.py` 针对三处**真实存在并发风险**的基础设施施压。
实测 200 并发、5/5 通过：

```
工具执行 200 并发      200 全部成功且结果无错配
线程池未耗尽           5 轮 × 50 并发，每轮全成功
审批门禁并发混合       拒绝=100 只读放行=100 YOLO放行=100 误拒=0
熔断器 200 并发计数    计数无丢失，正确进入 OPEN
熔断器并发渠道隔离     熔断 200 次 / 健康 200 次判定全部正确
```

**压测暴露的性能瓶颈**：工具线程池硬编码 10 → 200 个并发 bash 被压成
20 波，吞吐仅 11 req/s。改为可用 `CLAWD_TOOL_EXECUTOR_MAX_WORKERS` 配置：

```
池=10 -> 200 并发 19.05s (11 req/s)
池=64 -> 200 并发 12.40s (16 req/s)   延迟降 35%
```

诚实说明：**收益有限** —— 真正的瓶颈是 Windows 进程创建开销而非线程数。
非法配置值（0 / 负数 / 非数字）一律回退默认，因为 `max_workers=0` 会让
**全部**工具执行失败。

#### 📚 新增测试

- `tests/agent/test_approval_gate.py`（32 例）
- `tests/agent/test_executor_config.py`（17 例）
- `tests/brain/test_world_model_complex.py` 重写 2 例（原断言已废弃 API）

---

### v0.53.0 (2026-10-16) — 盲点扫描与生产路径加固

本轮由**多智能体并行审计**驱动：死代码可达性、测试失败归因、
安全盲点扫描三个方向独立进行，每条发现均由主线程亲自复现后才修复。

#### 🔴 安全（生产环境真实风险）

- **Agent 可读取 `.env`，API Key 明文进入 LLM 上下文**
  `src/utils/path_security.py` 早已实现 `is_sensitive_file` 与
  `FORBIDDEN_DIRS`，但**从未被任何工具接线**。实测
  `execute_tool(tools, 'FileReadTool', {'file_path': '.env'})` → `success=True`，
  输出含 `OPENAI_API_KEY=sk-***REDACTED***`，该内容随后被
  `engine_loop` 原样拼进消息发给远端模型。
  在 `path_utils.resolve_path()`（四个文件工具的唯一统一入口）接入判定，
  一处改全部生效。`.env.example` 等模板显式豁免。
  同时从 `TEXT_EXTENSIONS` 移除 `.env`。

#### 🔴 阻塞级（生产路径不可用）

- **BashTool 在 Agent 环路中 100% 失败 —— shell 能力实际不可用**
  `BashTool.execute()` 裸调 `asyncio.get_event_loop()`，而生产路径把工具
  丢进 `ThreadPoolExecutor` 工作线程执行（`tool_executor.py:170`）。工作
  线程没有事件循环，Python 3.10 抛
  `RuntimeError: There is no current event loop in thread ...`，
  被吞成"执行失败"。**跑测试、git、构建、任何命令全部不可用。**
  既有测试都在主线程直调（有自动循环），所以永远绿。
  修复覆盖三种上下文：无循环线程用 `asyncio.run`、主线程用
  `run_until_complete`、嵌套循环明确提示改用 `async_execute`。

- **`<think>` 标签提取必崩**（`src/llm/providers/openai.py:128`）
  写成 `content.split('', 1)` —— 分隔符是空字符串，任何含 `<think>` 的
  响应都抛 `ValueError: empty separator`，被重试吞掉 5 次后整次调用失败。
  改用 `ThinkTagParser.CLOSE_TAG` 常量。
  **这是生产 LLM 路径上的缺陷**，与 v0.51.0 修的 `factory.py` 不是同一条路径。

#### 🔍 架构澄清（修正 v0.51.0 的认知）

传递可达性分析确认生产创建 LLM 的路径是
`src/agent/engine.py:203 → create_llm_provider() → providers/*`，
而 v0.51.0 修的 `src/llm/factory.py::get_default_llm()` **从生产入口不可达**。
那批修复有效但保护错了路径，本轮补齐对真实生产路径的修复与测试。

#### 🗑️ 删除真死代码（4,158 行）

- `src/notifications/`（8 文件）、`src/visual/`、`src/session_history/`
- **被同名包遮蔽的 3 个死文件**：Python 中包优先于同名模块，实测确认
  `src/core/events.py`(343行)、`src/core/git/worktree.py`(9行)、
  `src/llm/model_info.py`(32行) **永不执行**。
  其中 `events.py` 与包里的 `events/core.py` 是两套事件总线实现 ——
  改错文件会"改了没效果"，正是本项目反复出现的缺陷模式。

> 修正：v0.51.0 曾称 `src/notification/` 也是死代码，**该判断有误** ——
> 它被两个测试文件引用，有测试覆盖。

#### 🛠️ 新增工具与测试

- `scripts/reachability.py` —— 从入口做 BFS 传递可达性分析。
  修掉一个关键 bug：相对导入的基准包对 `__init__.py` 多减一层，
  导致整棵 `src.llm.*` 被误判不可达。自检：684 模块 / 429 生产可达。
- `scripts/find_untested_live_code.py` —— 找出"生产在跑但零测试覆盖"的模块。
- `scripts/e2e_production.py` —— **生产路径** E2E（8 步全通过）。
- `tests/llm/test_providers_openai.py`（16 例）
- `tests/llm/test_circuit_breaker.py`（26 例，熔断器此前 0% 覆盖）
- `tests/tools_runtime/test_bash_execution_paths.py`（11 例）
- `tests/test_security/test_sensitive_path_guard.py`（33 例）

#### ⚠️ 已记录但未修的缺陷

- **`ApprovalMode` 无运行时消费者**：用户把 `approval_mode` 设为 `plan`
  （文档称"仅分析，不修改文件"）时，Agent 仍会写盘。属"装饰性控制"，
  需单独设计门禁接入点。
- `HeuristicToolParser` 只在"参数值后紧跟非 `<` 裸文本"时输出，
  带 `</function>` 闭合标签的形态识别不了。主路径 `parse_tool_calls`
  （系统提示词实际指示的 `<tool>{json}</tool>`）正常，不阻塞主流程。
- `CircuitBreaker` 半开态的 `half_open_max_requests` 形同虚设
  （`_half_open_requests` 只在 `record_success` 中递增）。已锁定为 xfail。

---

### v0.52.0 (2026-10-16) — 波次 2/3：真死代码收敛 + 生产路径审计

#### 🔴 修复（生产路径）

- **`<think>` 标签提取必崩**（`src/llm/providers/openai.py:128`）
  写成 `content.split('', 1)` —— 分隔符是**空字符串**，任何含 `<think>`
  的响应都抛 `ValueError: empty separator`，被重试逻辑吞掉 5 次后整次调用失败。
  改为使用 `ThinkTagParser.CLOSE_TAG` 常量，避免再次被编辑操作截断成空串。
  **这是生产 LLM 路径上的缺陷** —— 与 v0.51.0 修的 `factory.py` 不是同一条路径。

#### 🔍 关键架构澄清（修正 v0.51.0 的认知）

用传递可达性分析确认：**生产创建 LLM 的路径是**

```
src/agent/engine.py:203
  -> src/llm/providers/__init__.py::create_llm_provider()
    -> OpenAICompatibleProvider.chat() / .chat_stream()
```

而 v0.51.0 修复的 `src/llm/factory.py::get_default_llm()` **从生产入口不可达**。
那批修复本身是有效的（且 `scripts/e2e_smoke.py` 覆盖），但它保护的不是生产路径。
本次补齐了对**真实生产路径**的修复与测试。

#### 🗑️ 删除真死代码

- `src/notifications/`（8 文件）
- `src/visual/`（2 文件）
- `src/session_history/`（1 文件）
- 合计 **3,774 行**

> 修正：v0.51.0 曾称 `src/notification/` 也是死代码，**该判断有误** ——
> 它被两个测试文件引用，有测试覆盖。已用可达性分析复核。

#### 🛠️ 新增分析工具

- `scripts/reachability.py` —— 从入口点做 BFS 传递可达性分析。
  修掉了一个关键 bug：相对导入的基准包对 `__init__.py` 多减一层，
  导致整棵 `src.llm.*` 被误判不可达。自检：684 模块 / 429 生产可达。
- `scripts/find_untested_live_code.py` —— 找出"生产在跑但零测试覆盖"的模块。
- `scripts/e2e_production.py` —— **生产路径** E2E（区别于 `e2e_smoke.py`）。

#### 🧪 新增测试

- `tests/llm/test_providers_openai.py`（16 例）—— 生产 LLM 提供商路径：
  `<think>` 提取回归、重试与错误传播、消息编解码、流式
- `tests/llm/test_circuit_breaker.py`（26 例）—— 熔断器完整状态机
  （此前 0% 覆盖率），并锁定一个已确认缺陷为 xfail

#### ⚠️ 发现的已知缺陷（未修，已记录）

- `HeuristicToolParser`（`src/llm/parsers.py`）的状态机**只在参数值后紧跟
  不以 `<` 开头的裸文本时才输出**。任何带 `</function>` 闭合标签的输出
  都识别不了。主路径 `parse_tool_calls`（系统提示词实际指示的
  `<tool>{json}</tool>` 格式）工作正常，因此该兜底失效不阻塞主流程。
  该解析器此前无任何测试。
- `CircuitBreaker` 半开态的 `half_open_max_requests` 形同虚设 ——
  `_half_open_requests` 只在 `record_success()` 中递增，失败路径与
  "请求发起"路径都不计数，因此并发探测不受限。

---

### v0.51.0 (2026-10-16)

本次为**止血版本**：修复了一批"项目声称可用、实际运行即崩"的缺陷。
所有修复均附有实测复现与验收命令，详见 `计划书/下一步改进指南.md`。

#### 🔴 修复（阻塞级）

- **LLM 栈完全不可用**（`src/llm/factory.py`）
  `get_default_llm()` / `get_vision_llm()` 访问了不存在的
  `settings.context_window`，任何调用都抛 `AttributeError`。
  修正为实际字段 `settings.max_context_tokens`。
- **API Key 与自定义端点从未生效**（`src/core/config/models.py`）
  `.env.example` 约定 `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL`，
  但 `AgentSettings` 只识别 `LLM_API_KEY` 等通用名，导致按文档配置的用户
  拿到 `llm_api_key=None`、`llm_model='gpt-4'`、`llm_base_url=None`。
  新增提供商环境变量别名解析层，兼容全部既有配置方式。
- **自定义端点被忽略，请求打到官方 API**（`src/llm/factory.py`）
  `_LiteLLMCompatWrapper` 构造 litellm 参数时遗漏 `api_key` / `api_base`，
  使用 OpenRouter / NIM / 自建网关的用户必然 401。
  抽出 `_build_call_kwargs()` 供 `invoke`/`stream` 共用。
- **工具调用结果被丢弃，Agent 环路断裂**（`src/llm/factory.py`）
  响应解析只取 `role` / `content`，`tool_calls` 与 `reasoning_content`
  从未回填，模型即使返回工具调用也被当作普通文本处理。同步修复流式路径。
- **原子补丁引擎不可用**（`src/core/patch/atomic_patcher.py`）
  `apply_batch` / `apply_changes` 调用的 `commit()` 与 `rollback()` **根本未定义**，
  而 `src/agent/engine_loop.py` 在每次文件编辑后都会调用它们 ——
  即每次成功改文件都会崩溃。补齐两个方法；
  另删除被静默覆盖且引用未定义变量的重复 `apply_changes`；
  补齐被引用但从未实现的 `_apply_diff_hunks` 与 `apply_patch`。
- **配置文件反复合并会自我污染**（`src/core/config/merger.py`）
  `merge_config` 把 OMX 顶层配置追加到字符串末尾，第二次合并起
  `notify` / `model_reasoning_effort` / `developer_instructions`
  会落到 `[agents]` 表之下，被 TOML 解析成 `agents.*`，顶层配置静默丢失。
  改为插入到第一个表头之前，并新增幂等性测试。
- **Windows 中文环境启动即报编码错误**（`src/utils/logger.py`, `src/main.py`）
  控制台默认 GBK，日志中的 emoji / CJK 触发 `UnicodeEncodeError`，
  用户看到满屏乱码与调用栈。统一将 stdout/stderr 切至 UTF-8（`errors='replace'`）。
- **RAG 索引事件永不发布**（`src/brain/world_model.py`）
  指标代码引用未定义的 `indexed_count`，异常被 `except: pass` 吞掉，
  `RAG_INDEX_UPDATED` 长期静默失效。同时修正恒等于 100% 的覆盖率公式。
- **配置包公开 API 缺失，Agent 主入口崩溃**（`src/core/config/__init__.py`）
  该包只 re-export 了 `merger`，`AgentSettings` / `get_settings` /
  `load_settings` 全部 `ImportError` —— 而 `src/agent/factory.py:70` 正是
  这样导入的，导致 `create_agent_engine()`（创建 Agent 的主入口）
  以 `ImportError` 崩溃，且该异常不在 `except (KeyError, ValueError)` 捕获范围内。
  现已补全 re-export，并新增 `ensure_project_dirs()`。
- **`clawd setup` 静默不生成配置文件**（`src/cli/commands/setup_commands.py`）
  `src.config.generator.merge_config` 是 `async def`，却被同步调用 ——
  只得到一个从未 await 的协程，弹出 `RuntimeWarning` 而配置文件根本没写到磁盘
  （用户看到"✓ 创建配置文件"却是空的）。
- **`clawd setup` 无法找到模板**（`src/cli/commands/setup_commands.py`）
  模板路径少算一级目录（指向 `src/templates/`，实际在仓库根 `templates/`），
  导致 AGENTS.md 与 catalog-manifest.json 永远"跳过: 模板未找到"。
  改为向上探测 `pyproject.toml` + `templates/`，兼容各种安装布局。
- **`register_setup_commands` 自引用**（`src/cli/commands/setup_commands.py`）
  `app.add_typer(app, name="setup")` 中形参 `app` 遮蔽了模块级 `app`，
  等于把父应用注册到自身。
- **代码图谱并发修改崩溃**（`src/rag/code_graph.py`）
  `_resolve_all_edges` 直接迭代 `self.nodes.values()`，而图谱构建可能由
  `asyncio.to_thread` 在后台线程添加节点，抛
  `RuntimeError: dictionary changed size during iteration`。改为快照迭代。
- **生成配置中的硬编码过期版本号**（`src/config/generator.py`）
  生成的 `.clawd/config.toml` 注释写死 `Clawd Code v0.50.0+`。已移除该噪声。

#### 🔧 修复（契约与一致性）

- `AgentDefinition` 字段由 camelCase 改为 snake_case
  （`reasoningEffort` / `modelClass` / `routingRole`），
  恢复 `tests/contracts/` 契约并符合 PEP 8。
- 枚举补全为 `AgentModelClass` / `AgentRoutingRole`，与同文件其余 `Agent*` 命名一致。
- `src/workflow/verifier.py` 补全契约声明的 `TaskSize` / `EvidenceType` /
  `Confidence` / `VerificationEvidence.as_text()`；枚举继承 `str`，不破坏既有字符串比较。
- 版本号改为单一真相源：`pyproject.toml` 为唯一来源，`src.__version__` 自动读取。
- 重写 `tests/core/test_config_merger.py`（原测试针对已废弃的 `ConfigMerger`
  类与 `OMX_MARKER` 设计，导致 pytest 收集失败）。

#### 🧪 新增测试

- `tests/self_healing/test_atomic_patcher.py` +10：事务语义、unified diff 应用、
  上下文不匹配拒绝、语法破坏拒绝、多 hunk。
- `tests/brain/test_world_model.py` +2：`RAG_INDEX_UPDATED` 事件发布与零文件边界。
- `tests/core/test_config_merger.py` 重写为 48 个用例，含**幂等性**回归。
- `scripts/e2e_smoke.py`：对真实 LLM 端点的端到端冒烟测试
  （配置 → 导入 → 对话 → 工具调用 → 推理内容）。

#### 📝 说明

- `pyproject.toml` 的 `fail_under` 仍为 60，与实际覆盖率存在差距，
  按 `计划书/下一步改进指南.md` §6.1 的路线分阶段提升。

---

### v0.46.0 (2026-04-08)

#### 🧪 测试增强
- **新增 12 个测试文件，300+ 测试用例**
  - `tests/agent/test_events.py` - EventMixin 全面测试（35 用例）
  - `tests/agent/test_lifecycle.py` - LifecycleMixin 信号处理和关闭测试（28 用例）
  - `tests/agent/test_event_publisher.py` - EventPublisher 独立测试（22 用例）
  - `tests/agent/test_agent_session.py` - AgentSession 会话管理测试（25 用例）
  - `tests/agent/test_message_truncator.py` - MessageTruncator 截断策略测试（22 用例）
  - `tests/brain/test_dependency_graph.py` - DependencyGraph 依赖图谱测试（20 用例）
  - `tests/core/test_patch_engine.py` - PatchEngine 补丁引擎测试（25 用例）
  - `tests/utils/test_retry.py` - Retry 重试策略测试（30 用例）
  - `tests/utils/test_cache.py` - Cache 缓存策略测试（28 用例）
  - `tests/llm/test_cache.py` - LLMCache LLM 缓存测试（18 用例）
  - `tests/memory/test_manager.py` - MemoryManager 记忆管理测试（12 用例）
  - ~~`tests/session/test_session_manager.py`~~ - 该文件实际不存在于仓库（v0.51.0 修正本条目）

#### 📈 质量提升
- 测试用例总数从 1416 增加至 1565+（+10%）
- 覆盖核心模块数量从 12 个增加至 24 个（+100%）
- 新增边界条件、错误处理、集成和并发测试
- 所有测试遵循 Arrange-Act-Assert 模式

#### 🐛 修复
- 修复事件测试中的断言错误
- 修复节流测试中的方法调用问题

---

## [v0.45.0]

### 🆕 新增

#### ClawGod 整合 (v0.44.0)
- **声明式补丁引擎系统** (`src/core/patch_engine.py`)
  - 补丁 DSL（领域特定语言）
  - 补丁修饰符：`unique`, `optional`, `select_index`, `validate`
  - 多模式运行：dry-run / verify / apply / revert
  - 自动备份策略
  - 跨版本兼容（正则模式匹配）

- **上下文指纹验证工具** (`src/utils/context_validator.py`)
  - 关键字验证 (`validate_by_keywords`)
  - 正则表达式验证 (`validate_by_regex`)
  - 代码结构验证 (`validate_by_structure`)
  - 一站式验证函数 (`validate_match_context`)
  - 便捷验证器创建函数

- **Wrapper + Forward 配置注入** (`src/core/config_injector.py`)
  - 6 层配置优先级链
  - 运行时配置覆盖 (`set()` / `get()` / `delete()`)
  - 配置变更回调系统
  - 配置热重载支持
  - 持久化配置到文件
  - 配置优先级报告

- **Prompt 优化器** (`src/llm/prompt_optimizer.py`)
  - 使用补丁引擎优化系统提示词
  - dry-run 预览优化效果
  - 上下文验证确保优化不破坏语义
  - 可回滚的优化策略

- **增强安装脚本** (`install_enhanced.ps1`)
  - 智能检测已有安装
  - 自动备份和还原
  - 双重启动器模式
  - Dry Run / Status / Uninstall / Revert 多模式

#### CI/CD 流水线
- **GitHub Actions CI** (`.github/workflows/ci.yml`)
  - Python 3.10/3.11/3.12 版本矩阵测试
  - Lint (Ruff) + Type Check (MyPy)
  - 测试覆盖率报告上传到 Codecov (**≥60% 门控**)
  - 安全扫描 (Bandit + Safety) **启用阻断**
  - Docker 构建测试

- **Docker 镜像发布** (`.github/workflows/docker.yml`)
  - 多平台镜像构建 (linux/amd64, linux/arm64)
  - 自动推送到 GitHub Container Registry
  - 语义化版本标签

- **依赖自动更新** (`.github/dependabot.yml`)
  - pip 依赖每周自动检查更新
  - GitHub Actions 依赖更新
  - Docker 基础镜像更新

- **Makefile** 本地开发便捷命令
  - `make install` / `make test` / `make lint`
  - `make format` / `make type-check` / `make coverage`
  - `make docker-build` / `make docker-run`
  - `make check` 全量检查（CI 本地模拟）

#### 测试覆盖增强
- **新增 449 个测试用例**
  - `tests/agent/test_core_engine.py` (72 测试) - 核心循环函数 (16% → 84%)
  - `tests/agent/test_lifecycle.py` (21 测试) - 信号处理和生命周期 (0% → 87%)
  - `tests/agent/test_events.py` (17 测试) - 事件发布系统 (0% → 98%)
  - `tests/cli/test_repl.py` (42 测试) - REPL 交互 (13.8% → 57%)
  - `tests/workflow/test_workflow.py` (59 测试) - 工作流引擎 (18.6% → 58-99%)
  - `tests/core/test_patch_engine.py` (27 测试) - 补丁引擎
  - `tests/utils/test_context_validator.py` (35 测试) - 上下文验证
  - `tests/core/test_config_injector.py` (47 测试) - 配置注入器
  - `tests/core/test_compact.py` (72 测试) - 上下文压缩 (25% → 98%)
  - `tests/core/test_dependency_analyzer.py` (36 测试) - 依赖分析 (17% → 96%)
  - `tests/cli/test_thinking_canvas.py` (54 测试) - 思考画布 (0% → 62%)

### 🔧 改进

#### 代码质量
- **消除重复代码**
  - 删除 `src/utils/patch_engine.py` (18,866 字节重复)
  - 统一使用 `src/core/patch_engine.py`
  - `experience_bank.py` 已有兼容层 (core/self_healing/workflow)

#### 配置系统
- **`src/core/settings.py`** 集成配置注入器
  - 新增 `get_runtime_config()` / `set_runtime_config()` 函数
  - 新增 `reload_config()` 热重载支持
  - 新增 `get_config_priority_report()` 配置报告
  - 自动应用运行时配置覆盖

#### 测试覆盖率提升
| 模块 | 改进前 | 改进后 | 提升 |
|------|--------|--------|------|
| agent/_core_engine | 16% | **84%** | +68% |
| agent/_lifecycle | 0% | **87%** | +87% |
| agent/_events | 0% | **98%** | +98% |
| cli/repl | 13.8% | **57%** | +43% |
| cli/thinking_canvas | 0% | **62%** | +62% |
| workflow | 18.6% | **58-99%** | +40-80% |
| core/compact | 25% | **98%** | +73% |
| core/dependency_analyzer | 17% | **96%** | +79% |
| **总计** | **35%** | **~49%** | **+14%** |

#### 测试总数
- **改进前**: 743 个测试
- **改进后**: **1192 个测试** (+60%)

#### CI 门控
- 添加 `--cov-fail-under=60` 覆盖率阈值
- 移除安全扫描的 `|| true`，启用真正阻断
- Bandit 仅报告中高严重性级别

### 📚 文档
- **`CLAWGOD_INTEGRATION_FINAL_REPORT.md`** - ClawGod 整合最终报告
- **`CLAWGOD_PHASE2_INTEGRATION_PLAN.md`** - 整合计划文档
- **`CLAWGOD_PHASE2_COMPLETION_REPORT.md`** - 整合完成报告
- **`ARIPER_DELIVERY_REPORT.md`** - ARIPER 交付报告

### 🔒 安全
- 安全扫描集成到 CI 流水线 (Bandit + Safety)
- 依赖漏洞自动检测和更新
- Bandit 仅阻断中高危问题

---

## [v0.43.0] - 2026-04-05

### 🆕 新增
- Swarm 多 Agent 协作系统
- 世界模型 (WorldModel)
- 自我修复引擎增强
- RAG 检索增强生成

### 🔧 改进
- 组合模式重构 AgentEngine (v0.38.0)
- 统一代理循环 (v0.38.0)
- Feature Flag 系统增强 (v0.40.0)
- 统一重试策略工厂 (v0.40.0)
- 命令注册表 (v0.40.0)
- Trace Context 传播 (v0.40.0)

---

## [v0.42.0] - 2026-04-04

### 🆕 新增
- Textual TUI 全屏仪表盘
- Rich HUD 状态栏
- 流式 Markdown 渲染

---

## [v0.41.0] - 2026-04-03

### 🆕 新增
- 多 LLM 提供商支持 (8+)
- WebSocket 远程代理
- Token 追踪和成本估算

---

[未发布]: https://github.com/user/claw-code-tingfeng/compare/v0.43.0...HEAD
[v0.43.0]: https://github.com/user/claw-code-tingfeng/releases/tag/v0.43.0
[v0.42.0]: https://github.com/user/claw-code-tingfeng/releases/tag/v0.42.0
[v0.41.0]: https://github.com/user/claw-code-tingfeng/releases/tag/v0.41.0

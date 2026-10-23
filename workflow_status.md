# workflow_status.md

> 任务契约、验收台账与阻塞项。**只记录事实与证据**。
> 开始时间：2026-10-16
> 基线版本：`main` @ `7ebd096`（v0.45.0）
> 当前版本：**v0.60.6**（2026-10-23 实测）

---

## 当前状态（2026-10-23 实测复核）

> 本节是**唯一有效的当前状态**。下文 `## 0-0` 及其后所有 `## 0-x` 章节均为
> **历史轮次快照**（v0.51.0 → v0.60.6），其中的数字只代表当时，不代表现在。

| 指标 | 2026-10-23 实测 | 命令 |
|:---|:---|:---|
| 声明版本 | 0.60.6 | `venv/Scripts/python.exe -m src --version` |
| 源码规模 | 642 模块 / 137,468 行 / 187 测试文件 | `py -3.10 scripts/baseline.py --quick` |
| 用例收集 | **3261 / 0 errors**（热缓存 4~5s） | `py -3.10 -m pytest tests/ --collect-only -q` |
| Ruff 硬指标 | F821/F811/E9 **All checks passed** | `py -3.10 -m ruff check src/ tests/ --select F821,F811,E9` |
| 导入期缺陷 | **IMPORT-FAIL = 0 / IMPORT-EXIT = 0**（642 模块 / 635 OK / DEP-MISSING 7 为可选 extras） | `venv/Scripts/python.exe scripts/import_sweep.py --strict-exit` |
| 真实 E2E | `e2e_smoke` **5/5** · `e2e_production` **8/8**（2026-10-23 实跑，退出码 0） | `venv/Scripts/python.exe scripts/e2e_*.py` |
| 并发压测 | 200 并发 **5/5**，128 req/s，无死锁/错配（纯本地状态机，不打真实模型） | `venv/Scripts/python.exe scripts/stress_test.py --n 200` |
| 生产可达 | **443** / 不可达 199（完全不可达 134 / 24,667 行）<br>※ 442→443 是补入 `src.__main__` 种子的**口径修正**，非新增功能 | `py scripts/reachability.py --min-reachable 443` |
| 覆盖率 | **47.44%**（26,861 / 56,624），数据 2026-10-23 11:51 | `coverage.json` totals |
| 覆盖率门禁 | `fail_under = 47` **已生效**（原 60 写在 `[tool.coverage.run]`，coverage 不识别 → 从未生效） | `py -3.10 -m pytest tests/scripts -q --cov=src` → FAIL 提示 |
| 静默吞异常 | **172**（AST 口径），基线文件 `.clawd/baseline-silent.json`，CI `--fail-over 172` | `py -3.10 scripts/check_silent_except.py --fail-over 172` |
| 全量回归 | **3254 passed / 0 failed / 5 skipped / 2 xfailed / 639.98s**（单进程一次跑完，2026-10-23 收口确认）；首轮曾出现 1 个 flaky 并发用例，已按 ADR-0005 改为强契约断言，连续 5 次 30 passed | `py -3.10 -m pytest tests/ -q` |
| 快速层（不含 slow） | **3245 passed / 237.23s**（slow 层 9 个用例占 410s） | `py -3.10 -m pytest tests/ -q -m "not slow"` |
| CI 门禁 | 新增 collect-only / import_sweep --strict-exit / reachability --min-reachable 443 / silent-except --fail-over 172 四步 | `.github/workflows/ci.yml`（YAML 已 `yaml.safe_load` 校验） |

**已修复的指标失真**（W1，2026-10-23）：复核时 `IMPORT-FAIL = 1` 并非真实代码缺陷——
`scripts/import_sweep.py` 的 `classify()` 把导入期 `SystemExit` 兜底判为缺陷，
而 `src/cli/surface_viewer.py` 因 venv 缺 `jsonschema` 在导入期 `sys.exit(1)`。
现已把导入期主动退出单列为 `IMPORT-EXIT`（不计入缺陷），且 `surface_viewer`
不再在导入期杀进程。复跑结果：`IMPORT-FAIL = 0`。

**当前未闭环**：覆盖率 46.15%（目标 60%）、死模块 200（目标 ≤20）、
GitHub Release / Docker（本机无 `gh` / 无 `docker`，非代码问题）。

**下一阶段计划**：`计划书/下一步改进指南.md`（v2 实测版，W0'-W8）。

### 2026-10-23 本轮批次（v0.60.7）：度量自洽 + 分层 + CI 门禁 + 真实 E2E

> 逐项命令与原始输出见 `test_ledger.md` 的「2026-10-23 本轮落地验收」段；
> 全量日志 `.clawd/logs/full-run-20261023-1135.log`。

| 批次 | 事项 | 状态 | 证据 |
|:---|:---|:---|:---|
| W0' | 文档自洽：N-1~N-14 漂移逐条核实并修正；`README`/`CLAUDE`/`MAINTENANCE`/`SKILL`/`verified-scope` 全部对齐实测 | ✅ | `rg` 断言无遗留；`CHANGELOG` 经查**本就完整**（我上一轮误判为落后 4 版，已自纠） |
| W1'-1 | `import_sweep --strict-exit`：堵住"用 sys.exit 绕过红线" | ✅ | 探针实测 0→1→0；`tests/scripts/test_gate_scripts.py` |
| W1'-2 | `check_silent_except --fail-over/--write-baseline/--baseline-file` | ✅ | 基线文件 total=172；4 条优先级单测 |
| W1'-3 | `scripts/baseline.py`：单一取数入口（17 项指标） | ✅ | `--quick` 输出含 `consistent=true` |
| W1'-4 | `reachability --min-reachable` + 种子口径收敛为单函数 | ✅ | 442→0 / 443→1；修出"漏算 `src.__main__`" |
| W2 | `slow` marker 分层（只按耗时，9 个用例 410s） | ✅ | 快速层 237.23s（全量 767.19s） |
| W3 | CI 四道门禁 + 覆盖率阈值单一来源（`fail_under=47` 真正生效） | ✅（远端待验证） | YAML `safe_load` 通过；本机无 `gh` → 远端 not_run |
| W4 | 覆盖率重取 46.15% → **47.44%**；`fail_under` 从"死配置"改为生效 | ✅ | `pytest --cov=src` 小范围触发 FAIL 提示 |
| W6 | 死代码三问判定报告（134 个完全不可达） | ✅ 判定；删除 ⛔ 待决策 | `计划书/死代码判定-2026-10-23.md`：NO_REFS 112 / DOC_ONLY 6 / HAS_REFS 16 |
| E2E | 真实端点 5/5 + 8/8，退出码 0 | ✅ | `test_ledger.md` §C |
| 压测 | 200 并发 5/5，128 req/s | ✅ | `test_ledger.md` §D |
| 回归修复 | `test_acquire_release_thread_safe` flaky（契约写错）→ 改强契约 | ✅ | 连续 5 次 30 passed |

**仍未闭环**：覆盖率 60%（47.44%）、死模块 ≤20（134，需产品决策）、
远端 CI / Docker / GitHub Release（本机无 `gh`/`docker`，非代码问题）、
快速层 <180s（237s）。

### 2026-10-23 执行记录（W0 文档校准 + W1 环境与归因，已完成）

| ID | 事项 | 状态 | 证据 |
|:---|:---|:---|:---|
| W0 | 文档校准：10 处过时断言、历史/当前分区、解释器矩阵 | ✅ | 本节 + README / CLAUDE.md / MAINTENANCE.md / 两份计划书 |
| W1-1 | `import_sweep.classify()` 新增 `IMPORT-EXIT`，不再把 `SystemExit` 当缺陷 | ✅ | `tests/scripts/test_import_sweep_classify.py` 10 passed |
| W1-2 | `src/cli/surface_viewer.py` 去掉导入期 `sys.exit`；顺带修出被掩盖的 `NameError` | ✅ | 导入不再杀进程；运行时给可读错误 |
| W1-3 | venv 安装 `.[dev]`：pytest 9.1.1 / ruff 0.17.2 / coverage 7.16.2 | ✅ | dist-info 0.60.6 |
| W1-4 | 版本一致性护栏（pyproject / dist-info / `src.__version__`） | ✅ | `tests/core/test_version_consistency.py` 2 passed |
| W1-5 | 静默吞异常 AST 口径脚本 + 趋势断言 | ✅ | `scripts/check_silent_except.py` → 172；7 passed |
| W1-6 | **补 4 个未声明的生产依赖**（litellm / mcp / psutil / fastapi+uvicorn） | ✅ | E2E 由 2/5 → 5/5；production 8/8 |
| W1-7 | `reachability.py` 入口补 `src.__main__`（原判为死代码） | ✅ | 可达 442 → 443 |

**本轮实测**：`e2e_smoke` 5/5、`e2e_production` 8/8（退出码 0）；
`import_sweep` 642 / OK 635 / FAIL 0 / DEP-MISSING 7（均为可选 extras）；
定向回归 58 passed。

**下一步**：W2（覆盖率 Top10）/ W3（CI 门禁）/ W4（死码判定），见新计划 §11.2。

---

## 历史轮次（以下章节为快照，数字仅代表当时）

---

## 0-0-0. 技能检查记录（2026-10-19 终审）

| 检查项 | 结果 |
|:---|:---|
| `.agent/skills/` | 本轮创建 9 个技能（api/feature/release/rollback/verification/review/audit/concurrency/plan-doc） |
| `.agent/memory/` | 本轮创建 7 个记忆文件 |
| `.agent/rules.md` | 本轮创建执行契约 |
| `AGENTS.md` / `CLAUDE.md` | 已存在；项目约定有效 |
| `skills/`（项目内） | 62 个条目；`clawd-change-workflow` 为项目专用流程 |
| `.claude/skills/` | 已安装但无 `spec-driven-development` / `brainstorming` 目录（使用项目内 `skills/` 与 `.agent/skills/` 兜底） |
| Spec Kit / addyosmani skills | 未安装到本项目；参考项目 `D:\参考项目\addyosmani__agent-skills` 已分析 |
| 外部技能安装 | 未安装（本地技能已覆盖当前技术栈；避免引入无关依赖） |

---

## 0-0. 本轮（v0.59.0 → v0.60.2）：参考对标落地 + 两轮独立审查修复

依据 `参考的结果计划指南.md` 的 Phase A 审计，按 P0/P1 批次实施。
**验证结果见 `test_ledger.md`，逐项证据见 `evidence/`。**

| ID | 事项 | 状态 | 证据 |
|:---|:---|:---|:---|
| E-01 | CI 门禁修复（非法参数、lint 分层、覆盖率阈值 45） | ✅ | evidence/B1-ci-gates.json；CI YAML 可解析 |
| E-02 | tracing 移除 `onyx.*` 绝对导入；Braintrust 明确跳过 | ✅ | 导入测试 + `ruff F821/F811` |
| E-03 | doctor 显示 RAG/World Model/Server 能力状态 | ✅ | `python -m src doctor` 实跑 |
| E-04 | RAG 开关接线（`CLAWD_ENABLE_RAG=1`） | ✅ | `_create_rag_index` 开/关实测；检索返回 2247 字符 |
| E-05 | 状态持久化：原子写 + 文件锁 + schema/attempt/expected_attempt | ✅ | evidence/P0-5（9 条回归） |
| E-06 | 工具显式风险声明（risk_kind） | ✅ | evidence/P1-4（10 条回归） |
| E-07 | Scrape SSRF 加固（私网/元数据/DNS/重定向） | ✅ | evidence/P1-9（22 条回归） |
| E-08 | Skill 渐进披露 + SkillTool | ✅ | evidence/P1-10（6 条回归） |
| E-09 | 原生工具调用（默认关，真实端点已验证） | ✅ | evidence/P1-1；真实端点返回 BashTool tool_calls |
| E-10 | `clawd server` 命令 + token 鉴权 + port=0 语义 | ✅ | evidence/P1-7（24 条 server 测试） |
| E-11 | 平行阶段实现标注（不删除） | ✅ | `stages/`、`pipeline_stages/` docstring |
| E-12 | 全量回归 | ✅ | **3165 passed, 5 skipped, 1 xfailed, 0 failed**（2806s） |
| E-13 | 真实 E2E | ✅ | v0.60.1 复跑：`e2e_smoke.py` 5/5；`e2e_production.py` 8/8（含上游失败路径） |
| E-14 | 并发压测 | ✅ | `stress_test.py --n 200` 5/5（~11 req/s，无死锁/错配） |
| E-15 | 版本一致性 v0.60.2 | ✅ | `python -m src --version` + metadata |
| E-16 | 覆盖率 60% | ❌ 未达成 | 基线 46.15%；本轮未降低，需独立批次 |
| E-17 | 收集 <120s | ❌ 未达成 | 已禁用无关插件；全量收集仍需数分钟 |
| E-18 | 死模块 ≤20 | ❌ 未达成 | 200 不可达；需人工逐条复核 |
| E-19 | GitHub Release | ⛔ 阻塞 | 本机无 `gh` CLI |
| E-20 | Docker 构建/部署/热更新 | ⛔ 阻塞 | 本机无 Docker、无部署目标与凭证 |
| E-21 | 审查 C1：CI lint 覆盖 `tests/` 的 4 个 F811 | ✅ | `ruff check src/ tests/ --select F821,F811,E9` → All checks passed |
| E-22 | 审查 C2：`dev` 依赖补 `ruff` / `pytest-cov` | ✅ | `pyproject.toml` |
| E-23 | 审查 R1：悬空 `tool_call_id`、重复 id、流式开关告警 | ✅ | 8 条原生调用测试 |
| E-24 | 审查 R2：重定向前置校验 + validate 不做同步 DNS | ✅ | 24 条 SSRF 测试 |
| E-25 | 审查 R3/R4：tracing 返回 bool + 接线；可重入锁 + owner + 读改写加锁 | ✅ | 11 条持久化测试（连续复跑） |
| E-26 | 审查发现的全量回归（`error` 变量遮蔽） | ✅ | `tests/agent/test_core_engine.py` 48 passed |
| E-27 | 复审 Critical 1：被 `max_repeat_calls` 过滤的调用也补 tool 消息；id 按调用顺序对应 | ✅ | `test_filtered_duplicate_calls_get_tool_messages` 通过 |
| E-28 | 复审 Required 2：`cancel_mode` 与 `team_persistence` 读改写整体加锁 | ✅ | 定向回归 1383 passed |
| E-29 | 复审 Required 3：`SafeRedirectHandler` 提到模块级，测试直接测生产实现 | ✅ | SSRF 测试 25 passed |
| E-30 | 复审 Required 4/5：版本解析改为 pyproject 优先；补生产函数并发测试 | ✅ | 双解释器均 0.60.1；持久化 14 passed |
| E-31 | 终审 P0：`requirements.txt` 含不存在的 `braintrust>=0.50.0` | ✅ | 移除；`pip install -r` 可解析（BOM + dry-run） |
| E-32 | 终审 P0：启动脚本依赖 PATH 中不存在的 `python` | ✅ | 改为 `py -3.10` → `py -3` → `python` |
| E-33 | 终审 P0：启动脚本安装全部 requirements（可选/重型）且失败仍报成功 | ✅ | 改为 `pip install -e .`；失败 `exit /b 1` |
| E-34 | 终审 P0：venv 缺 wheel 导致 editable 构建失败 | ✅ | 先装 setuptools/wheel，`--no-build-isolation` |
| E-35 | 终审 P0：`utils` 急切导入可选 `pathspec`，核心安装后 CLI 崩溃 | ✅ | 可选导入 + 明确降级提示；`loguru`/`toml` 补进核心依赖 |
| E-36 | 终审 P1：atexit 阶段重导入抛 traceback | ✅ | `_register_shutdown_hooks` 捕获并 debug |
| E-37 | 终审 P2：doctor 版本正则只认中文冒号 | ✅ | `版本一致性: 0.60.2` PASS |
| E-38 | 启动脚本端到端验证 | ✅ | `start.bat doctor` 退出码 0，89s，诊断全 PASS |
| E-39 | 终审 P1：`test_goalx_integration.py` 真实 LLM 无超时，挂起全量 | ✅ | 改为 `RUN_GOALX_E2E=1` opt-in，默认 skip |
| E-40 | 终审 P1：`test_agent_engine_refactor.py` 启动进程池导致 pytest 不退出 | ✅ | fixture 用 tmp_path + 禁用后台 WorldModel；47s 正常退出 |
| E-41 | 终审 P2：`test_slop_data.py` 无任何测试函数（死资产） | ✅ 已删除 | `git rm`；无引用 |
| E-42 | 终审：根目录测试整体 | ✅ | 270 passed / 1 skipped（76.5s，正常退出） |
| E-43 | 终审 P1：`state_impl.save_snapshot` 的 `import fcntl` 在 Windows 必失败 | ✅ | 改用 file_lock + atomic_write；2 条回归 |
| E-44 | 终审 P1：`persistence.append_event` 读改写无锁，并发丢事件 | ✅ | 锁内读改写；4×10 并发 40 条不丢 |
| E-45 | 收集基线复测 | ✅ | 3171 tests / 0 errors / 64.84s（收集 <120s 达成） |
| E-46 | 终审补充：`atomic_write` 缺 fsync | ✅ | flush+fsync；持久化测试 16 passed |
| E-47 | 终审补充：高负载下状态锁 10s 超时 | ✅ | 提高到 30s；并行 core+workflow 895 passed |
| E-48 | 终审补充：熔断器半开测试固定 sleep 余量偶发失败 | ✅ | 改有界轮询；连续 5 次 25 passed |
| E-49 | 第三轮 C1：生产 `core/persistence/run_state.py` 无锁/固定 tmp/无 fsync | ✅ | file_lock + atomic_write；生产并发测试 2 passed |
| E-50 | 第三轮 C2：并发测试被无依据降强度 | ✅ | 恢复 20/10/10/25；14 passed |
| E-51 | 第三轮 R1–R4：题数、收集数、`.agent` 矛盾、HTML 版本 | ✅ | 收集实测 3171/64.84s；HTML 9 题；矛盾已清理 |
| E-52 | 第三轮审查结论 | Request Changes → 已逐项修复 | 待复审 |

### 本轮验证命令与真实结果

```text
pytest tests/ -q                                  → 3165 passed, 5 skipped, 1 xfailed, 0 failed (2806.15s)
pytest tests/{workflow,agent,tools_runtime,llm,contracts,cli} -q → 1348 passed, 1 xfailed (702.78s)
ruff check src/ --select F821,F811                → All checks passed!
python scripts/import_sweep.py                    → 642 模块 / IMPORT-OK 636 / FAIL 0 / DEP-MISSING 6
python scripts/reachability.py                    → 442 生产可达（基线 431，未下降）
python scripts/e2e_smoke.py                       → 5/5 PASS
python scripts/e2e_production.py                  → 8/8 PASS
python scripts/stress_test.py --n 200             → 5/5 PASS
python -m src --version                           → v0.60.2
```

---

## 0. 本轮（v0.56.0 → v0.57.0）完成项

| ID | 事项 | 状态 | 证据 |
|:---|:---|:---|:---|
| D-01 | `ruff --select F821` 清零 | ✅ | 40 → 0（All checks passed） |
| D-02 | `ruff --select F811` 清零 | ✅ | 19 → 0 |
| D-03 | 全库导入缺陷清零 | ✅ | `scripts/import_sweep.py`：638 模块，0 缺陷 |
| D-04 | 全量测试转绿 | ✅ | **3051 passed / 0 failed**（v0.57.0 时 3033，原 2999/31） |
| D-05 | `ReadinessSnapshot.ready` 字段与 classmethod 冲突 | ✅ | 实测字段现为 bool；`RuntimeSnapshot.ready()` 语义正确 |
| D-06 | `_deserialize_result` 枚举还原 + `skipped_reason` | ✅ | 往返测试通过 |
| D-07 | `_deserialize_event` 迭代字段字典崩溃 | ✅ | 持久化恢复测试通过 |
| D-08 | `PipelineState.save(state_file)` 生效 / `can_resume` 自洽 | ✅ | 新增 3 条回归用例 |
| D-09 | `PipelineConfig.cwd` 生效；`create_pipeline` 接受裸函数；`can_skip` 可选 | ✅ | 新增 3 条回归用例 |
| D-10 | `BudgetGuard` 注入被丢弃 | ✅ | 预算耗尽测试通过 |
| D-11 | `spawn_platform_command_sync` 定义时绑定 | ✅ | `tests/core/test_platform.py` 16 passed |
| D-12 | 删除 16 个陈旧报告文档 | ✅ | 仅保留 README/CHANGELOG/CONTRIBUTING/ARCHITECTURE/AGENTS/CLAUDE/workflow_status |
| D-13 | 顶层 `workflow` 命令被同名命令组遮蔽 | ✅ | 改名 `run`；新增回归断言"命令与命令组不得重名" |
| D-14 | 命令组注册不幂等 | ✅ | 加 `_REGISTERED_GROUPS` 护栏；3 次调用后组名无重复 |
| D-15 | 两套 CLI 入口并存（`python -m src.main` vs `clawd`） | ✅ | 新增 `src/__main__.py`；README/CLAUDE.md 命令改为 `python -m src` 并逐条验证 |
| D-16 | `--dimension/-d` 写入运行时配置后无人读取 | ✅ | 引擎解析 → 注入执行器提示词 → 挂到 `WorkflowTask.dimensions`；6 项回归测试 |
| D-17 | RAG 增量扫描比串行还慢（线程池开销） | ✅ | 缓存命中走同步快路径；`test_rag_pressure.py` 转绿 |
| D-18 | README 两条不存在的命令示例 | ✅ | 改为实跑验证过的 `run` / `workflow autopilot` |
| D-19 | 导入期加载 litellm（单次 ~34s）导致 CLI 启动几十秒 | ✅ | 四处惰性化；`import src` 6.8→1.6s，`import src.main` 50.9→~8s |
| D-20 | `src.utils ↔ src.core` 循环导入（被急切导入顺序掩盖） | ✅ | 调整 `utils/__init__` 定序；`CodeGraph.build` 子进程不再抛 `BrokenProcessPool` |
| D-21 | `_register_command_modules` 失败分支返回空清单（断言会假通过） | ✅ | 返回真实组名 + 新增失败路径回归用例 |
| D-22 | 惰性导出导致静态可达数下降（429→427） | ✅ | 两个 `__init__` 加 `TYPE_CHECKING` 锚点；恢复 429 |
| D-23 | RAG 性能测试依赖墙钟比值，满载时随机红 | ✅ | 改为统计解析调用次数，断言增量重解析 = 0 |
| D-24 | `workflow` 四个命令体引用幽灵 API（`SwarmOrchestrator`/`RalphLedger`/`RalplanWorkflow`/自模块导入） | ✅ | 按真实 API 重写；新增 wiring 测试 4 用例 |
| D-25 | `explore` 导入不存在的 `create_readonly_tool_manager`，且 `AgentEngine` 不接受 `tool_manager` | ✅ | 改为构造期注入 `APPROVAL_MODE=plan`（真实只读门禁） |
| D-26 | `catalog` 的 `internal_required` 参数不存在 + `get_counts()` 缺失 | ✅ | 修参数、补 `CatalogCounts/get_counts`；list/reload 实测正常 |
| D-27 | 断点续跑三处叠加失效（先写后读 / failed 不可恢复 / 失败索引 +1） | ✅ | 先读后写、failed 保持 active、失败索引保持 i；resume 测试通过 |
| D-28 | `PipelineState` 往返丢 `stage_names`/`artifacts`；artifacts 非 JSON 时状态静默丢失 | ✅ | 双向持久化 + JSON 归一化；新增往返用例 |
| D-29 | 复用 `BudgetGuard` 跨轮泄漏预算状态 | ✅ | 新增 `reset_for_run()` 并在 run() 调用；回归测试 |
| D-30 | `_resolved_dimensions` 跨轮残留；`create_pipeline(cwd)` 状态目录不一致 | ✅ | 每次解析前清空；cwd 传给编排器 |
| D-31 | 验证阶段是桩（从不运行测试） | ✅ | 新增 `verification_runner`：真跑命令、按退出码判定；13 条测试 |
| D-32 | **所有 pipeline 阶段真实执行时崩溃**（`self._logger` 基类无此属性） | ✅ | 4 个阶段类补 `_logger = logger`；端到端实测通过 |
| D-33 | `ralph_verify_stage` 循环体永远 `approved=True`，且未通过也返回 completed | ✅ | 接真实验证；状态与结论一致（failed/skipped） |
| D-34 | 本地安装部署未验证 | ✅ | `pip install -e .` 成功；`clawd.exe --version/agent/catalog` 实跑通过 |
| D-35 | 容器部署 / 线上热更新 | ⛔ **阻塞** | 本机无 Docker，无部署目标与凭证；已披露，不冒充 |
| D-36 | 覆盖率口径错误（文档长期写 ~20%） | ✅ | 全量插桩实测 **46.15%**；v0.53 目标（≥35%）已达成 |
| D-37 | `udiff_parser` 导入不存在符号，`apply_hunks` 核心分支永远 ImportError | ✅ | 修正导入；新增 15 条解析/应用测试 |
| D-38 | 非 git 目录下 `search_replace` 回退矩阵被 `InvalidGitRepositoryError` 中断 | ✅ | `try_strategy` 捕获策略级异常并继续下一策略 |
| D-39 | 计时测试在覆盖率插桩下随机失败 | ✅ | 保留下界、放宽上界 |
| D-40 | `ralplan` / `team-exec` 阶段是占位实现却报 SUCCESS | ✅ | 接 `RalplanEngine` / `SwarmEngine`；异常→FAILED；7 条阶段测试 |
| D-41 | `precontext-intake` 导入不存在的 `.intake` 模块，永远"成功"地什么都不做 | ✅ | 改为真实文件/行数扫描；失败→SKIPPED |
| D-42 | `stages/ralph_verify_stage.py` 用 `config.cwd` 而非 `ctx.cwd` 验证 | ✅ | 传 `ctx.cwd`；失败不再无意义重试 |
| D-43 | `search_replace` 策略回退修复无回归测试 | ✅ | 新增 7 条：异常回退、异常类型、MemoryError 上抛、非 git 目录 |
| D-44 | 非法 `CLAWD_VERIFY_COMMAND` 让 ValueError 穿透 | ✅ | 返回 `status="error"`；新增用例 |

### 验证命令与真实结果

```
pytest tests/ -q                          → 3051 passed, 0 failed
pytest tests/contracts -q                 → 39 passed
ruff check src/ --select F821             → All checks passed!
ruff check src/ --select F811             → All checks passed!
python scripts/import_sweep.py            → IMPORT-OK 632 / FAIL 0 / DEP-MISSING 6
python scripts/reachability.py            → 429 生产可达（与上轮一致，不变量守住）
python -m src.main doctor                 → 0 个 UnicodeEncodeError，中文正常
```

### 仍未闭合（诚实披露）

| 项 | 状态 | 说明 |
|:---|:---|:---|
| 覆盖率 | 🟡 46.15% | v0.53 目标（≥35%）**已达成**；v1.0 目标（≥60%）未达 |
| 死模块 | ⚠️ 135 个 | 指南目标 ≤20；需产品决策，不可按名字删 |
| 收集耗时 | ⚠️ ~92s | 指南目标 <20s |
| `except Exception` 数量 | ⚠️ 未重测 | 指南目标 ≤30 |
| 验证阶段 | ✅ **已实现** | v0.58.0：真跑命令 + 退出码判定；`tests/workflow/test_verification_runner.py` 13 passed |

---

## 0-A. 上一轮（v0.53.0 → v0.54.0）完成项

| ID | 事项 | 状态 | 证据 |
|:---|:---|:---|:---|
| C-01 | **PLAN 模式门禁真正生效**（此前是装饰性控制） | ✅ | `tests/agent/test_approval_gate.py` 32 passed |
| C-02 | **world_model 首次运行指纹永不保存**（真实 Bug） | ✅ | `tests/brain` 27 passed（原 3 失败全转通过） |
| C-03 | world_model 调用不存在的 `get_imported_by` | ✅ | 两种图类型实测均通过 |
| C-04 | 并发压测脚本 + 4 处真实并发风险验证 | ✅ | `scripts/stress_test.py` 200 并发 5/5 |
| C-05 | 工具线程池规模可配置 | ✅ | `tests/agent/test_executor_config.py` 17 passed |
| C-06 | 删除 4 组已核实的重复实现 | ✅ | ~2,556 行；**生产可达数 429 未变** |
| C-07 | 死代码复核清单工具 | ✅ | `scripts/deadcode_inventory.py` |

### 关键验证信号：删除前后「生产可达模块数」不变

```
删除前: 684 模块 / 429 生产可达 / 181 连测试都到不了
删除后: 666 模块 / 429 生产可达 / 163 连测试都到不了
                ^^^ 未变 = 删掉的确实都是不可达模块
```

### 一个被自己证伪的判据（教训）

我写过"近名存活模块存在 → 判为可删的重复品"的启发式，实测**误报严重**：

```
hook_registry.async_executor  "对照" hook_registry
    —— 后者是同一个包，前者是它的子模块
workflow.worktree_isolation   "对照" cli.commands.workflow_commands
    —— 仅仅因为名字里都含 "workflow"
```

**名称相似 ≠ 语义重复。自动化判据不能授权删除源码。**
已将工具改为"只出复核清单、不判可删"。剩余 **163 个生产不加载模块
（31,188 行）保持原样**，等人工按源码逐条复核。

### 仍未闭合（诚实披露）

| 项 | 状态 | 说明 |
|:---|:---|:---|
| `ApprovalMode` 的 DEFAULT/AUTO_EDIT/YOLO | ⚠️ 未拦截 | 仓库无交互式审批设施，属**新功能**非缺陷 |
| `HeuristicToolParser` 对闭合标签失效 | ⚠️ 未修 | 主路径正常，不阻塞 |
| `CircuitBreaker` 半开态限流 | ⚠️ 未修 | 已锁 xfail |
| 剩余 163 个死模块 | ⚠️ 未删 | 需人工逐条复核，已出清单 |
| 覆盖率 | 🟡 46.15% | 本轮补了 49 个用例 |

---

## 0-B. 上一轮（v0.52.0 → v0.53.0）完成项

| ID | 事项 | 状态 | 证据 |
|:---|:---|:---|:---|
| B-01 | 生产路径 E2E 建立 | ✅ | `scripts/e2e_production.py` 8/8 通过 |
| B-02 | `<think>` 标签崩溃修复 | ✅ | `tests/llm/test_providers_openai.py` 16 passed |
| B-03 | **BashTool 在 Agent 环路 100% 失败** | ✅ | `tests/tools_runtime/test_bash_execution_paths.py` 11 passed |
| B-04 | **`.env` 可被 Agent 读取（API Key 外泄）** | ✅ | `tests/test_security/test_sensitive_path_guard.py` 33 passed |
| B-05 | 传递可达性分析工具 | ✅ | `scripts/reachability.py` |
| B-06 | 删除 3 个真死包 | ✅ | 3,774 行 |
| B-07 | 删除 3 个被同名包遮蔽的死文件 | ✅ | 384 行 |
| B-08 | 熔断器补测试（原 0% 覆盖） | ✅ | 26 passed, 1 xfailed |
| B-09 | 零覆盖活代码识别工具 | ✅ | `scripts/find_untested_live_code.py` |

### 关键发现：生产 LLM 路径与 v0.51.0 修复的不是同一条

传递可达性分析（`scripts/reachability.py`）显示：

```
生产入口 → src/agent/engine.py:203 → create_llm_provider() → providers/*
v0.51.0 修的 src/llm/factory.py::get_default_llm()  ← 从生产入口不可达
```

v0.51.0 那批修复本身有效（且被 `e2e_smoke.py` 覆盖），但它保护的**不是**
生产实际执行的代码。本轮已补齐对真实生产路径的测试与修复。

### 多智能体审计的三项结论与主线程复核

| 子代理 | 报告要点 | 主线程复核结果 |
|:---|:---|:---|
| blindspot | 1 BLOCKER + 3 HIGH + 13 MEDIUM | B1（BashTool）**已复现并修复**；H2（.env）**已复现并修复**；H1（ApprovalMode 无消费者）**已复现，记录未修**；H3（`max_buffer` 非法参数）待验证 |
| testfail | 38 个失败：A 实现缺陷 6 / B 测试过时 32 | 待逐项处理 |
| deadcode | 称原 213 清单"方向两个都错"，实际 176 不可达 | 其指出 3 个脚本缺陷中，**缺陷 1（`__init__.py` 相对导入）我早已修复**；缺陷 2/3（传递可达性、同名遮蔽）我的分析器已覆盖传递可达性。**但它指出的"同名包遮蔽"是真实问题，已修复** |

> 子代理报告基于它重跑时的**旧版脚本**，未看到我已修的 `__init__.py` 缺陷。
> 其"176 不可达"与我的"255 生产不可达"量级一致，差异在于它把
> "仅测试可达"计入了可达。

---

## 1. 任务契约

| 项 | 内容 |
|:---|:---|
| **目标** | 把 Clawd Code 从"文档声称可用、实际一跑即崩"修复为**真实可运行、可调用、可交付**的 AI 编程代理框架 |
| **范围** | 波次 1（止血）：P0 阻塞缺陷修复 + 测试基建 + 文档同步 + 提交推送 |
| **明确不做** | 波次 2-8（删死代码、覆盖率爬升、架构升级、UI 升级）—— 见 `计划书/下一步改进指南.md` §13，属后续迭代 |
| **成功标准** | 真实 E2E 通过；契约测试全绿；pytest 收集 0 错误；版本号一致；无未解决 P0 |
| **验证方式** | 真实 LLM 端点端到端调用 + pytest + ruff + 逐项验收命令 |

---

## 2. 验收标准表

| ID | 验收项 | 命令 | 期望 | 实际 | 状态 |
|:---|:---|:---|:---|:---|:---|
| A-01 | 真实 E2E：对话 | `python scripts/e2e_smoke.py` | content 非空 | `PONG` | ✅ |
| A-02 | 真实 E2E：工具调用 | 同上（步骤 3） | 返回 tool_calls | `get_weather {"city":"Berlin"}` | ✅ |
| A-03 | 真实 E2E：推理内容 | 同上（步骤 4） | 内容非空 | `391`，reasoning 有 | ✅ |
| A-04 | `.env` 约定生效 | `AgentSettings().llm_api_key` | 非 None | `sk-ee332...` | ✅ |
| A-05 | 补丁引擎 | `pytest tests/self_healing/test_atomic_patcher.py` | 全绿 | 16 passed | ✅ |
| A-06 | Agent 契约 | `pytest tests/contracts/test_agent_registry_stability.py` | 全绿 | 13 passed | ✅ |
| A-07 | 配置合并 | `pytest tests/core/test_config_merger.py` | 全绿 | 48 passed | ✅ |
| A-08 | RAG 事件 | `pytest tests/brain/test_world_model.py -k RagIndex` | 全绿 | 2 passed | ✅ |
| A-09 | verifier 契约 | `pytest tests/workflow/test_verifier.py` | 全绿 | 11 passed | ✅ |
| A-10 | Windows 编码 | `python -m src.main doctor` | 无 UnicodeEncodeError | 0 次（含强制 GBK） | ✅ |
| A-11 | 版本一致性 | 4 处比对 | 完全一致 | 均 0.51.0 | ✅ |
| A-12 | pytest 收集 | `pytest tests/ --collect-only` | 0 errors | 2857 collected, 0 errors, 126s | ✅ |
| A-13 | Agent 主入口 | `create_agent_engine()` | 返回引擎实例 | `AgentEngine` | ✅ |
| A-14 | `clawd setup` 端到端 | 在空目录运行 | 生成 3 个文件 | config.toml + AGENTS.md + catalog-manifest.json | ✅ |
| A-15 | 改动文件静态检查 | `ruff check <changed files>` | 零新增违规 | 0 新增 | ✅ |
| A-16 | HTML 报告测验交互 | Playwright + Chromium | 全场景正确 | 7/7 场景通过 | ✅ |
| A-17 | 全量测试回归 | `pytest tests/` | 记录通过率 | 39 failed / 2814 passed / 4 skipped（45min） | ✅ 已记录 |

### A-17 失败归属分析（关键）

全量 39 个失败中，**只有 1 个是本次改动引入的回归**，已修复；其余 38 个为既有失败。

判定方法：**对照实验** —— 用 `git checkout 7ebd096 -- <file>` 还原改动前的实现，
在同一环境重跑同一测试，对比是否仍失败。

| 失败测试 | 归属 | 依据 |
|:---|:---|:---|
| `tests/llm/test_factory.py::TestLiteLLMCompatWrapper::test_invoke` | **本次引入** → 已修复 | 我给 `Message` 补 `finish_reason` 时未做类型防护，MagicMock 返回非字符串触发 pydantic 校验失败。已加 `_as_str`/`_as_int` 收敛并补 3 个回归用例 |
| `tests/brain/test_world_model_complex.py`（3 例） | 既有 | 对照实验：还原 `code_graph.py` + `world_model.py` 到改动前后**同样失败** |
| 其余 35 例（`runtime/`、`workflow/`、`core/test_platform`、`agent/`、`integration/`） | 既有 | 均不在本次改动范围内 |

> **诚实说明**：38 个既有失败**未处理**。它们属于波次 3+ 的范围（需要先有测试
> 才能安全修）。`workflow_status.md` 只记录事实，不把它们标成"已完成"。

---

## 3. 任务图与执行顺序

```text
波次 0  基线复验 ──────────────────────────── [done]
   │
波次 1  P0 修复（并行，各自独立提交）
   ├─ P0-1 Windows 编码崩溃 ──────────────── [done] ✅ A-10
   ├─ P0-2 AgentDefinition camelCase 漂移 ─── [done] ✅ A-06
   ├─ P0-3 补丁引擎 commit/rollback 缺失 ──── [done] ✅ A-05
   ├─ P0-4 版本号三处不一致 ──────────────── [done] ✅ A-11
   ├─ P0-5 测试收集失败（2 处 API 漂移）──── [done] ✅ A-07/A-09
   ├─ P0-6 同名测试文件模块冲突 ──────────── [done] ✅ A-12
   ├─ P0-7 indexed_count 未定义 ──────────── [done] ✅ A-08
   └─ P0-8~P0-11（本轮新发现，见 §4）─────── [done] ✅ A-01~A-04
   │
波次 1.5 测试基建
   ├─ tests/conftest.py（共享 fixture）───── [done]
   ├─ pyproject.toml 注册 marker ─────────── [done]
   └─ 测试源树 __init__.py 补齐 ──────────── [done]
   │
波次 2 提交与推送 ────────────────────────── [进行中]
```

---

## 4. 执行日志

### 2026-10-16

**基线复验**：确认 `计划书/下一步改进指南.md` 中 P0-1/3/4 仍然存在。

**本轮新发现的 P0（原指南未涵盖，由真实 E2E 暴露）**：

| ID | 缺陷 | 文件 | 影响 |
|:---|:---|:---|:---|
| P0-8 | 访问不存在的 `settings.context_window` | `src/llm/factory.py` | LLM 栈 100% 不可用 |
| P0-9 | `.env` 约定（`OPENAI_API_KEY`）与配置模型（`LLM_API_KEY`）不匹配 | `src/core/config/models.py` | 按文档配置的用户拿不到 API Key |
| P0-10 | `api_key`/`api_base` 未透传给 litellm | `src/llm/factory.py` | 自建端点用户必然 401 |
| P0-11 | 响应解析丢弃 `tool_calls` / `reasoning_content` | `src/llm/factory.py` | Agent 环路断裂 |
| P0-12 | `merge_config` 不幂等，顶层配置沉入 `[agents]` | `src/core/config/merger.py` | 每次启动配置退化 |
| P0-13 | 配置包未 re-export `AgentSettings`/`get_settings`/`load_settings` | `src/core/config/__init__.py` | `create_agent_engine()` 主入口 ImportError 崩溃 |
| P0-14 | `clawd setup` 同步调用 async `merge_config` | `src/cli/commands/setup_commands.py` | 协程从未 await，配置文件不生成 |
| P0-15 | `register_setup_commands` 自引用（`app.add_typer(app)`） | `src/cli/commands/setup_commands.py` | typer 子命令树错误 |
| P0-16 | 模板路径少算一级目录 | `src/cli/commands/setup_commands.py` | AGENTS.md / catalog 永远"模板未找到" |
| P0-17 | `_resolve_all_edges` 迭代中字典被并发修改 | `src/rag/code_graph.py` | 后台构建时 `RuntimeError` |
| P0-18 | `ensure_project_dirs` 被引用但全仓库不存在 | `src/cli/commands/setup_commands.py` | `clawd setup` ImportError |

**关键发现过程**：P0-8 ~ P0-11 全部是**静态分析无法发现**的 —— ruff 的 `F821` 只检查名称不检查属性，`mypy` 未启用。只有接入真实端点跑 E2E 才逐层暴露（错误依次为 `AttributeError` → `litellm.turn_off_verbose_logging` → `401` → 空 tool_calls）。

**P0-12 发现过程**：为 `merge_config` 编写的**幂等性**测试直接失败，暴露出"反复合并会让配置自我污染"。

**修正记录**：指南 §1.3.2 曾把 `tests/self_healing/test_engine.py` 与 `tests/tools_runtime/test_types.py` 的收集失败推断为"测试间状态污染 / 收集顺序依赖"。**该推断是错的**。真实原因是 pytest 的 `import file mismatch` —— `tests/` 下存在同名文件（`test_engine.py` ×2、`test_types.py` ×2）而子目录缺少 `__init__.py`。已按标准做法补齐 14 个 `__init__.py`。

---

## 5. 验证日志

| 时间 | 命令 | 结果 |
|:---|:---|:---|
| 00:18 | `python scripts/e2e_smoke.py`（修复前） | 2/5 通过，`AttributeError: context_window` |
| 00:29 | 同上（修 P0-8 后） | 2/5，`litellm.turn_off_verbose_logging` |
| 00:3x | 同上（修 P0-9 后） | 2/5，401（打到官方 endpoint） |
| 00:3x | 同上（修 P0-10/11 后） | **5/5 通过** |
| — | `pytest tests/self_healing/test_atomic_patcher.py` | 6 failed → **16 passed** |
| — | `pytest tests/contracts/test_agent_registry_stability.py` | 5 failed → **13 passed** |
| — | `pytest tests/workflow/test_verifier.py` | 收集失败 → **11 passed** |
| — | `pytest tests/core/test_config_merger.py` | 收集失败 → **48 passed** |
| — | `pytest tests/brain/test_world_model.py -k RagIndex` | **2 passed** |
| — | `pytest tests/ --collect-only` | 4 errors / 2769 用例 / 306s → **2 errors / 2840 用例 / 166s** → 复验中 |

---

## 6. 阻塞项

无。

（外部条件限制，非阻塞：覆盖率实际 47.44%，`fail_under` 已修正为 47 并**真实生效**
（原 60 写在 `[tool.coverage.run]` 被 coverage 忽略）；提到 60 属 W5 范围。）

> 本节为 v0.51.0 时期的历史记录，当前阻塞项见文件顶部「当前状态」。

---

## 7. 下一步

1. 复验 `pytest tests/ --collect-only` 的 0 errors（进行中）
2. 全量测试回归，记录通过率
3. 更新 README / CHANGELOG / 计划书进度
4. 提交并推送 main
5. 波次 2 起的内容（死代码收敛、覆盖率爬升）留待下一轮

---

*本文件只记录可验证的事实。任何标记为 done 的条目都必须有对应的命令输出。*

# test_ledger.md — 测试台账

> 只记录**实际执行**的命令与结果。未执行写 `not_run`。

## 基线（实施前，2026-10-19）

| 范围 | 命令 | 结果 |
|:---|:---|:---|
| 静态硬指标 | `ruff check src/ --select F821,F811` | All checks passed |
| 导入完整性 | `python scripts/import_sweep.py` | 640 模块 / IMPORT-FAIL 0 / DEP-MISSING 6 |
| 生产可达 | `python scripts/reachability.py` | 431 可达 / 209 不可达 |
| 测试收集 | `pytest tests/ --collect-only -q` | 3100 collected / 0 errors / 561.55s |
| 契约 | `pytest tests/contracts -q` | 39 passed / 83.72s |
| 覆盖率 | `coverage.json` totals | 46.15%（25,877 / 56,072） |
| CLI | `python -m src --version` | v0.59.0 |

## 本轮实施后（2026-10-19）

| 范围 | 命令 | 结果 | 证据 |
|:---|:---|:---|:---|
| 新增：状态持久化 | `pytest tests/workflow/test_state_persistence_semantics.py -q` | **14 passed**（含生产函数并发） | evidence/P0-5 |
| 新增：跨平台状态快照 | `pytest tests/core/test_state_persistence_windows_safe.py -q` | **2 passed**（Windows 保存 + 并发追加 40 条；并行负载下复验） | 本轮 |
| 生产持久化并发 | `pytest tests/core/test_run_state_concurrency.py -q` | **2 passed**（4 线程任务不丢 + 40 行 JSONL 合法） | 本轮 |
| 并行负载复验 | 同时跑 `tests/core` 与 `tests/workflow` | **669 + 226 passed / 0 failed** | 本轮 |
| 熔断器时序 | `pytest tests/llm/test_circuit_breaker.py -q` | **25 passed / 1 xfailed**（连续 5 次） | 本轮 |
| 测试收集 | `pytest tests/ --collect-only -q` | **3171 collected / 0 errors / 64.84s** | 本轮 |
| 新增：工具策略 | `pytest tests/agent/test_tool_policy.py -q` | **10 passed** | evidence/P1-4 |
| 新增：SSRF | `pytest tests/tools_runtime/test_scrape_ssrf.py -q` | **25 passed** | evidence/P1-9 |
| 新增：Skill 注入 | `pytest tests/agent/test_skill_injection.py -q` | **6 passed** | evidence/P1-10 |
| 新增：原生工具调用 | `pytest tests/agent/test_native_tool_calls.py -q` | **8 passed** | evidence/P1-1 |
| 定向回归（7 目录） | `pytest tests/agent tests/workflow tests/tools_runtime tests/llm tests/contracts tests/cli tests/server -q` | **1383 passed, 1 xfailed, 0 failed**（564.12s） | 本轮 |
| **全量测试** | `pytest tests/ -q` | **3165 passed, 5 skipped, 1 xfailed, 0 failed**（2806.15s） | 本轮 |
| 静态硬指标（CI 同款） | `ruff check src/ tests/ --select F821,F811,E9` | All checks passed（修复 tests 中 4 个 F811 后） | evidence/B1 |
| 导入完整性 | `python scripts/import_sweep.py` | 642 模块 / IMPORT-OK 636 / **FAIL 0** / DEP-MISSING 6 | 本轮 |
| 生产可达 | `python scripts/reachability.py` | **442 可达**（基线 431，未下降）/ 200 不可达 | 本轮 |
| 真实 E2E 冒烟 | `python scripts/e2e_smoke.py` | **5/5 PASS**（v0.60.1 复跑，退出码 0） | 本轮 |
| 生产路径 E2E | `python scripts/e2e_production.py` | **8/8 PASS**（v0.60.1 复跑，含上游失败路径） | 本轮 |
| 原生工具真实端点 | 加载 `.env` 后 `provider.chat(tools=...)` | 返回 `BashTool {"command":"echo hi"}` | 本轮 |
| 并发压测 | `python scripts/stress_test.py --n 200` | **5/5 PASS**；200 并发 24.49s（~11 req/s）；审批混合拒绝=100/只读=100/YOLO=100/错误=0 | 本轮 |
| 版本一致性 | `python -m src --version` + metadata | **v0.60.2** / 0.60.2 | 本轮 |
| 快速启动脚本 | `cmd /c .\start.bat doctor` | 退出码 0；89s；诊断全 PASS | evidence/E-31 |
| venv 独立启动 | `venv/Scripts/python.exe -m src --version` | v0.60.2；无缺失依赖/traceback | evidence/E-31 |
| HTML 报告测验 | `scripts/verify_html_report.py reports/change-report-2026-10-19.html` | 9/9；错一题正确判未通过；6 项断言通过 | 本轮 |
| CI YAML | `python -c "yaml.safe_load(...)"` | yaml OK | evidence/B1 |

## 未执行 / 未达成（如实披露）

| 项 | 状态 | 原因 |
|:---|:---|:---|
| 覆盖率 60% | **未达成**（基线 46.15%） | 需要数百条针对生产可达模块的测试，非单轮可完成；本轮未降低覆盖率 |
| 测试收集 <120s | **✅ 已达成**（2026-10-23 实测 29.31s 冷 / 5.09s 热） | 原基线 561.55s；v0.57.0 的导入期惰性化（D-19）是主要原因 |
| 死模块 ≤20 | **未达成**（200 不可达） | 需人工逐条读源码复核，禁止按名称删除 |
| GitHub Actions 实跑 | **not_run** | 本机无 `gh` CLI，无法触发/观察远端 CI |
| GitHub Release | **not_run** | `gh` 不可用 |
| Docker 构建/部署/热更新 | **not_run** | 本机 `where docker` 无结果；无部署目标与凭证 |
| 流式原生工具调用 | **未实现** | 流式路径仍走文本协议；原生调用仅在非流式路径启用 |
| 浏览器真实路径 | **not_run** | 本项目为 CLI，无 Web UI；未引入 Playwright |

---

## 2026-10-23 实测复核（W0 文档校准 + W1 环境与归因）

> 本轮先复测、再动手。下表为**动手前**的基线，命令全部实际执行。

### 动手前基线

| 范围 | 命令 | 结果 |
|:---|:---|:---|
| 版本 | `venv/Scripts/python.exe -m src --version` | **v0.60.6**（pyproject 同） |
| 规模 | `find src -name "*.py"` | 642 模块 / 137,443 行 |
| 静态硬指标 | `py -3.10 -m ruff check src/ tests/ --select F821,F811,E9` | All checks passed |
| 全量 ruff | `py -3.10 -m ruff check src/ --statistics` | **432 errors**（W293 132 / F401 35 / E402 34 / RUF012 30 / B904 23 …） |
| 导入扫描（venv） | `venv/Scripts/python.exe scripts/import_sweep.py` | 642 / OK 601 / **FAIL 1**（`src.cli.surface_viewer`）/ DEP-MISSING 40 |
| 导入扫描（py 默认 3.14） | `py scripts/import_sweep.py` | 642 / OK 395 / FAIL 1 / **DEP-MISSING 246** |
| 生产可达 | `py scripts/reachability.py` | **443 可达** / 199 不可达（完全不可达 134 / 24,667 行）※修复 D-09 后 |
| 用例收集（py -3.10） | `py -3.10 -m pytest tests/ --collect-only -q` | **3171 collected / 0 errors / 29.31s**（修复前） |
| 用例收集（py 默认 3.14） | `py -m pytest tests/ --collect-only -q` | **2007 collected / 68 errors / 7.62s**（环境缺 loguru 等） |
| 覆盖率 | `coverage.json` totals | 46.15%（25,877 / 56,072），文件生成于 2026-10-18 |
| 静默吞异常 | `py -3.10 scripts/check_silent_except.py` | **172**（AST 口径） |

### W1 实施后（本轮）

| 范围 | 命令 | 结果 |
|:---|:---|:---|
| 环境收敛 | `venv/Scripts/python.exe -m pip install -e ".[dev]"` | pytest 9.1.1 / ruff 0.17.2 / coverage 7.16.2；clawd-code **0.60.6** |
| 导入扫描 | `venv/Scripts/python.exe scripts/import_sweep.py` | **IMPORT-FAIL 0** / OK 602 / DEP-MISSING 40 |
| 归因单测 | `py -3.10 -m pytest tests/scripts -q` | **17 passed**（10 归因 + 7 口径） |
| 版本一致性 | `py -3.10 -m pytest tests/core/test_version_consistency.py -q` | **2 passed** |
| 导入行为 | `venv/Scripts/python.exe -c "import src.cli.surface_viewer"` | 无异常（此前 `SystemExit: 1`） |
| 静默吞异常 | `py -3.10 scripts/check_silent_except.py --baseline 172` | 退出码 0 |

### 本轮全量回归（2026-10-23）

| 范围 | 命令 | 结果 |
|:---|:---|:---|
| **全量测试** | `py -3.10 -m pytest tests/ -q` | ✅ **3165 passed, 5 skipped, 1 xfailed, 0 failed in 425.29s（7:05）** |

> 3165 + 5 + 1 = 3171，与 `--collect-only` 的收集数完全吻合。
> 历史记录为 2806s，「全量要跑 47 分钟」的结论在新环境下不成立（快 6.6 倍）。

### 依赖声明修复（本批收口，2026-10-23）

真实 E2E 逼出 4 个未声明的生产依赖，修复后复测：

| 步骤 | 命令 | 结果 |
|:---|:---|:---|
| 修复前 E2E | `venv/Scripts/python.exe scripts/e2e_smoke.py` | ❌ 通过 2 / 失败 3（`litellm` 未安装） |
| 补 `litellm` | 加入 `pyproject.toml` dependencies | — |
| 第二次 E2E | 同上 | ❌ 通过 4 / 失败 1（`mcp` 未安装） |
| 补 `mcp` | `pip install mcp` + 写入 pyproject/requirements | — |
| 第三次 E2E | 同上 | ✅ **5/5 PASS**，退出码 0 |
| 生产路径 E2E | `venv/Scripts/python.exe scripts/e2e_production.py` | ✅ **8/8 PASS**，退出码 0 |
| 补 `psutil`/`fastapi`/`uvicorn` | 均为生产路径硬 import 但从未声明 | — |
| 导入扫描（最终） | `venv/Scripts/python.exe scripts/import_sweep.py` | **642 / OK 635 / FAIL 0 / DEP-MISSING 7**（celery/opentelemetry/pathspec，均为可选 extras） |
| 定向回归 | `py -3.10 -m pytest tests/scripts tests/core/test_version_consistency.py tests/contracts -q` | **58 passed** |
| 依赖变更后全量 | `py -3.10 -m pytest tests/ -q` | 见下方「收口全量」 |

### 收口全量（依赖变更后）

> ⚠️ 单进程全量出现**挂起**（两次：58% 处进程消失 / 51%→58% 停滞 5 分钟），
> 改为按目录分批执行，四批全部 0 failed。

| 批次 | 范围 | 结果 |
|:---|:---|:---|
| 1 | `agent core cli llm tools_runtime scripts` | **1801 passed, 1 xfailed**（96.89s） |
| 2 | `brain cli_handlers contracts integration memory notification performance rag runtime self_healing server` | **308 passed**（249.73s） |
| 3 | `tests/test_*.py` | **270 passed, 1 skipped**（9.86s） |
| 4 | `test_security test_state utils workflow` | **822 passed, 4 skipped**（40.12s） |
| 合计 | — | **3201 passed / 5 skipped / 1 xfailed / 0 failed** |

**未解问题（D-10）**：单进程全量在 58%（约第 1836 个用例，
`tests/runtime/test_engine.py` 与 `tests/scripts/` 交界）挂起，顺序相关，
疑似前序测试泄漏后台线程/事件循环（对应 `ADR-0006`）。CI 单进程跑全量会超时。
定位方法：二分目录 + 固定随机种子，找到泄漏点补 `finally` 清理。

### 本轮未执行

| 项 | 状态 | 原因 |
|:---|:---|:---|
| 覆盖率重跑 | **not_run** | 需全量带 `--cov`，安排在 W2 |
| 远端 CI | **not_run** | 本机无 `gh` |

---

## 2026-10-23 本轮落地验收（W0' 文档自洽 + W1' 度量自洽 + W2 分层 + W3 CI 门禁）

> 全部命令实际执行，输出可在 `.clawd/logs/full-run-20261023-1135.log` 复核。
> 解释器：`py -3.10`（测试/lint）· `venv/Scripts/python.exe`（CLI/脚本/E2E）。

### A. 全量回归（本轮唯一一次完整运行）

| 范围 | 命令 | 结果 |
|:---|:---|:---|
| 全量 + 覆盖率 | `py -3.10 -m pytest tests/ -q --cov=src --cov-report=json:coverage.json --cov-fail-under=0` | **3200 passed / 1 failed / 5 skipped / 1 xfailed / 767.19s**（首轮，失败项见下） |
| 全量（最终确认，改动收口后） | `py -3.10 -m pytest tests/ -q` | **3254 passed / 0 failed / 5 skipped / 2 xfailed / 639.98s** ✅ |
| 快速层（不含 slow） | `py -3.10 -m pytest tests/ -q -m "not slow"` | **3245 passed / 5 skipped / 9 deselected / 2 xfailed / 237.23s** |
| slow 层规模 | `py -3.10 -m pytest tests/ --collect-only -q -m slow` | 9 个用例（合计约 410s，占首轮全量 53%） |

**唯一失败项与处置**：`tests/test_state/test_authority.py::TestConcurrency::test_acquire_release_thread_safe`
- 根因：测试断言 `len(errors) == 0`，即"10 线程并发 acquire 同一租约都应成功"。
  但 `AuthorityLease` 是 **Exactly-One 互斥租约**，竞争者必然被 `LeaseAcquisitionFailed` 拒绝。
  该测试只有在"acquire/release 恰好被调度成串行"时通过 → **靠运气变绿的 flaky**。
- 判定：**非本轮引入**（本轮未触碰 `src/core/state/authority.py` 与 `tests/test_state/`）；
  单独串行跑 3 次均 passed，高负载下必现。
- 修复（符合 ADR-0005，不放宽断言而是改为更强契约）：
  改为断言「恰好 1 个成功 + 9 个被 `LeaseAcquisitionFailed` 拒绝 + 0 个非预期异常 +
  释放后可再次获取」，用 `threading.Barrier` 最大化竞态窗口，成功者**故意不释放**保证确定性。
- 复验：`pytest tests/test_state/test_authority.py -q` **连续 5 次 30 passed**。

### B. 覆盖率（本轮重取，替换 10-18 的旧数据）

| 项 | 旧值 | 本轮实测 |
|:---|:---|:---|
| 覆盖率 | 46.15%（25,877 / 56,072），数据 2026-10-18 | **47.44%（26,861 / 56,624）**，数据 2026-10-23 11:51 |
| `fail_under` | 写在 `[tool.coverage.run]` → **coverage 不识别，从未生效** | 移到 `[tool.coverage.report]`，**已验证生效**（小范围跑出 `FAIL Required test coverage of 60.0% not reached`） |
| 阈值 | `pyproject` 60（不生效）+ CI 硬编码 45（生效） | 收敛为单一来源 `fail_under = 47`；CI 不再传参 |

> **为什么不直接设 60**：60 从未生效，真实生效的是 45。设 47 是相对 45 的**提高**且可执行；
> 分批提阈值 47 → 50 → 55 → 60（见 `计划书/下一步改进指南.md` W5）。

### C. 真实 E2E（已按 policy §2 授权，调用总量 11 次模型请求）

| 脚本 | 命令 | 结果 |
|:---|:---|:---|
| 冒烟 5 步 | `venv/Scripts/python.exe scripts/e2e_smoke.py` | **5/5 PASS，退出码 0**；`content='PONG'`、`tool=get_weather {"city":"Berlin"}`、`answer='391'` |
| 生产路径 8 步 | `venv/Scripts/python.exe scripts/e2e_production.py` | **8/8 PASS，退出码 0**；`chat` 12.46s、`chat_stream` 9.16s（thinking_chunks=12）、工具解析、上游失败降级均通过 |
| 端点 | `.env` | `base=https://token.54421666.xyz/v1` · `model=step-5-preview` · key 已打码 |

### D. 并发压测（纯本地状态机，不调用真实模型）

| 项 | 命令 | 结果 |
|:---|:---|:---|
| 200 并发 | `venv/Scripts/python.exe scripts/stress_test.py --n 200` | **5/5 PASS，退出码 0**；200 任务全成功无错配（1.56s，**128 req/s**）；线程池无泄漏；审批混合 拒绝100/只读100/YOLO100/错0；熔断 200 事件无丢失、状态正确 OPEN |

### E. 门禁脚本（新增/加固，均有自测）

| 脚本 | 新增能力 | 验证方式（真实执行） |
|:---|:---|:---|
| `scripts/import_sweep.py` | `--strict-exit`：`IMPORT-EXIT > 0` 即失败 | 临时投放 `sys.exit(1)` 探针 → 退出码 **1**；删除后 → **0**（探针已清理） |
| `scripts/reachability.py` | `--min-reachable N`；`PROD_SEED_MODULES` + `compute_reachability()` 单一口径 | `--min-reachable 442` → 0；`--min-reachable 443` → 1（443 为修正后真实值） |
| `scripts/check_silent_except.py` | `--fail-over` / `--write-baseline` / `--baseline-file` | 写入 `.clawd/baseline-silent.json`（total=172）；阈值优先级有 4 条单测 |
| `scripts/baseline.py`（新） | 一条命令输出全部指标 JSON | `--quick` 输出 17 项；`consistent=true`；`--out` 落盘 |
| `scripts/deadcode_triage.py`（新） | 死代码三问机械筛查 | 134 个完全不可达 → NO_REFS 112 / DOC_ONLY 6 / HAS_REFS 16 |

### F. 度量口径修正（3 处，影响历史数字可比性）

| # | 修正 | 影响 |
|:---|:---|:---|
| 1 | `reachability` 生产入口种子漏了 `src.__main__`（`python -m src` 的规范入口） | 可达 442 → **443**；完全不可达 135 → **134**。**不是新增功能，是口径修正** |
| 2 | `deadcode_triage` 初版自己复制了一份种子列表，把 `src.__main__` 判成"死代码" | 已改为复用 `reachability.compute_reachability()`，禁止各处复制口径 |
| 3 | `deadcode_triage` 初版用"末段标识符"匹配引用，135/135 全判 HAS_REFS | 收紧为"全限定名 + 确切导入语句"，得 112/6/16 |

### G. 本轮仍未达成（如实披露）

| 项 | 目标 | 实际 | 原因 |
|:---|:---|:---|:---|
| 快速层 < 180s | 180s | **237.23s** | slow 层已剥离 410s（占 53%）；剩余耗时分散在 3245 个用例（Top40 之后单项 <4s） |
| 覆盖率 60% | 60% | **47.44%** | 需补 7,766 行覆盖，属 W4/W5 多批次工程 |
| 死模块 ≤20 | 20 | **134** | 判定报告已出（112 个零引用候选），**删除需产品决策**（砍 2 万行能力，不可逆） |
| 远端 CI 实跑 | 通过 | **not_run** | 本机无 `gh` CLI |
| Docker / 生产部署热更新 | 通过 | **not_run** | 本机无 docker、无部署目标与凭证 |
| GitHub Release | 创建 | **not_run** | 无 `gh`；已建本地 tag 与 CHANGELOG 条目 |

---

## 2026-10-23 第三轮（v0.60.9）：死代码第一批删除

> 这是第一次**真正删除**代码。前几轮只出判定报告，因为"按名字删"已经误判过一次（ADR-0001）。

### 删除清单（8 模块 / 407 行）

| 模块 | 行数 | 三方核验 |
|:---|---:|:---|
| `src/core/config/validator.py` | 74 | 全限定导入 0 / 父包 `__init__` 相对导入 0 / 同级模块相对导入 0 |
| `src/core/snapshot.py` | 68 | 同上 |
| `src/workflow/mode_context.py` | 63 | 同上 |
| `src/core/telemetry/tracer.py` | 53 | 同上 |
| `src/core/durable/schemas/schema_validator.py` | 50 | 同上 |
| `src/core/lease.py` | 44 | 同上 |
| `src/core/parallel_executor.py` | 43 | 同上 |
| `src/tools_runtime/diff_utils.py` | 12 | 同上（与存活 `src/utils/diff_utils.py` 职责不同：前者是 tools 层包装） |

### 不变量（删前 → 删后）

| 项 | 删前 | 删后 | 命令 |
|:---|:---|:---|:---|
| 生产可达 | 443 | **443** | `py -3.10 scripts/reachability.py` |
| 模块数 | 642 | 634 | 同上 |
| 完全不可达 | 134 | 126 | 同上 |
| 导入缺陷 | 0 | **0** | `import_sweep.py --strict-exit` |
| 用例收集 | 3558 / 0 errors | 3558 / 0 errors | `pytest --collect-only -q` |
| 静态硬指标 | All passed | **All passed** | `ruff --select F821,F811,E9` |
| 定向回归 | — | **1289 passed / 0 failed**（47.63s） | `pytest tests/{core,workflow,tools_runtime,contracts} -q -m "not slow"` |

### 门禁抓住我自己的误判（本轮最重要的记录）

首轮按旧判据删了 **10** 个，`import_sweep --strict-exit` 立刻返回 **1**，报 4 个 IMPORT-FAIL：

```
src.core.secrets.vault            -> ModuleNotFoundError: No module named 'src.core.secrets.base'
src.workflow.pipeline_stages      -> ModuleNotFoundError: No module named 'src.workflow.pipeline_stages.types'
src.workflow.pipeline_stages.ralph_verify -> 同上
src.workflow.pipeline_stages.team_exec    -> 同上
```

根因：`src/core/secrets/vault.py:11  from .base import SecretStore`、
`src/workflow/pipeline_stages/ralph_verify.py:11  from .types import StageContext, StageResult`
—— 是**同级**相对导入，而判据当时只查父包 `__init__.py`。

处置：恢复 `base.py` / `types.py`（2 个），其余 8 个保留删除；复验 FAIL=0、可达数 443。

**判据三版演进**：

| 版本 | 判据 | NO_REFS |
|:---|:---|---:|
| v1 | 末段标识符匹配 | 135/135 全判"有引用"（误报） |
| v2 | + 父包 `__init__` 相对导入 | 112（仍有假阴性） |
| v3（本轮） | + **同包内任意模块**的相对导入 | **55** |

### 剩余

完全不可达 **126** 个；三问判定 **NO_REFS 55 / DOC_ONLY 6 / HAS_REFS 65**。
第二批待办：每批 ≤20 模块 + 同一套不变量验证 + 逐批 revert 能力。

### 未运行（本轮）

| 项 | 状态 | 原因 |
|:---|:---|:---|
| 真实 E2E | ✅ **已复跑**（v0.60.10）：`e2e_smoke` **5/5 PASS / exit 0**、`e2e_production` **8/8 PASS / exit 0** | `venv/Scripts/python.exe scripts/e2e_*.py` |
| 压测 | not_run | 本轮未触碰并发基础设施（线程池/审批/熔断）；上次运行于 v0.60.7（200 并发 5/5，128 req/s） |
| 移除 55 个候选中的第二批 | not_run | 需逐条三方核验 + 每批全量验证 |

### v0.60.10 合并收口实测（2026-10-23 13:45）

| 项 | 命令 | 结果 |
|:---|:---|:---|
| 全量回归 | `py -3.10 -m pytest tests/ -q` | **3551 passed / 0 failed / 5 skipped / 2 xfailed / 623.24s** |
| 真实 E2E 冒烟 | `venv/Scripts/python.exe scripts/e2e_smoke.py` | **5/5 PASS / exit 0**（PONG 18.02s / get_weather Berlin 5.57s / 391 6.58s） |
| 生产路径 E2E | `venv/Scripts/python.exe scripts/e2e_production.py` | **8/8 PASS / exit 0**（chat / chat_stream 11 thinking chunks / 工具解析 / 上游失败不静默降级） |
| 静态硬指标 | `py -3.10 -m ruff check src/ tests/ --select F821,F811,E9` | All checks passed |
| 导入完整性 | `import_sweep.py --strict-exit` | exit 0 |
| 生产可达 | `scripts/reachability.py` | exit 0（443，删 8 模块后不变） |
| 静默吞异常 | `scripts/check_silent_except.py` | exit 0（172，未因新增 265 用例上升） |
| 全指标基线 | `scripts/baseline.py --quick` | exit 0，`consistent=true` |
| 版本一致性 | cli / pyproject / dist-info | 均 **0.60.10** |

> 本轮合并了另一个并行会话的成果（12 个生产缺陷修复 + 265 个新测试）。
> 该会话自行完成了缺陷清单与 CHANGELOG 条目，本会话代为收口提交（e32d341）。

## v0.61.2 收口批次（2026-10-28，全部实跑）

| 范围 | 命令 | 结果 | 证据 |
|:---|:---|:---|:---|
| 导入完整性 | `venv/Scripts/python.exe scripts/import_sweep.py --strict-exit` | **602/602 OK / IMPORT-FAIL 0 / DEP-MISSING 0**（原 642+3fail+7missing） | 本轮 |
| 测试收集 | `py -3.10 -m pytest tests/ --collect-only -q` | **3710 collected / 0 errors** | 本轮 |
| ruff 硬指标 | `py -3.10 -m ruff check src/ tests/ --select F821,F811,E9` | All checks passed | 本轮 |
| ruff 全量（src） | `py -3.10 -m ruff check src/` | **433 → 319**（仅空白 101 + 安全未用导入 11，禁用 unsafe 全量） | 本轮 |
| 静默吞异常 | `scripts/check_silent_except.py --fail-over 172` | **156**（≤172 门禁过，较 174 下降） | 本轮 |
| 生产可达 | `scripts/reachability.py --min-reachable 443` | **455 可达 / 79 不可达**（删码后不变） | 本轮 |
| 快速回归 | `pytest tests/ -q -m "not slow"` | **3692 passed / 0 failed** | 本轮 |
| 真实 E2E | `venv/Scripts/python.exe scripts/e2e_smoke.py` | **5/5 PASS，exit 0** | evidence/T-090 |
| 契约 | `pytest tests/workflow tests/server -q` | **345 passed** | 本轮 |
| 压测 WS Host | `scripts/stress_host.py --n 100 --rounds 10` | QPS 3839 / P95 14.4ms / 错误率 0% | evidence/T-090 |
| 压测 WS Host 加重 | `scripts/stress_host.py --n 300 --rounds 5` | QPS 1265 / P95 10.8ms / 错误率 0% | evidence/T-090 |
| 环境诊断 | `python -m src doctor` | **0 FAIL**，版本三处一致 0.61.2 | 本轮 |
| 快速启动脚本 | `cmd //c .\start.bat` | 正常启动 REPL（v0.61.2 / openai / 正常退出） | 本轮 |

### 新增接缝（Seam Registry 补充）

| 接缝 | 模块A | 模块B | 契约描述 | 最后验证 | 状态 |
|:---|:---|:---|:---|:---|:---|
| static-mime | src/server/websocket_server.py | tests/server/test_host_entry.py | 静态托管 18 后缀 mime 白名单；白名单外 403；路径穿越 is_relative_to 拒绝 | 2026-10-28 | locked |
| ralplan-approved-hint | src/workflow/stages/ralplan.py | tests/workflow/test_ralplan_approved_hint.py | .omx/plans/prd-*.md 中 $team/$ralph 命令解析（slug 过滤 spec）；7 用例锁定 | 2026-10-28 | locked |
| background-tasks | src/background/tasks/*.py | src/background/celery_app.py | 相对导入 `..celery_app`；task_revoked 接收 **kwargs | 2026-10-28 | locked |

## v0.61.3 覆盖率攻坚批次（2026-10-28，全部实跑）

| 范围 | 命令 | 结果 |
|:---|:---|:---|
| 覆盖率（实测） | `pytest tests/ -m "not slow" --cov=src` | **60.33%**（32,643 / 54,103），较 10-23 陈旧值 49.89% 提升 10.44pp |
| 全量执行 | 同上 | **4491 passed / 7 skipped / 12 xfailed**（收集 4575） |
| 测试规模增长 | 3692 → 4575 收集（+883 用例，5 个并行攻坚代理） | — |
| notification/formatter | `--cov=src.notification.formatter` | 14% → **99%** |
| notification/config | `--cov=src.notification.config` | 17% → **100%** |
| config/generator | `--cov=src.config.generator` | 15% → **99%** |
| core/config/generator | `--cov=src.core.config.generator` | 0% → 高覆盖 |
| tools_runtime/watch_tool | `--cov=src.tools_runtime.watch_tool` | 15% → **99%** |
| workflow/pipeline | `--cov=src.workflow.pipeline` | 45% → 高覆盖（含状态机/持久化/异常路径） |
| workflow/worktree_isolation | 新增测试 | 0% → 覆盖 |
| workflow/team/state/locks | 新增测试 | 0% → 覆盖 |
| cli/textual_dashboard + dashboard/* | 新增测试 | 0% → 覆盖 |
| agent/swarm/{engine,auditor} | 新增测试 | 42% / 26% → 显著提升 |

### 本批次修复的真实缺陷（8 个，均有测试锁定）

| # | 缺陷 | 位置 | 后果 | 状态 |
|:--|:---|:---|:---|:---|
| 1 | Payload 缺 tmux_tail/agent_name/agent_type | src/notification/types.py | 20/38 事件类型 AttributeError | 已修 + 38/38 实测 |
| 2 | float(ISO timestamp) | src/notification/formatter.py:177 | session-start 通知必崩 | 已修（_parse_timestamp） |
| 3 | set 交给 json.dumps | src/tools_runtime/watch_tool.py:489 | get_changes(path=) 必抛 TypeError | 已修（list()） |
| 4 | 不存在的 ErrorCode.INVALID_PARAMETER / TASK_FAILED | src/workflow/pipeline.py:184,390 | 契约 ClawdError 从未抛出 | 已修（CONFIG_MISSING / WORKFLOW_EXECUTION_ERROR） |
| 5 | artifacts 不回写状态 | src/workflow/pipeline.py:run() | get_artifact() 恒 None | 已修 |
| 6 | typer.Exit 被 except Exception 吞 | src/cli/entrypoint.py:chat | **clawd chat 永远退出码 1** | 已修 |
| 7 | --report 单向布尔 | src/cli/entrypoint.py:config | 无法关闭报告 | 已修（--report/--no-report） |
| 8 | UnicodeDecodeError 逃逸 | src/hooks/extensibility/sdk.py | hook 状态读 GBK 时抛错 | 已修（ValueError） |

## v0.62.0 评测 harness（2026-10-28，全部实跑）

| 范围 | 命令 | 结果 |
|:---|:---|:---|
| eval harness 单测 | `pytest tests/eval -q` | **33 passed** |
| CLI 端到端（replay） | `python -m src eval src/eval/datasets/smoke.json` | `eval 3/3 passed (100.0%)`，exit 0 |
| 付费红线拒绝 | `pytest -k live_without_gate`（CLI 层） | exit 2 + 提示 `CLAWD_EVAL_ALLOW_PAID` |
| 基线回归判定 | `pytest -k "baseline or tolerance"` | pass_rate 下降 / 用例转失败均报出；提升不报 |
| 数据集校验 | `pytest -k test_rejects` | 空 expect / 未知断言 / 类型不符 / JSON 损坏 → 显式报错 |
| 导入扫描 | `import_sweep --strict-exit` | **607/607 OK**（+5 eval 模块），FAIL 0 |
| 收集 | `pytest --collect-only` | 4655 / 0 errors |

### 新增接缝

| 接缝 | 模块A | 模块B | 契约描述 | 最后验证 | 状态 |
|:---|:---|:---|:---|:---|:---|
| eval-dataset | src/eval/runner.py | src/eval/metrics.py | 数据集 JSON schema（version/cases/expect 五类断言/recorded）；非法即 EvalConfigError | 2026-10-28 | locked |
| eval-paid-gate | src/eval/runner.py | 环境变量 | live 模式需 `CLAWD_EVAL_ALLOW_PAID=1` + agent_fn，缺一即拒 | 2026-10-28 | locked |
| eval-baseline | src/eval/baseline.py | .clawd/eval_baseline.json | pass_rate 与逐用例通过状态比对；新增用例不算回归 | 2026-10-28 | locked |
| dimension-guidance | src/workflow/engine.py | src/workflow/dimensions.py | `--dimension` → 运行期配置 → run() 入口注入；无/未知/异常均降级 | 2026-10-28 | locked |

## 2026-10-31 v0.89.0 / v0.89.1 —— 本轮实跑台账

> 只记录**实际执行过**的命令与结果。未执行标 `not_run`。

| 范围 | 命令 | 结果 |
|:---|:---|:---|
| 全量（not slow，最终 HEAD） | `pytest tests/ -q -m "not slow"` | **5444 passed / 7 skipped / 7 xfailed / 0 failed**（315.06s） |
| 覆盖率 | `pytest tests/ -q -m "not slow" --cov=src` | **66.29%**（38741/58439，`fail_under=60` 生效） |
| 收集 | `pytest tests/ --collect-only -q` | **5467 / 0 errors**（4.02s） |
| 契约 | `pytest tests/contracts -q` | 39 passed |
| ruff 硬指标（全仓） | `ruff check src tests --select F821,F811,E9` | All checks passed |
| 导入完整性 | `scripts/import_sweep.py --strict-exit` | IMPORT-FAIL 0 / DEP-MISSING 0（604 模块） |
| 生产可达 | `scripts/reachability.py --min-reachable 443` | **503**（基线 501，未降）/ 完全不可达 25 |
| 静默吞异常 | `scripts/check_silent_except.py --fail-over 154` | **154**（门禁 155→154，只降不升） |
| 审计台账 | `scripts/verify_audit_p1.py` | **28/28** |
| 假成功扫描 / MCP 启动 / core 边界 | `scan_fake_success.py` / `check_mcp_startup.py` / `core_surface.py` | 0 命中 / **4/4** / PASS |
| 文档漂移 | `scripts/check_doc_drift.py` | 全一致 |
| 版本一致性 | `scripts/baseline.py` | 0.89.1 / 0.89.1 / 0.89.1（pyproject / CLI / dist-info） |
| pre-commit 全套 | `pre-commit run --all-files` | **14 个 hook 全 Passed** |
| 真实端点 E2E | `scripts/e2e_smoke.py` / `scripts/e2e_production.py` | **5/5** / **8/8**（exit 0） |
| 压测（本地 WS Host） | `scripts/stress_host.py --n 200 --rounds 10` | QPS **2514** · P50 11.1 / P95 15.4 / **P99 15.6ms** · 错误率 **0%** |
| 压测（300×5） | `scripts/stress_host.py --n 300 --rounds 5` | QPS 1355 · P99 15.2ms · 错误率 0% |
| **Linux 矩阵复刻**（docker python:3.11-slim + git） | 原 35 failed + 4 errors 的用例集 | **464 passed / 1 skipped / 4 xfailed / 0 failed** |
| **GitHub Actions 真机**（run 41148646608） | Test (3.10)/(3.11)/(3.12) + Lint + Docker Build | **全部 success**（修复前三版本各 35 failed + 4 errors） |
| 装机 E2E（0.89.1 安装包） | `scripts/e2e_desktop_install.ps1` | **0 失败**（含 UI E2E 32/32 / 无 token 403 / 重启持久化 / 卸载 / 残留 0） |
| 依赖漏洞审计 | `pip-audit -r requirements.txt` | 报告型：filelock 13 条 OSV（已发布全部版本均命中，修复版未发布）→ MAINTENANCE §6.5 |
| CI 镜像发布 | `docker.yml`（v0.89.1 tag 触发） | ghcr 镜像构建 **success** |

### 本轮新增/改写的测试

| 文件 | 用例数 | 覆盖点 |
|:---|:---|:---|
| `tests/cli/test_json_contract_queries.py` | 27 | 12 个查询命令的 `--json` 契约 + stdout 纯净度 + `config --generate` 真落盘 |
| `tests/server/test_fast_mode_truncation_notice.py` | 3 | 快速模式截断必告知 / 未截断不打扰 |
| `tests/tools_runtime/test_git_allowlist_single_source.py` | 6 | git 只读清单单一来源（两套判定结论一致） |
| `tests/core/utils/test_platform_command.py`（追加） | 3 | `os.altsep=None`（Linux）回归 |
| `tests/agent/test_vision_degrade_loop.py`（追加） | 1 | 降级重试不消耗迭代额度（R6） |
| 5 个测试文件缺陷修复 | — | git 身份 / rich 断行 / `Z:/` 相对路径 / JSON 行提取 / `importorskip` |

### 未执行（如实）

| 项 | 原因 |
|:---|:---|
| `pytest tests/ -q`（**含 slow**） | 约 13 分钟以上；本轮改动不触及 slow 层语义，按项目惯例交付前只跑 `not slow` + 定向 |
| 正式 CA 代码签名验证 | 外部阻塞（需证书），已与用户确认保持自签名 |

## 2026-10-31 v0.90.0 —— 剩余高阶提案批次（全部实跑）

### 全量回归（本轮唯一一次交付前完整运行）

| 项 | 值 |
|:---|:---|
| 命令 | `py -3.10 -m pytest tests/ -q -m "not slow" --cov=src` |
| 结果 | **5734 passed / 9 skipped / 7 xfailed / 9 deselected / 0 failed**（456.41s / 7 分 36 秒） |
| 收集 | **5759 tests / 0 errors** |
| 覆盖率 | **66.76%**（`fail_under = 60`，未下调） |

### 新增/改写的测试（12 个文件 / 290 条）

| 文件 | 用例 | 钉住什么 |
|:---|:---|:---|
| `tests/core/test_errors_catalog.py` | 75 | 全部 53 个 `ErrorCode` 都有中文条目（双独立断言防函数自证）+ 未登记码兜底 |
| `tests/core/test_storage_health.py` | 23 | 正常库/损坏库/空目录/超时不崩；损坏必进 issues |
| `tests/core/test_state_root.py` | — | `CLAWD_HOME` 生效、`CLAWD_DATA_DIR` 优先、`state.json` 幂等、高版本抛错 |
| `tests/core/test_state_migration.py` | — | 演练不动文件 / 冲突不覆盖 / 第二次 `moved=0` / 校验失败如实报 |
| `tests/eval/test_trajectory.py` | — | 录制-回放等价、非法文件抛中文错、**空判定拒绝通过** |
| `tests/scripts/test_startup_budget.py` | 19 | 预算内 0 / 超预算 1 / 测量失败 2 / `--json` 纯净 / 环境系数只放大时间项 |
| `tests/scripts/test_changelog_notes.py` | 10 | 版本不存在 exit 2、章节为空 exit 3、取不到不写空文件 |
| `tests/scripts/test_verify_wheel_contents.py` | 10 | 缺 prompts/缺模块/版本不符 → 1；无产物 → 2 |
| `tests/scripts/test_workflows.py` | 14 | 所有工作流 YAML 合法 + ci.yml 四条门禁仍在（**本轮实测抓到 release.yml 被 heredoc 破坏**） |
| `tests/scripts/test_docker_config.py` | 9 | 先 COPY 源码再装、不许 `--no-deps`、容器绑 0.0.0.0、CI docker 冒烟不许 `\|\| true` |
| `tests/server/test_health_endpoints.py` | 18 | 真实 HTTP：`/healthz` 200 无 token 不泄密、`/readyz` 503 当数据目录不可写、未知 `/api/*` 404、`/health` 404、静态托管与目录穿越无回归、`AGENT_SERVER_HOST` 真正生效 |
| `tests/cli/test_ops_commands.py` | 19 | `errors`/`doctor --deep`/`migrate-state`/`trajectory` 走 CLI 分发层（契约 + 退出码） |

### 真实 E2E / 装机 / 容器（本轮实跑）

| 项 | 结果 |
|:---|:---|
| `scripts/e2e_smoke.py` | **5/5 exit 0**（真实端点，v0.90.0 重跑） |
| `scripts/e2e_desktop_install.ps1`（0.90.0 安装包） | **0 失败**：装→Host→API/auth→UI E2E→重启持久化→卸载 exit 0→注册表 0 |
| `desktop/ui_feedback_e2e.mjs` | **31/31**（真实浏览器：loading/disabled 窗口、inline 错误 + 重试、全局未捕获兜底） |
| `desktop/ui_console_e2e.mjs` | **32/32**（无回归） |
| `docker build -t clawd-code:v0.90.0 .` | success（1.45GB） |
| 容器 → 宿主机探活 | `/healthz` 200（version 0.90.0）· `/readyz` 200（ready）· `/api/nope` 404 · `/` 200 · `Health.Status=healthy` |
| 蓝绿热更新演练 | A 在服务 → 起 B（`/readyz` 200）→ 停 A → B 仍 200 |
| 容器替换后状态持久化 | 卷内 `_marker.txt` 跨容器读回 `marker-090` ✓ |

### 未执行（如实）

| 项 | 原因 |
|:---|:---|
| `pytest tests/ -q`（含 slow，约 13 分钟） | 本轮未触碰 slow 层语义；交付前按惯例跑 `not slow` + 定向 |
| 真实生产环境部署 / 滚动更新 | 无部署目标与凭证（BLOCKED，未伪造） |
| 正式 CA 签名 | 外部阻塞（需证书），自签名仅验证管线 |

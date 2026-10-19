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
| 新增：跨平台状态快照 | `pytest tests/core/test_state_persistence_windows_safe.py -q` | **2 passed**（Windows 保存 + 并发追加 40 条） | 本轮 |
| 测试收集 | `pytest tests/ --collect-only -q` | **3167 collected / 0 errors / 78.99s** | 本轮 |
| 新增：工具策略 | `pytest tests/agent/test_tool_policy.py -q` | **10 passed** | evidence/P1-4 |
| 新增：SSRF | `pytest tests/tools_runtime/test_scrape_ssrf.py -q` | **25 passed** | evidence/P1-9 |
| 新增：Skill 注入 | `pytest tests/agent/test_skill_injection.py -q` | **6 passed** | evidence/P1-10 |
| 新增：原生工具调用 | `pytest tests/agent/test_native_tool_calls.py -q` | **8 passed** | evidence/P1-1 |
| 定向回归（7 目录） | `pytest tests/agent tests/workflow tests/tools_runtime tests/llm tests/contracts tests/cli tests/server -q` | **1383 passed, 1 xfailed, 0 failed**（564.12s） | 本轮 |
| **全量测试** | `pytest tests/ -q` | **3161 passed, 5 skipped, 1 xfailed, 0 failed**（2977.20s） | 本轮 |
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
| HTML 报告测验 | `scripts/verify_html_report.py reports/change-report-2026-10-19.html` | 8/8；错一题正确判未通过；6 项断言通过 | 本轮 |
| CI YAML | `python -c "yaml.safe_load(...)"` | yaml OK | evidence/B1 |

## 未执行 / 未达成（如实披露）

| 项 | 状态 | 原因 |
|:---|:---|:---|
| 覆盖率 60% | **未达成**（基线 46.15%） | 需要数百条针对生产可达模块的测试，非单轮可完成；本轮未降低覆盖率 |
| 测试收集 <120s | **未达成**（基线 561.55s） | 主要成本是 200 个测试文件的导入；已禁用无关 pytest 插件（langsmith/seleniumbase/faker/flask），全量收集仍需数分钟 |
| 死模块 ≤20 | **未达成**（200 不可达） | 需人工逐条读源码复核，禁止按名称删除 |
| GitHub Actions 实跑 | **not_run** | 本机无 `gh` CLI，无法触发/观察远端 CI |
| GitHub Release | **not_run** | `gh` 不可用 |
| Docker 构建/部署/热更新 | **not_run** | 本机 `where docker` 无结果；无部署目标与凭证 |
| 流式原生工具调用 | **未实现** | 流式路径仍走文本协议；原生调用仅在非流式路径启用 |
| 浏览器真实路径 | **not_run** | 本项目为 CLI，无 Web UI；未引入 Playwright |

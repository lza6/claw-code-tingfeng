# Tested Scope

> 只记录实际执行过的测试；未执行标 `not_run`。

## 已测试（2026-10-19，v0.60.2）

| 范围 | 命令 | 结果 |
|:---|:---|:---|
| 全量 | `pytest tests/ -q` | 3162 passed / 4 skipped / 1 xfailed / 0 failed |
| Agent + Workflow + Server | `pytest tests/agent tests/workflow tests/server -q` | 692 passed |
| 7 目录定向 | `pytest tests/agent tests/workflow tests/tools_runtime tests/llm tests/contracts tests/cli tests/server -q` | 1383 passed / 1 xfailed |
| 状态持久化 | `tests/workflow/test_state_persistence_semantics.py` | 14 passed（含生产函数并发） |
| 跨平台状态 | `tests/core/test_state_persistence_windows_safe.py` | 2 passed（Windows 保存 + 并发 40 条） |
| 收集 | `pytest tests/ --collect-only -q` | 3171 / 0 errors / 64.84s |
| 原生工具调用 | `tests/agent/test_native_tool_calls.py` | 9 passed |
| 工具策略 | `tests/agent/test_tool_policy.py` | 10 passed |
| SSRF | `tests/tools_runtime/test_scrape_ssrf.py` | 25 passed |
| Skill | `tests/agent/test_skill_injection.py` | 6 passed |
| Server | `tests/server` | 24 passed |
| 真实 E2E | `scripts/e2e_smoke.py` / `e2e_production.py` | 5/5 / 8/8 |
| 压测 | `scripts/stress_test.py --n 200` | 5/5 |

## 未测试
| 范围 | 原因 |
|:---|:---|
| GitHub Actions 远端 | 无 gh / 无法触发 |
| Docker 构建/部署 | 无 Docker |
| 浏览器/Web UI | 项目无 Web UI |
| 流式原生工具调用 | 未实现 |
| 跨进程锁竞争 | 未做（仅线程并发） |

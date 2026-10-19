# Verified Scope

> 最后更新：2026-10-19（v0.60.2）

| 项 | 命令 | 结果 |
|:---|:---|:---|
| 静态硬错误（src+tests） | `ruff check src/ tests/ --select F821,F811,E9` | All checks passed |
| 导入完整性 | `python scripts/import_sweep.py` | 642 模块 / IMPORT-FAIL 0 / DEP-MISSING 6 |
| 生产可达 | `python scripts/reachability.py` | 442（基线 431，未下降） |
| 全量测试 | `pytest tests/ -q` | 3161 passed / 5 skipped / 1 xfailed / 0 failed（v0.60.3；v0.60.4 定向 957 passed） |
| 测试收集 | `pytest tests/ --collect-only -q` | **3171 collected / 0 errors / 64.84s** |
| 状态持久化 | `pytest tests/core/test_state_persistence_windows_safe.py -q` | 2 passed（Windows 保存 + 并发 40 条） |
| 定向回归 | 7 目录 | 1383 passed / 1 xfailed |
| 契约 | `pytest tests/contracts -q` | 39 passed |
| 真实 E2E | `python scripts/e2e_smoke.py` | 5/5（退出码 0） |
| 生产路径 E2E | `python scripts/e2e_production.py` | 8/8 |
| 并发压测 | `python scripts/stress_test.py --n 200` | 5/5，~11 req/s |
| 版本一致性 | `python -m src --version` / metadata | 0.60.2 / 0.60.2 |
| Server 鉴权 | WebSocket 客户端握手 | 错误 token 拒绝、正确 token authenticated、port=0 随机 |
| 原生工具真实端点 | `provider.chat(tools=...)` | 返回 `BashTool` tool_calls |

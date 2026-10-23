# Verified Scope

> 最后更新：2026-10-23（v0.60.6，W0'/W1' 批次实测）
> 取数入口统一为 `py -3.10 scripts/baseline.py`（本机 `python` 命令不存在）。

| 项 | 命令 | 结果 |
|:---|:---|:---|
| 静态硬错误（src+tests） | `py -3.10 -m ruff check src/ tests/ --select F821,F811,E9` | ✅ All checks passed |
| Ruff 全量（仅记录，不作门禁） | `py -3.10 -m ruff check src/ --statistics` | 433 errors（W293 132 / F401 35 / E402 34 …） |
| 导入完整性（strict） | `venv/Scripts/python.exe scripts/import_sweep.py --strict-exit` | ✅ 642 模块 / OK 635 / **IMPORT-FAIL 0** / **IMPORT-EXIT 0** / DEP-MISSING 7 |
| 生产可达 | `py -3.10 scripts/reachability.py --min-reachable 443` | ✅ 443 可达 / 生产不加载 199 / 完全不可达 134（24,667 行）<br>（442 → 443 是入口种子口径修正：补入 `src.__main__`，非新增功能） |
| 测试收集 | `py -3.10 -m pytest tests/ --collect-only -q` | **3190 collected / 0 errors / 5.09s**（热缓存） |
| 版本一致性 | `py -3.10 scripts/baseline.py --quick` → version | cli / pyproject / dist-info 均 0.60.6，consistent=true |
| 静默吞异常（趋势） | `venv/Scripts/python.exe scripts/check_silent_except.py --fail-over 172` | 172（基线文件 `.clawd/baseline-silent.json`，只降不升） |
| 覆盖率 | `coverage.json` totals | 46.15%（25,877 / 56,072）；数据时间以 `baseline.py` 的 `file_mtime` 为准 |
| 状态持久化 | `pytest tests/core/test_state_persistence_windows_safe.py -q` | 2 passed（Windows 保存 + 并发 40 条） |
| 生产状态并发 | `pytest tests/core/test_run_state_concurrency.py -q` | 2 passed（4 线程不丢 + 40 行 JSONL 合法） |
| 契约 | `pytest tests/contracts -q` | 39 passed |
| 门禁脚本自测 | `pytest tests/scripts -q` | 34 passed（归因 + 口径 + 门禁行为 + baseline 解析） |
| 定向回归（4 目录） | `pytest tests/{scripts,core,contracts,cli} -q` | 953 passed / 0 failed / 33.12s |
| 真实 E2E | `scripts/e2e_smoke.py` | 见 `test_ledger.md` 2026-10-23 段（本轮已授权复跑） |
| 生产路径 E2E | `scripts/e2e_production.py` | 同上 |
| 并发压测 | `scripts/stress_test.py` | 同上（纯本地状态机，不调用真实模型） |
| Server 鉴权 | WebSocket 客户端握手 | 错误 token 拒绝、正确 token authenticated、port=0 随机（历史值，本轮未复跑） |
| 原生工具真实端点 | `provider.chat(tools=...)` | 返回 `BashTool` tool_calls（历史值，本轮未复跑） |

## 门禁脚本清单（2026-10-23 新增/加固）

| 脚本 | 门禁参数 | 已接入 CI |
|:---|:---|:---|
| `scripts/import_sweep.py` | `--strict-exit`（IMPORT-EXIT > 0 即失败） | ✅ |
| `scripts/reachability.py` | `--min-reachable 442` | ✅ |
| `scripts/check_silent_except.py` | `--fail-over 172` + `--write-baseline` | ✅ |
| `scripts/baseline.py` | 一条命令输出全部指标（`--quick` / `--with-tests`） | ⬜ 本地工具 |

## 不要相信的东西

- 任何**没有 `baseline.py` 时间戳**的覆盖率数字（`coverage.json` 可能停在数天前）。
- `README.md` / `CLAUDE.md` / `workflow_status.md` 里手写的数字——它们会漂移，以 `baseline.py` 为准。
- `.agent/memory/*` 里 2026-10-23 之前的条目。

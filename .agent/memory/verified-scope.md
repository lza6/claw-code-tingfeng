# 已验证范围（避免重复跑同一验证）

## 2026-10-27
| 验证项 | 命令 | 结果 | 时间戳 |
|--------|------|------|--------|
| 新增模块测试 116 个 | pytest tests/mcp/ tests/reasoning/ tests/security/ tests/reverse_tools/ tests/agent/test_engine_extended_tools.py tests/cli_handlers/test_reason_handler.py -q | 全绿 | 2026-10-27 |
| 契约测试 | pytest tests/contracts/ -q | 39 passed | 2026-10-27 |
| reason CLI 注册 | python -m src reason --help | 正常输出用法 | 2026-10-27 |
| ruff | ruff check src/ tests/ --select F821,F811,E9 | All passed | 2026-10-27 |
| 导入扫描 | python scripts/import_sweep.py | IMPORT-FAIL=0 | 2026-10-27 |
| 全量快检 | pytest tests/ -q -m "not slow" | 3632 passed / 17 存量失败（已定性） | 2026-10-27 |
| 基线对照 | git stash 后复跑失败用例 | 同样失败 → 存量确认 | 2026-10-27 |

## 2026-10-29 v0.74.0 复核（全部实测）

| 指标 | 实测值 | 命令 |
|:---|:---|:---|
| 版本一致性 | v0.74.0 三处一致（pyproject / CLI / 桌面 package.json） | `python -m src --version` |
| 模块/行数 | 624 模块 / 135,471 行 | `scripts/baseline.py` |
| 测试收集 | 4,964 / 0 errors | `pytest --collect-only` |
| 全量回归（not slow） | **4,936 passed / 0 failed** | `pytest -m "not slow"` |
| ruff 硬指标 | All passed（F821/F811/E9） | `ruff check src/ tests/ --select F821,F811,E9` |
| ruff 全量（src 口径） | **374**（自 410 降 36） | `ruff check src/` |
| 静默吞异常 | **162**（门禁 ≤172） | `scripts/check_silent_except.py --fail-over 172` |
| 导入扫描 | 624/624 OK，FAIL 0，DEP-MISSING 0 | `scripts/import_sweep.py --strict-exit` |
| 生产可达 | **478**（自 455 升 23），不可达 76 | `scripts/reachability.py` |
| 覆盖率（真实重算） | **62.39%**（35,802/57,380） | `pytest --cov=src` |
| 真实 E2E 冒烟 | 5/5 PASS，exit 0 | `scripts/e2e_smoke.py` |
| doctor | 0 FAIL | `python -m src doctor` |
| 压测 WS Host | QPS 1128 / P95 22.2ms / 错误率 0% | `scripts/stress_host.py --n 200` |
| Soak（300 轮后端进程） | PASS：RSS +1.0MB、残留子进程 0 | `scripts/soak_backend.py --iters 300` |
| 桌面端 E2E | 31 项全绿（ui_settings 17 / electron_bridge 10 / update_feed 4） | `desktop/*.mjs` |

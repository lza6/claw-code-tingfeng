# verification-matrix

## 适用场景
任何声称“完成/修复/可上线”之前。

## 分层矩阵

| 层 | 命令 | 适用 |
|:---|:---|:---|
| 静态硬错误 | `ruff check src/ tests/ --select F821,F811,E9` | 每次 |
| 导入完整性 | `python scripts/import_sweep.py` | 改导入/删模块 |
| 生产可达 | `python scripts/reachability.py` | 删代码/改入口 |
| 契约 | `pytest tests/contracts -q` | 改公共 API |
| 定向单测 | `pytest <相关目录> -q` | 每次改动 |
| 全量 | `pytest tests/ -q` | 发布前 |
| 真实 E2E | `python scripts/e2e_smoke.py` | 改 LLM/工具/配置 |
| 生产路径 E2E | `python scripts/e2e_production.py` | 改生产路径 |
| 并发压测 | `python scripts/stress_test.py --n 200` | 改并发/锁/审批 |
| 浏览器 | Playwright（本项目无 Web UI） | 前端任务 |

## 判定
- 退出码 0 且输出含期望摘要才算通过。
- `skipped` / `not_configured` / `xfail` 不得算通过。
- 未运行的项写 `not_run` 并说明原因。

## 证据
`evidence/<task>.json`：cmd、exit_code、raw_output_tail、files_changed、limitations。

## 常见坑
- 只跑 `src/` 的 lint，CI 跑 `src/ tests/`（本项目真实踩过）。
- 用 mock 结果描述为真实外部服务结果。
- 测试通过但生产入口不可达。

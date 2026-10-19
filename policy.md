# policy.md — 本轮执行策略（硬性数值）

> 本文件为本轮实施的门禁与授权边界。数值不可用"适当/尽量"替代。

## 1. 验证门禁

| 门禁 | 阈值 | 命令 |
|:---|:---|:---|
| 静态未定义名/重复定义 | `F821 = 0` · `F811 = 0` | `ruff check src/ --select F821,F811` |
| 导入完整性 | `IMPORT-FAIL = 0` | `python scripts/import_sweep.py` |
| 生产可达数 | 删除代码前后**不得下降** | `python scripts/reachability.py` |
| 契约测试 | 100% 通过 | `pytest tests/contracts -q` |
| 测试收集 | 0 errors | `pytest tests/ --collect-only -q` |
| 全量测试 | 0 failed | `pytest tests/ -q` |
| 覆盖率 | 本轮不降低（基线 46.15%）；目标 60% 为后续批次 | `coverage.json` totals |
| 真实 E2E | `e2e_smoke.py` 退出码 0 | `python scripts/e2e_smoke.py` |
| 生产路径 E2E | `e2e_production.py` 全通过（若存在） | `python scripts/e2e_production.py` |

## 2. 付费/外部 API

- 真实 LLM 端点位于 `.env`（自建/中转网关，OpenAI 兼容）。
- 本轮允许的**最小真实调用**：`e2e_smoke.py` 1 次、`e2e_production.py` 1 次；总计不超过 20 次模型请求。
- 禁止批量生成、压测打真实模型、循环重试刷 token。
- 任何新增付费服务调用默认禁止。

## 3. 任务分级

| 等级 | 定义 | 处理 |
|:---|:---|:---|
| L1 | 单文件、可逆、不改公共接口 | 直接实施 + 定向验证 |
| L2 | 多文件、有下游影响 | 拆批、记录前后行为、扩大回归 |
| L3 | 公共 API / 持久化 / 安全边界 | 特性开关 + 最小实验 + 回滚方案 |

## 4. 审查与证据

- 每个任务节点必须生成 `evidence/<task_id>.json`。
- 无真实命令输出，不得标记 `passed`。
- 未运行项写 `not_run` 并说明原因，不得留空或猜测。
- 独立审查最多 3 轮；未 Approve 必须记录未解决项。
- 节点状态只有：`TODO / DOING / REVIEW / DONE / BLOCKED`；`DONE` 必须有证据路径。

## 5. 版本控制与发布

- 允许：原子提交、推送 `main`、创建本地 tag。
- 禁止：force push、amend 已推送历史、删除测试/放宽断言。
- `gh` CLI 不可用 → GitHub Release 无法创建，标记 BLOCKED 并报告。
- Docker 不可用 → 生产部署/热更新无法执行，标记 BLOCKED 并报告；不得声称已部署。

## 6. 回滚

- 每个批次一个提交；回滚 = `git revert <sha>`。
- 数据库/schema 变更必须可逆；本轮如涉及 SQLite 迁移，先备份并保留旧表。

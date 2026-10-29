# ADR 0021 — `src/core/` 边界治理：分层方向 + 存量登记 + 规模告警

- 日期：2026-10-30
- 状态：已采纳
- 相关：审计 P3-1「src/core/ 作为杂物间（161 文件 / 34,923 行）的边界治理」

## 背景

`src/core/` 目前 **153 文件 / 34,112 行**，混居 config/auth/patch/persistence/events/hooks/journal/secrets 等。
彻底拆包是重构级工程（跨模块、高风险），但**不做任何约束**它会继续膨胀并反向依赖上层。

本轮实测到 **6 处向上层 import**（core → tools_runtime / workflow）：
`args_parser.py`、`config/generator.py`、`patch/atomic_patcher.py`（2 处）、`persistence/run_state.py`、`security/allowlist.py`。

## 决策

1. **分层方向硬约束**：`core` 必须是最底层，禁止 import `cli` / `tools_runtime` / `agent` / `server` / `workflow`。
2. **存量登记**：上述 6 处进 `scripts/core_surface_allow.json` 并注明"待迁移"；脚本只阻断**新增**越界，
   存量按清单逐步清零（不是永久豁免）。
3. **公开面登记**：`src/core/__init__.py` 的 `__all__`（当前 89 个符号）即对外承诺；新增对外符号需登记。
4. **规模告警**：文件 > 200 或行数 > 40,000 时提示"新能力请放专用子包"，不阻断。
5. 门禁：`scripts/core_surface.py`（越界即退出 1），已接入 `scripts/verify_audit_p1.py`。

## 代价

- 迁移存量 6 处需要动 `patch` / `config` / `security` 这几个热路径，本轮**没做**（高风险、收益慢）。
- 允许清单可能变成"垃圾桶"，所以每条都写了 reason 与迁移方向。

## 何时重新考虑

- 当 core 文件数继续增长到 > 200，或再出现 3 处以上新越界时，应启动真正的拆包（core/config、core/patch、
  core/persistence 各自独立子包，共享的只有 protocols 与 exceptions）。

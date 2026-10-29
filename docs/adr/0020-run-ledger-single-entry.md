# ADR 0020 — 运行账本：语义分家、入口归一（mode_state + ralph_ledger）

- 日期：2026-10-30
- 状态：已采纳
- 相关：审计 2.4 风险表「两套账本（mode_state / ralph_ledger）语义重叠」

## 背景（实测）

- `src/workflow/mode_state.py`（889 行）：记"当前处于哪个模式/阶段"，落盘 `.clawd/state/mode-*.json`；
- `src/workflow/ralph_ledger.py`（451 行）：记"一步步做了什么"，落盘 `.clawd/ralph/*.json`；
- 两者都回答"长任务跑到哪了"，但**格式、位置、写入时机都不同**，中断恢复时可能各说一套。

本轮跑 `clawd ledger` 在本仓库立刻抓到真实案例：`.clawd/state/mode-autopilot.json` 有模式状态，
但 ralph 进度为空 —— **只写了一本账**。

## 决策

1. **不合并存储**：`mode_state` = 状态真相（phase），`ralph_ledger` = 进度真相（entries）。职责不同，硬合并会丢语义。
2. **读只走 `RunLedger.snapshot()`**（`src/workflow/run_ledger.py`）：合并视图 + 一致性检查（只写一半 / 孤儿进度 / 时间漂移 > 60min）。
3. **写只走 `RunLedger.record_stage(mode, phase, note, task)`**：一次写两处；只成功一处返回 False 并告警，避免"以为记上了"。
4. **直接调用底层 manager 的新代码视为绕过账本**，评审要求改回本模块。
5. 命令行：`clawd ledger [--json]`，不一致时退出码 1（可挂 CI）。

## 代价

- 多一层门面（~200 行）：写入要串行两次 IO（都很小，实测毫秒级）。
- 存量数据可能已不一致（本仓库就有一条），`clawd ledger` 会明确列出，需要人工清理或忽略。

## 何时重新考虑

若未来引入真正的 run 目录（`.clawd/runs/<run_id>/`）作为唯一真相源，则应让两个账本都变成它的投影，
届时 `RunLedger` 退化为读投影；在那之前不要各自再加一套"进度"字段。

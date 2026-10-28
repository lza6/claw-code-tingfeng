# ADR-0011：领域能力"内置优先"，MCP 仅作跨引擎桥（含大仓库保护）

- **状态**：已接受（2026-10-28）
- **推翻了什么**：ADR-0010 把领域能力主要做成 MCP 工具，等于让**我们自己的 agent 也绕一层进程 + JSON 序列化**。
- **影响面**：`src/tools_runtime/domain_tools.py`（新）、`src/brain/warmup.py`（新）、
  `src/agent/engine.py`（装配）、`src/rag/code_graph.py`（并发降级修复）

## 问题

上一版把 `clawd_read_file` / `clawd_grep` / `clawd_project_map` / `clawd_world_model_*` 主要实现成 MCP 工具。
对**外部引擎**（Codex/OpenCode 在别的进程）这是唯一可行方式；但对我们**自己的 agent**，
这意味着一路多余开销：起子进程 → 每次调用 JSON 序列化 → 无法共享进程内缓存 → 超时要单独设。

更糟的是世界模型索引：为了一次 MCP 调用去全量索引仓库，结果"要么挂死、要么超时"。

## 决策

**分层，不是统一走 MCP：**

| 调用方 | 走哪条路 | 理由 |
|:---|:---|:---|
| 我们自己的 agent | **原生工具**（`src/tools_runtime/domain_tools.py`） | 零进程、零序列化、可共享进程内缓存 |
| 外部引擎（Codex/OpenCode/…） | MCP（`src/mcp/domain_server.py`） | 跨进程只能靠协议 |

**索引自动触发，不靠人记得：**
- 引擎装配工具时调用 `warmup.ensure_warm(workdir)` —— **非阻塞**（实测启动开销 0.00s）
- 索引完成后工具秒级返回；未就绪时**如实返回状态**，绝不挂起

## 大仓库保护（实测驱动）

实测本仓库（600+ 模块）：**全量索引 >4 分钟仍未完成**。后台白烧几分钟 CPU 不值得。

因此默认策略：
- 源文件数 > `DEFAULT_MAX_FILES`（300）→ **跳过自动索引**，state=`skipped_large`，附原因与替代方案
- 覆盖方式：`CLAWD_WM_FORCE=1`（强制）或 `CLAWD_WM_MAX_FILES=<更大值>`
- 轻量替代（始终可用）：`ProjectMapTool`（符号地图）、原生 grep、`/api/info`

实测（真实仓库）：`ensure_warm` 1.69s → `skipped_large`；`stats` 0.00s 返回原因；`project_map` 4.73s 给出 30 文件图谱。

## 顺带修掉的真实 bug：多进程在非主线程必失败

`src/rag/code_graph.py` 用 `ProcessPoolExecutor` 并行解析。而**预热跑在后台线程**，
Windows(spawn) 下直接报：

```
An attempt has been made to start a new process before the current process
has finished its bootstrapping phase.
```

后果：**世界模型永远卡在 indexing 永不完成**（这正是之前"预热没效果"的真因）。
修复：`_parse_batch()` 三档降级 —— 非主线程直接线程池 / 进程池异常回退线程池 / 再退回串行，
每一步都有日志，不静默。

## 验证

- `tests/tools_runtime/test_domain_tools.py` → **25 passed**
  （含：预热就绪/幂等/非阻塞返回、工具 stats·context·predict、路径穿越拒绝、
  大仓库跳过、force 覆盖、引擎装配后工具在池中）
- 真实仓库：启动 1.69s 不阻塞、`stats` 0.00s 诚实报因、`project_map` 4.73s 可用

## 边界

- 世界模型在**大仓库**上默认不可用（这是设计取舍，不是 bug）：需要时手动 `CLAWD_WM_FORCE=1`，
  且要接受数分钟索引时间
- `skipped_large` 是终态，不会自动重试；同一进程内改变 `CLAWD_WM_FORCE` 需新进程

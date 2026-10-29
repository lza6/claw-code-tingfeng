---
name: trace
description: Show agent flow trace timeline and summary
---

# Agent Flow Trace

[TRACE MODE ACTIVATED]

## Objective

Display the flow trace showing how hooks, keywords, skills, agents, and tools interacted during this session.

## Instructions

> 工具名以真实注册为准（`src/core/mcp/trace_server.py` 的 `TRACE_SERVER_TOOLS`）。
> 早期文档写的 `trace_timeline` / `trace_summary` 在全仓**没有任何实现**，
> 照着调只会得到「未知工具」。下面是现在真实可用的四个工具。

1. **`get_recent_traces`** —— 列出最近的追踪（先看有哪些 trace_id）
   - 参数：`limit`（默认 10）

2. **`get_trace`** —— 取某条追踪的完整 span 列表（时间顺序）
   - 参数：`trace_id`

3. **`summarize_trace`** —— 聚合统计（span 数、最慢 span、错误数）
   - 参数：`trace_id`

4. **`export_trace`** —— 导出为 json / text，便于贴到报告里
   - 参数：`trace_id`、`format`（默认 json）

采集侧：Agent 引擎在 `SESSION_START` / `SESSION_END` / `PRE_TOOL_USE` /
`POST_TOOL_USE` / `TOOL_ERROR` 五个 hook 点已接线，把 hook 里记录的事件
写进追踪即可得到完整时间线；`export_trace` 的输出就是"发生了什么"的可核对版本。

## Output Format

Present the timeline first, then the summary. Highlight:
- **Mode transitions** (how execution modes changed)
- **Bottlenecks** (slow tools or agents)
- **Flow patterns** (keyword -> skill -> agent chains)

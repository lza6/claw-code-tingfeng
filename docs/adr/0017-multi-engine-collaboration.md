# ADR-0017：多引擎协同（plan → execute → review → 返工）+ 两处误判更正

- **状态**：已接受（2026-10-29）
- **推翻了什么**：ADR-0010/0012 里我写的两条"未闭环"，经实测是**我自己测错了**

## 一、两处更正（重要：之前是我判错，不是做不到）

### 更正 1：Codex 的多轮 MCP 工具循环一直能跑通
之前我写"受网关限制：`previous_response_id ... only supported on Responses WebSocket v2`"。
实测结论：**只是慢，不是坏**。用 `--dangerously-bypass-approvals-and-sandbox` 并把超时放到 900s：

```
EXIT: 0 | mcp_calls: 2
  call: clawd_tool_list  status: completed
  result: {"content":[{"type":"text","text":"- ASTGrepTool: ..."}]}
TEXT: 19        ← 正确回答了"我们有多少个工具"
```

CLI 全链路也验证通过：
```
clawd codex --with-clawd-tools --bypass-approvals "用 clawd_grep 搜索 'clawd-domain'"
→ 返回 tests/mcp/test_domain_server.py、src/mcp/domain_server.py（结果正确）
```
根因：本地网关每轮 ~3 分钟（27k+ prompt tokens），我之前给 500s 超时等于没等够。

### 更正 2：OpenCode 不需要我"配凭据"，需要**注册模型**
之前我写"凭据未配置"。真实报错是：
`ProviderModelNotFoundError: Model not found: openai/step-5-preview`
修法是在 `opencode.json` 里注册自定义模型（**baseURL 用 `{env:OPENAI_BASE_URL}`，不落密钥**）：
```json
"provider": {"openai": {"options": {"baseURL": "{env:OPENAI_BASE_URL}"},
                        "models": {"step-5-preview": {"name": "step-5-preview"}}}}
```
实测：`opencode run -m openai/step-5-preview "只回复 PONG"` → 返回 `PONG`（25,853 in / 37 out）。

## 二、协同模型（用户要的"多个智能体合成一个"）

`src/workflow/collaborate.py` + `clawd collaborate`：

```
规划(planner) → 执行(executor) → 独立审查(reviewer) → 不合格则返工 → 再审查
```

| 设计点 | 做法 | 为什么 |
|:---|:---|:---|
| 引擎可混搭 | `--planner codex --executor native --reviewer opencode` | 支持任意外部引擎与内置引擎组合 |
| 默认全用内置 | 新增 `src/backends/native.py`（把我们的 AgentEngine 接进统一驱动层） | 不装外部 CLI 也能跑；内置引擎含 19 工具/LSP/世界模型 |
| 判定必须确定性 | 审查者必须输出 `VERDICT: APPROVE` 或 `VERDICT: NEEDS_FIX`，正则解析 | 不依赖模型"语气"；**两种都写时以 NEEDS_FIX 为准**，绝不误放行 |
| 无标记 = 不通过 | 解析不到标记 → `UNKNOWN`，按未通过处理 | 宁可多返工一次，也不"看起来过了就放行" |
| 返工有上限 | `--rounds`（默认 1），防止两引擎互相挑刺无限循环 | 已测：`max_repair_rounds=2` 时确实只跑 2 轮 |
| 阶段失败不炸流水线 | 每阶段 try/except → 记入 `PhaseRecord.error` | 规划失败直接中止并说明（不空烧执行阶段） |

协同的价值：**换一个引擎来审**，能抓住"自己审自己"放过的问题——本项目历史上多次出现
"本机模型自称完成、独立审查发现是假闭环"。

## 三、验证

- `tests/workflow/test_collaborate.py` **13 passed**（注入假后端，确定性）：
  结论解析（APPROVE / NEEDS_FIX+编号问题 / 两种都写判不通过 / 无标记判 UNKNOWN）、
  三阶段顺序、计划与结果正确传递、返工回灌审查意见、返工轮数上限、
  规划失败提前中止（执行阶段不被调用）、引擎异常被记录不抛出、CLI 选项暴露
- 真实 E2E（`clawd collaborate "写 demo_collab.txt" --rounds 0`）：见 CHANGELOG 结论
- `clawd codex --with-clawd-tools` 真实链路：Codex 调用我们的 `clawd_grep` 并返回正确文件

## 四、边界

- 协同是**串行**的（规划完才执行），不是并行多智能体辩论；并行版需要共享状态与仲裁策略
- 每阶段都会重新起一次引擎/agent（无跨阶段记忆，只靠 prompt 传计划与结果）
- 真实 E2E 单阶段约 2-3 分钟（网关吞吐），三阶段 + 返工会很长；建议配 `--timeout` 与 `--rounds`
- "审查者"仍是被提示词约束的同一个模型族，不是形式化验证；不替代测试与人工验收

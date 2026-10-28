# ADR-0010：多引擎整合 —— 统一驱动 + MCP 领域工具反向供给

- **状态**：已接受（2026-10-28）
- **前置**：ADR-0009（采用 Codex 作为外部内核后端）
- **影响面**：`src/backends/`（base/registry/drivers）、`src/mcp/domain_server.py`、CLI `clawd engines`

## 背景与纠正

"把 Codex、Grok、OpenCode、OpenClaw、Hermes、Pi 六个开源项目合并成一个智能体"这个想法需要先纠正事实
（2026-10-28 对 `D:\参考项目` 与 npm 注册表的实测）：

| 名称 | 真实性质 | 语言 | 本机状态 |
|:---|:---|:---|:---|
| **Codex** | Agent CLI（Rust 内核 21.5k 行 + TS 启动器），Apache-2.0 | Rust | ✅ codex-cli 0.165.0 可用 |
| **OpenCode** | Agent CLI，支持 `run --format json` / `serve` / `acp` | Go | ✅ 1.19.5 可用（协议跑通，凭据需自行登录） |
| **OpenClaw** | Agent CLI | TS | ⚠️ 对 Node 版本要求严格（22.22 / 24.15 / 25.9），本机 25.8.1 → 拒跑 |
| **Grok**（grok-cli） | **不是引擎**：anthropic-proxy，把 Claude Code 的请求路由到 Grok 模型 | TS | 属 **provider 层** |
| **Pi**（pi-agenticoding） | **不是引擎**：`pi-package`，提供 spawn/notebook/handoff 上下文原语 | TS | 属 **能力层** |
| **Hermes** | 参考库中**空目录**，无源码 | — | 无法评估 |

**结论：六个项目不可能"合并源码"**——Rust/Go/TS 三套运行时、互不兼容的协议与依赖，合并必然崩。

## 决策

采用**三层整合**，而不是代码合并：

### 1. 引擎层：统一驱动 + 注册表（`src/backends/`）
- `base.py`：`CliBackend`（子进程 + JSONL 归一化 + 超时 + **进程树强杀**）+ `EngineProbe`（真实探活）
- `registry.py`：`ENGINES`（codex/opencode/openclaw）+ `NON_ENGINES`（grok/pi/hermes，明确不当引擎驱动）
- 新增引擎只需一份 `CliEngineProfile`（argv 模板 + 事件字段映射），不复制驱动逻辑
- `clawd engines`：列出真实探活状态（ready / incompatible / not_installed / error）

### 2. 模型层：provider 而非引擎
Grok 这类"模型代理"不进引擎注册表，只作为模型来源接在 provider 配置里。

### 3. 领域层：MCP 反向供给（关键）
`src/mcp/domain_server.py` 把**我们自己的领域能力**暴露成标准 MCP server，任何引擎都能挂上：

| 工具 | 作用 |
|:---|:---|
| `clawd_read_file` | 项目内只读文件（路径穿越防护 + 大小上限） |
| `clawd_grep` | 文本/正则搜索（优先 ripgrep，回退纯 Python） |
| `clawd_project_map` | 代码库符号地图（复用 `src/rag/repo_map.py`） |
| `clawd_tool_list` | 列出本项目注册的领域工具 |

Codex 侧注入方式（适配层已支持）：
```python
CodexBackend(mcp_servers={"clawd": {"command": python, "args": ["-m","src.mcp.domain_server","--root","."]}})
# → -c mcp_servers.clawd.command=... -c mcp_servers.clawd.args=...
```

**这才是"在现成内核上做领域魔改"**：内核是别人的（稳、可升级），领域能力是我们的（工具/世界模型/项目认知）。

## 实测中挡掉的真 bug（都已修）

1. **MCP stdio 在 Windows 上必须显式 UTF-8**：中文被 GBK 编码写出 → 客户端按 UTF-8 解码失败 →
   读任务死掉 → 所有请求超时。修复：`io.TextIOWrapper(..., encoding="utf-8", newline=chr(10))`。
   （这个 bug 只有"真实客户端往返"才能发现，进程内单测发现不了。）
2. **`for line in stdin` 会预读缓冲**导致交互式协议死锁 → 改 `readline()` 逐行。
3. **通知（无 id）不得产生响应**：否则客户端视为协议违规。
4. **JSON 里的 error 事件必须计入 `errors`**：否则引擎失败会被当成"无输出成功"（静默失败）。

## 验证（真实执行）

- `pytest tests/backends tests/mcp` → **93 passed**（含假进程注入、真实 MCP 客户端子进程往返）
- `clawd engines` 真实探活：codex `ready` / opencode `ready` / openclaw `incompatible`
- **Codex 确实发现了我们的 MCP 工具并发起调用**（事件证据）：
  ```
  mcp_tool_call | {"server":"clawd","tool":"clawd_grep","arguments":{"pattern":"clawd-domain"}}
  mcp_tool_call | {"server":"clawd","tool":"clawd_tool_list","arguments":{}}
  ```
  但最终返回 `MCP tool call requires approval, but approval policy is never`
  → 需审批策略配合；用 `--dangerously-bypass-approvals-and-sandbox` 绕过时，
  又撞上网关的 Responses 续传限制（见下）。

## 未闭环（如实披露）

1. **Codex 内完整多轮 MCP 工具循环未跑通**：我们的兼容网关报
   `function_call_output requires call_id on HTTP requests; continuation via previous_response_id
   is only supported on Responses WebSocket v2`
   → 需要支持 Responses 续传的端点（或 WebSocket v2），这是**网关能力问题，不是适配层问题**。
2. **OpenClaw 无法在本机运行**：Node 25.8.1 不在其支持区间；换 Node 会影响现有 Electron 构建，
   未擅自切换。
3. **OpenCode 凭据未配置**：协议已跑通（能返回 `sessionID` 与 JSON 事件），但需 `opencode auth` 登录后用真实模型验证。
4. **Hermes 无处获取源码**（参考库空目录），未集成。
5. World Model（`src/brain/`）尚未暴露为 MCP 工具（当前只暴露项目图谱/grep/读文件）。

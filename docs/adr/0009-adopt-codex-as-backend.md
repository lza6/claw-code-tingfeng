# ADR-0009：采用 OpenAI Codex 作为外部 agent 内核后端（不重复造轮子）

- **状态**：已接受（2026-10-28）
- **决策者**：项目所有者（明确选择"搬 Codex"路线）+ 主控代理
- **影响面**：新增 `src/backends/`、`clawd codex` CLI、新增运行时依赖（可选）

## 背景

项目已有 13 万行 Python：agent engine、工具运行时、5 阶段工作流、记忆、World Model、
MCP 桥接、桌面端、评测 harness。但从零自研"长程稳定 + 可排障"的 agent 内核成本很高：
循环健壮性、工具沙箱、审批策略、会话续跑、上下文压缩这些"跑久了才暴露"的部分，
成熟项目已经踩完坑。

`D:\参考项目` 中有 1678 个开源项目，实测评估候选：

| 候选 | 语言 | 规模 | 许可 | 结论 |
|---|---|---|---|---|
| **OpenAI Codex**（`codex-main`） | **Rust 内核**（`codex-rs` 21.5k 行）+ TS 启动器 | 源码 32MB | **Apache-2.0** | **采用** |
| LongHorizon-Harness | Python | ~20k | MIT | 备选（循环层可借鉴） |
| SWE-agent | Python | 15k | MIT | 备选（与我们工具层重叠） |
| PI agent desktop / DSH 系列 | TS | 9-41k | MIT | 不采用（与桌面层重叠） |

## 决策

**采用 Codex 作为"外部 agent 内核后端"，通过协议适配接入，不 fork 其循环。**

- 我们负责：参数/配置映射、JSONL 事件归一化、进程超时与进程树回收、用量统计、CLI 暴露
- Codex 负责：agent 循环、工具执行、沙箱（`read-only` / `workspace-write` / `danger-full-access`）、会话续跑（`thread_id`）
- **不做**：把 105k 行 TS/Rust 搬进主仓、双运行时、改 Codex 源码

理由：
1. 同语言不是前提——它本来就是独立进程，进程边界天然隔离，故障不传染宿主
2. 升级 Codex 不需要改我们的代码（除非 JSONL schema 变化，只需改 `parse_events`）
3. 出问题可定位：事件流原样保留在 `CodexRunResult.events`，可回放

## 落地实现

- `src/backends/codex.py`：`CodexBackend`（`build_argv` / `run` / `version` / `_kill_tree`）、`parse_events`
- CLI：`clawd codex "<任务>" [--cd] [--model] [--provider] [--base-url] [--sandbox] [--timeout] [--json]`
- 测试：`tests/backends/test_codex_backend.py`（19 项，假进程注入 JSONL，零网络）

## 实测中发现的真实约束（都已在适配层处理）

1. **Codex 禁止覆盖内置 provider**：
   `Error loading config.toml: model_providers contains reserved built-in provider IDs: openai`
   → 适配层把自定义端点注册成 `<provider>-custom`（如 `openai-custom`）
2. **Codex 0.165 已废弃 `wire_api="chat"`**，只支持 `responses`
   → 默认 `wire_api="responses"`；**因此端点必须支持 Responses API**（我们现有网关支持）
3. **Windows 下 npm 全局装的是 `codex.cmd`** → `_resolve_binary` 依次尝试 `codex` / `.cmd` / `.exe` / `.bat`
4. **codex 会拉起子进程** → 超时必须 `taskkill /T /F` 杀进程树，否则残留进程会累积（内存/句柄泄漏源）

## 许可证与合规

- Codex 为 **Apache-2.0**：允许商用与修改，需保留版权与 NOTICE
- 我们**不复制其源码到本仓**，因此不产生衍生作品义务；仅在 `docs/adr/` 记录依赖关系与版本
- 安装方式：`npm i -g @openai/codex`（官方发行包），版本记录见下方

## 已验证（2026-10-28 真实 E2E，非桩）

```
$ clawd codex "只回复 PONG" --cd .clawd/codex_e2e
codex: codex-cli 0.165.0 · sandbox=workspace-write
PONG
tokens: {'input_tokens': 27189, ..., 'output_tokens': 86}

$ clawd codex "读取 readme.txt，然后只回复文件里的那个单词"
probe
(执行了 1 条命令)
tokens: {'input_tokens': 38429, 'cached_input_tokens': 17408, ..., 'output_tokens': 135}
```

## 未闭环 / 边界

- 未验证长程（>1h）连续运行的稳定性——需 soak 测试单独立项；
  已提供 `scripts/soak_backend.py` 做进程级 RSS/句柄/线程增长检测
- 未验证 Codex 的 `--sandbox danger-full-access` 在 Windows 上的实际隔离强度
- 未做 Codex 与本项目工具池的互通（Codex 用自己的工具，不用我们的 ToolRegistry）——
  若需要互通，得走 MCP：把我们的工具暴露成 MCP server 让 Codex 调（下阶段）

# ADR-0012：定向汲优补缺 —— LSP / 检查点压缩 / 笔记本（含两级删除）

- **状态**：已接受（2026-10-29）
- **来源**：直接读源码提取，不依赖代理转述
  - OpenCode `internal/lsp/`（Go, MIT）
  - Codex `codex-rs/core/src/compact.rs` + `templates/compact/{prompt,summary_prefix}.md`（Rust, Apache-2.0）
  - Pi `pi-agenticoding/{handoff/eligibility.ts, notebook/}`（TS, MIT）

## 一、LSP 集成（补"代码理解靠 AST 猜"）

**从 OpenCode 提取的机制**：stdio + `Content-Length` 分帧的 JSON-RPC；请求 id → 响应分发；
`publishDiagnostics` 是**通知**（无 id）需单独收集；语言→服务器命令映射。

**我们的实现** `src/lsp/client.py` + `src/tools_runtime/lsp_tool.py`：
- 三件事：`diagnostics` / `definition` / `hover`
- 行号：**对外 1-based（人与模型习惯），内部转 0-based（LSP 约定）**
- 客户端按 (root, language) **复用**（LSP 启动要几秒，反复起会拖死体验）
- 缺失服务器时明确报 `exit_code=2` + 安装提示，不静默降级

**踩到的坑（只有真实服务器才暴露）**：
1. **必须走二进制流**：文本流会做换行转换并按本地编码写入 → `Content-Length` 与实际字节数不符
2. **`shutil.which` 找不到 venv 里的服务器**：改查"PATH + 当前解释器同目录"
3. **pylsp 依赖 `pyflakes`/`jedi`**：缺了不报错、只是**一条诊断都不给**（表现为"LSP 没反应"）

**真实 E2E（pylsp 0.165 环境实测）**：`undefined_name` 被检出（1-based 第 5 行）、
`definition` 命中 `mod.py`、`hover` 返回 `helper(x: int) -> int`。

## 二、上下文检查点压缩（补"压缩策略粗糙"）

**原实现的问题**：`HistoryProcessor` 超预算就**丢弃旧条目**并放一句"已省略 N 条"——信息全丢，
模型只能重读文件。

**从 Codex 提取的机制**：
- 触发：累计 usage tokens ≥ `auto_compact_token_limit`
- 方式：产出**结构化 handoff 摘要**（进展与决策 / 上下文与约束 / 待办 / 关键数据）
- `summary_prefix` 告诉后续模型"这是继承来的，接着干别重复"
- 摘要本身有 token 上限

**我们的实现** `src/agent/compaction.py`：
- `COMPACTION_PROMPT` / `SUMMARY_PREFIX` 与 Codex 语义对齐
- `build_checkpoint()`：**默认不依赖 LLM**（确定性抽取目标/决策/文件/工具/错误/待办），
  传入 summarizer 时才用模型；**LLM 失败自动降级**，绝不因摘要失败丢上下文
- 摘要超限截断（`MAX_SUMMARY_TOKENS`）
- 接入 `HistoryProcessor.process()`：丢弃区段 → 结构化检查点，且检查点本身 **pinned**（否则下一轮又被压）

## 三、笔记本 + 两级删除（补"长会话只有上下文窗口"）

**从 Pi 提取的两个洞见**：
1. **handoff 有最小有用阈值**（`MIN_HANDOFF_TOKENS = 30_000`）——上下文太小时压缩是净损失
2. **两级式删除**（`prepareNotebookDiscard` → `commitNotebookDiscard`）——压缩成功后才真删

**我们的实现**：
- `src/memory/notebook.py`：页面（topic→slug）、`active_topic` + **boundary hint**、
  `prepare_discard`（只算计划+留快照）/ `commit_discard` / `abort_discard`
- `src/tools_runtime/notebook_tool.py`：`save|read|list|set_topic|prepare_discard|commit_discard|abort_discard`
- `src/agent/compaction.py` 增加 `MIN_COMPACT_TOKENS`、`estimate_context_tokens`、
  `is_compaction_eligible`、`format_context_usage`（usage 未知时如实说"未知"，不猜）

## 落地形态：全部是**内置原生工具**，不是 MCP

| 能力 | 工具 | 类别 | 风险 |
|:---|:---|:---|:---|
| 代码智能 | `LSPTool` | SEARCH | read |
| 项目认知 | `WorldModelTool` / `ProjectMapTool` | KNOWLEDGE_GRAPH / SEARCH | read |
| 长会话记忆 | `NotebookTool` | MEMORY | **write（需审批）** |

引擎 `_load_extended_tools()` 自动装配，无需用户配置。

## 验证

| 套件 | 结果 |
|:---|:---|
| `tests/tools_runtime/test_lsp_tool.py` | **20 passed**（含真实 pylsp E2E + 假服务器分帧单测） |
| `tests/agent/test_compaction.py` | **16 passed** |
| `tests/memory/test_notebook.py` | **26 passed**（含 Pi 准入阈值、两级删除安全模型） |
| 全量回归 | 见 CHANGELOG（v0.65.0 条目） |

## 边界（如实披露）

- LSP 只覆盖 `.py/.go/.ts/.tsx/.js/.jsx/.rs`；未装服务器时该工具报"未安装"而非降级猜测
- 压缩的确定性摘要**不如 LLM 摘要自然**，只保事实骨架；接 LLM 时才有自然语言段落
- 笔记本删除**不可撤销**（commit 后文件即删）；风险靠"两级 + 快照"控制，快照只在内存
- 未做：Codex 的 `run_inline_remote_auto_compact_task`（远端压缩端点）——我们网关不支持

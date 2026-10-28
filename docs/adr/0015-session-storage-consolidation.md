# ADR-0015：会话存储收敛 —— 两套并存 + 无人写盘的连环缺陷

- **状态**：已接受（2026-10-29）
- **关联**：ADR-0014（会话分叉元数据）

## 发现的三个叠加缺陷

审查"`clawd session` 为什么看不到任何会话"时，发现的不是单个 bug，而是三层叠加：

### 1. 两套会话存储并存，schema 不兼容，且写同一目录

| 实现 | 消息格式 | 额外字段 |
|:---|:---|:---|
| `src/memory/session_manager.py`（**引擎侧**） | `messages: [{role, content, timestamp, metadata}]` | `status` / `user_id` / `created_at` / `updated_at` |
| `src/core/session_store.py`（**早期**） | `messages: ["u", "a"]` 字符串元组 | `input_tokens` / `output_tokens` / `total_cost` / `turn_count` |

两者都写 `.clawd/sessions/<id>.json`。只读其中一套的代码，看另一套写的数据就是**空白或错乱**
（读字符串元组的实现拿到 dict 会当字符串用；反之 role 丢失）。

### 2. 两套都**没人真正写盘**

实测 `.clawd/sessions/` 为空：引擎调用的是 `record_user_goal` / `save_checkpoint`，
`SessionManager.save_session()` 没有任何调用方；`core.session_store.save_session()`
在 `src/` 里也无生产调用者。**"实现了但没人用"**——最容易被误判为"已完成"的形态。

### 3. CLI 完全没有入口

即便数据存在，用户也没有命令能看到/分叉/命名。

## 决策

**不删任何一套**（都可能有外部依赖与历史数据），而是加一层**格式自适应的桥**：

- `src/core/session_bridge.py`
  - `list_all / load / save / fork / set_title / chain`
  - **按文件内容自动识别格式**（`messages[0]` 是 dict → engine 格式；否则 legacy）
  - **写盘统一用引擎格式**（与 Agent 运行时同源），旧文件只读不改写（避免误伤历史）
- **引擎侧补上落盘**：`AgentEngine.run()/run_stream()` 完成后 `_persist_session()`，
  写 `.clawd/sessions/sess-<时间戳>.json`（goal / steps / final_result / tokens）
- **CLI 入口**：`clawd session list|show|fork|title`

## 为什么选"桥"而不是"统一重写"

- 重写会把两套的历史数据迁移风险转嫁给用户；桥是**只读兼容 + 单写格式**，最小风险
- 未来若要彻底收敛，只需把 `core.session_store` 标为 deprecated 并迁移，不动运行时

## 验证

- `tests/cli/test_session_commands.py` **13 passed**，其中 4 个就是针对本缺陷的回归：
  1. 引擎落盘后 CLI 能看见（此前永远"暂无"）
  2. 桥接能读 **engine** 格式
  3. 桥接能读 **legacy** 格式
  4. 从 legacy 分叉 → 写出 engine 格式，且**父文件未被改写**
- `tests/core/test_session_fork.py` **11 passed**
- 真实 CLI 实跑：`list` → `fork` → `show`（链 `["demo2","demo1"]`）

## 边界

- `clawd chat --resume <id>` 仍未打通：消息现在带 role 了，但 REPL 要把历史回灌进
  agent 循环（`_run_agent_core` 目前固定 `messages=[]`）。这是**下一步**，不做假装完成
- 会话标题目前取 goal 前 60 字，未做智能命名
- 旧的 `core.session_store` 保留原地（含 v0.67.0 新增的 `parent_session_id/title/summary_message_id`），
  但已明确：**引擎与 CLI 都以 bridge 为准**

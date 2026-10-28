# ADR-0014：命令执行策略（execpolicy）+ 会话分叉元数据

- **状态**：已接受（2026-10-29）
- **来源**（直接读源码）：
  - Codex `codex-rs/execpolicy/src/decision.rs` + `core/src/exec_policy.rs`（Rust, Apache-2.0）
  - OpenCode `internal/session/session.go`（Go, MIT）
  - Pi `os-sandbox.ts` 的 `quoteShellArgument` —— **本项目已有等价实现**
    （`src/utils/string_utils.py: quote_shell_arg` / `quote_powershell_arg`），未重复造

## 一、命令执行策略（Codex execpolicy）

### 为什么需要

ADR-0013 的权限引擎只能按「read / write / exec」分类，表达不了
「`git status` 放行、`git push --force` 禁止、`rm -rf` 一律禁」这种**命令级**策略。

### Codex 的机制（逐条对齐实现）

| Codex 行为 | 我们的实现 |
|:---|:---|
| 规则是 **argv 前缀匹配** | `Rule.prefix` 按**段**比较（`git pushy` 不会误命中 `git push`） |
| 三种决策 `Allow/Prompt/Forbidden` | `Decision.ALLOW/PROMPT/FORBIDDEN` |
| **最长匹配获胜**（most specific wins） | `max(matched, key=specificity)` |
| 每条规则可带 `justification` | `Rule.justification` 拼进理由 |
| `` `cmd` rejected: {justification} `` | 一致 |
| `` `cmd` rejected: policy forbids commands starting with `{prefix}` `` | 一致 |
| `` `cmd` rejected: blocked by policy ``（无匹配但默认禁） | 一致 |
| `` `cmd` requires approval: {justification} `` / `... by policy` | 一致 |

### 落地

- `src/core/exec_policy.py`：`Rule` / `Decision` / `Evaluation` / `ExecPolicy`
- **内置安全规则**（宁严勿松）：`rm -rf`、`git push --force`、`git reset --hard`、
  `git clean -fd`、`terraform destroy`、`dd`、`mkfs`、`shutdown/reboot` 等直接禁；
  `curl/wget`、`pip install`、`npm publish`、`chmod 777`、`docker rm` 等需审批；
  `git status/diff/log`、`ls/cat/grep/rg/pwd/echo` 明确放行（避免什么都问）
- **用户可覆盖**：`.clawd/exec_policy.json`
  `{"default": "prompt", "rules": [{"prefix": ["deploy"], "decision": "forbidden", "justification": "走流水线"}]}`
  同前缀时**用户规则优先**；文件缺失/损坏/非法决策值 → 回退内置（不崩）

### 集成点与一个必须记的坑

`PermissionEngine.decide()` 对 `action == "exec"` 先过策略，再走保护路径/会话授权。

**坑（实测回归）**：一开始让策略的 `ALLOW` 直接返回 `Effect.ALLOW`，结果
`AUTO_EDIT`/`DEFAULT` 模式下 `echo` 之类**永不再询问**，破坏了既有契约
（`test_approval_gate` 10 项失败）。
修正语义：**`ALLOW` 只表示"策略不禁止"，不越过 `ApprovalMode` 的询问语义**。
`PROMPT` 则**跳过会话授权**（命令级审批每次都问，更安全）。

## 二、会话分叉与元数据（OpenCode Session）

OpenCode `Session` 结构比我们的 `StoredSession` 多三样东西，补上：

| OpenCode 字段 | 我们的新字段 | 用途 |
|:---|:---|:---|
| `ParentSessionID` | `parent_session_id` | **分叉**：从某节点另走一条路而不破坏原历史 |
| `Title` | `title` | 恢复时能辨认是哪个会话 |
| `SummaryMessageID` | `summary_message_id` | 指向压缩检查点（ADR-0012），续跑时先加载摘要 |

新 API：`fork_session()` / `update_session_meta()` / `session_chain()`（带环形保护）。
**向后兼容**：老格式会话文件缺这些字段时按空值读，不崩（有专门测试）。

## 验证

| 套件 | 结果 |
|:---|:---|
| `tests/core/test_exec_policy.py` | **32 passed**（拆分/段匹配/最长获胜/三档理由文案/内置危险命令全挡/只读命令放行/用户文件覆盖/损坏回退/ToolManager 集成：YOLO 也挡 `rm -rf` 与强推、PLAN 连 `ls` 也拒） |
| `tests/core/test_session_fork.py` | **11 passed**（分叉复制历史且不改父、标题、摘要关联、链回溯、老格式兼容） |
| `tests/agent/` 全量 | **645 passed**（含既有审批契约，无回归） |

## 边界

- 策略只做**前缀**匹配，不做 shell 语法解析：`bash -c "rm -rf /"` 这类包装需要
  「命令归一化」才能识别（未做，属已知缺口）
- 未实现 Codex 的 Starlark 策略文件格式，用 JSON 替代（更简单，够用）
- 会话分叉是**浅复制历史**（消息为字符串元组）；真实的"分支对话"还需消息级 parent 链（未做）

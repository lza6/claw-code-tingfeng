# ADR-0013：权限决策引擎 —— 会话授权 / 拒绝理由回灌 / 写入边界

- **状态**：已接受（2026-10-29）
- **来源**（直接读源码提取）：
  - OpenCode `internal/permission/permission.go`（Go, MIT）—— 会话级授权
  - Codex `core/src/apply_patch.rs`、`core/src/exec_policy.rs`（Rust, Apache-2.0）—— 拒绝带理由回灌
  - Pi `readonly-boundary.ts`（TS, MIT）—— 边界概念（OS 沙箱部分 Windows 不适用）

## 改造前的真实缺口

我们有 `ApprovalMode`（plan / default / auto-edit / yolo）且已能在运行时生效（见 `_enforce_approval`），
但缺三件东西：

1. **粒度太粗**：只有"全问 / 全不问"。用户批准一次写 `src/a.py`，写 `src/b.py` 还要再问一遍，
   实际体验下来用户会直接切 YOLO —— 反而更不安全。
2. **拒绝无理由**：`ToolApprovalDeniedError` 只说明"模式不允许"，模型拿不到"为什么被拒"，
   只会原样重试。
3. **没有硬边界**：任何模式下都能写 `.git/config`、`id_rsa`、`.clawd_host_port`。

## 三个借鉴点与落地

### 1. 会话级细粒度授权（OpenCode）

OpenCode 的 `permissionService`：
- 授权键为 `(tool_name, action, session_id, path_dir)`——**批准一次目录级写入，同会话同类免问**
- 三种结果：`Grant`（一次性）、`GrantPersistant`（本会话持久）、`Deny`
- `AutoApproveSession(session_id)` 整会话跳过

**我们的实现**：`SessionGrants`（`src/core/permissions.py`）
- 键 `(session_id, tool, action, scope_dir)`，其中 `scope_dir` = 目标路径的**父目录**
- 用户点"同意"→ 记入会话授权；同目录同类操作直接放行
- `clear(session_id)` 支持按会话撤销

### 2. 拒绝带理由回灌给模型（Codex）

Codex 的做法：
- `apply_patch.rs`：`FunctionCallError::RespondToModel(format!("patch rejected: {reason}"))`
- `exec_policy.rs`：`` `{command}` rejected: {justification} ``

**我们的实现**：
- `ToolApprovalDeniedError(tool, kind, mode, reason=...)` 新增 `reason`：
  非空时文案变为 `` `{tool}` rejected: {reason} ``，并写入 `details['reason']`
- `PermissionEngine.denial_message()` 生成同款文案
- 该异常是 `ToolExecutionError` 子类 → `engine_loop` 会转成
  `ToolResult(success=False, error=str(e))` **回灌模型**（已验证代码路径 `engine_loop.py:693`），
  模型因此能看到"什么被拒 + 为什么"，从而换方案

### 3. 写入边界（Pi 的 readonly-boundary 思路）

Pi 的 OS 沙箱（`bwrap` / `sandbox-exec`）在 **Windows 无原语**，未采纳；
采纳的是"边界必须先划清楚"的思路：

| 受保护对象 | 理由 |
|:---|:---|
| `.git/` 内任意路径 | 版本控制目录，模型改它等于破坏可回滚性 |
| `*.pem` / `*.key` / `*.pfx` / `*.p12` | 密钥/证书类文件 |
| `id_rsa*` / `id_ed25519*` | 私钥文件 |
| `.clawd_host_port` | 含运行时 token |

**默认即使 YOLO 也拒绝**（`protect_even_in_yolo=True`）——密钥和版本库不该因为"全自动模式"就能被模型改写；
可用 `protect_even_in_yolo=False` 显式放宽（需要知情）。

> 有意**不**保护 `.env`：首次配置流程与用户脚本会合法写它，贸然拦会打断既有工作流。
> 这条取舍写在这里，避免以后有人以为是漏了。

## 决策顺序（先硬后软）

```
read → 放行
保护路径 → 拒绝（带理由，回灌模型）
会话已授权 → 放行
其余 → 交给 ApprovalMode（plan 拒绝 / yolo 放行 / default·auto-edit 询问）
       询问通过 → 记入会话授权
```

## 验证

`tests/agent/test_permissions.py` → **41 passed**，覆盖：
- 保护路径识别（含各类密钥后缀、`.git`、token 文件）与正常路径不误伤
- 会话授权的作用域（同目录复用 / 换目录重问 / 跨工具不串 / 跨会话隔离）
- 决策顺序（read 放行、保护优先于会话授权、YOLO 仍守保护、可显式放宽）
- Codex 风格拒绝文案（带路径 / 不带路径）
- 路径提取（各家工具命名差异：path/file_path/filepath/target/filename/file，exec 用 cwd）
- **与 ToolManager 集成**：保护路径无回调也拒、YOLO 也拒、plan 仍拒、
  **批准一次后同目录第二次不再询问**（OpenCode 洞见）、换目录会再问、用户拒绝理由可达模型

既有 `tests/agent/test_approval_gate.py` 等 83 项审批相关测试仍全过（无回归）。

## 边界

- 保护路径按**字面路径片段**匹配，不解析符号链接与 `..`；需要在更外层（工具实现）再做真实路径校验
- 会话授权是**进程内**的，进程重启即失效（符合"会话"语义，不落盘）
- `exec` 类工具没有明确路径时以 `cwd/_` 作为作用域，粒度偏粗（能过，但不如按命令分类精细）
- 未做 Codex 的 `exec_policy` 完整命令前缀策略引擎（那是另一个量级的能力）

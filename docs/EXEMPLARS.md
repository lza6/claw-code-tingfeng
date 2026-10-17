# 黄金代码范例

> 从本仓库**正在生产运行**的代码里提取的 5 个范式。
> 新增代码时优先模仿这些，而不是凭直觉写。
> 每段都标了真实 `file:line`，改动后请同步更新本文。

---

## 1. 工具定义：声明式参数 + 明确的能力边界

`src/tools_runtime/file_read_tool.py:15`

```python
class FileReadTool(BaseTool):
    name = "FileReadTool"
    description = "读取文件内容…"

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name="file_path", param_type="str", required=True,
            description="要读取的文件路径", min_length=1,
        ),
    )
```

**为什么这样写**
- 参数模式由 `BaseTool` 统一校验，工具本身不重复写校验逻辑。
- `description` 明确写出**不支持**的能力（例如 BashTool 明确写"不支持管道/重定向"），
  避免模型反复尝试无效用法、把迭代浪费在困惑的报错上。

**反例**：把校验散落在 `execute()` 里，导致同一个约束在不同入口行为不一致。

---

## 2. 审批咽喉点：所有副作用工具只过一个门

`src/agent/tool_manager.py:96`

```python
def _enforce_approval(self, tool_name, tool_args=None) -> None:
    kind = classify_tool(tool_name)          # read / write / exec
    if kind == "read":
        return
    if self.approval_mode is ApprovalMode.PLAN:
        raise ToolApprovalDeniedError(...)
    if self.approval_mode is ApprovalMode.YOLO:
        return
    if self.approval_mode is ApprovalMode.AUTO_EDIT and kind == "write":
        return
    if self._confirm_callback is None:
        return                                # 非交互场景保持既有行为
    if self._confirm_callback(tool_name, kind, tool_args or {}):
        return
    raise ToolApprovalDeniedError(...)
```

**为什么这样写**
- `ToolApprovalDeniedError` **继承 `ToolExecutionError`**，这样
  `engine_loop._execute_single_tool` 会把它转成模型可见的 `ToolResult`，
  而不是穿透出去触发自愈引擎去"修复"一次策略拒绝。
- `execute_tool` 与 `execute_tools_parallel` **都**走这一个方法，
  否则门禁只挡住一半请求。

**反例**：在每个工具内部各自判断权限 —— 漏一个工具就是一条绕过路径。

---

## 3. 结构化的异常：带 code / details / recoverable

`src/core/exceptions.py:297`

```python
class ToolApprovalDeniedError(ToolExecutionError):
    def __init__(self, tool_name, tool_kind, mode):
        super().__init__(
            message=f"工具 {tool_name} 被审批策略拒绝（approval_mode={mode}）；"
                    "如需放行请调整 approval_mode 或提供交互式确认",
            code=ErrorCode.TOOL_APPROVAL_DENIED,
            details={"tool_kind": tool_kind},
            recoverable=False,
        )
```

**为什么这样写**
- `message` 必须**告诉用户怎么解锁**，而不只是"被拒绝"。
- `recoverable=False` 表示重试不会改变结果 —— 自愈引擎据此不再重试。
- 继承层级决定异常被谁捕获，**这比错误信息更重要**。

**反例**：抛 `Exception("denied")`，既无错误码，也无法被分层捕获。

---

## 4. 让降级可见：失败可观测，且可被测试断言

`src/cli/entrypoint.py:329`

```python
def _load_command_modules() -> tuple[tuple[str, object, str], ...]:
    from .commands import (
        agent_commands, catalog_commands, setup_commands, workflow_commands,
    )
    return (
        ("agent", agent_commands, "register_agent_commands"),
        ...
    )

def _register_command_modules() -> list[str]:
    ...
    try:
        groups = _load_command_modules()
    except Exception as exc:
        logger.warning("命令组模块导入失败…%s: %s", type(exc).__name__, exc)
        return [name for name, _m, _f in _COMMAND_MODULES]
    ...
```

**为什么这样写**
- 用**显式 import**（不是 `importlib.import_module("字符串")`）：
  `scripts/reachability.py` 靠 AST 里的 import 语句建图，字符串形式会让模块
  从图中消失，生产可达数凭空下降（实测 429 → 416）。
- 降级保留，但失败必须写日志并返回失败清单，测试可以直接断言 `== []`。
- 只接 `ImportError` 不够：`NameError`（未定义名称）同样会让整组命令消失。

---

## 5. 测试隔离：进程级全局必须快照/恢复

`tests/agent/test_approval_gate.py:46`

```python
@pytest.fixture(autouse=True)
def _restore_allowed_workdirs():
    from src.tools_runtime import bash_constants
    saved = bash_constants._ALLOWED_WORKDIRS
    try:
        yield
    finally:
        bash_constants._ALLOWED_WORKDIRS = saved
```

**为什么这样写**
- `set_allowed_workdirs()` 用 `global ... = [...]` 重新绑定模块属性，
  作用域是**整个进程**。不恢复的话，后续所有测试都会撞上
  "工作目录不在允许范围内"，表现为一批看似无关的失败。
- 只回滚自己改的键（`dimensions` 等），**不要**调用 `clear_*()` 清空他人设置。

**识别信号**：某个测试文件单独跑全绿、合并跑变红 → 先怀疑全局状态泄漏。

---

## 附：写新代码前的自检

```text
[ ] 参数在函数体里真的被使用了吗？（不接受但忽略的参数）
[ ] 失败路径有没有留下可观测痕迹？（日志 / 返回值 / 异常码）
[ ] 异常类型能被正确的层级捕获吗？
[ ] 新符号能在两套分析下都存活吗？（reachability + import_sweep）
[ ] 测试断言的是行为，还是仅仅"没报错"？
```

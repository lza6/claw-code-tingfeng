# 变更日志

所有重要的项目变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [未发布]

### v0.56.0 (2026-10-17) — 导入期缺陷清剿：7 个 CLI 命令从"静默消失"到可见

#### 🔴 主缺陷：两个命令组整体从 CLI 消失，启动无任何提示

`src/cli/entrypoint.py` 的 `_register_command_modules()` 用
`try: ... except ImportError: pass` 包裹四处注册。本意是"可选模块缺失时优雅降级"，
实际把**硬错误**吞成了静默失败：

| 模块 | 断裂点 | 后果 |
|:---|:---|:---|
| `agent_commands.py:16` | 导入 `get_registered_keywords`（该函数不存在，现名 `get_all_keywords`） | `clawd agent` 整组不可用 |
| `workflow_commands.py:18` | 从 `pipeline_orchestrator` 导入三个 stage 工厂（它们定义在 `workflow.pipeline`） | `clawd workflow` 整组不可用 |
| `hud_improved.py:20` | `from ...core` 但模块深度只有 2 层 → 越过顶层包 | `clawd hud` 不可用 |

**7 个命令**（agent list/show/keywords、workflow ralph/ralplan/team/autopilot）
因此从未被注册，而 `clawd --help` 看不出任何异常。

实测确认（修复前）：

```
$ clawd agent --help
main.py: error: argument command: invalid choice: 'agent'
已注册组: ['catalog', 'setup']        ← agent / workflow 完全缺席
```

#### 隐藏的第四类缺陷：自引用注册

`setup_commands.py` 早已修过 `app.add_typer(app, name="setup")` 这个自引用
（形参遮蔽了模块级 `app`，等于把父应用注册到自己身上），并留了警告注释。
但 **`agent` / `workflow` / `catalog` 三个模块没有同步**，全部沿用错误写法。

#### 修复

1. **让降级可观测** —— `except ImportError: pass` 改为 `except Exception` +
   `logger.warning`，并返回失败组名清单供测试断言。只接 `ImportError`
   会漏掉 `NameError`（`field` 未定义）这类同样致命的错误。
2. **修正三个断链**，命令体按真实 API 重写（不是简单改名）。
3. **四个 register 函数**统一改为 `parent_app.add_typer(app, ...)`。
4. **新增 `clawd agent intent <text>`** —— 暴露 `intent_router` 的真实意图分类能力。

#### 导入期全库扫描：16 → 1 → 0

新增 `scripts/import_sweep.py`，逐个 import 全部 639 个模块，
区分「项目内代码缺陷」与「第三方依赖缺失」（后者是环境问题，不计入缺陷）：

```
修复前： IMPORT-OK 617 / IMPORT-FAIL 16 / DEP-MISSING 6
修复后： IMPORT-OK 632 / IMPORT-FAIL  1 / DEP-MISSING 6
清零后： IMPORT-OK 638 / IMPORT-FAIL  0
```

16 个缺陷的根因分布（多数在**生产不可达**模块，非 P0）：

| 根因 | 模块数 | 处置 |
|:---|:---|:---|
| 相对导入层数算错 | 5（`team/state/*`） | 修 `locks.py:22` 一处，连带解除 5 个 |
| 字符串按位或冒充字面量联合 | 3（`autoresearch/*`） | 改用 `Literal` + `from __future__ import annotations` |
| 类名/函数名与真实实现不符 | 4 | 按真实 API 重写消费者 |
| dataclass 字段顺序违反继承规则 | 1（`charter.py`） | 给子类字段补默认值 |
| 引用了从未存在的模块 | 2（`coder_agent`、`core.mcp.code_intel_server`） | 删除孤儿 / 移除坏配置项 |
| 残壳包指向不存在的文件 | 1（`core/auth`） | 改为转发真实实现 `core/auth_module` |

#### ⚠️ `coder_agent.py` 的处置说明

它 `from .consensus import SemanticValidator, Vote, VoteType`，而
`src/agent/swarm/consensus.py` **在 git 全历史中从未存在过** ——
该模块从写下的第一天起就无法导入。核实：`CoderAgent` 零消费者、
`swarm/__init__.py` 未导出。

**选择删除而非补造 `consensus.py`**：补造一个"能导入但验证永远通过"的桩，
正是本项目 v0.55.0 刚刚清理掉的那类伪实现。若将来需要 swarm 的 Coder 专家，
应连同真实共识机制一起立项。

#### 修复"生成的 MCP 配置指向坏模块"

`src/core/config/generator.py` 的 `DEFAULT_MCP_SERVERS` 有 5 条，
其中 **2 条必然启动失败**：

- `clawd-memory` → `src.core.mcp.memory_server`：导入 `EnterpriseLongTermMemory`
  （类已更名 `EnterpriseLTM`），且调用的 `store_entity/store_observation/
  store_relation/search` 在该类中**从未存在**——两者数据模型不同
  （代码实现模式 vs 知识图谱三要素），无诚实映射方式。
  → 移除臆测的集成，`search()` 改为在本服务自己的 JSON 存储上做关键词检索。
- `clawd-code-intel` → `src.core.mcp.code_intel_server`：该文件不存在。
  → 移除该条配置。

修复后 4 条配置**全部可导入**（实测）。

#### 测试隔离缺陷

`tests/agent/test_approval_gate.py` 调用 `set_allowed_workdirs([tmp_path])`，
该函数用 `global ... = [...]` **重新绑定进程级模块属性**且不恢复。
后果是**同进程后续所有测试**都撞上"工作目录不在允许范围内"：

```
pytest tests/agent tests/tools_runtime tests/cli   → 6 failed（看似无关的 bash 用例）
pytest tests/tools_runtime/test_bash_execution_paths.py（单独） → 11 passed
```

已加 `autouse` fixture 在每个用例前后快照/恢复该全局。

#### 验证

| 项目 | 结果 |
|:---|:---|
| CLI 命令注册回归（新增 15 用例） | **15 passed** |
| `tests/agent + tools_runtime + cli` 合并 | **754 passed / 0 failed** |
| 生产路径 E2E（真实端点） | **8/8** |
| 并发压测 | **5/5** |
| 导入全库扫描 | **0 缺陷**（638/638 可导入） |
| 可达性不变量 | **429 → 429**（未变） |

#### 一处自我更正

初版修复把命令组模块清单写成字符串 + `importlib.import_module()`。
运行时正确，但 `scripts/reachability.py` 靠 AST 里的 import 语句建图，
这 4 个模块因此在图中消失，可达数从 429 掉到 416。
已改回显式 `from .commands import (...)`（保留失败可见的 `try/except`）。

> **教训：替换导入方式前，先确认项目自身的静态分析工具依赖什么形式。**

---

### v0.55.0 (2026-10-17) — 死代码复核、伪验证诚实化

#### 🔴 发现：验证阶段是假的

生产管道 `src/workflow/pipeline.py` 的验证阶段有 **4 处桩**，其中：

```python
# TODO: 集成 Ralph 循环逻辑
artifacts = {
    "verification_result": "passed",   # ← 硬编码
    "iterations": 3,                   # ← 也是假的
}
```

**它从不运行任何测试、不做任何检查，直接返回"通过"。**

更关键的是：未接线侧 `src/workflow/stages/ralph_verify_stage.py` 虽然循环结构
更完整（有 `while ... and not approved`），但它的 `_verify_implementation`
**同样是桩**：

```python
# TODO: 实现真正的验证逻辑
return {"approved": True,  # 简化为总是通过
        "evidence": {"tests_passed": True}}
```

**两者都是桩。** 把它接上去等于用一个更精致的"永远通过"替换一个简陋的
"永远通过"，不解决问题。（子代理最初的判断是"未接线侧是真实实现"，
主线程读源码后更正了这一结论。）

**本次修复**：把三处桩的伪造值改为**诚实值**（`plan_implemented: False`、
`execution_completed: False`、`verification_result: "not_implemented"`、
`verified: False`），使"未实现"不再伪装成"已通过"。
消费方检查为 0（已验证），因此零行为风险。

**仍待立项**：让验证阶段真正调用测试执行器；在此之前，任何依赖该阶段结果
做自动化放行决策的逻辑都不可信。

#### 🗑️ 死代码复核与收敛

由三个并行子代理逐模块读源码复核 163 个"生产不加载"模块（31,188 行），
删除 20 个经确认被取代的模块：

```
src/session/ src/openclaw/ src/mcp/code_intel.py src/mcp/state_paths.py
src/brain/repomap.py src/brain/file_watcher.py src/brain/special_files.py
src/self_healing/doctor.py src/self_healing/session_manager.py
src/server/mcp.py src/runtime/bridge.py src/runtime/mailbox.py
src/utils/paths.py src/rag/context_index.py src/rag/lang_engine.py
src/cli/report.py src/cli/onboarding.py src/cli/hud_authority.py
src/cli/tui/models.py src/cli/tui/animations.py
```

**安全验证**：删除前后「从生产入口可达的模块数」均为 **429（未变）**。

**为什么不继续删**：剩余模块多属"未接线功能"（如 swarm 专家类、
team 状态层、workflow worktree 护栏），删除等于砍能力，需产品决策。
完整清单与判定见 `计划书/死代码复核报告.md`。

#### 📚 新增文档

- `计划书/死代码复核报告.md` —— 复核方法、本轮删除、待决策清单、
  以及"验证阶段是假的"这一更正的完整记录

---

### v0.54.0 (2026-10-17) — 门禁落地、并发压测、真死代码收敛

#### 🔴 安全：PLAN 模式首次真正生效

`ApprovalMode` 此前只在配置层被读写，**没有任何运行时消费者**。
用户按文档把 `approval_mode` 设为 `plan`（"仅分析，不修改文件"），
Agent **照样写盘** —— 一个"装饰性控制"。

现在在 `ToolManager.execute_tool` / `execute_tools_parallel`（生产工具执行的
唯一咽喉点）按类别拦截：read 放行，write / exec 拒绝。

- 只实施 PLAN；DEFAULT / AUTO_EDIT / YOLO 不拦截 —— 因为**仓库里没有任何
  交互式审批设施**，DEFAULT 语义中的"需要审批"无法落地，强行拦截会让
  开箱即用的默认配置直接不可用。`.env.example` 已如实说明这一边界。
- 一个集成陷阱：初版抛 `SecurityError`，但 `engine_loop._execute_single_tool`
  只捕获 `ToolExecutionError`（二者是**兄弟类**）→ 异常穿透触发自愈引擎去
  "修复"一个策略拒绝。改为新增 `ToolApprovalDeniedError` + 错误码 `E2009`，
  使拒绝变成**模型可见的 ToolResult**。
- 配置读取失败时退回 `DEFAULT` 而非 `YOLO` —— "读不到配置就放开全部管控"
  是最危险的降级方向。

#### 🔴 修复：world_model 的 4 个缺陷

- **首次运行时指纹永不保存**（真实 Bug，静默降级）
  `import json` 位于 `if fp_path.exists():` 内，Python 因此把 `json` 视为
  **整个函数的局部变量** → 指纹文件不存在时抛 `UnboundLocalError`，被
  `except` 吞成 warning。后果：**增量索引每次退化为全量重建**，
  该模块的核心卖点长期失效。
- `predict_relevant_files` 无条件调用 `get_imported_by()`，但只有
  `CodeGraph` 有该方法；默认的 `DependencyGraph`（兼容层）只有
  `get_upstream` → 图谱构建失败退回兼容层时抛 AttributeError。
  改用两者都提供的 `impact_analysis()`，按各自返回结构读取。
- `isinstance(x, CodeGraph)` 在测试把 `CodeGraph` 替换成 MagicMock 时抛
  TypeError，使并行构建路径无法被 mock 覆盖。
- `import asyncio` 在方法内 —— stdlib 导入本就有缓存，局部化无收益却
  破坏 `patch("...world_model.asyncio.to_thread")`。

#### 🗑️ 真死代码收敛（净删 ~2,600 行）

本轮删除的都是**经人工核对确认同一 TS 源文件**的重复移植：

| 删除 | 行数 | 存活侧（生产可达） |
|:---|:---|:---|
| `src/pipeline/` | 248 | `src/workflow/pipeline.py` |
| `src/team/` | 1,065 | `src/workflow/team/` |
| `src/subagents/` | 230 | `src/agent/swarm/subagent_tracker.py` |
| `src/screens/hud/` | 1,013 | `src/cli/hud*.py` |

**安全验证**：删除前后「生产入口可达模块数」均为 **429**（未变），
证明删掉的确实都是不可达模块。模块总数 684 → 666。

#### ⚠️ 一个被证伪的自动化判据（重要）

我写过一个"近名存活模块存在 → 判为已取代的重复品"的启发式。实测**误报严重**：

```
src.core.hook_registry.async_executor  "对照" src.core.hook_registry
    —— 后者是同一个包，前者是它的子模块，不是重复品
src.workflow.worktree_isolation        "对照" src.cli.commands.workflow_commands
    —— 仅仅因为名字里都含 "workflow"
```

**名称相似 ≠ 语义重复。基于名称的启发式不足以授权删除源码。**
因此 `scripts/deadcode_inventory.py` 改为**只出复核清单、不判"可删"**。
剩余 163 个生产不加载模块（31,188 行）保持原样，等人工按源码逐条复核。

#### 🧪 新增：并发压测与深度自检

`scripts/stress_test.py` 针对三处**真实存在并发风险**的基础设施施压。
实测 200 并发、5/5 通过：

```
工具执行 200 并发      200 全部成功且结果无错配
线程池未耗尽           5 轮 × 50 并发，每轮全成功
审批门禁并发混合       拒绝=100 只读放行=100 YOLO放行=100 误拒=0
熔断器 200 并发计数    计数无丢失，正确进入 OPEN
熔断器并发渠道隔离     熔断 200 次 / 健康 200 次判定全部正确
```

**压测暴露的性能瓶颈**：工具线程池硬编码 10 → 200 个并发 bash 被压成
20 波，吞吐仅 11 req/s。改为可用 `CLAWD_TOOL_EXECUTOR_MAX_WORKERS` 配置：

```
池=10 -> 200 并发 19.05s (11 req/s)
池=64 -> 200 并发 12.40s (16 req/s)   延迟降 35%
```

诚实说明：**收益有限** —— 真正的瓶颈是 Windows 进程创建开销而非线程数。
非法配置值（0 / 负数 / 非数字）一律回退默认，因为 `max_workers=0` 会让
**全部**工具执行失败。

#### 📚 新增测试

- `tests/agent/test_approval_gate.py`（32 例）
- `tests/agent/test_executor_config.py`（17 例）
- `tests/brain/test_world_model_complex.py` 重写 2 例（原断言已废弃 API）

---

### v0.53.0 (2026-10-16) — 盲点扫描与生产路径加固

本轮由**多智能体并行审计**驱动：死代码可达性、测试失败归因、
安全盲点扫描三个方向独立进行，每条发现均由主线程亲自复现后才修复。

#### 🔴 安全（生产环境真实风险）

- **Agent 可读取 `.env`，API Key 明文进入 LLM 上下文**
  `src/utils/path_security.py` 早已实现 `is_sensitive_file` 与
  `FORBIDDEN_DIRS`，但**从未被任何工具接线**。实测
  `execute_tool(tools, 'FileReadTool', {'file_path': '.env'})` → `success=True`，
  输出含 `OPENAI_API_KEY=sk-***REDACTED***`，该内容随后被
  `engine_loop` 原样拼进消息发给远端模型。
  在 `path_utils.resolve_path()`（四个文件工具的唯一统一入口）接入判定，
  一处改全部生效。`.env.example` 等模板显式豁免。
  同时从 `TEXT_EXTENSIONS` 移除 `.env`。

#### 🔴 阻塞级（生产路径不可用）

- **BashTool 在 Agent 环路中 100% 失败 —— shell 能力实际不可用**
  `BashTool.execute()` 裸调 `asyncio.get_event_loop()`，而生产路径把工具
  丢进 `ThreadPoolExecutor` 工作线程执行（`tool_executor.py:170`）。工作
  线程没有事件循环，Python 3.10 抛
  `RuntimeError: There is no current event loop in thread ...`，
  被吞成"执行失败"。**跑测试、git、构建、任何命令全部不可用。**
  既有测试都在主线程直调（有自动循环），所以永远绿。
  修复覆盖三种上下文：无循环线程用 `asyncio.run`、主线程用
  `run_until_complete`、嵌套循环明确提示改用 `async_execute`。

- **`<think>` 标签提取必崩**（`src/llm/providers/openai.py:128`）
  写成 `content.split('', 1)` —— 分隔符是空字符串，任何含 `<think>` 的
  响应都抛 `ValueError: empty separator`，被重试吞掉 5 次后整次调用失败。
  改用 `ThinkTagParser.CLOSE_TAG` 常量。
  **这是生产 LLM 路径上的缺陷**，与 v0.51.0 修的 `factory.py` 不是同一条路径。

#### 🔍 架构澄清（修正 v0.51.0 的认知）

传递可达性分析确认生产创建 LLM 的路径是
`src/agent/engine.py:203 → create_llm_provider() → providers/*`，
而 v0.51.0 修的 `src/llm/factory.py::get_default_llm()` **从生产入口不可达**。
那批修复有效但保护错了路径，本轮补齐对真实生产路径的修复与测试。

#### 🗑️ 删除真死代码（4,158 行）

- `src/notifications/`（8 文件）、`src/visual/`、`src/session_history/`
- **被同名包遮蔽的 3 个死文件**：Python 中包优先于同名模块，实测确认
  `src/core/events.py`(343行)、`src/core/git/worktree.py`(9行)、
  `src/llm/model_info.py`(32行) **永不执行**。
  其中 `events.py` 与包里的 `events/core.py` 是两套事件总线实现 ——
  改错文件会"改了没效果"，正是本项目反复出现的缺陷模式。

> 修正：v0.51.0 曾称 `src/notification/` 也是死代码，**该判断有误** ——
> 它被两个测试文件引用，有测试覆盖。

#### 🛠️ 新增工具与测试

- `scripts/reachability.py` —— 从入口做 BFS 传递可达性分析。
  修掉一个关键 bug：相对导入的基准包对 `__init__.py` 多减一层，
  导致整棵 `src.llm.*` 被误判不可达。自检：684 模块 / 429 生产可达。
- `scripts/find_untested_live_code.py` —— 找出"生产在跑但零测试覆盖"的模块。
- `scripts/e2e_production.py` —— **生产路径** E2E（8 步全通过）。
- `tests/llm/test_providers_openai.py`（16 例）
- `tests/llm/test_circuit_breaker.py`（26 例，熔断器此前 0% 覆盖）
- `tests/tools_runtime/test_bash_execution_paths.py`（11 例）
- `tests/test_security/test_sensitive_path_guard.py`（33 例）

#### ⚠️ 已记录但未修的缺陷

- **`ApprovalMode` 无运行时消费者**：用户把 `approval_mode` 设为 `plan`
  （文档称"仅分析，不修改文件"）时，Agent 仍会写盘。属"装饰性控制"，
  需单独设计门禁接入点。
- `HeuristicToolParser` 只在"参数值后紧跟非 `<` 裸文本"时输出，
  带 `</function>` 闭合标签的形态识别不了。主路径 `parse_tool_calls`
  （系统提示词实际指示的 `<tool>{json}</tool>`）正常，不阻塞主流程。
- `CircuitBreaker` 半开态的 `half_open_max_requests` 形同虚设
  （`_half_open_requests` 只在 `record_success` 中递增）。已锁定为 xfail。

---

### v0.52.0 (2026-10-16) — 波次 2/3：真死代码收敛 + 生产路径审计

#### 🔴 修复（生产路径）

- **`<think>` 标签提取必崩**（`src/llm/providers/openai.py:128`）
  写成 `content.split('', 1)` —— 分隔符是**空字符串**，任何含 `<think>`
  的响应都抛 `ValueError: empty separator`，被重试逻辑吞掉 5 次后整次调用失败。
  改为使用 `ThinkTagParser.CLOSE_TAG` 常量，避免再次被编辑操作截断成空串。
  **这是生产 LLM 路径上的缺陷** —— 与 v0.51.0 修的 `factory.py` 不是同一条路径。

#### 🔍 关键架构澄清（修正 v0.51.0 的认知）

用传递可达性分析确认：**生产创建 LLM 的路径是**

```
src/agent/engine.py:203
  -> src/llm/providers/__init__.py::create_llm_provider()
    -> OpenAICompatibleProvider.chat() / .chat_stream()
```

而 v0.51.0 修复的 `src/llm/factory.py::get_default_llm()` **从生产入口不可达**。
那批修复本身是有效的（且 `scripts/e2e_smoke.py` 覆盖），但它保护的不是生产路径。
本次补齐了对**真实生产路径**的修复与测试。

#### 🗑️ 删除真死代码

- `src/notifications/`（8 文件）
- `src/visual/`（2 文件）
- `src/session_history/`（1 文件）
- 合计 **3,774 行**

> 修正：v0.51.0 曾称 `src/notification/` 也是死代码，**该判断有误** ——
> 它被两个测试文件引用，有测试覆盖。已用可达性分析复核。

#### 🛠️ 新增分析工具

- `scripts/reachability.py` —— 从入口点做 BFS 传递可达性分析。
  修掉了一个关键 bug：相对导入的基准包对 `__init__.py` 多减一层，
  导致整棵 `src.llm.*` 被误判不可达。自检：684 模块 / 429 生产可达。
- `scripts/find_untested_live_code.py` —— 找出"生产在跑但零测试覆盖"的模块。
- `scripts/e2e_production.py` —— **生产路径** E2E（区别于 `e2e_smoke.py`）。

#### 🧪 新增测试

- `tests/llm/test_providers_openai.py`（16 例）—— 生产 LLM 提供商路径：
  `<think>` 提取回归、重试与错误传播、消息编解码、流式
- `tests/llm/test_circuit_breaker.py`（26 例）—— 熔断器完整状态机
  （此前 0% 覆盖率），并锁定一个已确认缺陷为 xfail

#### ⚠️ 发现的已知缺陷（未修，已记录）

- `HeuristicToolParser`（`src/llm/parsers.py`）的状态机**只在参数值后紧跟
  不以 `<` 开头的裸文本时才输出**。任何带 `</function>` 闭合标签的输出
  都识别不了。主路径 `parse_tool_calls`（系统提示词实际指示的
  `<tool>{json}</tool>` 格式）工作正常，因此该兜底失效不阻塞主流程。
  该解析器此前无任何测试。
- `CircuitBreaker` 半开态的 `half_open_max_requests` 形同虚设 ——
  `_half_open_requests` 只在 `record_success()` 中递增，失败路径与
  "请求发起"路径都不计数，因此并发探测不受限。

---

### v0.51.0 (2026-10-16)

本次为**止血版本**：修复了一批"项目声称可用、实际运行即崩"的缺陷。
所有修复均附有实测复现与验收命令，详见 `计划书/下一步改进指南.md`。

#### 🔴 修复（阻塞级）

- **LLM 栈完全不可用**（`src/llm/factory.py`）
  `get_default_llm()` / `get_vision_llm()` 访问了不存在的
  `settings.context_window`，任何调用都抛 `AttributeError`。
  修正为实际字段 `settings.max_context_tokens`。
- **API Key 与自定义端点从未生效**（`src/core/config/models.py`）
  `.env.example` 约定 `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL`，
  但 `AgentSettings` 只识别 `LLM_API_KEY` 等通用名，导致按文档配置的用户
  拿到 `llm_api_key=None`、`llm_model='gpt-4'`、`llm_base_url=None`。
  新增提供商环境变量别名解析层，兼容全部既有配置方式。
- **自定义端点被忽略，请求打到官方 API**（`src/llm/factory.py`）
  `_LiteLLMCompatWrapper` 构造 litellm 参数时遗漏 `api_key` / `api_base`，
  使用 OpenRouter / NIM / 自建网关的用户必然 401。
  抽出 `_build_call_kwargs()` 供 `invoke`/`stream` 共用。
- **工具调用结果被丢弃，Agent 环路断裂**（`src/llm/factory.py`）
  响应解析只取 `role` / `content`，`tool_calls` 与 `reasoning_content`
  从未回填，模型即使返回工具调用也被当作普通文本处理。同步修复流式路径。
- **原子补丁引擎不可用**（`src/core/patch/atomic_patcher.py`）
  `apply_batch` / `apply_changes` 调用的 `commit()` 与 `rollback()` **根本未定义**，
  而 `src/agent/engine_loop.py` 在每次文件编辑后都会调用它们 ——
  即每次成功改文件都会崩溃。补齐两个方法；
  另删除被静默覆盖且引用未定义变量的重复 `apply_changes`；
  补齐被引用但从未实现的 `_apply_diff_hunks` 与 `apply_patch`。
- **配置文件反复合并会自我污染**（`src/core/config/merger.py`）
  `merge_config` 把 OMX 顶层配置追加到字符串末尾，第二次合并起
  `notify` / `model_reasoning_effort` / `developer_instructions`
  会落到 `[agents]` 表之下，被 TOML 解析成 `agents.*`，顶层配置静默丢失。
  改为插入到第一个表头之前，并新增幂等性测试。
- **Windows 中文环境启动即报编码错误**（`src/utils/logger.py`, `src/main.py`）
  控制台默认 GBK，日志中的 emoji / CJK 触发 `UnicodeEncodeError`，
  用户看到满屏乱码与调用栈。统一将 stdout/stderr 切至 UTF-8（`errors='replace'`）。
- **RAG 索引事件永不发布**（`src/brain/world_model.py`）
  指标代码引用未定义的 `indexed_count`，异常被 `except: pass` 吞掉，
  `RAG_INDEX_UPDATED` 长期静默失效。同时修正恒等于 100% 的覆盖率公式。
- **配置包公开 API 缺失，Agent 主入口崩溃**（`src/core/config/__init__.py`）
  该包只 re-export 了 `merger`，`AgentSettings` / `get_settings` /
  `load_settings` 全部 `ImportError` —— 而 `src/agent/factory.py:70` 正是
  这样导入的，导致 `create_agent_engine()`（创建 Agent 的主入口）
  以 `ImportError` 崩溃，且该异常不在 `except (KeyError, ValueError)` 捕获范围内。
  现已补全 re-export，并新增 `ensure_project_dirs()`。
- **`clawd setup` 静默不生成配置文件**（`src/cli/commands/setup_commands.py`）
  `src.config.generator.merge_config` 是 `async def`，却被同步调用 ——
  只得到一个从未 await 的协程，弹出 `RuntimeWarning` 而配置文件根本没写到磁盘
  （用户看到"✓ 创建配置文件"却是空的）。
- **`clawd setup` 无法找到模板**（`src/cli/commands/setup_commands.py`）
  模板路径少算一级目录（指向 `src/templates/`，实际在仓库根 `templates/`），
  导致 AGENTS.md 与 catalog-manifest.json 永远"跳过: 模板未找到"。
  改为向上探测 `pyproject.toml` + `templates/`，兼容各种安装布局。
- **`register_setup_commands` 自引用**（`src/cli/commands/setup_commands.py`）
  `app.add_typer(app, name="setup")` 中形参 `app` 遮蔽了模块级 `app`，
  等于把父应用注册到自身。
- **代码图谱并发修改崩溃**（`src/rag/code_graph.py`）
  `_resolve_all_edges` 直接迭代 `self.nodes.values()`，而图谱构建可能由
  `asyncio.to_thread` 在后台线程添加节点，抛
  `RuntimeError: dictionary changed size during iteration`。改为快照迭代。
- **生成配置中的硬编码过期版本号**（`src/config/generator.py`）
  生成的 `.clawd/config.toml` 注释写死 `Clawd Code v0.50.0+`。已移除该噪声。

#### 🔧 修复（契约与一致性）

- `AgentDefinition` 字段由 camelCase 改为 snake_case
  （`reasoningEffort` / `modelClass` / `routingRole`），
  恢复 `tests/contracts/` 契约并符合 PEP 8。
- 枚举补全为 `AgentModelClass` / `AgentRoutingRole`，与同文件其余 `Agent*` 命名一致。
- `src/workflow/verifier.py` 补全契约声明的 `TaskSize` / `EvidenceType` /
  `Confidence` / `VerificationEvidence.as_text()`；枚举继承 `str`，不破坏既有字符串比较。
- 版本号改为单一真相源：`pyproject.toml` 为唯一来源，`src.__version__` 自动读取。
- 重写 `tests/core/test_config_merger.py`（原测试针对已废弃的 `ConfigMerger`
  类与 `OMX_MARKER` 设计，导致 pytest 收集失败）。

#### 🧪 新增测试

- `tests/self_healing/test_atomic_patcher.py` +10：事务语义、unified diff 应用、
  上下文不匹配拒绝、语法破坏拒绝、多 hunk。
- `tests/brain/test_world_model.py` +2：`RAG_INDEX_UPDATED` 事件发布与零文件边界。
- `tests/core/test_config_merger.py` 重写为 48 个用例，含**幂等性**回归。
- `scripts/e2e_smoke.py`：对真实 LLM 端点的端到端冒烟测试
  （配置 → 导入 → 对话 → 工具调用 → 推理内容）。

#### 📝 说明

- `pyproject.toml` 的 `fail_under` 仍为 60，与实际覆盖率存在差距，
  按 `计划书/下一步改进指南.md` §6.1 的路线分阶段提升。

---

### v0.46.0 (2026-04-08)

#### 🧪 测试增强
- **新增 12 个测试文件，300+ 测试用例**
  - `tests/agent/test_events.py` - EventMixin 全面测试（35 用例）
  - `tests/agent/test_lifecycle.py` - LifecycleMixin 信号处理和关闭测试（28 用例）
  - `tests/agent/test_event_publisher.py` - EventPublisher 独立测试（22 用例）
  - `tests/agent/test_agent_session.py` - AgentSession 会话管理测试（25 用例）
  - `tests/agent/test_message_truncator.py` - MessageTruncator 截断策略测试（22 用例）
  - `tests/brain/test_dependency_graph.py` - DependencyGraph 依赖图谱测试（20 用例）
  - `tests/core/test_patch_engine.py` - PatchEngine 补丁引擎测试（25 用例）
  - `tests/utils/test_retry.py` - Retry 重试策略测试（30 用例）
  - `tests/utils/test_cache.py` - Cache 缓存策略测试（28 用例）
  - `tests/llm/test_cache.py` - LLMCache LLM 缓存测试（18 用例）
  - `tests/memory/test_manager.py` - MemoryManager 记忆管理测试（12 用例）
  - ~~`tests/session/test_session_manager.py`~~ - 该文件实际不存在于仓库（v0.51.0 修正本条目）

#### 📈 质量提升
- 测试用例总数从 1416 增加至 1565+（+10%）
- 覆盖核心模块数量从 12 个增加至 24 个（+100%）
- 新增边界条件、错误处理、集成和并发测试
- 所有测试遵循 Arrange-Act-Assert 模式

#### 🐛 修复
- 修复事件测试中的断言错误
- 修复节流测试中的方法调用问题

---

## [v0.45.0]

### 🆕 新增

#### ClawGod 整合 (v0.44.0)
- **声明式补丁引擎系统** (`src/core/patch_engine.py`)
  - 补丁 DSL（领域特定语言）
  - 补丁修饰符：`unique`, `optional`, `select_index`, `validate`
  - 多模式运行：dry-run / verify / apply / revert
  - 自动备份策略
  - 跨版本兼容（正则模式匹配）

- **上下文指纹验证工具** (`src/utils/context_validator.py`)
  - 关键字验证 (`validate_by_keywords`)
  - 正则表达式验证 (`validate_by_regex`)
  - 代码结构验证 (`validate_by_structure`)
  - 一站式验证函数 (`validate_match_context`)
  - 便捷验证器创建函数

- **Wrapper + Forward 配置注入** (`src/core/config_injector.py`)
  - 6 层配置优先级链
  - 运行时配置覆盖 (`set()` / `get()` / `delete()`)
  - 配置变更回调系统
  - 配置热重载支持
  - 持久化配置到文件
  - 配置优先级报告

- **Prompt 优化器** (`src/llm/prompt_optimizer.py`)
  - 使用补丁引擎优化系统提示词
  - dry-run 预览优化效果
  - 上下文验证确保优化不破坏语义
  - 可回滚的优化策略

- **增强安装脚本** (`install_enhanced.ps1`)
  - 智能检测已有安装
  - 自动备份和还原
  - 双重启动器模式
  - Dry Run / Status / Uninstall / Revert 多模式

#### CI/CD 流水线
- **GitHub Actions CI** (`.github/workflows/ci.yml`)
  - Python 3.10/3.11/3.12 版本矩阵测试
  - Lint (Ruff) + Type Check (MyPy)
  - 测试覆盖率报告上传到 Codecov (**≥60% 门控**)
  - 安全扫描 (Bandit + Safety) **启用阻断**
  - Docker 构建测试

- **Docker 镜像发布** (`.github/workflows/docker.yml`)
  - 多平台镜像构建 (linux/amd64, linux/arm64)
  - 自动推送到 GitHub Container Registry
  - 语义化版本标签

- **依赖自动更新** (`.github/dependabot.yml`)
  - pip 依赖每周自动检查更新
  - GitHub Actions 依赖更新
  - Docker 基础镜像更新

- **Makefile** 本地开发便捷命令
  - `make install` / `make test` / `make lint`
  - `make format` / `make type-check` / `make coverage`
  - `make docker-build` / `make docker-run`
  - `make check` 全量检查（CI 本地模拟）

#### 测试覆盖增强
- **新增 449 个测试用例**
  - `tests/agent/test_core_engine.py` (72 测试) - 核心循环函数 (16% → 84%)
  - `tests/agent/test_lifecycle.py` (21 测试) - 信号处理和生命周期 (0% → 87%)
  - `tests/agent/test_events.py` (17 测试) - 事件发布系统 (0% → 98%)
  - `tests/cli/test_repl.py` (42 测试) - REPL 交互 (13.8% → 57%)
  - `tests/workflow/test_workflow.py` (59 测试) - 工作流引擎 (18.6% → 58-99%)
  - `tests/core/test_patch_engine.py` (27 测试) - 补丁引擎
  - `tests/utils/test_context_validator.py` (35 测试) - 上下文验证
  - `tests/core/test_config_injector.py` (47 测试) - 配置注入器
  - `tests/core/test_compact.py` (72 测试) - 上下文压缩 (25% → 98%)
  - `tests/core/test_dependency_analyzer.py` (36 测试) - 依赖分析 (17% → 96%)
  - `tests/cli/test_thinking_canvas.py` (54 测试) - 思考画布 (0% → 62%)

### 🔧 改进

#### 代码质量
- **消除重复代码**
  - 删除 `src/utils/patch_engine.py` (18,866 字节重复)
  - 统一使用 `src/core/patch_engine.py`
  - `experience_bank.py` 已有兼容层 (core/self_healing/workflow)

#### 配置系统
- **`src/core/settings.py`** 集成配置注入器
  - 新增 `get_runtime_config()` / `set_runtime_config()` 函数
  - 新增 `reload_config()` 热重载支持
  - 新增 `get_config_priority_report()` 配置报告
  - 自动应用运行时配置覆盖

#### 测试覆盖率提升
| 模块 | 改进前 | 改进后 | 提升 |
|------|--------|--------|------|
| agent/_core_engine | 16% | **84%** | +68% |
| agent/_lifecycle | 0% | **87%** | +87% |
| agent/_events | 0% | **98%** | +98% |
| cli/repl | 13.8% | **57%** | +43% |
| cli/thinking_canvas | 0% | **62%** | +62% |
| workflow | 18.6% | **58-99%** | +40-80% |
| core/compact | 25% | **98%** | +73% |
| core/dependency_analyzer | 17% | **96%** | +79% |
| **总计** | **35%** | **~49%** | **+14%** |

#### 测试总数
- **改进前**: 743 个测试
- **改进后**: **1192 个测试** (+60%)

#### CI 门控
- 添加 `--cov-fail-under=60` 覆盖率阈值
- 移除安全扫描的 `|| true`，启用真正阻断
- Bandit 仅报告中高严重性级别

### 📚 文档
- **`CLAWGOD_INTEGRATION_FINAL_REPORT.md`** - ClawGod 整合最终报告
- **`CLAWGOD_PHASE2_INTEGRATION_PLAN.md`** - 整合计划文档
- **`CLAWGOD_PHASE2_COMPLETION_REPORT.md`** - 整合完成报告
- **`ARIPER_DELIVERY_REPORT.md`** - ARIPER 交付报告

### 🔒 安全
- 安全扫描集成到 CI 流水线 (Bandit + Safety)
- 依赖漏洞自动检测和更新
- Bandit 仅阻断中高危问题

---

## [v0.43.0] - 2026-04-05

### 🆕 新增
- Swarm 多 Agent 协作系统
- 世界模型 (WorldModel)
- 自我修复引擎增强
- RAG 检索增强生成

### 🔧 改进
- 组合模式重构 AgentEngine (v0.38.0)
- 统一代理循环 (v0.38.0)
- Feature Flag 系统增强 (v0.40.0)
- 统一重试策略工厂 (v0.40.0)
- 命令注册表 (v0.40.0)
- Trace Context 传播 (v0.40.0)

---

## [v0.42.0] - 2026-04-04

### 🆕 新增
- Textual TUI 全屏仪表盘
- Rich HUD 状态栏
- 流式 Markdown 渲染

---

## [v0.41.0] - 2026-04-03

### 🆕 新增
- 多 LLM 提供商支持 (8+)
- WebSocket 远程代理
- Token 追踪和成本估算

---

[未发布]: https://github.com/user/claw-code-tingfeng/compare/v0.43.0...HEAD
[v0.43.0]: https://github.com/user/claw-code-tingfeng/releases/tag/v0.43.0
[v0.42.0]: https://github.com/user/claw-code-tingfeng/releases/tag/v0.42.0
[v0.41.0]: https://github.com/user/claw-code-tingfeng/releases/tag/v0.41.0

# ADR 0019 — `src/hooks/` 保留为参考快照，不接线；活的 Hook 系统是 `src/core/hook_registry`

- 日期：2026-10-29
- 状态：已采纳
- 相关：ADR 0018（MCP 单一真相源，同样的判断方式）

## 背景（实测证据）

`src/hooks/` 共 **10 个模块 / 2,541 行**，全部**不可达**：
`scripts/reachability.py --list` 把它们逐条列为不可达；`grep -rn "src.hooks" src/ tests/`
除 `src/core/events/__init__.py` 里那条 `from ..hooks import ...`（解析到
`src.core.hooks`，是另一个模块）外没有任何引用。

逐模块看它们在想解决什么，以及仓库里**已经有什么**：

| 模块 | 行数 | 它想做的事 | 仓库里已经有的活实现 |
|---|---:|---|---|
| `codebase_map.py` | 196 | 文件节点 + import 关系图谱 | `src/rag/repo_map.py`（Aider 风格符号图）、`src/brain/world_model` |
| `explore_routing.py` | 417 | 探索模式的技能路由 | `src/agent/intent_router.py` + `keyword_registry.py` |
| `agents_overlay.py` | 166 | Agent 分层遮罩/覆盖状态 | `src/agent/definitions.py` + `src/agent/swarm/roles.py` |
| `prompt_guidance_contract.py` | 209 | 校验提示词模板是否含必需语句 | 无对等物，但**模式串是 omx 专属**（"Choose the lane before acting" 等），套到我们的模板上只会恒假 |
| `session.py` | 260 | 会话期 Hook 上下文 | `src/core/hook_registry/specs.py::HookContext`（已接线） |
| `extensibility/`（7 模块） | 1,464 | 插件加载/分发/SDK | `src/plugins/`（`websocket_server.py` 在用） |

## 决策

1. **不接线**。把这些模块接进主流程会立刻制造"第二套真相源"——这正是 ADR 0018 刚
   规避掉的问题。它们的语义（omx 的 lane / overlay / 专属提示词契约）与 clawd 的实际
   架构不对齐，硬接只会得到"看起来有、实际恒假"的功能。
2. **不删除**（项目规则明确要求：发现无关死代码先提示、不删）。每个模块 docstring 顶部
   加一行 note，指明它是上游快照、活的实现对位表、以及不要在此新增功能。
3. **活的 Hook 系统 = `src/core/hook_registry/`**，v0.76.5 起已在引擎五个点真实接线
   （`SESSION_START` / `SESSION_END` / `PRE_TOOL_USE` 可 DENY / `POST_TOOL_USE` / `TOOL_ERROR`），
   有测试 `tests/agent/test_engine_hooks_wiring.py` 守着。

## 代价

- 仓库里继续躺着 2,541 行不可达代码，`reachability` 的"不可达体量"指标不会下降。
- 新人可能误改一份永远不会跑的代码。缓解：docstring note + 本 ADR。

## 何时应重新考虑

- 当 `prompt_guidance_contract` 的断言被改写成**我们自己的**提示词契约（并进 CI 校验
  `src/llm/prompts/*` 与 `prompts/agents/*`），它就有价值了 —— 那时应迁到 `src/agent/`
  并配测试，而不是留在 `src/hooks/`。
- 或者：决定彻底清理死代码时，整目录删除（git 历史可追），而不是挑着接。

## 验证命令

```bash
venv/Scripts/python.exe scripts/reachability.py --list | grep "src.hooks"   # 仍列在不可达里（本轮不动）
py -3.10 -m pytest tests/agent/test_engine_hooks_wiring.py -q               # 10 passed（活的 hook 系统）
```

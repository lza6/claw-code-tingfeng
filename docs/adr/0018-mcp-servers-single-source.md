# ADR 0018 — MCP 状态/记忆/追踪服务器的单一真相源

- 日期：2026-10-29
- 状态：已采纳
- 相关：ADR 0011（内置优先、MCP 仅跨引擎桥）、ADR 0017（多引擎协同）

## 背景（审计证据）

同一能力存在两套实现，且**生成配置指向的那套当时根本起不来**：

| 能力 | 路径 A（被登记） | 路径 B（有对外导出、无入口） |
|---|---|---|
| state | `src/core/mcp/state_server.py`（190 行） | `src/mcp/state_server.py`（493 行） |
| memory | `src/core/mcp/memory_server.py`（341 行） | `src/mcp/memory_server.py`（182 行） |
| trace | `src/core/mcp/trace_server.py`（278 行） | `src/mcp/trace_server.py`（221 行） |

- `DEFAULT_MCP_SERVERS` 登记的是 A，但 A **没有 `__main__`**：`python -m src.core.mcp.state_server`
  以 exit 0 静默退出、零输出，MCP 客户端只看到 EOF → 对外承诺的四个 server 全部不可用。
- B 只在 `src/mcp/__init__.py` 里被 re-export，无 spawn 入口，API 与 A 不同
  （`MemoryEntry` vs `MemoryEntity`；state 按"模式"组织 vs 按 session/surface 组织）。
- `src/core/mcp/trace_server.py` 的工具名还被写成 `sumsummarize_trace`，调用必失败。

## 决策

1. **`src/core/mcp/` 是唯一真相源（canonical）**：生成配置、CLI、`collaborate` 都只认它。
2. 为 A 补上通用 stdio 协议层 `src/core/mcp/stdio_server.py`（initialize / tools/list /
   tools/call / ping，UTF-8 逐行 flush），四个模块各自获得 `main()` + `__main__`。
3. **`src/mcp/{memory,state,trace}_server.py` 冻结为 legacy**：仅在模块 docstring 标注，
   不删除（有历史导入路径），**不再新增功能**，避免第二套实现继续漂移。
   `src/mcp/domain_server.py`（领域工具桥）与 `src/mcp/client.py` 不是重复实现，正常演进。
4. 生成配置里的 `command` 从裸 `"python"` 改为 `sys.executable`：
   本机裸 `python` 指向 3.14（缺 loguru 等运行依赖），spawn 起来会立即失败。

## 后果

- 正向：四个 server 真的能被 MCP 客户端握手并调用（已验证：真实 spawn 全部返回
  `serverInfo` + 工具清单；`set_surface`/`get_surface`/`create_entity`/`search_memory`
  完成真实往返）。工具名拼写错误已修，且有测试守着"注册的工具必须有真实方法"。
- 负向：仓库里仍存在三对同名文件，新人可能误改 legacy 那份。缓解：legacy 文件头
  有明确 note，本 ADR 记录判断依据。
- 未处理：legacy 实现里独有的功能（如按模式组织的 state）没有迁到 canonical。
  若将来需要，应先在 `src/core/mcp/` 加能力 + 测试，再把 legacy 改成薄适配层。

## 验证命令

```bash
py -3.10 -m pytest tests/mcp/test_core_stdio_server.py -q      # 15 passed
python -m src.core.mcp.state_server < <(printf '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n')
```

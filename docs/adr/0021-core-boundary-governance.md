# ADR 0021 — `src/core/` 边界治理：分层方向 + 存量登记 + 规模告警

- 日期：2026-10-30
- 状态：已采纳
- 相关：审计 P3-1「src/core/ 作为杂物间（161 文件 / 34,923 行）的边界治理」

## 背景

`src/core/` 目前 **153 文件 / 34,112 行**，混居 config/auth/patch/persistence/events/hooks/journal/secrets 等。
彻底拆包是重构级工程（跨模块、高风险），但**不做任何约束**它会继续膨胀并反向依赖上层。

本轮实测到 **6 处向上层 import**（core → tools_runtime / workflow）：
`args_parser.py`、`config/generator.py`、`patch/atomic_patcher.py`（2 处）、`persistence/run_state.py`、`security/allowlist.py`。

## 决策

1. **分层方向硬约束**：`core` 必须是最底层，禁止 import `cli` / `tools_runtime` / `agent` / `server` / `workflow`。
2. **存量登记**：上述 6 处进 `scripts/core_surface_allow.json` 并注明"待迁移"；脚本只阻断**新增**越界，
   存量按清单逐步清零（不是永久豁免）。
3. **公开面登记**：`src/core/__init__.py` 的 `__all__`（当前 89 个符号）即对外承诺；新增对外符号需登记。
4. **规模告警**：文件 > 200 或行数 > 40,000 时提示"新能力请放专用子包"，不阻断。
5. 门禁：`scripts/core_surface.py`（越界即退出 1），已接入 `scripts/verify_audit_p1.py`。

## 代价

- 迁移存量 6 处需要动 `patch` / `config` / `security` 这几个热路径，本轮**没做**（高风险、收益慢）。
- 允许清单可能变成"垃圾桶"，所以每条都写了 reason 与迁移方向。

## 何时重新考虑

- 当 core 文件数继续增长到 > 200，或再出现 3 处以上新越界时，应启动真正的拆包（core/config、core/patch、
  core/persistence 各自独立子包，共享的只有 protocols 与 exceptions）。

## 后续（2026-10-30，v0.88.4）：存量已清零

允许清单从 5 条（`args_parser` / `config/generator` / `patch/atomic_patcher` / `persistence/run_state` /
`security/allowlist`）降到 **0 条**，`core_surface_allow.json` 只剩注释。查证过程有个重要发现：
**其中 3 处指向的名字/模块全仓库都不存在**（`bash_constants.READ_ONLY_GIT_SUBCOMMANDS`、
`code_edit.EDIT_FORMAT_REGISTRY`、`tool_manager.TOOL_REGISTRY`），全靠 `except ImportError` 的内联兜底
活着 —— 也就是说它们既是"越界 import"，又是"死引用"，清单当初把**不存在的依赖**也登记成了"待迁移"。

处理方式（按依赖的**真实性**分流，而不是一律搬迁）：

| 类型 | 处理 | 实例 |
|:---|:---|:---|
| 真依赖、纯函数/纯枚举、无上层依赖 | **下沉到 core**，原处 re-export 保持兼容 | `patch/fuzzy_matcher.py`、`workflow_status.py` |
| 死引用（目标不存在） | **删 import**，把内联兜底提升为唯一来源 | `allowlist` 的只读子命令表、`args_parser` 的编辑格式表 |
| 死引用 + 上层概念 | **改成调用方注入** | `config/generator.generate_tool_signatures(tools=)` |

顺带修掉同一批文件里 3 个"调用即崩"的缺陷（`clawd config generate` 100% AttributeError、
`generate_tool_signatures` 必然 ModuleNotFoundError、`categories: []` 让技能静默消失）。

**踩坑记录**：本想放 `core/models/workflow_status.py`，但 `core/models.py` **已经是一个模块** ——
Python 中同名目录（包）会优先于同名模块，于是整个 `core.models` 被静默劫持
（`from .models import PermissionDenial` 直接 ImportError）。最终放 `core/workflow_status.py`。
**新增子包前先 `ls` 目标目录，确认没有同名 .py。**

**经验**：治理清单里的"待迁移"要先验证依赖**是否存在**再动手 —— 不存在的依赖不是"迁移对象"，
是"该删的死引用"。否则会把死代码从一层搬到另一层，越治越乱。


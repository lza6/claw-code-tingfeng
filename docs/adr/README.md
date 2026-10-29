# 架构决策记录（ADR）

> 只记录**会影响后续判断**的决策，不记录日常改动。
> 每条包含：背景 → 决策 → 代价 → 何时应重新考虑。

---

## 📑 ADR 索引（先看这里）

**汇总在本文件内**：0001~0006（见下）

**独立文件**（每条一个文件，含完整背景/代价/边界）：

| 编号 | 决策 | 文件 |
|:---|:---|:---|
| 0009 | 采用 OpenAI Codex 作为外部 agent 内核后端 | [0009-adopt-codex-as-backend.md](0009-adopt-codex-as-backend.md) |
| 0010 | 多引擎整合：统一驱动 + MCP 领域工具反向供给 | [0010-multi-engine-integration.md](0010-multi-engine-integration.md) |
| 0011 | 领域能力内置优先 + 索引自动预热 + 大仓库保护 | [0011-native-domain-tools-and-warmup.md](0011-native-domain-tools-and-warmup.md) |
| 0012 | 定向汲优补缺：LSP / 检查点压缩 / 笔记本（含两级删除） | [0012-targeted-absorb-lsp-compaction-notebook.md](0012-targeted-absorb-lsp-compaction-notebook.md) |
| 0013 | 权限决策引擎：会话授权 / 拒绝理由回灌 / 写入边界 | [0013-permission-engine.md](0013-permission-engine.md) |
| 0014 | 命令执行策略（execpolicy）+ 会话分叉元数据 | [0014-exec-policy-and-session-fork.md](0014-exec-policy-and-session-fork.md) |
| 0015 | 会话存储收敛：两套并存 + 无人写盘的连环缺陷 | [0015-session-storage-consolidation.md](0015-session-storage-consolidation.md) |
| 0016 | 挂机自主决策引擎 + 权限全中文表达 | [0016-autonomy-and-chinese-permissions.md](0016-autonomy-and-chinese-permissions.md) |
| 0017 | 多引擎协同（plan→execute→review→返工）+ 两处误判更正 | [0017-multi-engine-collaboration.md](0017-multi-engine-collaboration.md) |
| 0018 | MCP 状态/记忆/追踪服务器的单一真相源（core/mcp 为准，其余冻结） | [0018-mcp-servers-single-source.md](0018-mcp-servers-single-source.md) |
| 0019 | `src/hooks/` 是上游参考快照，不接线；活的 Hook 系统是 `src/core/hook_registry` | [0019-hooks-package-is-reference-only.md](0019-hooks-package-is-reference-only.md) |

> 判断某个改动"为什么要这么做"时，先查 ADR 再查 commit；两者冲突以 ADR 为准（commit 可能只写了当时的一半理由）。

---

## ADR-0001：用「可达性 + 导入扫描」双闸门判断模块是否可用

**背景**
`scripts/reachability.py` 只回答"从生产入口有没有 import 链"。v0.57.0 实测发现
有 16 个模块静态可达、但 `import` 就抛异常（属性名漂移、相对导入越界、
类名不存在）。"可达"被误当成"可用"。

**决策**
两条都跑，缺一不可：

```bash
python scripts/reachability.py      # 能否走到
python scripts/import_sweep.py      # 走到了会不会炸
```

`import_sweep.py` 必须区分「项目内缺模块」（真缺陷）与「第三方依赖未安装」
（环境问题），否则会制造大量假问题。

**代价**
每次删除/改导入多花约 1 分钟。

**何时重新考虑**
若引入 `mypy --strict` 且 CI 强制执行，可部分替代导入扫描；但两层语义
（可导入 vs 可调用）仍需真实执行验证。

---

## ADR-0002：伪实现零容忍 —— 桩必须自报为桩

**背景**
生产管道 `pipeline.py` 的验证阶段曾硬编码 `verification_result="passed"`，
从不运行任何测试。未接线的 `ralph_verify_stage.py` 循环结构完整，但循环体
同样永远返回 `approved: True`。两者都是桩，前者更危险——它**谎称通过**。

**决策**
1. 桩一律返回可检测的"未实现"值（`verified: False` / `"not_implemented"`），
   不得返回成功语义。
2. 消费者必须区分 `not_implemented` 与 `failed`。
3. 不为了"看起来完整"而补造一个永远通过的模块（`consensus.py` 即因此未补）。

**代价**
短期看到更多 `not_implemented`；依赖 `=="passed"` 的自动化流程需要适配。

**何时重新考虑**
当验证阶段真正接入测试执行器后，可恢复 `passed/failed` 二值。

---

## ADR-0003：单一 CLI 入口

**背景**
仓库同时存在 argparse（`src/main.py`）与 Typer（`src/cli/entrypoint.py`）两套 CLI，
命令集不同，且 `workflow` 在两边语义不同。文档示例混用两者，照抄即失败。

**决策**
- 规范入口：`clawd` = `python -m src`（Typer）。
- `python -m src.main` 保留为历史 argparse 入口，不再作为文档推荐用法。
- 命令行名不得与命令组名冲突（Typer 中组会遮蔽命令）。

**代价**
`python -m src.main` 的用户需要迁移到 `python -m src`。

**何时重新考虑**
若决定彻底废弃 argparse CLI，可删除 `src/main.py` 中的命令分发层
（保留 `initialize` / `_register_shutdown_hooks` 等被 Typer 复用的部分）。

---

## ADR-0004：维度系统只保留一份实现

**背景**
存在两份 `BUILTIN_DIMENSIONS`：
- `src/core/config/dimensions.py`（中文，生产可达，被 config resolver 使用）
- `src/workflow/dimensions.py`（英文，生产不可达）

同时 CLI 的 `-d/--dimension` 只写入运行时配置，**无人读取**。

**决策**
统一使用 `src/core/config/dimensions.py`。引擎在 `run()` 中解析运行时配置，
注入执行器提示词，并挂到 `WorkflowTask.dimensions` 持久化。

**代价**
英文内置库的措辞（更简洁）不再生效；如需英文，应在中文库里维护双语。

**何时重新考虑**
若维度系统扩展到需要按语言切换，再引入 i18n 层，而不是维护两份库。

---

## ADR-0005：测试不得为变绿而放宽断言

**背景**
`tests/workflow/test_pipeline_orchestrator.py` 从初始提交起从未通过，
引用了一批 git 全历史中不存在的 API。若简单删除失败断言，会永久丢失
它原本想验证的行为。

**决策**
处理顺序：
1. 先判断"是测试引用幽灵 API，还是实现被误删"（`git log -S"符号名"`）。
2. 幽灵 API → 按**真实 API 重写测试，保留原行为意图**；
   重写过程中暴露的实现缺陷一并修掉。
3. 实现被误删 → 补实现。
4. 只有在"断言本身算错"（如事件计数 1+3+2+1+1 写成 7）时才改数字，
   并在注释里写明算式。

**代价**
重写测试比删断言慢得多。

**何时重新考虑**
不重新考虑。这是底线。

---

## ADR-0006：测试必须隔离进程级全局状态

**背景**
两次真实事故：
- `tests/agent/test_approval_gate.py` 调用 `set_allowed_workdirs()` 修改进程全局
  且不恢复 → 合并运行时 6 个看似无关的 bash 用例变红，单独跑全绿。
- 新增的维度测试调用 `set_config("dimensions", ...)` 不恢复 →
  `test_workflow.py::test_run_with_code` 在合并运行时带着维度配置启动，
  触发了接线代码里的 `FrozenInstanceError`（`WorkflowTask` 是 frozen dataclass，
  不能原地赋值）。泄漏让一个**只在配置生效时才走到**的缺陷暴露出来——
  但它同样说明：不隔离的测试会把失败归因到错误的地方。

**决策**
任何修改进程级全局（环境变量、模块级可变对象、运行时配置）的测试，
必须用 `autouse` fixture 在用例前后快照/恢复，且**只回滚自己改的键**，
不要调用 `clear_*()` 清空他人设置。

**代价**
每个此类测试文件多 10 行样板。

**何时重新考虑**
若项目引入 pytest-xdist 的进程隔离，泄漏的爆炸半径会变小，但同进程内的
顺序依赖仍会发生——隔离仍需保留。

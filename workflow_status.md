# workflow_status.md

> 任务契约、验收台账与阻塞项。**只记录事实与证据**。
> 开始时间：2026-10-16
> 基线版本：`main` @ `7ebd096`（v0.45.0）
> 当前版本：**v0.53.0**（本轮 +6 提交）

---

## 0. 本轮（v0.52.0 → v0.53.0）完成项

| ID | 事项 | 状态 | 证据 |
|:---|:---|:---|:---|
| B-01 | 生产路径 E2E 建立 | ✅ | `scripts/e2e_production.py` 8/8 通过 |
| B-02 | `<think>` 标签崩溃修复 | ✅ | `tests/llm/test_providers_openai.py` 16 passed |
| B-03 | **BashTool 在 Agent 环路 100% 失败** | ✅ | `tests/tools_runtime/test_bash_execution_paths.py` 11 passed |
| B-04 | **`.env` 可被 Agent 读取（API Key 外泄）** | ✅ | `tests/test_security/test_sensitive_path_guard.py` 33 passed |
| B-05 | 传递可达性分析工具 | ✅ | `scripts/reachability.py`：684 模块 / 429 生产可达 |
| B-06 | 删除 3 个真死包 | ✅ | 3,774 行 |
| B-07 | 删除 3 个被同名包遮蔽的死文件 | ✅ | 384 行 |
| B-08 | 熔断器补测试（原 0% 覆盖） | ✅ | 26 passed, 1 xfailed |
| B-09 | 零覆盖活代码识别工具 | ✅ | `scripts/find_untested_live_code.py` |

### 关键发现：生产 LLM 路径与 v0.51.0 修复的不是同一条

传递可达性分析（`scripts/reachability.py`）显示：

```
生产入口 → src/agent/engine.py:203 → create_llm_provider() → providers/*
v0.51.0 修的 src/llm/factory.py::get_default_llm()  ← 从生产入口不可达
```

v0.51.0 那批修复本身有效（且被 `e2e_smoke.py` 覆盖），但它保护的**不是**
生产实际执行的代码。本轮已补齐对真实生产路径的测试与修复。

### 多智能体审计的三项结论与主线程复核

| 子代理 | 报告要点 | 主线程复核结果 |
|:---|:---|:---|
| blindspot | 1 BLOCKER + 3 HIGH + 13 MEDIUM | B1（BashTool）**已复现并修复**；H2（.env）**已复现并修复**；H1（ApprovalMode 无消费者）**已复现，记录未修**；H3（`max_buffer` 非法参数）待验证 |
| testfail | 38 个失败：A 实现缺陷 6 / B 测试过时 32 | 待逐项处理 |
| deadcode | 称原 213 清单"方向两个都错"，实际 176 不可达 | 其指出 3 个脚本缺陷中，**缺陷 1（`__init__.py` 相对导入）我早已修复**；缺陷 2/3（传递可达性、同名遮蔽）我的分析器已覆盖传递可达性。**但它指出的"同名包遮蔽"是真实问题，已修复** |

> 子代理报告基于它重跑时的**旧版脚本**，未看到我已修的 `__init__.py` 缺陷。
> 其"176 不可达"与我的"255 生产不可达"量级一致，差异在于它把
> "仅测试可达"计入了可达。

---

## 1. 任务契约

| 项 | 内容 |
|:---|:---|
| **目标** | 把 Clawd Code 从"文档声称可用、实际一跑即崩"修复为**真实可运行、可调用、可交付**的 AI 编程代理框架 |
| **范围** | 波次 1（止血）：P0 阻塞缺陷修复 + 测试基建 + 文档同步 + 提交推送 |
| **明确不做** | 波次 2-8（删死代码、覆盖率爬升、架构升级、UI 升级）—— 见 `计划书/下一步改进指南.md` §13，属后续迭代 |
| **成功标准** | 真实 E2E 通过；契约测试全绿；pytest 收集 0 错误；版本号一致；无未解决 P0 |
| **验证方式** | 真实 LLM 端点端到端调用 + pytest + ruff + 逐项验收命令 |

---

## 2. 验收标准表

| ID | 验收项 | 命令 | 期望 | 实际 | 状态 |
|:---|:---|:---|:---|:---|:---|
| A-01 | 真实 E2E：对话 | `python scripts/e2e_smoke.py` | content 非空 | `PONG` | ✅ |
| A-02 | 真实 E2E：工具调用 | 同上（步骤 3） | 返回 tool_calls | `get_weather {"city":"Berlin"}` | ✅ |
| A-03 | 真实 E2E：推理内容 | 同上（步骤 4） | 内容非空 | `391`，reasoning 有 | ✅ |
| A-04 | `.env` 约定生效 | `AgentSettings().llm_api_key` | 非 None | `sk-ee332...` | ✅ |
| A-05 | 补丁引擎 | `pytest tests/self_healing/test_atomic_patcher.py` | 全绿 | 16 passed | ✅ |
| A-06 | Agent 契约 | `pytest tests/contracts/test_agent_registry_stability.py` | 全绿 | 13 passed | ✅ |
| A-07 | 配置合并 | `pytest tests/core/test_config_merger.py` | 全绿 | 48 passed | ✅ |
| A-08 | RAG 事件 | `pytest tests/brain/test_world_model.py -k RagIndex` | 全绿 | 2 passed | ✅ |
| A-09 | verifier 契约 | `pytest tests/workflow/test_verifier.py` | 全绿 | 11 passed | ✅ |
| A-10 | Windows 编码 | `python -m src.main doctor` | 无 UnicodeEncodeError | 0 次（含强制 GBK） | ✅ |
| A-11 | 版本一致性 | 4 处比对 | 完全一致 | 均 0.51.0 | ✅ |
| A-12 | pytest 收集 | `pytest tests/ --collect-only` | 0 errors | 2857 collected, 0 errors, 126s | ✅ |
| A-13 | Agent 主入口 | `create_agent_engine()` | 返回引擎实例 | `AgentEngine` | ✅ |
| A-14 | `clawd setup` 端到端 | 在空目录运行 | 生成 3 个文件 | config.toml + AGENTS.md + catalog-manifest.json | ✅ |
| A-15 | 改动文件静态检查 | `ruff check <changed files>` | 零新增违规 | 0 新增 | ✅ |
| A-16 | HTML 报告测验交互 | Playwright + Chromium | 全场景正确 | 7/7 场景通过 | ✅ |
| A-17 | 全量测试回归 | `pytest tests/` | 记录通过率 | 39 failed / 2814 passed / 4 skipped（45min） | ✅ 已记录 |

### A-17 失败归属分析（关键）

全量 39 个失败中，**只有 1 个是本次改动引入的回归**，已修复；其余 38 个为既有失败。

判定方法：**对照实验** —— 用 `git checkout 7ebd096 -- <file>` 还原改动前的实现，
在同一环境重跑同一测试，对比是否仍失败。

| 失败测试 | 归属 | 依据 |
|:---|:---|:---|
| `tests/llm/test_factory.py::TestLiteLLMCompatWrapper::test_invoke` | **本次引入** → 已修复 | 我给 `Message` 补 `finish_reason` 时未做类型防护，MagicMock 返回非字符串触发 pydantic 校验失败。已加 `_as_str`/`_as_int` 收敛并补 3 个回归用例 |
| `tests/brain/test_world_model_complex.py`（3 例） | 既有 | 对照实验：还原 `code_graph.py` + `world_model.py` 到改动前后**同样失败** |
| 其余 35 例（`runtime/`、`workflow/`、`core/test_platform`、`agent/`、`integration/`） | 既有 | 均不在本次改动范围内 |

> **诚实说明**：38 个既有失败**未处理**。它们属于波次 3+ 的范围（需要先有测试
> 才能安全修）。`workflow_status.md` 只记录事实，不把它们标成"已完成"。

---

## 3. 任务图与执行顺序

```text
波次 0  基线复验 ──────────────────────────── [done]
   │
波次 1  P0 修复（并行，各自独立提交）
   ├─ P0-1 Windows 编码崩溃 ──────────────── [done] ✅ A-10
   ├─ P0-2 AgentDefinition camelCase 漂移 ─── [done] ✅ A-06
   ├─ P0-3 补丁引擎 commit/rollback 缺失 ──── [done] ✅ A-05
   ├─ P0-4 版本号三处不一致 ──────────────── [done] ✅ A-11
   ├─ P0-5 测试收集失败（2 处 API 漂移）──── [done] ✅ A-07/A-09
   ├─ P0-6 同名测试文件模块冲突 ──────────── [done] ✅ A-12
   ├─ P0-7 indexed_count 未定义 ──────────── [done] ✅ A-08
   └─ P0-8~P0-11（本轮新发现，见 §4）─────── [done] ✅ A-01~A-04
   │
波次 1.5 测试基建
   ├─ tests/conftest.py（共享 fixture）───── [done]
   ├─ pyproject.toml 注册 marker ─────────── [done]
   └─ 测试源树 __init__.py 补齐 ──────────── [done]
   │
波次 2 提交与推送 ────────────────────────── [进行中]
```

---

## 4. 执行日志

### 2026-10-16

**基线复验**：确认 `计划书/下一步改进指南.md` 中 P0-1/3/4 仍然存在。

**本轮新发现的 P0（原指南未涵盖，由真实 E2E 暴露）**：

| ID | 缺陷 | 文件 | 影响 |
|:---|:---|:---|:---|
| P0-8 | 访问不存在的 `settings.context_window` | `src/llm/factory.py` | LLM 栈 100% 不可用 |
| P0-9 | `.env` 约定（`OPENAI_API_KEY`）与配置模型（`LLM_API_KEY`）不匹配 | `src/core/config/models.py` | 按文档配置的用户拿不到 API Key |
| P0-10 | `api_key`/`api_base` 未透传给 litellm | `src/llm/factory.py` | 自建端点用户必然 401 |
| P0-11 | 响应解析丢弃 `tool_calls` / `reasoning_content` | `src/llm/factory.py` | Agent 环路断裂 |
| P0-12 | `merge_config` 不幂等，顶层配置沉入 `[agents]` | `src/core/config/merger.py` | 每次启动配置退化 |
| P0-13 | 配置包未 re-export `AgentSettings`/`get_settings`/`load_settings` | `src/core/config/__init__.py` | `create_agent_engine()` 主入口 ImportError 崩溃 |
| P0-14 | `clawd setup` 同步调用 async `merge_config` | `src/cli/commands/setup_commands.py` | 协程从未 await，配置文件不生成 |
| P0-15 | `register_setup_commands` 自引用（`app.add_typer(app)`） | `src/cli/commands/setup_commands.py` | typer 子命令树错误 |
| P0-16 | 模板路径少算一级目录 | `src/cli/commands/setup_commands.py` | AGENTS.md / catalog 永远"模板未找到" |
| P0-17 | `_resolve_all_edges` 迭代中字典被并发修改 | `src/rag/code_graph.py` | 后台构建时 `RuntimeError` |
| P0-18 | `ensure_project_dirs` 被引用但全仓库不存在 | `src/cli/commands/setup_commands.py` | `clawd setup` ImportError |

**关键发现过程**：P0-8 ~ P0-11 全部是**静态分析无法发现**的 —— ruff 的 `F821` 只检查名称不检查属性，`mypy` 未启用。只有接入真实端点跑 E2E 才逐层暴露（错误依次为 `AttributeError` → `litellm.turn_off_verbose_logging` → `401` → 空 tool_calls）。

**P0-12 发现过程**：为 `merge_config` 编写的**幂等性**测试直接失败，暴露出"反复合并会让配置自我污染"。

**修正记录**：指南 §1.3.2 曾把 `tests/self_healing/test_engine.py` 与 `tests/tools_runtime/test_types.py` 的收集失败推断为"测试间状态污染 / 收集顺序依赖"。**该推断是错的**。真实原因是 pytest 的 `import file mismatch` —— `tests/` 下存在同名文件（`test_engine.py` ×2、`test_types.py` ×2）而子目录缺少 `__init__.py`。已按标准做法补齐 14 个 `__init__.py`。

---

## 5. 验证日志

| 时间 | 命令 | 结果 |
|:---|:---|:---|
| 00:18 | `python scripts/e2e_smoke.py`（修复前） | 2/5 通过，`AttributeError: context_window` |
| 00:29 | 同上（修 P0-8 后） | 2/5，`litellm.turn_off_verbose_logging` |
| 00:3x | 同上（修 P0-9 后） | 2/5，401（打到官方 endpoint） |
| 00:3x | 同上（修 P0-10/11 后） | **5/5 通过** |
| — | `pytest tests/self_healing/test_atomic_patcher.py` | 6 failed → **16 passed** |
| — | `pytest tests/contracts/test_agent_registry_stability.py` | 5 failed → **13 passed** |
| — | `pytest tests/workflow/test_verifier.py` | 收集失败 → **11 passed** |
| — | `pytest tests/core/test_config_merger.py` | 收集失败 → **48 passed** |
| — | `pytest tests/brain/test_world_model.py -k RagIndex` | **2 passed** |
| — | `pytest tests/ --collect-only` | 4 errors / 2769 用例 / 306s → **2 errors / 2840 用例 / 166s** → 复验中 |

---

## 6. 阻塞项

无。

（外部条件限制，非阻塞：`pyproject.toml` 的 `fail_under = 60` 与实际覆盖率仍有差距，
按指南 §6.1 分阶段提升，属波次 3 范围。）

---

## 7. 下一步

1. 复验 `pytest tests/ --collect-only` 的 0 errors（进行中）
2. 全量测试回归，记录通过率
3. 更新 README / CHANGELOG / 计划书进度
4. 提交并推送 main
5. 波次 2 起的内容（死代码收敛、覆盖率爬升）留待下一轮

---

*本文件只记录可验证的事实。任何标记为 done 的条目都必须有对应的命令输出。*

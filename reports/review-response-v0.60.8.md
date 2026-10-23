# 独立审查响应记录（v0.60.8，2026-10-23）

> 审查方：只读子代理（`reviewer-round4`），范围为本轮全部 git diff + 7 项疑点清单。
> 结论：**Request Changes**，5 个阻塞项 + 6 条 Required。
> 本文件记录逐条响应与**真实复验证据**。
> 关联：`reports/final-report-v0.60.7.md`（主报告）· `test_ledger.md` · `CHANGELOG.md` v0.60.8 段

---

## 1. 审查结论与我的判断

审查给的是 **Request Changes**，且每条都附了可复现命令。我逐条复现，**全部成立**，没有一条是误报。
其中三条最扎心：

1. **C-2/C-3：我自己写的"单一取数入口"在说谎。** `baseline.py` 的三个指标恒为 `null`，
   而 `null` 又被判为通过 —— 即"什么都没测到"也算成功。
   我在上一轮还把它写进 `CLAUDE.md`："17 项指标一条命令出数，文档里的数字以它为准"。
   一份会返回 `exit=0` 的坏尺子，比手抄数字更危险。
2. **C-1：我新加的 CI 门禁第一次推送就会红。** `numpy` 从未声明，本机因系统 Python
   装过而看不见，干净环境 `collect` 直接 1 error。**"本地通过"不等于"CI 通过"**。
3. **C-4：死代码名单有 35% 假阴性。** 判据不认相对导入，而 `src/agent/modes/__init__.py:17`
   就是 `from .architect import X` —— 按我那份名单删，`import src.agent.modes` 当场崩。

**C-5 最危险**：`classify()` 把与 `src/` 子目录同名的第三方包判成"项目代码缺陷"，
而 `--strict-exit` 会把它升级成 CI 阻断。方向完全相反：该装依赖，却报"你代码有 bug"。

---

## 2. 逐条响应

### C-1 干净环境 collect 失败 → ✅ 已修复

| 项 | 内容 |
|:---|:---|
| 复现（修前） | `venv/Scripts/python.exe -m pytest tests/ --collect-only -q` → `3259 collected, 1 error`, exit=2；`ERROR tests/memory/test_faiss_store.py: ModuleNotFoundError: No module named 'numpy'` |
| 根因 | `tests/memory/test_faiss_store.py` 顶层 `import numpy`；`numpy` 不在任何依赖清单。`ci.yml` 用 `pip install -e ".[dev]"`，ubuntu 没有 numpy |
| 修复 | `pyproject.toml` 的 `[project.optional-dependencies].dev` 加 `numpy>=1.24` |
| 复验（修后） | `3261 tests collected in 4.03s`，0 error |

### C-2 / C-3 baseline.py 失败吞成功 → ✅ 已修复（含负向测试）

**证据（修前，审查给出、我复现）**：
```
collect      : {"collected": 3259, "errors": 1, "exit_code": 2, "status": "failed"}
import_sweep : {"fail": null, "import_exit": null, "dep_missing": null}
reachability : {"reachable": null}
→ 脚本 exit=0
```

**根因（三条叠加）**：
1. `import_sweep` 汇总行在 stdout **顶部**，642 次 import 的 loguru 日志在 stderr，
   `out = stdout + stderr` 后取末 6 行 → 只剩噪音；
2. `reachable` 用中文锚点正则解析子进程 stdout，而子进程按 GBK 输出 → 恒 None；
3. `hard_fail` 写 `fail not in (0, None)` → **None 算通过**，且不含 collect / reachability / 覆盖率。

**修复**：
| 动作 | 文件 |
|:---|:---|
| `reachability.py` 新增 `--json`（输出 `prod_reachable` 等结构化字段） | `scripts/reachability.py` |
| `baseline.py` 改为**消费 JSON**（`_run_to_json`），不再抠中文 stdout | `scripts/baseline.py` |
| `_run` 强制 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`；输出尾部 6 → 20 行 | 同上 |
| 门禁重写为 `_hard_fail_reasons()`：**`None` 一律算失败**；collect 退出码、reachability 缺失、覆盖率低于阈值全部纳入 | 同上 |
| `_interp_runtime()`：venv 不存在时回退当前解释器（ubuntu 上不再静默 error） | 同上 |

**复验（修后）**：
```
import_sweep : {"fail": 0, "import_exit": 0, "dep_missing": 7, "parse_error": null}
reachability : {"prod_reachable": 443, "fully_unreachable": 134, "parse_error": null}
→ exit=0（真实全绿才会 0）
```
**负向测试**：`tests/scripts/test_baseline_gate.py`（14 例）——把任一字段改成 `None`、
把 collect 改成 `exit_code=2`、把可达数改成 442，`_hard_fail_reasons` 必须返回非空。
`test_thresholds_are_single_source_of_truth` 还断言 `MIN_COVERAGE_PERCENT == pyproject.fail_under`。

### C-4 NO_REFS 35% 假阴性 → ✅ 已修复，名单重出

| 项 | 内容 |
|:---|:---|
| 复现 | `rg -n "from \.architect import" src/agent/modes/__init__.py` → `17:from .architect import ArchitectMode`，而报告里 `src.agent.modes.architect` 被判 `NO_REFS / 静态引用：无` |
| 修复 | 新增 `_parent_package_references_leaf()`：覆盖 `from .<leaf> import`、`from . import <leaf>`、`from .<leaf>.`；搜索范围补 `skills/ prompts/ hooks/ references/ .claude/`；排除脚本自身（其 docstring 示例会把自己扫成"动态引用"，这是修复过程中新发现的**自指污染**） |
| 复验 | **NO_REFS 112 → 71**；HAS_REFS 16 → **57**；DYNAMIC 2 → 0（自指污染消除后） |
| 独立核验 | `src.agent.modes.architect` 现在判 `HAS_REFS`，引用依据写明 `src/agent/modes/__init__.py（父包相对导入）` |

### C-5 classify 归因反向 → ✅ 已修复

| 输入 | 修前 | 修后 |
|:---|:---|:---|
| `ModuleNotFoundError('mcp')` | IMPORT-FAIL ❌（mcp 是本批刚声明的第三方包） | **DEP-MISSING** ✅ |
| `ModuleNotFoundError('numpy')` | DEP-MISSING | DEP-MISSING ✅ |
| `ModuleNotFoundError('pathspec')` | DEP-MISSING | DEP-MISSING ✅ |
| `ModuleNotFoundError('loguru')` | DEP-MISSING | DEP-MISSING ✅ |
| `ModuleNotFoundError('config')`（`src/config/` 存在） | IMPORT-FAIL | IMPORT-FAIL ✅（确是绝对导入写错） |
| `ModuleNotFoundError('src.nope')` | IMPORT-FAIL | IMPORT-FAIL ✅ |

修复：新增 `_declared_distributions()` 读 `pyproject.toml` 已声明依赖，判定顺序改为
「`src.` 前缀 → 已声明依赖 → `src/<top>` 存在 → 其余」。

### C-6 文档残留 → ✅ 已修复

| 位置 | 修前 | 修后 |
|:---|:---|:---|
| `workflow_status.md:18` | 137,443 行 | **137,468 行 / 187 测试文件**（实测） |
| `workflow_status.md:19` | 3190 / 5.09s | **3261 / 0 errors** |
| `README.md:237` | Ruff 全量 **433** | 改为"会随批次波动（2026-10-23 实测 432）…跑 `--statistics` 看当前值"（它已连续三次漂移 432/433/434，硬编码必然再错） |
| `CLAUDE.md:96` | 已在上一提交修 | — |

### 6 条 Required 的处置

| # | Required | 处置 |
|:---|:---|:---|
| 1 | `hard_fail` 不含 collect / reachability / coverage | ✅ 纳入，且 `None` 算失败 |
| 2 | 解析链路改 JSON + UTF8 环境 | ✅ 全部改为 `--json` 消费 |
| 3 | `reachability` 两套口径实现 | ✅ `main()` 改为复用 `compute_reachability()`；注释与实现一致 |
| 4 | 阈值四处硬编码、两处不同值 | ✅ 新建 `scripts/hard_metrics.py` 作唯一来源；三个脚本 import；**CI 不再传数值** |
| 5 | 基线文件在 gitignore 目录里不可审计 | ✅ 移入 `scripts/baseline-silent.json` 并入库；`by_file` 路径改 `as_posix()`（跨平台一致）；新增测试断言"文件 total == hard_metrics 常量" |
| 6 | DEP-MISSING 不在门禁 | 🟡 **有意不改**：缺可选 extras（celery/opentelemetry 等）不应阻断构建。已在 `baseline` 中记录数量（7）供趋势观察；`classify()` 现在能正确区分它与代码缺陷，这是更有价值的改进 |
| 7 | requirements 与 pyproject 不同步 | ✅ `requirements.txt` 补 `psutil / fastapi / uvicorn` |
| 8 | deadcode 动态判据是死的 | ✅ 去掉"任意字符串+`)`"这条脏正则，改抓 `import_module` / `__import__` / `globals()[...]`；相对形式由父包判据从另一方向覆盖 |
| 9 | 搜索范围缺口 | ✅ 补 5 个目录（实测当轮 0 命中，机制已补齐） |
| 10 | 测试强度（baseline 零测试） | ✅ 新增 14 例；计划书里不存在的 `--fail-under 442` 改为真实命令；`test_baseline_outputs_all_keys` 改为实际存在的 `test_baseline_gate.py::TestNoneMeansFailure` |
| 11 | 覆盖率阈值单一来源（已做对） | 保持 |

---

## 3. 复验汇总（全部实跑）

| 项 | 命令 | 结果 |
|:---|:---|:---|
| 干净环境收集 | `venv/Scripts/python.exe -m pytest tests/ --collect-only -q` | **3261 / 0 errors**（修前 3259 / 1 error） |
| 全量回归 | `py -3.10 -m pytest tests/ -q` | **3269 passed / 0 failed / 5 skipped / 2 xfailed / 559.89s** |
| 快速层 | `... -m "not slow"` | 3536 passed / 233.31s |
| 门禁脚本自测 | `py -3.10 -m pytest tests/scripts -q` | **50 passed** |
| 静态硬指标 | `py -3.10 -m ruff check src/ tests/ --select F821,F811,E9` | All checks passed |
| baseline 全指标 | `py -3.10 scripts/baseline.py` | `fail=0 / import_exit=0 / dep_missing=7 / prod_reachable=443`，exit=0 |
| 静默异常门禁 | `venv/Scripts/python.exe scripts/check_silent_except.py` | 172 ≤ 172，exit=0（不传参即门禁） |
| 可达门禁 | `py -3.10 scripts/reachability.py` | 443 ≥ 443，exit=0 |
| CI YAML | `yaml.safe_load` | OK，4 jobs / 11 steps |
| 版本 | `-m src --version` / pyproject / dist-info | 均 **0.60.8** |

---

## 4. 仍未解决 / 明确不做

| # | 项 | 理由 |
|:---|:---|:---|
| 1 | 覆盖率 60% | 47.44%，差 7,766 行，需多批次（W4/W5） |
| 2 | 死模块删除 | 名单已可靠（71 个真候选），但删除 = 砍约 2 万行能力代码，**需产品决策** |
| 3 | 快速层 180s | 233s，slow 层已剥离 410s，剩余耗时分散 |
| 4 | DEP-MISSING 纳入门禁 | 有意不做（见上 Required 6） |
| 5 | 远端 CI / Docker / Release | 本机无 `gh` / `docker` / token —— 环境阻塞 |
| 6 | `.clawd/` 里并发会话产生的 `.coverage.*` 分片 | 已加 `.gitignore`；属另一个会话的工作产物 |

---

## 5. 关于并发会话（必须披露）

本项目目录下**同时有另一个会话在进行 W4 覆盖率补测**：
12:50 之后新增了 `tests/agent/swarm/test_pipeline_flow.py`、
`tests/core/test_budget_guard_deep.py`、`tests/memory/test_memory_manager_deep.py`、
`tests/rag/test_repo_map_deep.py`、`tests/workflow/test_mode_state_deep.py` 共 5 个文件、
约 276 个用例，以及一批 `.coverage.*` 分片。

因此：
- 本报告的全量结果（3269 passed）是**我提交快照**上的数字；
- 之后 `--collect-only` 已达 **3552**，新增用例**未纳入本轮验证**；
- 我的提交是**精确 add**（19 个文件），未卷入对方半成品。

---

## 6. 结论

审查的 5 个阻塞项 **全部关闭**，Required 11 条中 **10 条已处置**、1 条有意不做并说明理由。

**Verdict：从 Request Changes → 可接受（附带 §4 的 6 条未闭环）**。
这只代表"严格审查后未发现新的阻塞问题"，不代表"代码完美"。

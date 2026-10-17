---
name: clawd-change-workflow
description: Guides safe changes to the Clawd Code codebase by reading the doc/memory layer first, checking it for staleness against real code, then implementing with real-E2E verification. Use when adding a new API, provider, tool, CLI command, or any feature to this repo; when fixing a bug; or when onboarding onto an unfamiliar area of the code.
---

# Clawd Code 变更工作流

## Overview

这个仓库的真实约束不是"代码难写"，而是**代码量远超测试覆盖**（截止 v0.57.0：
约 147K 行源码，覆盖率约 20%）。这意味着：

- 静态检查抓不住大部分真实缺陷。`ruff` 的 `F821` 只检查**名称**是否存在，
  不检查**对象属性**是否存在；`mypy` 未启用。
- 因此"看起来对"的代码经常在第一次真实运行时崩溃。
- **可达 ≠ 可导入**：v0.57.0 实测有 16 个模块静态可达、但 `import` 即崩。

本 skill 的用途是把历轮修复中付出代价换来的经验固化成流程，
让下一次变更是**可复用**的，而不是重新踩一遍。

---

## 三个必须先跑的分析工具

| 工具 | 回答的问题 | 命令 |
|:---|:---|:---|
| `scripts/reachability.py` | 从生产入口**能否走到**某模块 | `python scripts/reachability.py --prod --list` |
| `scripts/import_sweep.py` | 走到了**会不会 import 就炸** | `python scripts/import_sweep.py` |
| `ruff --select F821,F811` | 有没有未定义名称 / 重复定义 | `python -m ruff check src/ --select F821,F811` |

**三者必须一起用**。只跑任何一个都会漏掉另外两类缺陷：
- 只跑可达性 → 漏掉"能走到但导入即崩"
- 只跑导入扫描 → 漏掉"根本走不到、但读起来像能用"的模块
- 只跑 ruff → 漏掉运行时属性/类型错误

> ⚠️ **改导入形式前先想清楚**：`reachability.py` 靠 **AST 里的 import 语句**建图。
> 把 `from .commands import X` 改成 `importlib.import_module("字符串")`
> 会让模块从图中消失，生产可达数凭空下降。v0.57.0 踩过这个坑
> （429 → 416），不得不改回显式导入。

---

## When to Use

在以下任一情况下必须加载本 skill：

- 向本项目添加新功能 / 新 API / 新 LLM 供应商 / 新工具 / 新 CLI 命令
- 修复 bug
- 进入一块自己没读过的代码区域
- 用户问"这个功能实现了吗"、"能不能跑"

---

## Phase 0：读文档层（在写任何代码之前）

按顺序读，**不要跳**：

| 顺序 | 文件 | 读它是为了 |
|:---|:---|:---|
| 1 | `CLAUDE.md` / `AGENTS.md` | 项目约定、命令、边界 |
| 2 | `workflow_status.md` | **上一轮改了什么、验证到哪一步、什么还没做** |
| 3 | `计划书/` 下最新文档 | 当前的计划与已知缺陷台账 |
| 4 | `CHANGELOG.md` 顶部章节 | 最近一次发布改了什么 |
| 5 | 跨会话记忆（`memory/`） | 端点配置、用户偏好、上次踩的坑 |

---

## Phase 1：文档保鲜检查（关键步骤，不可省略）

**这些文档会过时。** 直接照着做会浪费大量时间在已经不存在的代码上。

对第 3、4 步读到的**每一条具体断言**，用真实代码验证：

```bash
# 文档说"X 尚未实现" → 查它是否已经实现
grep -rn "def X\|class X" src/

# 文档提到某个文件/函数 → 确认它真的存在
ls src/path/to/file.py

# 文档声称"覆盖率约 N%" → 不要信，看 coverage.json 的 totals
python -c "import json; t=json.load(open('coverage.json'))['totals']; print(t['percent_covered'])"

# 文档给定的版本号 → 与 pyproject.toml / src.__version__ 比对
grep -m1 '^version' pyproject.toml
python -c "import src; print(src.__version__)"
```

**判定规则**：

| 情况 | 动作 |
|:---|:---|
| 文档断言与代码一致 | 直接按文档推进 |
| 文档断言已过时（代码已更新） | **先更新文档**，再推进 |
| 文档描述的 API 不存在 | 停下来确认：是**有意重写**还是**遗漏**？见下 |

> ⚠️ **"文档描述的 API 不存在"有两种截然不同的成因**，处理方式相反：
>
> - **有意重写**（实现是一致的、有意的，只是文档没跟上）→ **改文档**
> - **误删 / 未接线**（实现本应存在）→ **补实现**
>
> 判断方法：看该 API 的**调用点**。若有活着（可达）的调用方 →
> 是实现被误删，补实现；若无任何调用方 → 大概率是有意重写，改文档。
>
> v0.51.0 的实例：`AtomicPatcher.commit()` 有活调用方
> （`src/agent/engine_loop.py`）→ 补实现；`ConfigMerger` 类无任何调用方
> → 是有意重写，改测试。

---

## Phase 2：理解真实代码（不要只看文档）

**先定位可达性**，再改：

```bash
# 找符号在哪
grep -rn "def <name>\|class <name>" src/

# 找谁在调用它（决定这次改动的爆炸半径）
grep -rn "<name>" src/ tests/ | grep -v "def <name>"

# 查模块是否真的被引用（本项目有 213 个不可达模块）
grep -rn "from .*<module>\|import <module>" src/ tests/
```

> 本项目史上有四次"集成波次"（Aider / GoalX / oh-my-codex / ClawGod），
> 每次都把源项目目录搬进来但**没接线**。所以"文件存在"≠"代码在跑"。

---

## Phase 3：实现

### 3.1 先写测试

- 新功能 → 先写会失败的测试
- 修 bug → 先写能复现 bug 的测试
- 改 API → 先看 `tests/contracts/` 是否已锁定该接口

### 3.2 用 `str` 子类枚举做兼容性变更

如果契约要求 `TaskSize` 而实现用的是字符串字面量，**不要二选一**：

```python
class TaskSize(str, Enum):
    SMALL = "small"      # TaskSize.SMALL == "small" 为 True
```

这样新旧两种调用方式同时成立，不构成破坏性变更。本项目已用该模式处理
`src/workflow/verifier.py`。

### 3.3 对外部响应一律做类型收敛

第三方（LLM provider / 代理层 / MCP）返回的数据不在我们控制内。
直接塞进 pydantic 模型会因单个字段类型不标准而让整条链路失败。

参考 `src/llm/factory.py` 的 `_as_str()` / `_as_int()`。

### 3.4 禁止静默吞异常

```python
# ❌ 禁止：功能失效但无任何信号
try: ...
except Exception: pass

# ✅ 允许：明确说明为何可忽略，并留下痕迹
except Exception as e:  # noqa: BLE001 - 指纹仅影响增量索引效率
    logger.warning(f"指纹文件写入失败 {fp_path}: {e}")
```

本项目 v0.51.0 时已有 255 处静默吞异常。**不得增加。**

### 3.5 不要重写文件

用户明确要求：在现有代码上做**外科手术式修改**，不推倒重写。
200 行能改到 50 行再考虑精简，但不要为"优雅"重写能跑的代码。

---

## Phase 4：验证（分层，按风险选择）

### 第 1 层：真实 E2E（最灵敏的探针）

```bash
python scripts/e2e_smoke.py     # 需要 .env 配好可用端点
```

五步：读配置 → 应用可导入 → 真实对话 → 工具调用 → 推理内容。
**退出码 0 才算通过。** 它专门用来抓静态分析看不见的缺陷。

### 第 2 层：回归探针（改到对应模块时必跑）

| 改动区域 | 必跑 |
|:---|:---|
| `src/llm/` | `pytest tests/llm/test_factory.py` + E2E |
| `src/core/patch/` | `pytest tests/self_healing/test_atomic_patcher.py` |
| `src/core/config/` | `pytest tests/core/test_config_merger.py` |
| `src/agent/` | `pytest tests/contracts/` |
| `src/rag/`、`src/brain/` | `pytest tests/brain/` |

### 第 3 层：契约测试（改公共 API 必跑）

```bash
pytest tests/contracts/ -q
```

### 第 4 层：收集完整性（新增测试文件后跑）

```bash
pytest tests/ --collect-only -q 2>&1 | tail -2      # 期望 "0 errors"
```

### 第 5 层：导入完整性（改导入 / 删模块 / 改包结构后必跑）

```bash
python scripts/import_sweep.py
# 期望：IMPORT-FAIL 0；DEP-MISSING 只应包含环境未装的第三方包
```

### 第 6 层：交付物验证（产出 HTML / 报告 / 交互页面时）

```bash
python scripts/verify_html_report.py 计划书/变更报告-v0.57.0.html
# 真实浏览器驱动：答对全部题 → 判定通过；错一题 → 判定未通过
```

---

## Phase 5：收尾

1. 更新 `CHANGELOG.md`（写**为什么这么改**，不是改了什么）
2. 更新 `workflow_status.md` 的验收表
3. 若文档断言已变 → 同步更新
4. 提交信息用约定式提交（`fix:` / `feat:` / `refactor:` / `test:`）

---

## 已知陷阱（本项目实际发生过）

| 陷阱 | 症状 | 预防 |
|:---|:---|:---|
| **dataclass 字段被同名 classmethod 覆盖** | 字段值是 `<bound method>`，`if x.flag:` 恒为真 | 字段与 classmethod **禁止同名**；`ruff F811` 能抓到 |
| **签名默认值里绑定模块属性** | `def f(spawn=subprocess.run)` → monkeypatch 无效，测试跑真实子进程 | 默认写 `None`，函数体内再解析 |
| **`__dataclass_fields__` 是 dict** | `for f in cls.__dataclass_fields__: f.name` → `'str' has no attribute 'name'` | 用 `.values()` 或直接迭代键 |
| **参数被接受但被忽略** | `save(path)` 里从不使用 `path`，文件写到别处 | 每个参数都要在函数体里被真正使用；否则删掉参数 |
| **字符串当字面量联合** | `"a" \| "b"` 是字符串按位或 → `TypeError` | 用 `Literal["a","b"]` |
| **同名类在两个模块各定义一份** | `isinstance` 互不为真，序列化/反序列化失配 | 唯一定义，另一处 import |
| 属性名漂移 | `AttributeError: ... has no attribute 'X'` | 改配置/数据模型时，用 `grep` 核对全部属性访问 |
| 环境变量约定与字段名不匹配 | 按文档配置却拿不到值 | 文档约定与代码字段名不一致时，**加别名解析**而非改文档 |
| 同名字段/方法定义两次 | 后者静默覆盖前者，改第一个没效果 | `ruff --select F811` |
| 移植了调用方没移植被调用方 | 调用不存在的属性/方法 | 改完立刻跑真实 E2E |
| 同名测试文件 + 缺 `__init__.py` | pytest `import file mismatch` | `tests/` 每个子目录都要有 `__init__.py` |
| 幂等性缺失 | 反复执行会自我污染（配置、缓存、索引） | 写**重复执行两次结果相同**的测试 |
| 并发迭代原字典 | `RuntimeError: dictionary changed size` | 后台线程会改的容器，迭代时取快照 `list(d)` |
| 同步调用 async 函数 | 只得到协程，`RuntimeWarning`，功能静默失效 | 看 `inspect.iscoroutinefunction()` |
| Windows 控制台 GBK | `UnicodeEncodeError` + 满屏乱码 | 输出前 `reconfigure(encoding='utf-8', errors='replace')` |
| **测试文件从初始提交起就没通过** | 没人把它当信号，缺陷长期隐藏 | 见到长期红的文件，先查它引用的 API 是否真实存在 |

---

## Common Rationalizations（这些借口一律不接受）

| 借口 | 为什么是错的 |
|:---|:---|
| "ruff 通过了，所以没问题" | `F821` 不管属性；本项目 11 个 P0 里 5 个 ruff 全过 |
| "单测过了" | 未覆盖的代码路径不算测过；覆盖率 19.5% |
| "文档说已经实现了" | 文档已经漂移过多次，必须核对代码 |
| "这个模块存在，所以能用" | 本项目 213 个模块存在但不可达 |
| "先合进去，之后补测试" | 这正是造成现状的原因 |
| "加个 try/except 让它别崩" | 静默吞异常 = 功能失效但无信号，已有 255 处 |
| "删掉死代码覆盖率就上去了" | 那只是分母变小。看**绝对覆盖行数** |
| "本地跑过就行" | 没有实际命令输出 = 未验证 |

---

## Red Flags（出现即停下）

- 你在改一个**从未被任何测试执行过**的函数
- 你在给某个 `except` 加 `pass`
- 你准备**重写**整个文件
- 你改了公共 API 但没跑 `tests/contracts/`
- 你打算"顺手"降低 `pyproject.toml` 的 `fail_under`
- 你说"应该可以"、"理论上没问题"
- 你新增了文件但没新增对应测试
- 你准备 `git push` 但拿不出验证命令的输出

---

## Verification

一次变更只有在以下**全部**满足时才算完成：

```text
[ ] 1. scripts/e2e_smoke.py 退出码 0（改动涉及 LLM / 工具 / 配置路径时）
[ ] 2. 对应模块的回归探针全绿
[ ] 3. pytest tests/ --collect-only 为 0 errors（新增测试文件时）
[ ] 4. ruff --select F821,F811 无新增违规
[ ] 5. 未增加 except: pass
[ ] 6. CHANGELOG.md 与 workflow_status.md 已同步
[ ] 7. 每条"已完成"的断言都有实际命令输出支撑
[ ] 8. 改导入 / 删模块后：scripts/import_sweep.py 的 IMPORT-FAIL 仍为 0
[ ] 9. 删代码后：scripts/reachability.py 的生产可达数**unchanged**
[ ] 10. 产出交互页面时：scripts/verify_html_report.py 真实浏览器通过
```

**第 7 条是硬门槛。** 拿不出输出的，一律按"未完成"处理。

---

## 快速参考：模块地图

```text
src/
├── agent/           Agent 引擎 + 多智能体 swarm + 意图路由
├── llm/             LLM 抽象层（9 供应商）+ factory（构造入口）
├── core/            基础设施：配置、事件、异常、补丁引擎、Git
│   ├── config/         AgentSettings（配置唯一入口）
│   └── patch/          AtomicPatcher（代码修改）
├── rag/             Trigram 索引 + Tree-sitter + 代码图谱
├── brain/           World Model（代码库感知）
├── tools_runtime/   工具执行（bash / 文件 / 搜索）
├── workflow/        5 阶段执行管道
├── self_healing/    自动错误检测与修复
├── memory/          长效记忆
└── cli/             REPL / TUI

scripts/e2e_smoke.py   真实端点冒烟测试（最重要的回归探针）
tests/contracts/       公共 API 契约锁定
```

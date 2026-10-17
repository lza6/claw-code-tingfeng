# 维护 SOP —— 新增能力与交接

> 面向下一次修改本项目的 AI / 工程师。
> 与 `skills/clawd-change-workflow/SKILL.md` 配套：SKILL 讲"怎么想"，本文讲"按什么顺序做"。

---

## 0. 进入项目的第一步（不可跳过）

```bash
# 1) 读
#    workflow_status.md          —— 上一轮改了什么、验证到哪一步
#    skills/clawd-change-workflow/SKILL.md
#    计划书/下一步改进指南.md     —— 剩余路线图（含"已完成/未完成"实跑状态表）

# 2) 建立事实基线（3 分钟，别信文档里的数字）
python scripts/reachability.py                 # 生产可达数
python scripts/import_sweep.py                 # 导入期缺陷数
python -m ruff check src/ --select F821,F811   # 静态缺陷数
```

**判定规则**：文档里的每条具体断言（"X 未实现"、"覆盖率约 N%"、"文件在 Y"），
先用上面的命令或 `grep` 核实。文档过时是常态。

---

## 1. 新增一个 LLM Provider

| 步骤 | 位置 | 要点 |
|:---|:---|:---|
| 1 | `src/llm/providers/<name>.py` | 实现与 `openai.py` 相同的接口 |
| 2 | `src/llm/providers/__init__.py` | 注册到工厂表 |
| 3 | `src/core/config/models.py` | 增加配置项（若有鉴权差异） |
| 4 | `tests/llm/` | 用 mock 覆盖：success / timeout / rate_limit / malformed |
| 5 | `.env.example` | 写清必填变量 |
| 6 | 验证 | `pytest tests/llm -q` + `python scripts/e2e_smoke.py` |

> ⚠️ 生产路径是 `src/agent/engine.py → create_llm_provider()`，**不是** `src/llm/factory.py`。
> 改完先确认哪条路径实际在用（见记忆 `claw-code-production-path-vs-source`）。

---

## 2. 新增一个工具（Tool）

| 步骤 | 位置 | 要点 |
|:---|:---|:---|
| 1 | `src/tools_runtime/<name>_tool.py` | 继承 `BaseTool`，声明 `name` / `description` / `parameter_schemas` |
| 2 | `src/tools_runtime/__init__.py` | 导出并注册 |
| 3 | `src/agent/tool_manager.py` | 确认它被 `classify_tool()` 归入 read/write/exec |
| 4 | 审批语义 | write/exec 必须走 `_enforce_approval`（唯一咽喉点） |
| 5 | 验证 | `pytest tests/tools_runtime tests/agent -q` |

**红线**：新增工具若能在磁盘/网络产生副作用，必须落入 `write` 或 `exec` 分类，
否则审批门禁形同虚设。

---

## 3. 新增一个 CLI 命令

| 步骤 | 位置 | 要点 |
|:---|:---|:---|
| 1 | `src/cli/commands/<x>_commands.py` | 定义 `app = typer.Typer(...)` 与命令 |
| 2 | 注册函数 | 形参必须叫 `parent_app`，内容 `parent_app.add_typer(app, name="x")` |
| 3 | `src/cli/entrypoint.py` 的 `_load_command_modules()` | 加显式 import + 清单项 |
| 4 | 验证 | `python -m src <x> --help` + `pytest tests/cli -q` |

**三条硬约束**（都踩过坑）：
1. **禁止** `app.add_typer(app, name=...)` —— 参数遮蔽模块级 `app`，会把父应用注册到自己身上。
2. **禁止**用 `importlib.import_module("字符串")` 注册 —— `reachability.py` 靠 AST 建图，会看不见。
3. **禁止**让命令名与命令组名重名 —— Typer 中组会遮蔽命令（`workflow` 曾因此永远跑不到）。

---

## 4. 改公共 API

1. 先看 `tests/contracts/` 是否锁定了该接口。
2. 兼容性优先：用 `str` 子类枚举（`class X(str, Enum)`）让新旧写法同时成立。
3. 破坏性变更必须在 `CHANGELOG.md` 写清迁移方式。
4. 验证：`pytest tests/contracts -q`。

---

## 5. 删除代码

```bash
# 1) 删除前的基线
python scripts/reachability.py | head -3

# 2) 确认没有动、静态引用
grep -rn "<模块名>" src/ tests/ --include=*.py

# 3) 删除后核对不变量
python scripts/reachability.py | head -3   # 「生产可达」必须不变
python scripts/import_sweep.py             # 导入缺陷不得增加
pytest tests/ --collect-only -q            # 0 errors
```

**红线**：
- ❌ 按名字相似判"可删"（`hook_registry.async_executor` 曾被误判为 `hook_registry` 的重复）
- ❌ 删前不读源码确认"同一能力在别处存在"
- ❌ 把"有循环结构"当成"真实实现"

---

## 6. 发布前检查单

```text
[ ] pytest tests/ -q                    → 0 failed
[ ] pytest tests/contracts -q           → 全绿
[ ] ruff --select F821,F811             → All checks passed
[ ] python scripts/import_sweep.py      → IMPORT-FAIL = 0
[ ] python scripts/reachability.py      → 生产可达数未下降
[ ] python scripts/e2e_smoke.py         → 退出码 0（改动涉及 LLM/工具/配置时）
[ ] python scripts/e2e_production.py    → 8/8（改动涉及生产路径时）
[ ] 版本号三处一致（pyproject / src.__version__ / README）
[ ] CHANGELOG.md、workflow_status.md 已同步
[ ] 提交信息用约定式格式，不含密钥
```

---

## 7. 排障索引

| 现象 | 先查 |
|:---|:---|
| CLI 少了一组命令 | `src/cli/entrypoint.py` 的降级告警日志 |
| 某模块 import 就崩 | `python scripts/import_sweep.py` |
| 改了配置不生效 | `get_runtime_config` 的 6 层优先级；是否有代码读取该键 |
| 测试单独跑绿、合并跑红 | 进程级全局泄漏（`set_allowed_workdirs`、`set_config`） |
| 断点续跑行为异常 | `PipelineState` / `_deserialize_result` 的枚举还原 |
| 长任务扫描变慢 | 是否在缓存命中路径上付了线程池调度开销 |

---

## 8. 交接时要交代的三件事

1. **哪些是真实现、哪些是桩** —— 当前唯一已知的桩是工作流验证阶段
   （返回 `verification_result="not_implemented"`）。
2. **哪些指标没达标** —— 覆盖率 ~20%、死模块 135、静默吞异常 101、收集 92s。
3. **下一步最该做什么** —— 见 `计划书/下一步改进指南.md` 顶部的状态表。

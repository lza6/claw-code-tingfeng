# 维护 SOP —— 新增能力与交接

> 面向下一次修改本项目的 AI / 工程师。
> 与 `skills/clawd-change-workflow/SKILL.md` 配套：SKILL 讲"怎么想"，本文讲"按什么顺序做"。

---

## 0. 进入项目的第一步（不可跳过）

```bash
# 1) 读
#    workflow_status.md                       —— 顶部「当前状态」区块
#    skills/clawd-change-workflow/SKILL.md
#    计划书/下一步改进指南.md                —— 当前计划（v4，2026-10-29 实测版）

# 2) 建立事实基线（3 分钟，别信文档里的数字）
py scripts/reachability.py                                   # 生产可达数
venv/Scripts/python.exe scripts/import_sweep.py              # 导入期缺陷数
py -3.10 -m ruff check src/ --select F821,F811               # 静态缺陷数
```

### 0.1 解释器矩阵（本机 `python` 命令不存在）

| 解释器 | 版本 | 运行依赖 | pytest / ruff | 用途 |
|:---|:---|:---|:---|:---|
| `venv/Scripts/python.exe` | 3.10.9 | ✅（缺 jsonschema/psutil 等可选包） | ✅ pytest 9.1.1 / ruff 0.17.2 / pytest-cov 7.1.0 | **首选**：跑 CLI、E2E、脚本、测试、ruff（与 CI 的 `pip install -e ".[dev]"` 一致） |
| `py -3.10` | 3.10.9 | ✅ | ✅ | **跑测试、跑 ruff** |
| `py`（默认） | 3.14 | ❌ 缺 loguru | ✅ | **不要用**：收集会报 68 个假错误 |

> 实测：同一份测试，`py` 得 `68 errors`，`py -3.10` 得 `0 errors`。
> 混用解释器是本项目"指标互相矛盾"的头号原因。


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
| 1 | `src/tools_runtime/<name>_tool.py` | 继承 `BaseTool`，声明 `name` / `description` / `parameter_schemas` / **`risk_kind`** |
| 2 | `src/tools_runtime/__init__.py` | 导出并注册 |
| 3 | `src/agent/tool_manager.py` | 确认它被 `classify_tool()` 归入 read/write/exec |
| 4 | 审批语义 | write/exec 必须走 `_enforce_approval`（唯一咽喉点） |
| 5 | 验证 | `pytest tests/tools_runtime tests/agent -q` |

**红线**：新增工具若能在磁盘/网络产生副作用，必须显式声明
`risk_kind = 'write'` 或 `'exec'`。未声明时门禁会回退到名称启发式，
命名不合约定就会绕过审批。`ScrapeTool` 这类网络访问工具按 `exec` 处理。

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

## 3.4 给命令加 `--json`（脚本/CI 契约）

统一走 `src/cli/command_result.py` 的 `CommandResult` + `emit()`，**不要自己 `print(json.dumps(...))`**。

| 要求 | 原因 |
|:---|:---|
| 输出形如 `{ok, code, ...业务字段}` | 脚本要能稳定解析；裸数组/裸对象每次改都要猜结构 |
| `raise typer.Exit(emit(result, json_out))` | **退出码必须等于 JSON 里的 `code`**，否则 CI 判断失真 |
| 错误也输出合法 JSON（`ok=false` + `code>=1`） | `--json \| jq` 不能因为一句中文报错就崩 |
| 人读文本走 `human` 字段，不进 stdout 的 JSON | 混在一起就无法解析 |
| 中间日志一律 `stderr`（`print(..., file=sys.stderr)` 或 logger） | 保持 `stdout` 只有一行 JSON |
| 不做的事要**写进 data**（如 `budget_ignored: true`） | 只在人读里提示 = 机器侧永远不知道 |

自查一条命令是否合规：

```bash
venv/Scripts/python.exe -m src <cmd> --json 2>/dev/null | venv/Scripts/python.exe -c "import sys,json;d=json.loads(sys.stdin.read().strip().splitlines()[-1]);print(d['ok'],d['code'])"
```

契约测试在 `tests/cli/test_command_result.py`（地基）与 `tests/cli/test_json_contract_queries.py`（查询类全覆盖）。

---

## 3.5 新增一个桌面端接口（WS handler 或 HTTP 端点）

桌面端 UI 的所有数据都来自这两类接缝，加功能基本都落在这里。

### WS handler（`src/server/handlers.py`）

| 步骤 | 位置 | 要点 |
|:---|:---|:---|
| 1 | `MessageRouter` 的 handlers 字典 | 加 `'<msg_type>': self._handle_<x>` |
| 2 | 处理函数 | 必须接受 **3 个参数** `(self, ws, message, engine_factory)` |
| 3 | 前端 | `wsRequest({type: '<msg_type>'}, '<msg_type>')` 等响应 |
| 4 | 验证 | `pytest tests/server -q` + 装好的 UI 上点一次 |

**硬约束（真实事故）**：`dispatch()` 永远按三个位置参数调用 handler。
少写 `engine_factory` 时 TypeError 会被外层 `except Exception` 吞成 `E_INTERNAL_ERROR`，
UI 表现为"面板一直是空的"，日志里只有一行通用错误 —— 排查方向容易跑偏。

### HTTP 端点（`src/server/websocket_server.py`）

1. 在 HTTP 分支里加 `if path == '/api/<x>':`，返回 `_WsResponse(200, 'OK', _H([...]), body)`；
2. **数据目录一律走 `data_path(...)`**（`src/core/data_dir.py`），禁止 `Path.cwd() / '.clawd'`：
   桌面端的数据在 `userData/data`，硬编码 cwd 会让端点永远返回空（`/api/sessions` 就这么空了很久）；
3. 敏感字段只回掩码/环境变量名，不回明文；
4. 验证：`pytest tests/server -q`，并在装好的安装版上 `Invoke-WebRequest http://127.0.0.1:<port>/api/<x>`。

### Electron 壳（`desktop/electron/`）

1. 主进程用 `ipcMain.handle('<ch>:<action>')`，**顶部** `require('electron')` 的解构里必须有这个符号；
2. **禁止在函数体内再写一次 `const { ipcMain, app } = require('electron')`** —— 函数作用域 const
   会提升成 TDZ，上方所有 `ipcMain.handle(...)` 抛 `Cannot access 'ipcMain' before initialization`，
   主进程在开窗前就挂掉（安装包表现为"双击没反应"）。`node --check` 查不出来；
3. preload 用 `contextBridge.exposeInMainWorld` 暴露最小能力，渲染端 `window.clawdDesktop.<x>()`；
4. 验证：`py -3.10 -m pytest tests/test_electron_main_static.py -q`（7 条静态检查）+ 真实装一次。

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

## 5.5 版本号陷阱：editable 安装的元数据会滞后

`src.__version__` 优先读 **已安装发行版的元数据**。`pip install -e .` 之后
再改 `pyproject.toml` 的版本号，元数据仍停留在旧值 —— 表现为
`python -m src --version` 与 `pyproject.toml` 不一致。

**每次 bump 版本后必须重装**：

```bash
python -m pip install -e . --no-deps --no-build-isolation
python -c "import importlib.metadata as m; print(m.version('clawd-code'))"
```

**还要删仓库根目录的 `clawd_code.egg-info/`**（v0.89.0 实测再踩一次）：
从仓库根跑测试时，`clawd_code.egg-info/PKG-INFO` 会**盖过** venv 里新装的
`clawd_code-<ver>.dist-info`，`importlib.metadata.version('clawd-code')` 返回旧版本，
`tests/core/test_version_consistency.py::test_installed_metadata_matches_pyproject` 直接红。

```bash
rm -rf clawd_code.egg-info     # 已在 .gitignore（构建产物，删了不影响源码）
```

---

## 6. 发布前检查单


```text
[ ] pytest tests/ -q                    → 0 failed
[ ] pytest tests/contracts/ -q          → 全绿
[ ] ruff check src/ tests/ --select F821,F811,E9 → All checks passed
[ ] python scripts/import_sweep.py --strict-exit → IMPORT-FAIL = 0
[ ] python scripts/reachability.py --min-reachable <上轮值> → 生产可达数未下降
[ ] python scripts/check_silent_except.py --fail-over 155 → 未回升
[ ] python scripts/coverage_gap.py       → 只给「生产可达」模块补测试，不给死代码刷覆盖率
[ ] python scripts/e2e_smoke.py         → 退出码 0（改动涉及 LLM/工具/配置时）
[ ] python scripts/e2e_production.py    → 8/8（改动涉及生产路径时）
[ ] python scripts/verify_audit_p1.py   → 28/28
[ ] python scripts/check_mcp_startup.py → 4/4
[ ] python scripts/core_surface.py      → core 未 import 上层
[ ] python scripts/check_doc_drift.py   → README 数字与现跑一致
[ ] 版本号三处一致（pyproject / src.__version__ / README）
[ ] CHANGELOG.md、workflow_status.md 已同步
[ ] 提交信息用约定式格式，不含密钥
```

**桌面端出包额外三步（少一步就会装出坏包）**：

```text
[ ] python scripts/prepare_host_bundle.py   → [5/5] 自检全过（含 CLI --help）
[ ] pwsh -File scripts/build_desktop_signed.ps1 [-SelfSigned|-Pfx ...] → DONE
[ ] pwsh -File scripts/e2e_desktop_install.ps1 → 退出码 0（装→真跑→重启→卸载→残留）
```

`scripts/e2e_desktop_install.ps1` 是 v0.89.0 起**入库的装机 E2E**（以前是会话里手打的一次性脚本，
每次都要重新拼，并重复踩过同样的坑）。它覆盖：静默安装 → 版本/内嵌 host/prompts 校验 →
预置 `.env` → 启应用 → `/ /api/info /api/providers /api/usage /api/sessions` → 破坏性端点无 token 必须 403 →
真浏览器 UI E2E（`desktop/ui_console_e2e.mjs`）→ 重启后配置与会话仍在 → 无残留进程 → 静默卸载 → 注册表残留 0。
`-SkipUi` 只验 Host；`-KeepInstalled` 跑完不卸载（调试用）。

打包自检为什么不能省：bundle 里少一个包/一个 DLL，源码、单测、`node --check`、静态检查**全是绿的**，
只有装到别人机器上双击才发现（本项目一天内踩了三次：`annotated_doc`、`exceptiongroup`、
`python3.dll`）。`prepare_host_bundle.py` 的 [5/5] 用**打包后的解释器**真实 import + 起 CLI，
缺什么自动从 venv 补齐，补不齐就中断打包。

---

## 6.5 已知依赖告警（报告型，非阻断）

`ci.yml` 的 Security Scan 有两个报告步骤，**都不阻断流水线**（阻断判定交给安全审查流程）：

| 步骤 | 工具 | 现状 |
|---|---|---|
| 静态扫描 | `bandit -r src/` | 无 medium+ 命中（`--exit-zero` 出报告） |
| 依赖漏洞 | `pip-audit -r requirements.txt` | **filelock 有 13 条 OSV 公告，且修复版本（4.2.1）尚未在 PyPI 发布** —— 已发布的全部版本（含最新 4.1.0）都命中，属于上游未修复，无法靠升级消除 |

> 为什么把 `safety` 换成 `pip-audit`：safety 3.x 起 `check` 子命令要求登录/API key，
> 匿名调用必然失败 → 该 job 会永远红，与真实漏洞无关。
>
> 处理原则：**不为了"看起来绿"而删检查**，也不假装修好了。报告保留、结论如实写在这里，
> 等上游发布 filelock 修复版本后再抬底。

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
| 安装版双击没反应 / 只有 Error 窗口 | 用内嵌解释器手工跑 `resources/host/python/python.exe -m src serve`，缺依赖会直接报 ModuleNotFoundError；再看 `%APPDATA%\clawd-desktop\shell.log` |
| 安装版停在"首次配置"窗口、Host 不启动 | 正常行为：`userData/.env` 不存在时会先引导填 API。自动化必须先预置 `.env`，否则会卡在这里（装机 E2E 的 STEP1b 就是干这个） |
| 装机 E2E 报"连不上/落盘 0" | 先怀疑脚本：userData 目录是 `clawd-desktop`（package.json `name`，不是 productName）；探针文件必须写进**当前项目**目录 |
| 模型说"我没有可用的 FileReadTool" | 不是工具没了（打包版注册 7 个且能执行）：`prepare_host_bundle.py` 的 [5/5] 会真实执行一次 FileReadTool。模型遵从性不记在产品账上 |
| `from .models import X` 突然 ImportError，但 models.py 明明有 X | 是不是有人新建了**同名目录** `models/`？Python 里包优先于同名模块，整个包会被静默劫持（v0.88.4 真实踩到）。新增子包前先 `ls` 目标目录 |
| 治理清单里"待迁移"的依赖，改完照样报错 | 先验证**依赖是否真的存在**：`core_surface_allow.json` 曾有 3 条指向全仓库不存在的名字（死引用，靠 `except ImportError` 活着）。不存在的不是迁移对象，是该删的死引用 |
| 传图后报 `a bytes-like object is required, not 'list'` | 有代码把多模态 `content`（块列表）当字符串用；`message_truncator.count_tokens` 踩过，用 `_content_text()` 归一化 |
| 传图后报 `APIConnectionError` / `Connection error` 而不是 400 | 有些端点拒绝 `image_url` 的方式是**直接断连**。用 `scripts/probe_vision_endpoint.py` 直连对比（纯文本 vs 带图）确认端点能力；产品侧已实现"带图失败自动降级纯文本重试一次" |

**排查原则（2026-10-30 三次假阴性换来的）**：断言要分层 —— 确定性事实（能 import、能执行、文件落盘、
接口返回结构）做门禁；依赖模型/外部行为的（"模型是否按预期调工具"）只做信息输出。
E2E 红了先问"是不是断言本身写错了"，再动产品代码。

---

## 7.5 能力开关与状态持久化（v0.60.0）

| 能力 | 开关 | 默认 | 说明 |
|:---|:---|:---|:---|
| RAG 首轮上下文 | `CLAWD_ENABLE_RAG=1` | 关 | `create_agent_engine()` 为工作目录建立 `LazyIndexer`；`doctor` 显示状态 |
| 原生 function calling | `CLAWD_NATIVE_TOOLS=1` | 关 | provider 解析 `tool_calls`；Agent 循环用 `role=tool` + `tool_call_id` 回传结果 |
| Scrape 私网访问 | `CLAWD_SCRAPE_ALLOW_PRIVATE=1` | 关 | **仅本地测试**；生产保持关闭 |

状态写入统一走 `src/utils/file_ops.py` 的 `atomic_write` / `file_lock` /
`locked_atomic_write_json`：

- `file_lock` 是**可重入**的（同线程嵌套不会自锁），锁目录内写 `pid-随机 owner`，
  释放时只删除自己持有的锁；陈旧锁通过原子 rename 回收。
- 读改写（read → modify → write）必须把**整段**放进 `file_lock`，只给写加锁
  仍会丢更新。
- `PipelineState.save(expected_attempt=N)` 做乐观并发检查，不匹配抛 `StaleStateError`；
  该类主要用于兼容/测试，生产路径是 `ModeStateManager`。
- 状态文件包含 `schema_version`，更高版本会被拒绝恢复（不猜测未来格式）。
- `mode_state.update_state` / `ralph_ledger.add_progress_entry` 已覆盖读改写；
  `record_visual_feedback` 目前只保证原子写，未覆盖读改写（已知限制）。

新增状态文件时**不要**直接 `open(path, 'w')`；复用上述原语。

---

## 8. 交接时要交代的三件事

1. **哪些是真实现、哪些是桩** —— v0.59.0 起，pipeline 的 ralplan / team-exec /
   ralph-verify / precontext-intake 四个阶段都接的是真实实现
   （有替身驱动的阶段回归测试）。仍需注意：`src/workflow/stages/` 与
   `src/workflow/pipeline_stages/` 是**未被引用的平行实现**，不要误认为它们在生产路径上。
2. **哪些指标没达标** —— 2026-10-29 实测：覆盖率 **62.39%**（目标 60% ✅）、
   死模块 **76**（完全不可达）、静默吞异常 **162**（门禁 ≤172）、收集 **4,964 / 18.6s**。
   口径以 `scripts/baseline.py --out .clawd/baseline.json` 为准，不要手抄数字。
3. **下一步最该做什么** —— 见 `计划书/下一步改进指南.md`（v4，现行）§3 问题清单与 §6 批次拆解。

---

## 9. 部署与热更新（2026-10-18 实测边界）

### 本地安装部署（已验证）

```bash
python -m pip install -e . --no-deps --no-build-isolation   # 成功构建 clawd-code
clawd --version            # Clawd Code v0.57.3
clawd agent keywords       # 11 个关键词
clawd catalog reload       # 技能数 39（活跃 23）/ Agent 数 30（活跃 18）
```

> `clawd.exe` 默认装在 `%LOCALAPPDATA%\Programs\Python\Python310\Scripts\`，
> 该目录可能不在 PATH —— 用完整路径或 `python -m src` 等价调用。

### 容器部署（**未验证，环境缺失**）

`Dockerfile` 与 `docker-compose.yml` 存在，但本机**没有安装 Docker**
（`where docker` 无结果）。因此：

- 镜像构建、容器启动、健康检查、热更新**均未实测**；
- 不能声称"容器可部署"；
- 恢复验证的最小条件：安装 Docker Desktop 后执行
  `docker compose build && docker compose up -d`，
  再验证 `:8765` 端口与 `clawd doctor`。

### Python CLI 的"热更新"

本项目是 CLI / 库，没有常驻服务进程。变更生效方式是重新安装
（`pip install -e .` 后新进程即加载新代码），不存在需要 reload 的运行时。
所谓"线上热更新"命令本仓库尚无可验证的落地路径，需要真实部署目标与凭证。

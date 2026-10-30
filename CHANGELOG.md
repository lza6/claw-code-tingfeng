# 变更日志

所有重要的项目变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [v0.89.1] (2026-10-31) — CI Linux 矩阵清零：35 failed + 4 errors → 0

CI 的 `ci.yml` 测试矩阵跑在 **Linux** 上，本机（Windows）测不出来的一批跨平台缺陷
全在那里暴露。逐条查实并修复：

### 真实产品缺陷（Windows 上被掩盖）

| 缺陷 | 现象 | 根因 | 修法 |
|---|---|---|---|
| `FileReadTool` 在子线程必崩 | 全部读文件测试报"读取错误: signal only works in main thread"（**9 个测试**连带失败） | `_read_with_timeout()` 无条件用 `signal.alarm`，而 `BaseTool.execute_async` 走 `asyncio.to_thread` → 子线程调 `signal.signal` 直接抛 | 非主线程 / Windows 退化为直接读（大小校验仍在 validate 兜底） |
| `platform_command` 探活在 Linux 必崩 | `probe/which/is_command_available` 5 个测试 TypeError | Linux 上 `os.altsep` 是 **None**，`None in command` 抛 "'in <string>' requires string as left operand" | 显式判空后比较；顺带加空 command 防御 |
| GitManager 构造在只读路径炸 | `GenericManager("/nonexistent")` PermissionError（**4 个 ERROR**） | `WorktreeManager.__init__` 里 `mkdir(parents=True)`，探活构造就写盘 | 构造函数不 mkdir（延迟到 `create()`），失败只告警 |
| 循环符号链接检测失效 | `a->b->a` 被判"安全"（沙箱逃逸面） | 循环链上 `stat()` **跟随链接** → ELOOP 抛 OSError → `except OSError: pass` 跳过记录 → inode 永不命中 | 改用 `lstat()`（不跟随）+ 路径指纹兜底 |
| 损坏符号链接被判"合法" | `-> 不存在目标` 的链接校验通过 | `resolve(strict=False)` 把链接替换成目标路径并"成功"返回 | 链上有链接且最终路径不存在 → `broken`（**先判逃逸**，越权优先） |
| 生成的 config.toml 在 Windows 非法 | xfail(strict) 在 Linux 上 XPASS | MCP 参数用 `str(Path)` 直接嵌 TOML，`C:\pkg\...` 的 `\p` 是保留转义 | 统一转 POSIX 斜杠再嵌入；xfail 标记移除转为正向断言 |
| `CLAWD_CONFIG_DIR` 被忽略 | features.json 加载恒为空（`assert 0 > 0`） | `_load_features_config()` 只查 `~/.clawd` 与 `cwd/.clawd`，环境变量形同虚设 | 纳入搜索链首位（与 `core/data_dir.py` 同名约定一致） |
| codex 后端"假可用" | `build_argv` 抛"未找到 codex"（6 个测试） | 显式 `binary=["codex"]` 时把裸命令名当**路径**校验 | 裸命令名不在解析期抛错（留给运行时），但 `available()` 如实返回 False、`run()` 给明确错误 |

### 测试自身缺陷（假红/环境依赖）

- `tests/integration/test_phase3_4_integration.py`：`git commit` 未设身份 → CI 容器 exit 128（4 个 ERROR）→ 显式传 `GIT_AUTHOR_*`/`GIT_COMMITTER_*`
- `tests/cli/test_repl_history.py` + `tests/workflow/test_collaborate.py`：rich 按终端宽度把 `--resume` 断行成 `-`+`
`+`-resume`，子串断言在无 TTY 环境失败 → 剥 ANSI + 去空白后断言
- `tests/core/test_local_storage.py`：`Z:/definitely/not/here` 在 Linux 是**合法相对路径**（能创建）→ 改 monkeypatch 精确触发失败路径；`usage --json` 取"最后一行"会拿到 stderr 横幅 → 按 JSON 行提取
- `tests/core/test_git_integration_deep.py`：顶层 `import git` 在无 git 环境整文件收集失败 → `pytest.importorskip`
- `pyproject.toml` 的 `dev` extras 缺 `pathspec`（watch 测试要）→ 补上（`watch` extra 里有，CI 只装 `.[dev]`）

### 顺带

- `GitManager` 导入 gitpython 前设 `GIT_PYTHON_REFRESH=quiet`，避免无 git 环境打印大段指引并污染收集

### 验证

- 本机 Windows：`pytest tests/core tests/config tests/backends tests/test_security -q` → **1213 passed / 4 xfailed**
- Linux 容器（`python:3.11-slim` + git，复刻 CI 矩阵）：同一批失败用例 **全绿**（见 evidence）
- `ruff check src tests --select F821,F811,E9` → All checks passed

---

## [v0.89.0] (2026-10-31) — CLI `--json` 全覆盖（查询类）+ R6 + P3 台账清零

### CLI：查询类命令全部接入 `--json` 契约（X-7 收尾）
- 新接入 12 个命令：`explore / pipeline / ralplan / quality-gate / config(+--generate/--reset) /
  permissions / agent list·show·keywords·intent / autonomy list·log / role show / eval`
- 统一契约 `{ok, code, ...业务字段}`；**退出码等于 `code`**；错误也输出合法 JSON
  （`agent show 不存在的名字 --json` → `ok:false` + exit 1，而不是中文报错混进 stdout）
- `agent list --format json` 与 `--json` 合并为同一契约（裸数组形态废弃）
- `--json` 时**日志整体改道 stderr**（`src/utils/logger.py`）：修"命令记一条 INFO，`| jq` 就崩"
  —— 机器可读输出是整条进程的约束，不是最后 print 一下的事
- 交互式/长驻命令（`chat/run/serve/collaborate/workflow *`）**故意不给** `--json`，README 写明边界
- 新增 `tests/cli/test_json_contract_queries.py`（27 条）：逐命令契约 + stdout 纯净度 + 真落盘

### R6（上轮如实未做项）：视觉降级改为**轮内**重试
- 修前：带图请求失败 → 外层 `continue` 剥图重试，**吃掉一次迭代额度** ——
  `max_iterations=1` 或最后一轮带图失败时，用户拿不到任何回答（降级等于没生效）
- 修后：同一轮内原地重试（内层 while），`max_iterations` 不被降级消耗；
  新增 loop 级测试钉住"同一轮内两次调用、只一条 assistant 消息"

### P3 台账五项清零（v0.88.10 报告 §5 遗留）
1. `generate_tool_signatures` 接上生产调用方：`clawd config --generate` 注入真实工具清单 →
   `tool_signatures.json`（原子写）；报告如实显示"工具签名: N 个"；core 不越界 import（CLI 层注入）
2. git 只读清单**单一来源**：`allowlist.py` 导出 18 项公开名；`bash_security.py` 删掉自己那份
   12 项副本改为 import（修"同一条 `git show-ref` 两套判定结论相反"）
3. `team_persistence._get_team_state_path()` 删死参数 `cwd`；公开 API 保留形参（兼容）并注明不参与路径
4. `fast_mode` 把输出压到 1024 时**必须告知**：`SYSTEM_CONFIG_CHANGED` 告警事件（WS 广播 +
   前端 trace 直接显示中文原因）；未截断不打扰；`FAST_MODE_MAX_TOKENS` 提为常量
5. litellm 兜底价补 `cache_creation_input_token_cost` → `cache_write_price`
   （原恒 0，Anthropic 系 cache write 比输入贵 1.25x，长期低估成本）

### 工程化
- **装机 E2E 入库**：`scripts/e2e_desktop_install.ps1`（装→版本/内嵌host/prompts校验→启动→API→
  403 鉴权→真浏览器 UI E2E→重启持久化→无残留→卸载→注册表 0；退出码=失败项数）。
  此前这条链路是会话里手打的一次性脚本，跑完即丢，每轮重拼还重复踩坑
- `tests/cli/test_entrypoint_commands.py` 的两条 doctor 用例改为注入体检结果
  （修"单独跑必红、整套跑被偷偷加载的 `.env` 掩盖"的环境依赖假红）
- `docs/MAINTENANCE.md` 新增 §3.4「给命令加 --json」（七条要求 + 自查命令）；
  §5.5 补"bump 版本后要删 `clawd_code.egg-info/`"（本轮实测：它盖过新 dist-info，
  `importlib.metadata` 返回旧版本，版本一致性测试直接红）
- `.agent/memory/` 更新 change-index / known-issues / decisions（D-28~30）

### 验证（全部实跑）
- 全量非 slow：**5440 passed / 7 skipped / 8 xfailed / 0 failed**（375.04s）；收集 **5464 / 0 errors**
- 覆盖率 **66.27%**（38699/58394，门禁 60 生效）；静默吞异常 **155**（未回升）；可达 **503**（基线 501 未降）
- 契约 39 passed；IMPORT-FAIL 0；core 边界 PASS；假成功扫描 0；MCP 启动 4/4；`verify_audit_p1` 28/28（文档数字同步后）
- 真实端点：`e2e_smoke` **5/5** · `e2e_production` **8/8**（按 policy.md 最小配额）
- 压测（本地 Host）：200 并发×10 轮 **QPS 2514 / P99 15.6ms / 错误率 0%**；300×5 QPS 1355 / 0%
- `--json` 12 命令逐一实测：stdout 单行合法 JSON、退出码一致

### 边界（不粉饰）
- 正式代码签名仍需 CA 证书；真实视觉对话仍需支持 `image_url` 的端点（`scripts/probe_vision_endpoint.py` 可复现）
- `workflow ralplan/team/ralph/autopilot`（命令组版本）与 `session fork/title/resume` 未接 `--json`（属长任务，见 D-28）
- 装机 E2E 本轮静态审查 + 语法校验；真机安装链路见 `scripts/e2e_desktop_install.ps1` 的用法说明

---

## [v0.88.10] (2026-10-30) — 采纳 Critic 的 P2 建议（5 项）+ 修 E2E 自身脆弱断言

独立 Critic 除 P0/P1 外还列了 R4~R9。本轮落地 5 项，1 项如实不做（理由见下）。

| 项 | 内容 | 验证 |
|---|---|---|
| **R9** | WS 传入的 `session_id` 同 HTTP query 一样不可信 → 复用 `_safe_session_id()` 白名单，非法则回落新开会话 | `tests/server` 全绿 |
| **R4** | 图片 token 改**常量累加**（`IMAGE_TOKEN_ESTIMATE`），不再用 `" " * (85*4)` 占位近似；顺手删掉被取代的 `_content_text` 死代码 | `tests/agent+server+llm` 1169 passed |
| **R5** | 视觉分支先用 `build_image_blocks()` 拿**真实块数**：全部超限/读不到时回退"路径告知"（否则模型以为图已在上下文里） | 同上 |
| **R7** | `resolve_log_dir()` 支持既有 `WORK_DIR` 约定（此前只认 `CLAWD_DATA_DIR`，`WORK_DIR` 形同虚设） | `test_log_dir` 6 passed |
| **R8** | team-exec 异常/取消路径统一收尾（`except BaseException` → 先 `_finish_team_state` 再 `raise`），避免 `team-state.json` 永远停在 `executing`、成员一直 busy | `tests/workflow` 488 passed |
| **R6（部分）** | 新增 **loop 级**降级测试：provider 首次抛连接错误 → 第二次自动改发纯文本（证明降级在整条链路生效，不只是 helper） | `test_vision_degrade_loop.py` 2 passed |

**R6 的"降级不占迭代"没做**（如实记录）：循环是 `for iteration in range(max_iterations)`，
要改成"原地重试"必须把整段 LLM 调用抽成函数再包重试 —— 属核心循环重构，风险大于收益
（当前降级只在"最后一轮恰好失败"时无效）。留作下轮 P3。

**顺带修了 E2E 自身的两处脆弱断言**（0.88.9 装机时暴露）：
- 「工具调用默认折叠成一组」原断言 `groupsAfter > before`、"展开后逐条可见"原断言 `items === 3`
  —— 但真实 run 已经产生过工具组，新事件会**复用同一组**，于是 `before=1`、`items=7` 让断言假红。
  改为 `groupsAfter >= 1 && collapsedByDefault` 与 `items >= 3 && openAfterClick`。

**验证**
- 全量非 slow：见下（本轮复跑）
- 0.88.9 装机终验：STEP2b/2c exit 0、**「未带 token 的写操作被拒绝（403）」PASS（P0 修复装机态确认）**、
  STEP2e/2f PASS、STEP3 残留 0、STEP5 注册表残留 0

---

## [v0.88.9] (2026-10-30) — 独立审查抓到的 P0/P1 修复（路径穿越删配置 / 任务丢失 / 跨 provider 选型）

独立 Critic（只读、不继承实现方推理）审 v0.86→v0.88.5，实跑后给出 **CONDITIONAL PASS**，
列出 1 个 P0 + 2 个 P1。全部修复并各自补了回归测试。

### P0（安全）：`/api/session/delete?id=../providers` 可删掉含 API key 的配置
Critic 的实跑证据：
```
GET /api/session/delete?id=../providers  →  200 {"ok": true}
providers.json 还在吗: False        # 含 api_key 的配置被删
```
两个根因叠加：
1. `session_bridge` 把 id 直接拼成 `<dir>/<id>.json`，`../providers` 一步穿越到数据目录；
2. `/api/session/rename|delete` 这些**破坏性**端点在 HTTP 层**完全没有 token 校验**
   （本机任意进程、或网页 CSRF 的简单 GET 就能触发）。

修复（两道防线）：
- `session_bridge._safe_session_id()`：白名单 `^[A-Za-z0-9._-]{1,80}$` 且禁 `..`，
  在 `load` / `save` / `rename` / `delete_session` 四个入口统一校验，不合法抛 `ValueError`
- HTTP 层：`/api/session/rename|delete` 必须带 `?token=` 或 `X-Clawd-Token`（`secrets.compare_digest`），
  否则 403；前端与 E2E 同步带 token，E2E 新增「无 token 必须 403」断言
- 新增 `tests/server/test_session_delete_security.py`（6 条）：穿越 id 被拒且 `providers.json` 仍在、
  无 token 403、带 token 正常删除、带 token 也不能穿越

### P1：pipeline 把 `ctx.task` 填成 `session_id`，team-exec/ralplan 全程跑空任务
`PipelineModeState` 没有 `task` 字段，`_initialize_state(task, ...)` 收到的目标初始化后就丢了，
构建 `StageContext` 时只能填 `self._state.session_id`（那串 hex）。
**上一版测试之所以是绿的**：它手工构造 `StageContext(task="...")`，绕开了真实 pipeline 的上下文构造。
修复：状态里真正存 `task`（`to_dict` 随 `asdict` 自动带上，`from_dict` 兼容旧文件缺字段），
`StageContext(task=self._state.task or self._state.session_id)`。
新增 `tests/workflow/test_pipeline_task_propagation.py`（4 条，**两条走真实 `run()` 入口**）；
`test_pipeline.py` 里那条登记该缺陷的 `xfail(strict)` 自动转正。

### P1：跨 provider 选模型只换 `model`，不换 provider/密钥/base_url
`/api/models` 返回**所有 provider** 的模型，前端原样回传，服务端只 `replace(model=...)`
→ 等于「用 A 家密钥发 B 家模型名」，跨 provider 选型必然失败（默认选第一个时恰好对，演示看不出来）。
修复：模型 id 改为复合键 `provider_id:model`，服务端解析后 `providers_store.build_llm_config(pid)`
取整份配置；前端按钮显示仍取纯模型名。新增 `tests/server/test_model_provider_switch.py`（3 条，
断言切到 B 家后 `api_key`/`base_url` 都换成 B 的）。

### 同时采纳的审查建议（P3）
- 删掉降级分支里的空语句 `if config.publish_token_and_cost: pass`，并把 `str(e)` 带进告警
  （否则降级后二次失败查不到第一因）

**验证**
- 定向：`tests/server + workflow + contracts + cli + agent` **1903 passed**（修完后 1 条 xfail 转正）
- 全量非 slow：见下（本轮复跑）
- `verify_audit_p1.py` 28/28 · `check_doc_drift` 全一致（5413 / 可达 501 / 静默 155）
- 新增 3 个测试文件共 13 条回归测试

---

## [v0.88.8] (2026-10-30) — X-7 收口：6 个命令接入 `--json` 契约 + 压测验收

**接入 `--json` 的命令（全部走 `CommandResult`，字段稳定、退出码一致）**

| 命令 | JSON 结构 |
|---|---|
| `session list` | `{ok, code, sessions[], count}` |
| `session show` | `{ok, code, session_id, title, status, ..., chain, roles}`（默认改为人读摘要） |
| `role list` | `{ok, code, personas[], count}` |
| `doctor` | `{ok, code, ready, checks[{section,level,text}], count, failed}` |
| `catalog list` | `{ok, code, agents[], skills[], count}`（尊重 `--skills`/`--agents`） |
| `catalog show` | `{ok, code, kind, name, category, status, core?, canonical}`；未找到 → `ok=false` |

**顺带修的两处**
- **启动提示污染 stdout**（v0.88.7）：`--json | jq` 原本必崩，已把 4 处启动期提示改到 stderr
- **诊断密钥不回显**（v0.88.7）：只报 `KEY=已设置（不回显）`

**验证（真实运行）**
- 全量非 slow：见 v0.88.7 的 5372 passed / 0 failed；本轮新增 catalog 测试随全量复跑
- **压测（本地 Host，200 并发 × 10 轮）**：成功 200/200，请求 2000，墙钟 0.77s，
  **QPS 2583**，P50 10.7ms / P95 15.9ms / **P99 16.3ms**，**错误率 0.0%** → `STRESS: PASS`
- **真实端点 E2E（`scripts/e2e_smoke.py`）5/5 通过**（读配置 / 应用可导入 / 真实对话 /
  function calling / reasoning_content）
- 基线 17 项：版本三处一致 0.88.8 · 收集 5399/0 errors · ruff 硬指标 ok · 静默 155 ·
  可达 501 · 完全不可达 26 · import_sweep ok(0) · 覆盖率 65.54%（门槛 60）

---

## [v0.88.7] (2026-10-30) — X-7 第二批：doctor --json + stdout 纯净

**1. `clawd doctor --json`（重构为"先收集再渲染"，单一来源）**
`_handle_doctor()` 以前是"边查边打印"，机器读不到。现在拆成：
- `collect_doctor_report()` → `{ready, checks[], count, failed}`（每项带 `section`/`level`/`text`）
- `_handle_doctor()` 只负责渲染；`--json` 用同一份数据 `emit`
两种模式**退出码一致**（无 fail 项 → 0，有 fail 项 → 1），CI 可直接用。

**2. 顺带修一个会毁掉所有 `--json` 的缺陷：启动提示污染 stdout**
`clawd doctor --json | jq` 本来必崩 —— 因为 CLI 启动时会往 **stdout** 打
`[*] 结构化日志已启用: ...`。这类人读提示按 Unix 惯例应走 stderr。
已把 4 处启动期提示改到 stderr（Tracing 已启用 / 结构化日志已启用 / 启动与停止优化引擎），
**stdout 现在只留命令结果**。实测 `python -m src doctor --json` 首字节就是 `{`。

**3. 密钥不回显（安全）**
诊断里 API Key 以前会打印 `前8位...后4位` 掩码；JSON 比人读更容易被采集/上报，
现在只报 `KEY=已设置（不回显）`，一个字符都不给。

**验证**
- 新增 `tests/cli/test_doctor_json.py` 4 条：报告结构、JSON 契约（`ok` 与 `code` 一致、
  退出码与 code 一致）、**明文密钥不泄漏**、人读模式仍可用
- 真实调用：`python -m src doctor --json` 输出单行合法 JSON（首字节 `{`）
- `tests/cli` **481 passed**

---

## [v0.88.6] (2026-10-30) — 死码清理（1804 行）：删"确定死"的，保留参考快照与真实能力

按《死代码判定-2026-10-28》的方法复核当前 33 个"完全不可达"模块（5904 行），删掉确定死的部分。
**关键判断：绝大多数"包不可达"其实是包的 `__init__.py` 没被直接 import**（调用方都直接 import 子模块），
删目录会误删活代码（例如 `core/security/allowlist.py` 就在一个"不可达"的包里），所以只删单文件死码。

**删除（1804 行，`git rm` 7 个文件）**
| 文件 | 行数 | 依据 |
|---|---:|---|
| `src/core/hook_registry/async_executor.py` | 606 | 旧的 hook 执行器；活的实现在 `hook_registry/registry.py`（`execute_hook`）。全仓库仅 `scripts/deadcode_inventory.py` 的注释提到名字 |
| `src/workflow/team/state/tasks.py` | 252 | 与 `team_persistence`（v0.88.5 已接线）语义重叠的第二套团队状态实现，零生产调用方 |
| `src/workflow/team/state/mailbox.py` | 265 | 同上 |
| `src/workflow/team/state/dispatch.py` | 199 | 同上 |
| `src/workflow/team/state/dispatch_lock.py` | 149 | 同上 |
| `src/workflow/team/state/approvals.py` | 177 | 同上 |
| `src/workflow/team/state/monitor.py` | 156 | 同上 |

`team/state/__init__.py` 同步重写：只导出 `locks.py` 的 8 个符号（真实的跨进程文件锁，
有独立测试 `test_team_state_locks.py`），并写明"团队状态以 `team_persistence` 为单入口"。

**保留（有明确理由，不删）**
- `src/hooks/*` 15 个模块：ADR 0019 明确"上游参考快照，不接线"
- `src/agent/modes/*`（674 行）、`src/agent/mailbox.py`（250 行）：未接线但属真实能力，删=砍功能
- `src/workflow/stages/{precontext_intake,ralph_verify}_stage.py`：未接线的 stage 实现，与已接线的 stage 同构
- 各包的 `__init__.py`（`core/security`、`security`、`core/utils`、`workflow/stages`）：
  它们"不可达"只是因为没人直接 import 包本身；**目录里的子模块是活的**

**验证**
- 可达性复核：模块 610→603，生产可达 **500 → 500（未下降）**，完全不可达 33→**26**、5904→**4058** 行
- `pytest tests/workflow` 483 passed · `ruff F821/F811/E9` All passed · `import_sweep` DEP-MISSING 0

---

## [v0.88.5] (2026-10-30) — 团队状态接线（270 行代码首次真跑）+ 定价接 litellm + 依赖锁

按《下一步改进指南》逐条对账后剩下的 4 项，全部处理：

**1. M5：`team_persistence` 接线（此前 270 行零调用）**
`src/workflow/team_persistence.py` 整套 API 造好了，却只在 `workflow/__init__.py` 里 re-export ——
"团队状态持久化"这个能力**从来没跑过**。现在 `TeamExecStage.run()` 三处落盘：
开始写成员（worker-1..N / busy）、成功收尾（idle + phase=completed）、失败收尾（offline + phase=failed），
并写系统消息。
- 顺带修两处**同源缺陷**：①`TEAM_STATE_DIR` 原来写死 `Path(".clawd")/state`（相对 cwd，
  桌面端会落进安装目录）→ 改走 `data_path("state")`；②接线时踩到 `update_member_status`
  的第 3 个参数是 **`current_task`** 而不是 `cwd`，按位置传会把 `cwd` 喂错 → 全部改成关键字传参
  （`add_team_message` 的真实签名也是 `(member_id, content, msg_type, cwd, session_id)`，
  传 `TeamMessage` 对象同样会错位，一并修正）。
- 新增 `tests/workflow/test_team_state_wiring.py`（4 条：成员/phase/时间落盘、失败置 failed、
  `session_id` 作用域隔离、状态目录跟随数据目录且不再写 cwd 的 `.clawd`）。

**2. P2-2：定价表接 litellm 内置价格兜底**
自有 `MODEL_PRICING`（91 条手写快照）已过期 **172 天**，每条 CLI 都警告，成本护栏按旧价估算。
新增 `resolve_pricing()`：**自有表 → litellm 内置（4500+ 模型，随包升级）→ 默认价**，
所有算钱的地方（`get_model_pricing` / 估算 / 记账）统一走它；自有表仍优先，可放自有报价。
实测：`gpt-4o` 走自有表 2.5/10.0，`deepseek-chat` 0.27/1.1，未知模型才落默认价。
新增 `tests/core/test_pricing_resolution.py`（6 条，含"只被 litellm 收录的模型能查到自己价格"
与 provider 前缀归一）。

**3. P2-6：加 `requirements.lock`**
Python 侧一直没有锁文件（`requirements.txt` 全是 `>=`），干净环境无法复现。
新增 `requirements.lock`（149 个精确版本，由 `pip freeze` 生成，文件头写明用途/更新时机）。
`requirements.txt` 保持 `>=` 不动。

**4. P2-5：更新源保持未配置（已确认）**
`build.publish.url` 仍是占位域名，代码里靠 `pkgUrl !== DEFAULT_UPDATE_URL` 判定 →
UI 明确提示"更新源未配置"，**不静默失败**。已与用户确认：占位域名不属于本项目，保持未配置状态。

---

## [v0.88.4] (2026-10-30) — core 边界清零（5 处）+ 修 3 个"调用即崩"的缺陷

**core 层不再 import 任何上层模块**（`scripts/core_surface_allow.json` 已清空，门禁从"允许 5 条存量"变成"0 条"）。
5 处的处理分两类 —— 查证后发现**其中 3 处指向的模块/名字全仓库都不存在**，是靠 `except ImportError` 的内联兜底活着的死引用：

| 位置 | 原依赖 | 真相 | 处理 |
|---|---|---|---|
| `core/patch/atomic_patcher.py` | `tools_runtime.code_edit.fuzzy_matcher` | 真实存在（344 行纯 stdlib） | **下沉**到 `core/patch/fuzzy_matcher.py`，原处改 re-export |
| `core/security/allowlist.py` | `tools_runtime.bash_constants.READ_ONLY_GIT_SUBCOMMANDS` | **该常量不存在** | 清单提升为 core 内唯一来源（并补齐 6 个只读子命令） |
| `core/args_parser.py` | `tools_runtime.code_edit.EDIT_FORMAT_REGISTRY` | **该名字不存在** | 删死引用，内联清单即为权威 |
| `core/config/generator.py` | `tools_runtime.tool_manager.TOOL_REGISTRY` | **该模块不存在**（注册表实为 `registry.ToolRegistry`） | 改成**调用方注入 tools** |
| `core/persistence/run_state.py` | `workflow.models` 的 3 个类 | 真实存在 | `WorkflowStatus` 下沉到 `core/workflow_status.py`；合同/义务模型只做序列化 → 注解改 `Any` |

**顺带修掉同一文件里 3 个"调用即崩"的真实缺陷**（此前用 `xfail(strict=True)` 诚实记着，现已转正向断言）：
1. `clawd config generate` **100% 崩溃** —— 它调 `logger.setLevel(...)`，而 `ClawdLogger` 没有该方法
   → 给 `ClawdLogger` 补 `setLevel()` / `getEffectiveLevel()`；
2. `generate_tool_signatures()` **必然 ModuleNotFoundError** → 改注入式，且新增 `_tool_signature()`
   支持真实工具形态（`name` / `description` / `parameter_schemas`，实测 `FileReadTool` 能产出
   `file_path`/`offset`/`limit` 的 JSON Schema）；
3. frontmatter 写 `categories: []` 时 `[][0]` 抛 IndexError 被 `except` 吞 → **技能静默消失**
   → 新增 `_first_category()` 容错（空列表/字符串/逗号分隔都认）。

**过程中的一个教训**（已写进 `core/workflow_status.py` 的注释）：本想放 `core/models/workflow_status.py`，
但 `core/models.py` **已经是一个模块**，建同名目录把模块遮蔽了 → `from .models import PermissionDenial`
直接 ImportError。同名"模块 vs 包"冲突会静默劫持整个包，落地前必须先 `ls`。

**顺带把「真视觉对话」这件事做了实测定性，并修了它暴露的两个 bug**

用现有端点强试（`CLAWD_VISION=1` + 传图），一路打出两个真实缺陷：

1. **多模态消息直接崩**：`message_truncator.count_tokens()` 拿 `content` 直接喂 tiktoken，
   而带图消息的 `content` 是内容块列表 → `TypeError: a bytes-like object is required, not 'list'`，
   整轮任务失败。修：新增 `_content_text()` 归一化（图片块按 85 token 占位）。
2. **端点拒绝的方式是断连**：`scripts/probe_vision_endpoint.py` 直连对比 —— 纯文本 `PONG` 正常，
   带 `image_url` 立刻 `APIConnectionError`。所以"模型不支持视觉"在这里不是 400。
   修：`_run_agent_loop` 里带图请求失败时**自动降级为纯文本重试一次**
   （`_strip_image_blocks()` 去掉图片块并追加"无法作为图像输入发送，别猜内容"），
   用户看到的是模型如实说"看不到这张图片"，而不是 `LLM 流式调用失败: Connection error.`

实测结论（有证据）：**当前 `step-5-preview` 端点不支持图像输入**；多模态代码路径、能力判定、
诚实回退、失败降级全部可用，换一个真支持视觉的模型即可真看图。

**验证**：`core_surface.py` PASS（存量 0）· 定向回归 `tests/core+workflow` 1451 passed ·
`tests/core+security+cli` 1448 passed · `tests/core/test_config_generator.py` 44 passed。

---

## [v0.88.3] (2026-10-30) — 结构化日志跟随数据目录（不再写进安装目录）

`src/main.py` 里日志目录写死 `WORK_DIR/.clawd/logs`，而桌面端的 cwd 是 `resources/host` ——
日志落在**安装目录**里：升级覆盖即丢，安装目录还可能只读。排障时按文档找不到日志。

- 新增 `src/utils/logger.py: resolve_log_dir(workdir=None)`：统一走 `data_dir` 唯一入口
  （与 provider / 会话 / 用量同一套规则，见 ADR 0022），数据目录不可用时才回落工作区并告警
- `src/main.py` 改用它；`ENABLE_FILE_LOGGING=false` 的行为不变（打包自检依赖它）
- 新增 `tests/core/test_log_dir.py`（6 条：跟随 CLAWD_DATA_DIR / 与 cwd 无关且不在 cwd 造
  `.clawd` / 无 env 时回落工作区 / 显式 workdir / main.py 不得再硬编码 WORK_DIR 日志路径 /
  开关仍有效）

---

## [v0.88.2] (2026-10-30) — UI 细节：标题残留提示词、会话行被按钮挤压

- 会话标题里的 goal 会被截断到 60 字（没有收尾的 `]`），原来的剥离正则要求闭合括号 →
  标题栏继续显示 `[随消息附图 1 张，已保存到本机: …`。改成不要求闭合，
  并对「完整 note / 截断 note / 纯文本」三种输入做过验证。
- 会话行悬停出现 `✎`/`✕` 后，标题被挤成一两个字宽、时间被压成竖排 →
  标题 `flex:1 1 auto` + 省略号，时间 `nowrap`。
- 验证：控制台 UI E2E **32 项全绿**；截图 `21-session-loaded.png` 复核。

---

## [v0.88.1] (2026-10-30) — 会话重命名/删除/搜索 + 修内联图片 403

**1. 会话管理（参考客户端标配）**
- 侧栏会话行悬停出现 `✎` / `✕`：重命名（只改标题，消息不丢）、删除（只删这一条会话文件）
- 侧栏加「搜索会话标题…」，输入即过滤（纯前端）
- 新端点：`/api/session/rename?id=&title=`、`/api/session/delete?id=`

**2. 修 `/api/file` 只认 cwd 导致的内联图片 403**
桌面端粘贴的图片落在 `<数据目录>/uploads`，而这个端点只允许 `Path.cwd()` 下的文件 ——
等于 Markdown 里的本地图片**一律 403**（v0.86 的 E2E 没抓到，是因为探针图被放进了
`resources/host`，恰好落在 cwd 里）。现在同时放行数据目录，但仍只允许图片后缀：
`providers.json` 这类配置继续 403（有测试守着）。

**验证**
- 新增 `tests/server/test_session_admin_api.py`（7 条：改名只改标题不丢消息 / 缺 id 400 /
  不存在 404 / 删除只删那一条 / 未知会话 ok=false / 数据目录图片 200 且是 PNG / providers.json 仍 403）
- 控制台 UI E2E 31 → **32 项全绿**（新增「会话可重命名 + 搜索过滤 + 删除（只动那一条）」）
- 顺带修了 E2E 自己的忙判定：按钮改成"忙时变停止"后不再 disabled，5 个脚本里
  `#send.disabled` 的等待全部失效（会在模型还没回时就判定完成，`ui_stream_persona_e2e`
  因此误报"不是真流式 deltaCount=0"）→ 统一改看 `stop-mode` class

---

## [v0.88.0] (2026-10-30) — 客户端"去垃圾"：输入框被顶出屏幕 + 协议原文漏渲染 + 停止生成

按"自己截图逐项挑毛病"的方式把桌面端又过了一遍，抓到 7 个用户一眼能看见的问题：

**1. 输入框在屏幕外（最严重）**
长会话会把 `main` 撑到 2038px，composer 跑到 `y=1895`（视口只有 860）——
用户看到的界面**根本没有输入框**。修：`main` 自己限高 + `overflow:hidden`，
`.view` 内部滚动；侧栏也改成"项目/会话各自滚动、底部入口固定"。
E2E 之前抓不到是因为 Playwright 会自动滚动到元素，所以新增断言
**「composer 必须在视口内」**（第 30 项）。

**2. 模型输出的 `<tool>{...}</tool>` 协议原文被渲染进气泡**
真实截图里助手回复是：`<tool>{"name": "BashTool", ...}</tool>` —— 这就是"半成品"的观感来源。
修：`stripToolProtocol()` 在渲染前剥掉三种协议的写法（`<tool>{json}</tool>`、
`<tool_call><x>{json}</x></tool_call>`、遗留 `<tool>Name</tool><args>{json}</args>`），
JSON 用**括号平衡扫描**取（正则 `\{.*?\}` 会在嵌套对象处截断，实测踩到）；
剥离后若正文为空则给一行淡色工具摘要（`⚙ BashTool ×2`），不留空气泡；
流式途中用 partial 模式，避免闪出半截 `<tool>{"na`。

**3. 注入给模型的说明被当成"用户说的话"显示**
用户气泡里出现`[随消息附图 1 张，已保存到本机: C:\Users\...]`。修：气泡与会话标题都剥掉这段。

**4. 同一条错误显示两遍，还带 `[E1002]` 与英文堆栈**
修：3 秒内同一条错误只显示一次；正文只说人话（"LLM 流式调用失败: Connection error."），
完整信息放 `title`。

**5. 模型挂住时按钮永久禁用，只能重启应用**
这是真卡死：`_message_loop` 以前 `await dispatch(...)` 串行执行，运行期间收不到任何消息。
修：run 起独立 task；新增 `cancel` 消息 —— **停止生成**（忙时发送键变 `■`，
点击打断，中断后回 `status: cancelled` 并解锁）；上一轮没结束时再发 run 返回 `E_BUSY`。
另加前端看门狗：解锁后 1.5s 若气泡仍"输出中"就强制收尾。

**6. 切会话/新会话后再回复，内容写进"看不见的地方"**
`$chat.innerHTML = ''` 时没重置 `streamEl`，后续增量写进已被移除的节点 → 气泡空白。
修：统一 `resetChatArea()`（清 DOM 同时重置 streamEl/streamBuf/pendingFinal）；
迟到的 `started`/delta 在 3 秒窗口内直接丢弃。

**7. 每轮 run 都新开一条会话 → 侧栏堆出 37 条同名记录**
修：续聊时客户端回传 `session_id`，Host **追加**到同一会话（`append=True`，
保留首次 title 与 created_at）；侧栏每项目默认只列最近 8 条，其余折成「还有 N 条 ▾」。

**顺带做的体验补齐**：空态欢迎区（一句"能干什么" + 3 个可点示例）、模型列表标「👁 可看图」、
不支持视觉时附件 chip 显示 `👁✕`、空回复给「（模型没有返回内容…）」而不是留白。

**验证**
- 控制台 UI E2E **31 项全绿**（新增：composer 在视口内、正文不露协议、忙时按钮变停止）
- 后端定向回归 `tests/server+core+agent+contracts` **1872 passed / 0 failed**
- 新增测试：`test_session_append.py`（5 条：追加不覆盖/保留 title/created_at/无 append 时覆盖）、
  `test_cancel.py`（3 条：run 不阻塞消息循环且 cancel 真打断 / E_BUSY / 空 cancel 无害）
- 走查截图：`20-main-empty.png`（空态+输入框可见）、`21-session-loaded.png`（无协议原文）

---

## [v0.87.0] (2026-10-30) — 真多模态：图片作为图像内容块进消息

此前桌面端粘贴图片只是"落盘 + 把路径写进 goal"，模型没有视觉能力就只能说看不到。
现在按模型能力分流：

- **视觉模型**（`gpt-4o`/`gpt-4.1`/`claude-3|4`/`gemini`/`qwen-vl`/`glm-4v`/`llava`/`pixtral`/
  `step-1v` 等，见 `src/llm/vision.py` 的 `VISION_MODEL_HINTS`）：
  图片转成 `[{"type":"text",…},{"type":"image_url","image_url":{"url":"data:image/png;base64,…"}}]`
  内容块随消息发出，模型直接看图回答；
- **其他模型**：保持原行为 —— 路径写进 goal + "看不到就直说，不要猜内容"；
- 开关：`CLAWD_VISION=1` / `0` 可强制开/关（模型名认不出来时**保守回退**，不硬塞内容块换 400）。

实现要点：
- `LLMMessage.content` 放宽为 `str | list[dict]`（没图时仍是纯字符串，旧行为不变）；
- `AgentLoopConfig.images` + `build_initial_messages()` 负责拼内容块；
  `engine.run/run_stream(images=…)` 透传；`/run` 按 `supports_vision(model)` 决定走哪条路；
- 单图 ≤ 2MB、单条消息 ≤ 4 张（base64 会膨胀 ~33%，超限直接跳过并记 debug 日志）；
- 读不到/超限的图**跳过而不是让整条消息失败**；全读不到时退回纯文本。

验证：
- `tests/llm/test_vision_blocks.py`（13 条：模型判定/环境变量强制/块构造/超大跳过/缺文件跳过/
  有图用块、无图用字符串、全读不到回退）；
- `tests/server/test_vision_pass_through.py`（6 条：视觉模型收到 images 且 goal 不含本机路径、
  非视觉模型 `images=None` 且 goal 有路径与"不要猜"、`CLAWD_VISION` 双向强制、非流式路径同样带图）；
- 真实视觉对话**待验证**：当前配置的 `step-5-preview` 不在白名单（无视觉证据），
  需要一个支持视觉的模型才能端到端跑通；单测已覆盖块构造与回退，真实调用留给有模型的环境。

---

## [v0.86.0] (2026-10-30) — 客户端照抄参考项目 + 会话按项目分组 + 右下角 toast + 修 3 个启动级 bug

按"先抄完再改"的要求，把参考客户端最核心的四块照抄过来（结构对齐、实现用我们的后端）：

**1. 项目（工作区）侧栏**
- 侧栏新增「项目」区：列出项目、点一下就切换（高亮当前）、`✕` 从列表移除（**不删文件**）；
- 项目存 `<数据目录>/projects.json`（JSON）；**新会话的工作目录 = 当前项目**（`run` 消息带 `workdir`，
  Host 传给引擎 `create(workdir=...)`）；
- `＋` 打开「添加项目」对话框（和你给的截图一致：主机下拉 / 浏览文件夹 / 从 URL 克隆）。

**2. 添加项目两条真实路径**
- **浏览文件夹**：走 Electron 原生选择器（`ipcMain.handle('clawd:pick-folder')` + preload `pickFolder()`）；
  非 Electron（纯网页）时自动降级为"粘贴路径"输入；
- **从 URL 克隆**：Host 真跑 `git clone --depth 1` 到 `<数据目录>/clones/<name>` 并自动加入项目列表。

**3. 模型选择器（照抄：搜索 + 推理强度 + 快速模式）**
- composer 左侧「模型 ⌄」按钮打开面板：搜索框、模型列表（含 provider 来源）、
  **推理强度 低/中/高/极高/最大**、**快速模式**开关（按钮会显示「模型 · 快速」）；
- `run` 消息带 `model` / `reasoning_effort` / `fast_mode`：Host 侧把推理强度映射成 temperature
  （0.9→0.0），快速模式把 max_tokens 压到 ≤1024；`/api/models` 与 WS `models_list` 提供清单。

**4. 会话计时**
- 会话栏显示「工作了 12s / 2m 3s」（每轮开始计时、结束停止）—— 对齐截图里那行"工作了 32m 3s"。

**装到机器上又抓到 1 个启动级 bug（已修）**
第一次打出来的 0.86.0 安装包**根本打不开**：`main.js` 里用了 `ipcMain.handle(...)`（新增的文件夹选择器），
但顶部 `require('electron')` 解构里**没有 ipcMain** → `registerIpcHandlers()` 抛 ReferenceError →
主进程在创建窗口前就挂了，Host 不启动、E2E 只看到"120s 内未生成端口文件"。
`node --check` 查不出来（语法合法），已补导入；并新增 `tests/test_electron_main_static.py`（6 条）
静态核对"用到的 electron 符号必须都解构导入 / 不再有默认菜单 / preload 不透 Node 能力"。

**第二处启动级 bug（同一天修完）**
补完导入后装出来还是打不开，日志是 `Cannot access 'ipcMain' before initialization`：
`registerIpcHandlers()` **函数体内**又写了一次 `const { ipcMain, app } = require('electron')`，
函数作用域里的 `const` 把整段提升成 TDZ，上方几十个 `ipcMain.handle(...)` 全部访问到未初始化绑定。
删掉函数内重复解构（改成注释说明为什么不能写），并把静态检查加到 **7 条**
（新增"同一函数内先用后声明"检测，**反向验证过**：故意注入重复解构 → 立刻 FAIL，恢复 → PASS）。

**会话按项目分组 + 更新提示改右下角 toast（本轮收口）**
- 会话落盘时把 `workdir` 写进 metadata；侧栏按 workdir 分组，组标题用项目名、右侧显示条数，
  未关联项目的会话沉到最下面（此前所有会话平铺一列，分不清哪个项目）。
- 更新提示不再挤在侧栏文字行里：右下角 toast 单条贯穿"检查→下载中→已就绪"，
  就绪时给「重启安装 / 稍后」，新增 `clawd:quit-and-install` IPC + preload 桥（此前只有 autoUpdater 内部会自动装，用户点不到）。
- **顺带修一个"侧栏永远空着"的根因**：`/api/sessions` 与 `/api/session` 把会话目录硬编码成
  `Path.cwd() / '.clawd' / 'sessions'`，而桌面端数据在 `userData/data/sessions` ——
  引擎写得再多侧栏也读不到。两个端点改走 `data_path('sessions')`（数据目录唯一入口）。
- 新增 `tests/server/test_sessions_api.py`（4 条**真 HTTP**：cwd 指向空目录仍能列出、条目带 `workdir`、
  详情能读回、缺失 404）+ 会话 workdir 3 条单测。

**第三处启动级 bug：打包版 Host 缺依赖（同一天修完）**
补完 TDZ 后再装，应用起来了但窗口只有 `Error`、端口文件不生成、userData 里连日志都没有。
手工用内嵌解释器跑一次就现形：
```
desktop/host/python/python.exe -m src serve
→ ModuleNotFoundError: No module named 'annotated_doc'
```
根因在 `scripts/prepare_host_bundle.py` 的依赖闭包：它把包名用**逗号**拼成一个参数
（`pip show a,b,c`），pip 只当作"一个不存在的包名" → **闭包永远为空**，
白名单实际只有「AST 扫到的直接 import + 人工补的名字」。typer 0.27 的间接依赖
`annotated-doc` 因此从来没进过 bundle（这也解释了为什么 `WHITELIST_EXTRA` 里要手工补
`pydantic_core`/`anyio`/`certifi` 等一长串传递依赖）。
修法：空格分隔 + 分批（40/批）+ 新增 **[5/5] 自检**——用**打包后的解释器**跑
`import typer, rich, click` 与 `-m src --help`，失败直接中断打包；
另外把 loguru 的 Windows 可选依赖 `win32_setctime` 也带上（它只在 loguru 的 extra 里，
缺了每次启动都打一条"模块导入失败"噪音）。白名单 91 → 101 个包。
修完再装，又暴露两个更深的：`No module named 'exceptiongroup'`（anyio 在 py3.10 的依赖，
**这个 venv 里 anyio 的 METADATA 根本没有 Requires-Dist**，靠元数据推闭包永远推不出来）
和 `ImportError: DLL load failed while importing _psutil_windows`（手写 DLL 清单漏了 `python3.dll`），
以及 `PackageNotFoundError: No package metadata was found for httpx2`
（只拷包目录、没拷 `*.dist-info`，而 anthropic 等包 import 时会读自己的版本元数据）。
于是 [5/5] 从"打勾检查"升级为**真实 import + 缺什么自动补什么**：
用打包后的解释器逐个 probe（typer/openai/anthropic/litellm/httpx/tiktoken/websockets/pydantic/
loguru/psutil/toml + `src.cli.entrypoint` + `src.server`），从 `ModuleNotFoundError` 里解析缺的模块名，
从 venv 补齐后重试（最多 30 轮），补不齐就中断；顶层 `*.dll` 改成全量复制；
dist-info 跟包一起拷；`.pth` 一律不拷（venv 的 editable finder 会把 sys.path 指回本机源码目录）；
自检子进程禁用文件日志，跑完清掉 `.clawd/`，避免把开发机日志打进安装包。
契约测试新增 6 条钉住这些（含"不得复制 .pth"、"dist-info 必须随包复制"）。

**图片附件"传上去了模型却不知道"（装机验证发现，已修）**
粘贴图片确实落到了 `<数据目录>/uploads/img-<hash>.png`，但代码用
`target.relative_to(self._workdir())` 转相对路径 —— 上传目录在数据目录（userData/data），
根本不在工作目录这棵树里，`relative_to` 抛 ValueError 被 `except` 吞掉，
**goal 里一条附件路径都没有**。用户看到的现象就是"图传上去了，模型说没看到图"。
改为写**绝对路径**并明确告知"模型不支持视觉就直说看不到，不要猜"，新增
`tests/server/test_attachments_goal.py`（4 条，含"工作目录与数据目录不同树"的场景）。

顺带把"验证什么"分层，别再拿不可控的东西当门禁：
- `scripts/prepare_host_bundle.py` 的 [5/5] 增加**真实执行一次 FileReadTool** 的探针
  （工具本体能不能跑是确定性事实）；
- `desktop/final_verify.mjs` 的硬断言改为"真实 LLM 有实质回复"，
  "模型是否按预期调工具"降级为信息输出 —— 实测 `step-5-preview` 会回"我没有可用的
  FileReadTool"，而打包版实际注册了 7 个工具且能执行，模型遵从性不该记在产品账上。

还有一处"自己把自己测挂"的乌龙（值得记）：STEP2e 段末尾残留一句
`taskkill /PID $app2.Id /T /F`，把刚重启起来的实例杀了，紧接着 STEP2f 检查
"重启后应用是否存活" → 永远 False、退出码 1。定位花了三轮：`diag_restart.ps1`
（装→启动→杀→再启动）存活 120s、`/api/providers` 200；`diag_restart_after_e2e.ps1`
（先跑完 27 项 Playwright 再重启）存活 60s；最后在"等端口循环"里逐轮查存活，
抓到"端口就绪 2s、app2 存活=True"→ 死亡点锁在 STEP2e 末尾两行。
教训：E2E 报"进程自己退了"时，先通读脚本里所有 `taskkill`/`Stop-Process`，再怀疑产品。

另外排错时修了 E2E 自身的两处假阴性：
- `final_verify.mjs` 把探针文件写到 `resources/host`，而 UI 当前项目是别的目录 →
  引擎按越界拒绝，回复"文件不存在: <repo>/desktop/final_probe.txt"。改为先读
  `/api/projects` 把探针写进**当前项目**目录。
- 装机脚本按 productName 猜 userData 目录（`%APPDATA%\Clawd Desktop`），
  实际是 `%APPDATA%\clawd-desktop`（Electron 用 package.json 的 `name`）→
  "附件落盘数=0"是查错目录；STEP2f 增加了重读端口 + 重试，STEP5 先留证再清理。

**验证（实跑）**
- 控制台 E2E **28 项全绿**：添加项目后出现在侧栏并可选中、
  模型选择器（列表 + 5 档推理强度 + 快速模式切换后按钮标注「… · 快速」）、工具折叠（命令 2 · 读取 1）、
  上下文面板（20.1k/200k 10%）、用量页、provider 掩码。
- 再扩 3 项（会话分组数=唯一项目数、`workdir` 字段、toast 出现在右下角）→ 27 项；v0.87.0 又加 1 项（模型列表视觉能力标注与后端一致）→ **28 项**。
- 新增 `tests/core/test_projects_store.py`（7 条：增删/切换/持久化/目录消失标记/active_workdir）。
- 走查截图：`29-add-project.png`、`30-model-picker.png`、`26-tool-fold.png`、`28-context-panel.png`、
  `31-session-groups.png`、`32-toast.png`。

---

## [v0.85.0] (2026-10-30) — 修「重启后数据丢」+ provider 改 JSON + 工具调用折叠 + 上下文面板

**1. 修致命问题：重启/升级后 provider、用量、会话全丢**
根因：桌面端把 Host 的 cwd 设成**安装目录**，于是 `.clawd/` 落在 `resources/host` 里，
升级/重装覆盖安装目录 → 数据一起没了。
- 新增 `src/core/data_dir.py`：数据目录解析 `CLAWD_DATA_DIR`（桌面端 = `userData/data`）→ 否则 `<workdir>/.clawd`；
  `local_db`（用量 SQLite）、`session_bridge`（会话）、附件上传、引擎落盘**全部改用它**；
- Electron 启动 Host 时传 `--data-dir <userData>/data` 并设同名环境变量；
  **旧数据自动迁移一次**（把安装目录里的 `.clawd` 拷到 userData，已有文件不覆盖，只迁移一次）。

**2. provider 配置改 JSON（你明确要求的）**
`<数据目录>/providers.json`：可读、可手改、升级不丢；写入用临时文件 + `os.replace` 原子替换。
老版本存在 SQLite 里的 provider **自动迁移**到 JSON（一次性）。
用量仍留 SQLite（高频、持续增长、要 GROUP BY）——这一点我保留了技术判断，理由写在模块 docstring 里。

**3. 工具调用折叠成一组（参考你给的那几张图）**
对话区不再一条条平铺工具行，而是折叠成一个组：
`🔧 命令 2 · 读取 1 · 执行中… ⌄` —— 点开逐条显示（✓/✗ + 工具名 + 参数，点某条看完整输出）。
LLM 轮次/token 之类的噪音事件只进「轨迹」页，不再污染对话区。

**4. 上下文用量面板（参考 orca 的"上下文 872.8k/1M"）**
输入框左侧新增 ◎ 按钮：显示 `已用 / 窗口（百分比）` + 进度条 + 分项（消息历史、技能清单、剩余空间），
数据来自新端点 `/api/context`（窗口大小可用 `CLAWD_CONTEXT_WINDOW` 覆盖，默认 200k）。

**5. 其它**
`clawd serve --data-dir`；`/api/info` 显示数据目录与 providers.json 位置（设置页能看到"配置到底存哪"）。

**验证（实跑）**
- 新增 `tests/core/test_data_dir_and_providers_json.py`（13 条，含**跨进程重启后仍能读到配置**）
- 控制台 E2E 扩到 **21 项**：工具默认折叠成一组（`命令 2 · 读取 1`、展开后 3 条）、上下文面板（`12.9k / 200.0k 6%`）全 PASS
- `tests/core+server+cli` 1459 passed；ruff F821/F811/E9 全过

---

## [v0.84.0] (2026-10-30) — P3 三项收口 + 风险表四条落地（全部机器可验）+ 死码 31 个/4.5k 行

**1. P3-2 死代码收敛：141 → 110 个不可达模块（29,933 → 25,441 行）**
删掉 31 个文件、约 4,500 行**真正没人用**的模块（每个都先核过零引用）：
`src/background/`（celery 脚手架 4 个）、`src/core/journal/`、`src/core/secrets/`、
`src/core/auth/` + `src/core/auth_module/`（与 `src/server/auth.py` 重复的旧认证）、
`src/core/middleware.py`、`src/core/health_check.py`、`src/cli/surface_viewer.py`、
`src/utils/version_check.py`、`src/agent/history_compressor.py`、`src/agent/task_analyzer.py`、
`src/agent/swarm/{team_types,synthesized_agent}.py`、`src/workflow/{integration_engine,integration_wrapper}.py`、
`src/workflow/pipeline_stages/`、`src/tools_runtime/code_simplifier.py`。
**可达数 494 → 495（没降）**，IMPORT-FAIL 0，收集 0 errors —— 证明删的都是死码。
顺带把静默吞异常从 162 收紧到 **159**（删码顺带少 3 个），门禁同步（`hard_metrics` 单一真相源）。

**2. P3-1 `src/core/` 边界治理（ADR 0021）**
新增 `scripts/core_surface.py`：核心层**禁止 import** `cli/tools_runtime/agent/server/workflow`；
实测抓到 6 处存量越界（`args_parser`、`config/generator`、`patch/atomic_patcher`×2、`persistence/run_state`、`security/allowlist`），
全部登记进 `scripts/core_surface_allow.json` 并写明迁移方向 —— **只阻断新增**，存量逐步清零；
同时报公开面（`__all__` 89 个符号）与规模（153 文件 / 34,112 行，阈值 200/40,000 告警）。

**3. P3-3 "讲人话"入口补齐**
`clawd explain`（单轮）已在；本轮补 `clawd explain --cross -n 10`：跨会话归因
（成功率 / 成本 / tokens / 最常见失败 / 失败最多的工具），全部确定性统计，不调 LLM。

**4. 风险表第 1 条：假成功专项扫描**
新增 `scripts/scan_fake_success.py`：AST 扫描"打日志/TODO 后直接 return True"的函数，
并排除能力谓词（`available/supports_*/can_*/is_*/has_*/validate`）。当前 **0 命中**，已接入总闸门。

**5. 风险表第 2 条：生成配置"可启动性"自检**
新增 `scripts/check_mcp_startup.py`：对 `DEFAULT_MCP_SERVERS` 逐个**真实 spawn**（用当前解释器），
发 `initialize`/`tools/list`，10s 内必须拿到 `serverInfo` 且工具非空 —— 实测 4/4 PASS。

**6. 风险表第 3 条：两套账本收敛（ADR 0020）**
新增 `src/workflow/run_ledger.py`：`mode_state`（状态真相）与 `ralph_ledger`（进度真相）**语义分家、入口归一**；
读只走 `RunLedger.snapshot()`（含一致性诊断：只写一半 / 孤儿进度 / 时间漂移），写只走 `record_stage()`（一次写两处）。
新增 `clawd ledger [--json]`，不一致时退出 1。**在真实仓库里立刻抓到一条存量不一致**
（有 autopilot 模式状态但没有 ralph 进度）。

**7. 风险表第 4 条：文档数字漂移门禁扩到单一口径**
`check_doc_drift.py` 不再手写阈值，改为 import `hard_metrics.MAX_SILENT_EXCEPT`（单一真相源）。

**验证（实跑）**
`scripts/verify_audit_p1.py` 扩到 **P1×16 + P2×6 + P3×3 + 风险×3 = 28 条 → 28/28 PASS**（失败即非 0，可挂 CI）。
`tests/workflow+cli+core` 1868 passed；`tests/brain+rag` 1074 passed；ruff F821/F811/E9 全过；
可达 495、静默 159、收集 5280 / 0 errors。

---

## [v0.83.0] (2026-10-30) — UI 走查迭代（自己截图逐项修）+ 图片可粘贴上传 + 续聊历史 + CLI Markdown + 签名脚本

按你"自己截图验证、迭代优化"的要求，我用真实浏览器/真实窗口截了 6 张图逐项挑毛病并修掉：

**1. 截图发现并修掉的 UI 缺陷**
- **打开历史会话答案显示两遍**：落盘时 `steps` 里已经有一条 assistant 结果，又追加了 `final_result`。
  两处都修：落盘去重（内容相同就不再追加）+ 加载历史时对连续相同 assistant 去重（老数据也不再重复）。
- **用量柱状图"一根柱子糊满"**：柱宽改为 `min(slot*0.7, 42px)` 居中，并补 Y 轴三条参考线 + 数值刻度。
- **设置里的下拉是系统白色**：select/input 统一深色主题（含 option 背景），不再和暗色界面割裂。
- **「当前生效 Provider」显示错乱**：拆成只读行（显示"provider 列表里的 X"或"未选择 → 走全局配置"），
  全局 provider 输入框明确标注"高级，仅在没有默认 provider 时生效"。

**2. 图片输入（粘贴 / 拖拽）——做了，且不假装视觉**
- 输入框支持 **Ctrl+V 粘贴图片 / 拖拽图片**（最多 4 张，缩略图可单个移除）；
- 发送时图片以 data URL 随 `run` 消息发出，Host 落盘到 `.clawd/uploads/img-<sha>.png`，并把路径写进目标文本；
- **模型不支持视觉时如实说"看不到图片"，不编造内容**（实测：`step-5-preview` 回的就是
  "我的模型不支持视觉输入，无法查看该图片内容"），对话区也不会把 base64 铺出来。

**3. 续聊：点开历史会话后能带着上下文继续**
- 加载会话时记录历史，下一条消息把 `prior_messages` 一起发出（Host 侧透传给引擎 `run/run_stream`）；
- 界面显示"已载入该会话 N 条历史，继续发消息会带上上下文"。

**4. CLI 端也有 Markdown 渲染**
- `clawd chat` 的 plain 模式原来直接打印原文；现在最终答案走 `rich.markdown`（标题/列表/表格/代码块），
  rich 不可用时自动降级纯文本。

**5. 签名：一条命令 + 缺证书时说清缺什么**
- 新增 `scripts/build_desktop_signed.ps1`：`-Pfx/-Password` 走真实证书，`-SelfSigned` 走自签名验证管线；
  **没有证书时退出码 2 并打印"缺什么、为什么产物不会被信任"**，不会假装签过。
- 之前的自签名验证已证明管线可用（`Status=UnknownError` = 签名存在但不在信任链）；要消 SmartScreen 必须 CA 证书。

**6. 根目录再清一次**
- `hermes-agent-tmp/`（390MB 参考克隆）**移出仓库**到 `听风自研智能体/hermes-agent-tmp-moved`（没删，数据还在）。

**7. 装到机器上才暴露的第三个 bug（也是最关键的）：索引把 UI 拖死**
实装 E2E 里用量/provider 面板一直停在"加载中…"，Host 日志显示
`检测到 11606 个文件发生语义变更，触发索引更新`。
根因：打包版 Host 的 cwd 是 `resources/host`，里面有内嵌 Python 运行时；
`WorldModel.initialize()` 用 `root.glob("**/*.py")` 把 `python/Lib/site-packages` 里的
**1.1 万个 .py** 全当项目源码，后台索引把事件循环与 CPU 占满，HTTP 请求排队。
修法：新增 `src/core/source_scan.py`（排除 site-packages / node_modules / venv / dist / .git / .clawd …），
`world_model` 与 `CodeGraph` 兜底扫描都改用它；超过 `CLAWD_WM_MAX_FILES`（默认 5000）时**跳过全量索引并如实告知**，
而不是静默截断。实测同一目录：**11606 → 635** 个源码文件。

**验证（实跑）**
- `desktop/ui_console_e2e.mjs` 从 14 项扩到 **17 项**，全绿：粘贴出现缩略图 / 带图发送完成且附件清空 /
  对话区无 base64 泄漏 / 会话列表可点开 / 用量图表 / provider 掩码…
- 走查截图：`screenshots/20-main-empty.png`…`25-settings-providers.png`（每次改完重新截）
- `tests/core+server+cli` 全绿（含 sessions 去重、prior_messages、附件解析）

---

## [v0.82.0] (2026-10-30) — P2 台账全部闭环（机器可验）+ 文档漂移门禁 + CLI 用量 + 调用方维度

**1. P2-1 ~ P2-6 全部闭环，并变成可执行断言**
`scripts/verify_audit_p1.py` 扩成 **P1-1~P1-16 + P2-1~P2-6 共 22 条**，跑一次给结论（当前 22/22 PASS，失败即非 0）：
- **P2-1** `skills/trace` 文档引用的工具真实存在（`get_recent_traces/get_trace/summarize_trace/export_trace` 都在注册表），
  旧的 `trace_timeline` 调用写法已移除；
- **P2-2** `skills/skill` 等 9 个移植技能已加「clawd 路径适配」块（原文 `~/.codex/...` 属 Codex 时代遗留）；
- **P2-3** `src/autoresearch`、`src/openclaw`、`src/templates` 三个空目录已不存在；
- **P2-4** 新增 `scripts/check_doc_drift.py` 门禁：README 的「用例收集 / 静默吞异常 / 生产可达」三项与现跑比对，
  不一致直接退出 1。本轮据此把 README 从 `5190/482` 更正为实测 **`5260/493`**（静默 162 一致）；
- **P2-5** 评测数据集 `smoke.json` 从 3 条扩到 **7 条**，另有 `honesty.json` **4 条**专演示三态（含 UNKNOWN）；
- **P2-6** `docs/getting-started.md` 已是「安装 → 配置 → 第一个任务 → 看懂它做了什么 → 权限挂机 → 多引擎 → 常见失败」教程，
  原「技能怎么分发给别的 agent」拆到 `docs/skills-distribution.md`。

**2. 用量面板加「应用」维度（对齐你截图里那列）**
- `usage` 表新增 `client` 列（**老库自动 ALTER 迁移**，只加列不动数据），引擎记账时带上调用方：
  桌面端 `desktop`、CLI `cli`；
- 汇总多一组 `by_client`（请求数/tokens/成本），桌面端用量表新增「应用」列，CLI 用量表同样展示。

**3. `clawd usage` —— CLI 也能看用量**
```bash
clawd usage                    # 成本 / 请求数 / tokens / 缓存命中率 + 按模型 + 最近 20 条
clawd usage --range week -n 50  # 近 7 天、最近 50 条
clawd usage --json             # 机器可读（与桌面端面板同一份数据）
```

**3.5 侧栏「工作区」显示历史会话（点开即加载上下文）**
- 新增 `/api/sessions`（列表）与 `/api/session?id=`（内容）；侧栏列出历史会话（标题 + 相对时间 + 状态），
  点开就把那段对话渲染回主区（user/assistant/tool 三类都还原），每轮跑完自动刷新列表。
- 之前侧栏那块一直是空的 —— 用户看不到历史，只能靠 `clawd session` 命令行。

**4. 设置页语义消歧（P2 之外的顺手修）**
「模型 / Base URL」明确标成**全局默认**（只在没选默认 provider 时生效），避免和上面的「API 提供商」列表打架。

**验证（实跑）**
- `scripts/verify_audit_p1.py` → **22/22 PASS**
- `scripts/check_doc_drift.py` → 3/3 一致（exit 0）
- `tests/core/test_local_storage.py` **23 条**（含 client 维度 + `clawd usage` CLI）
- 安装 E2E（0.82.0）：装 → final_verify / 流式角色 / 控制台（滚动·Markdown·图片·用量·provider）→ 卸载 → 清理

---

## [v0.81.0] (2026-10-30) — 滚动修复 + 完整 Markdown/图片 + 用量统计页 + 多 provider + 根目录卫生

**1. 修「消息一多就滚不动」**
根因是 flex 布局链上缺 `min-height:0`（`.main`），高度被内容顶开、`.view` 的 `overflow-y:auto` 失效。
已补 `.main{min-height:0}` + `.frame{overflow:hidden}`；同时把自动滚动改成**粘底**逻辑：
只有你本来就在底部附近才跟随，往上翻时不再被强行拉回，并出现「↓ 回到最新」按钮。

**2. Markdown / 图片真正渲染（之前只有最小版）**
新渲染器支持：标题、无序/有序列表、引用、分隔线、**表格**、链接、**图片**、
围栏代码块（带语言标签 + 复制按钮）、行内代码、粗体/斜体。
图片两种来源：`http(s)://` 直连；工作区内相对路径走新端点 `/api/file?path=…`
（**只放行图片后缀 + 路径必须在工作目录内**，实测 `../etc/passwd` 与 `src/agent/engine.py` 均 403）。
全部用 `textContent`/`createElement` 拼 DOM，**不走 innerHTML**。

**3. 用量统计页（对齐你截图里那种面板）**
- 新增本地 SQLite：`<工作区>/.clawd/clawd.db`（表 `usage`），**引擎每跑完一轮就记一行**：
  provider / model / 新增输入 token / 输出 token / 缓存读 token / 成本 / 步数 / 状态 / 时间。
- 侧栏新增「用量统计」：4 个 KPI（总成本 / 请求数 / 真实消耗 tokens / **缓存命中率**）+ 按小时柱状图 + 请求日志表。
- HTTP 端点 `/api/usage`（汇总 + 最近 50 条），WS 也有 `usage_summary` / `usage_recent`。
- 缓存命中率口径：`缓存读 / (缓存读 + 新增输入)`，与截图里的面板一致。

**4. 多 API 提供商（设置页闭环）**
- 同一份 SQLite 里存 `providers` 表：id / 名称 / 类型 / base_url / 模型 / `key_env` / `key_inline` / 是否默认。
- 设置页可**新增、编辑、删除、设为默认**；首次保存自动成为默认；删掉默认项会自动把最近的一条顶上。
- **密钥两种放法**：环境变量名（推荐）或明文（仅本机）；对外接口**只返回掩码**（`sk-ab…1234`），
  实测前端拿不到明文；编辑时不填密钥 = 保留原值（不会误清空）。

**5. 根目录卫生**
`analyze_*.py` / `inject_errors.py` / `cleanup.bat` / `FINAL_FIX_SUMMARY.txt` / `todos.txt` 等一次性产物
挪进 `scripts/oneoff/`（附 README 说明来历），散落的 `*.log` 归到 `logs/`，历史对标报告进 `docs/reports/`；
`.gitignore` 补 `x/`、`test-run/`、`hermes-agent-tmp/`、`latest/`、`logs/`。决策记入 `.agent/memory/decisions.md` D-27。

**6. 装到机器上才暴露的两处问题（本轮实装 E2E 抓的）**
- **模型又换了一种工具调用写法**：这次是 `<tool_call><file_read>{"file_path": "x"}</file_read></tool_call>`
  —— 前两种（`<tool>{json}</tool>`、`<tool>{json}>` 多符号）已兼容，这种 XML 风格漏了，导致工具不执行、
  原文被当答案。现在宽松解析同时支持：`<tool>{json}`、`<tag>{json}</tag>`（排除 tool_call/args 等包装标签），
  并把模型常写的工具名（`file_read`/`read_file`/`shell`/`grep`/`glob`…）映射到真实类名
  （`FileReadTool`/`BashTool`/`GrepTool`/`GlobTool`）。
- **流式 E2E 的判据不稳**：原来用 DOM 采样判断"文本是否在增长"，而预览模型常在末尾一次性吐字，
  采样会漏 → 误报失败。改为在渲染器里计**收到的 delta 事件数**（`window.__streamDeltas`），
  ≥2 才算真流式；DOM 只断言最终态。

**7. 让"多 provider"真的生效（否则只是好看的表格）**
- `_handle_run` 在未显式传 `llm_config` 时，会读取设置里的**默认 provider** 并构造 `LLMConfig`
  （provider/api_key/base_url/model）交给引擎；没配密钥时明确告警并回退全局配置。
- `/api/info` 增加 `active_provider` 摘要（不含密钥），设置页与用量页显示"生效: xxx"。
- 用量页支持**时间范围切换**（当天 / 近 7 天 / 近 30 天），`/api/usage?range=`。

**验证（实跑）**
- 新增 `desktop/ui_console_e2e.mjs`（真实浏览器 12 项断言）：
  长历史可滚动 / 上翻出「回到最新」/ 点击回底 / Markdown 标题列表引用 / 表格 / 代码块无 ``` 原文 /
  行内代码与链接 / **图片经 /api/file 真出图（naturalWidth=1360）** / 用量页 4 KPI + 日志行 / provider 保存 + 仅显示 env 名
  → **12/12 PASS**
- 新增 `tests/core/test_local_storage.py`（14 条）：provider CRUD / 默认互斥 / 删默认补位 / 密钥掩码 /
  env 优先 / 空 key 不清空 / 用量汇总口径 / 日志倒序 / 空库零值 / 记账失败不抛
- `scripts/verify_audit_p1.py` 仍 16/16 PASS；门禁 F821/F811/E9 全过

---

## [v0.80.0] (2026-10-30) — 去掉原生菜单栏 + 状态/记忆/追踪/团队内建为原生工具 + 修 Windows 编码系统性 bug

**1. 去掉 Electron 原生菜单栏（File / Edit / View / Window / Help）**
截图里那排 2003 年风格的菜单直接从 `Menu.setApplicationMenu(null)` 干掉（聊天式应用不需要它）。
必要的快捷键在窗口内用 `before-input-event` 本地补齐：Ctrl+R/F5 刷新、Ctrl+Shift+I/F12 开发者工具、
Ctrl+Q/W 关闭、Ctrl+=/-/0 缩放 —— **不注册系统全局热键**，不干扰其它软件。
验证方式：启动 unpacked 版后用 `CopyFromScreen` 截真实窗口图（见 workflow_status v0.80.0 段）。

**2. 状态 / 记忆 / 追踪 / 团队：从"MCP 专属"变成"原生内置"**
之前这四项能力只有 `src/core/mcp/*_server.py` 的 MCP 形态可用，agent 想用得先起 MCP 进程。
新增 `src/tools_runtime/builtin_capability_tools.py`：
- `MemoryTool`（search/create/observe/stats）、`StateTool`（surface/session 读写 + list_sessions）、
  `TraceTool`（recent/get/summarize/export）、`TeamTool`（create_task/list_tasks/assign/send/mailbox/workers）
- **实现同源**：直接调 `core/mcp` 的 Server 类（同进程、零端口、零 token 握手），
  所以内置工具与 MCP 工具共用一份存储逻辑，不会漂移；
- `get_domain_tools()` 现在装配 6 个工具（世界模型 + 项目图谱 + 这 4 个），引擎启动即可用。

> 结论：MCP 只留给**外部引擎跨进程**用（Codex/OpenCode 跑在别的进程），
> 自家 agent 一律走原生工具 —— 这正是 ADR 0011「内置优先」的落地，也是这次你问的"能不能直接内置"的答案。

**3. 修一个只在 Windows 上炸的系统性编码 bug**
`core/mcp` 与 `mcp` 两个目录里共 **38 处** `Path.write_text()/read_text()` 没写 `encoding`，
Windows 默认走 GBK：写中文进去、再按 UTF-8 读就 `UnicodeDecodeError`。
实测触发：`MemoryServer.create_entity(name="登录模块")` 后 `search("登录")` 直接崩；
`TeamServer` 写中文任务后 mailbox 打不开。已全部补 `encoding="utf-8"`（写 18 处 + 读 20 处）。

**4. 审计 P1 台账可复验**
新增 `scripts/verify_audit_p1.py`：把 P1-1 ~ P1-16 逐条变成机器可跑的断言（查代码 + 查测试 + 查数据集），
当前 **16/16 PASS**，任何一条回退都会退出非 0，适合挂 CI。

**验证（实跑）**
- `tests/tools_runtime` **299 passed / 4 skipped**；新增 `tests/tools_runtime/test_builtin_capability_tools.py`（16 条）
- `scripts/verify_audit_p1.py` → 16/16 PASS
- 安装包实装 E2E（见下一条 commit 的截图与报告）：窗口无菜单栏、UI 流式/角色库/无顶栏全通

---

## [v0.79.0] (2026-10-30) — 真流式回复 + 角色库 + 极简对话界面（对标 orca 的做法）

你反馈的两件事都在这一版：**"发消息后只刷工具调用、没有正常回复"** 与 **"顶栏老旧、不能选角色"**。

**1. 真流式回复（修的是真 bug，不是观感）**
- 根因：WS 的 `_handle_run` 在 stream 分支把 chunk 收进一个**本地 list 就扔掉了**，
  客户端全程只能收到工具事件；模型说的话要等整段跑完才出现 → 观感就是"只在汇报工具调用"。
- 现在：新增事件 `agent.stream_delta`，`_on_chunk` 边收边发（≥40 字符或 ≥120ms 合并一次，
  避免 token 级事件打爆 WS），`stream_started` / `stream_completed` 成对包住。
- 前端：助手气泡先出现、逐字填充（带光标），结束时用最终文本收尾并挂"复制"。

**2. 角色库（personas）——你不用再自己写提示词**
- `personas/<name>.md`：frontmatter 放 `name/title/description/category`，**正文就是系统提示词**。
- 三级搜索：`<项目>/personas` → `<当前目录>/personas` → `~/.clawd/personas`，同名后者覆盖前者。
- 内置 6 个：严谨工程师 / 极简输出 / 教学讲解 / 严格审查者 / 中文写作 / 排障专家。
- CLI：`clawd role list`、`clawd role show <name>`（**把完整系统提示词打印出来**，可审计）、
  `clawd chat --role <name>`。
- 桌面端：输入框左侧下拉切换角色，`run` 消息带 `persona`，Host 侧 `engine.apply_persona()` 注入系统提示词；
  会话落盘记录用了哪个角色（`metadata.persona`）。
- 说明：内置库只放工程/写作类角色。**越狱/绕过安全审查类的提示词内容我不内置**；
  机制是通用的，你自己的 `personas/*.md` 会按同样规则被加载（有测试守着内置库不含这类内容）。

**3. 对话界面重做（学 orca 的"transcript 优先"，只学思路）**
参考 `D:\参考项目\orca`（Electron+React 的 agentic IDE）的做法后改的：
- **去掉顶栏**：原来那条"标题 + 标准模式 + 对话/轨迹 tab"的一整行没了，
  换成一行轻量会话栏（标题 + 轨迹开关 + 连接状态），正文占满高度。
- **正文是主体、工具是脚注**：工具调用仍是 `▸ 工具名 预览` 的折叠单行，但降级为次级信息（80% 透明度），
  不再和助手回复抢注意力；点开才看完整参数/输出。
- **输入框常驻底部**，角色选择器与模型标记放在同一行（对应 orca 的 SessionOptionPickers 思路）。

7. **助手正文里的 ``` 代码块被原样显示**（截图里 nginx 配置就是一坨围栏符号）。
   加了最小 Markdown 渲染：``` 围栏 → `<pre class="code-block">`、`行内代码` → 代码 chip、
   `**粗体**` → strong，换行保留。**全部用 textContent 拼 DOM，不走 innerHTML**
   （模型输出不可信，避免把内容当 HTML 执行）。实测：1 个代码块 + 3 个行内 chip，正文里不再出现 ```。

**验证**
- 新增 `tests/agent/test_personas.py`（12 条：覆盖优先级、非法名、空正文、超长截断、内置库不含违规内容）
- 新增 `tests/server/test_streaming_and_persona.py`（7 条：增量事件、合并发送、非流式不发增量、
  persona 注入、未知角色报错、角色清单）
- 新增 `desktop/ui_stream_persona_e2e.mjs`：真实浏览器验证"流式文本确实在增长"+"角色下拉可用"+"顶栏已移除"
- 新增 `scripts/e2e_host_stream.py`：绕过 Electron 直接打 WS —— 实测
  `personas=6` + `delta #1 +5字 / #2 +30字 / #3 +41字` + `status=completed 文本 86 字`

**安装 E2E 又抓到 2 个真 bug（都在打包态才暴露）**
1. **流式一开就崩**：真实 provider（openai 兼容 + 推理模型）`chat_stream` 会 yield
   `("thinking", text)` 元组，而 `full_content += chunk` 直接 `TypeError:
   can only concatenate str (not "tuple") to str` —— 这条路径只在真流式下走到，所以"流式"从未真正跑通。
   现在 `thinking` 单独累积（不进用户可见正文），正文只拼字符串，并加测试钉住。
2. **角色下拉永远是空的**：`dispatch` 统一用 `handler(ws, message, engine_factory)` 三参调用，
   而新写的 `_handle_personas(self, ws, message)` 少一个参数 → TypeError 被吞成 `E_INTERNAL_ERROR`。
   已补参数，并加了"**必须走 dispatch**"的测试（直接调 handler 的测试发现不了这个）。
3. 打包链版本错配：先打 bundle 再升版本会让安装包内 host 停在旧版本号。流程固定为
   「先升版本 → prepare_host_bundle → electron-builder」，安装 E2E 会核对
   `resources/host/pyproject.toml` 与主程序版本一致。
4. **乱序导致"永远在输出中"的幽灵气泡**：实测 WS 上 `response(completed)` 会先于最后一条
   `stream_delta` 到达（事件总线投递是排队的）。前端原来在 response 时就 endStream，
   随后迟到的 delta 又新建一个气泡 —— 界面上一直挂着"正在输出"。
   修法：response 只记 `pendingFinal`，收尾交给 `AGENT_STREAM_COMPLETED`（1.2s 兜底），
   收尾后 3s 内的迟到 delta 直接丢弃。
5. 顺带把合并阈值从 40 字/120ms 降到 12 字/60ms，并在 flush 后 `await asyncio.sleep(0.08)`
   让事件先于 response 落地 —— 实测改造后 4 条 delta 全部先到，最后才来 response。

6. **模型把工具调用写成"半截标记"，工具没执行、原始标记还被当答案**
   实装 E2E 里模型输出 ` <tool>{"name": "FileReadTool", "args": {...}}}>`（多一个 `>`、漏 `</tool>`），
   严格正则 `<tool>\{.*?\}</tool>` 匹配不到 → 工具不执行，界面把 `<tool>…` 原文当最终回答。
   现在加括号配平扫描 + 宽松兜底（容忍多符号、漏闭合、`arguments` 别名），命中时打 warning；
   括号在字符串内也不会误判。新增 7 条测试覆盖这些变体。




---

## [v0.76.8] (2026-10-30) — 桌面端实装 E2E 跑通：修「工具成功却显示失败」，签名链路已验证

本轮按你拍板做了两件事：**完整跑一次 NSIS 实装（跑完自己清理）**、**自签名验证签名链路**。
安装 E2E 立刻抓到一个只在真实桌面上才看得见的缺陷。

**1. 桌面端完整实装 E2E（装 → 用 → 卸 → 清理）**
- `Clawd Desktop Setup 0.76.7.exe /S` 静默安装 → exit 0，装到 `%LOCALAPPDATA%\Programs\Clawd Desktop`
- 安装态核对：主程序 `FileVersion=0.76.7`、内嵌 `resources/host/pyproject.toml` = 0.76.7、
  `resources/host/prompts/agents` **33 个 .md**
- 启动 → Host 起来（`.clawd_host_port` port=8765/token 32 位）→ `GET /` **200**；
  Playwright 连**已安装版 Host** 完成真实对话 + 工具调用：回 `INSTALLED_APP_E2E_9527`，
  `PASS ✔ 安装版真实对话+工具调用全链路`，截图 `desktop/screenshots/07-installed-final.png`
- 关进程（0 残留）→ 静默卸载 exit 0 → 清 AppData/快捷方式/注册表（卸载注册表残留 **0**）
- **`GET /health` 返回 403**（需要 token）——这是鉴权行为，不是故障；已记入文档

**2. 修复：工具明明成功，界面却显示「(失败)」**
截图里 `FileReadTool` 那行写着「工具完成: FileReadTool (失败)」，但会话落盘 `ok: true`、
模型也正确用到了文件内容 —— 界面在说假话。
根因：`engine_loop` 里 `result` 可能是被包一层的 `(name, args, ToolResult)`，
而 `publish_tool_completed(tool_name, tool_args, result)` 直接把元组发出去；
`EventPublisher` 用 `hasattr(result, 'success')` 判断 → 元组没有该属性 → 一律上报 `False`。
修法：先解包成 `ToolResult` 再发事件。验证：同一探针再跑，界面事件变为
`"success": true`（GlobTool + FileReadTool 两条都对），不再出现「(失败)」。

**3. 自签名签名链路（按你选择"先做自签名验证流程"）**
- `New-SelfSignedCertificate` → 导出 pfx 到 `%TEMP%`（口令进程内生成，不打印、不进仓库）
- `CSC_LINK` + `electron-builder` 实际签了 5 个产物：`Clawd Desktop.exe`、`elevate.exe`、
  卸载器、Setup、Portable —— 构建日志从 `signing is skipped` 变为 `signing ... certificateFile=...`
- `Get-AuthenticodeSignature` → `Status=UnknownError, Signer=CN=Clawd Code Dev (self-signed)`：
  **签名确实存在，但自签名不在信任链里**，SmartScreen 仍会警告。
  也就是说：签名管线通了，**信任问题依然要靠 CA 证书解决**（P2-4 未闭环）
- 跑完已清理：临时证书与私钥从证书存储删除、`%TEMP%\clawd-signing` 删除

**4. 0.76.8 安装包重跑实装 E2E（确认修复随产物出去）**
装 `Clawd Desktop Setup 0.76.8.exe` → 主程序/内嵌 host 均 0.76.8、prompts 33 个、
`GET /` 200、Playwright 连已装 Host 真实对话 PASS、卸载 exit 0、注册表残留 0、AppData/快捷方式已清。
截图 `desktop/screenshots/07-installed-final.png` 里 `FileReadTool` 那行已变成
**「✓ 工具完成: FileReadTool」**（不再有「(失败)」），左下角版本 `v0.76.8`。
本次发布产物**未签名**（`Status=NotSigned`）——自签名只用于验证管线，验证完已把证书与私钥删除。

**验证（实跑）**
- 安装 E2E ×2：0.76.7（带自签名）与 0.76.8（发布态）各一次，全部装→用→卸→清理跑通
- 新增 `tests/agent/test_tool_event_payload.py`（3 条）：成功工具必须上报 `success=True`、
  失败工具 `success=False`，并钉住"元组形态必然被误判"这个根因
- 门禁与回归见 `workflow_status.md` 的 v0.76.8 段

---

## [v0.76.7] (2026-10-29) — 真实端点跑通后，修 3 个只有真跑才暴露的缺陷

本轮第一次把"真实 LLM 端点"跑到底（此前一直因付费红线跳过），结果**立刻抓到 3 个
单测完全覆盖不到的缺陷**——它们都在"用户真的用一次"的路径上。

**真实 E2E（`scripts/e2e_smoke.py`）**
`0. 读取 .env 配置` / `1. 应用模块可导入` / `2. 项目 LLM 栈真实对话`（PONG）/
`3. 工具调用 function calling`（get_weather Berlin）/ `4. 推理内容解析`（391 + reasoning）
→ **5/5 PASS，退出码 0**。

**修复 1：工具失败原因没进会话步骤，收尾消息只剩一句空话**
真实复现：PRE_TOOL_USE hook 拒绝 `BashTool` 后，模型反复重试 3 次，最终答案只有
「达到最大迭代次数，任务可能未完成。」—— 用户根本看不到"被策略拒绝"这个真原因。
原因：`AgentStep(result=_res_obj.output)` 在失败时 output 是空串，error 被丢掉。
已改为失败时把 `error` 写进 step.result，并让收尾消息带上
`最后一次失败: <工具> -> <原因>`（实测输出已带上完整拒绝理由）。

**修复 2：拒绝后没告诉模型"别重试"，白烧迭代**
拒绝结果只写了"被拒绝"，模型就用相同参数再试。现在显式追加
「该工具已被策略拒绝，不要用相同参数重试；请换方案或直接说明被拒绝的原因」。

**修复 3：会话落盘压平结构 + 用量全丢，`clawd explain` 只能显示"未知/0/0"**
真实会话文件里：工具步骤被写成 `role=assistant` 的文本、`model`/`provider` 为空、
`output_tokens=0`、`total_cost=0`。于是 `clawd explain` 显示
`模型: 未知 · 输出 0 tokens · $0.0000 · 工具调用: 没有记录`。
现在：execute 步骤以 `role=tool` + `name` + `ok` 结构化落盘；`model`/`provider` 取引擎配置；
输入/输出 token 与费用取 `CostEstimator.get_summary()`（估算器异常时降级为 session 总量，不阻断落盘）。
实测同一句话的 explain 输出变成：
`openai/step-5-preview · 输入 16323 / 输出 262 tokens · $0.0171 · 工具调用 1 次（成功 1 / 失败 0）: FileReadTool`。

**验证（实跑）**
- `scripts/e2e_smoke.py` → 5/5 PASS，exit 0
- 真实引擎跑 3 次（读文件 / 被 hook 拒绝 / 落盘后 explain），全部符合预期：
  - PRE/POST hook 在真实 `FileReadTool` 调用上各触发 1 次
  - 拒绝 BashTool 后 `hello-from-shell` **未出现**（真的没执行）
  - `clawd explain` 能列出工具、成败、模型、token、费用
- 新增 7 个测试：`tests/core/test_session_persist_structure.py`（落盘结构 + 用量来源 + 估算器失败降级）
  与 `tests/agent/test_engine_hooks_wiring.py` 增补 3 条（失败原因入步骤 / 别再重试提示）

**修复 4：评审裁决解析太窄，真实模型的中文/别名裁决被判 UNKNOWN**
真实跑 `clawd review`（4 角色并行、真实端点）时发现：`style-reviewer` 写的是中文结论，
被解析成 `UNKNOWN` → 整体 `INCOMPLETE`。现在接受
`VERDICT/结论/判定` + `APPROVE/PASS/OK/LGTM/通过/无问题/无需修改/NEEDS_FIX/REJECT/需要修复/有问题`；
**没写裁决行时按它自己报的分级兜底**（有 CRITICAL/HIGH/MEDIUM → NEEDS_FIX；只报 LOW 或啥都没报 → UNKNOWN），
依然不猜"通过"。修后同一文件同一角色：`APPROVE`。

**真实并行评审实测**（`clawd review /tmp/review_target/demo.py`，真实端点）
4 个角色并行，命中真实缺陷：`CRITICAL: SQL 注入（字符串拼接构造 SQL）`、
`HIGH: 数据库连接未关闭`；聚合裁决 `NEEDS_FIX`；`performance-reviewer` 120s 超时被如实标为
`FAILED/超时`（没有伪装成通过）。说明"并行调度 + 确定性裁决 + 不伪造通过"三件事在真实模型下成立。

**修复 5：桌面打包不含 `prompts/`，打包态 `clawd review` 直接 ModuleNotFoundError**
用打包好的 host 运行时实测：`python/python.exe -m src --version` 正常（v0.76.6），
但 `from src.agent.review_team import available_review_roles` 报
`ModuleNotFoundError: No module named 'prompts'` —— `scripts/prepare_host_bundle.py`
只拷了 `src/`。已补拷 `prompts/`（并在脚本里显式告警"缺 prompts 则 review 不可用"），
顺带给清理步骤加了 `rmtree_with_retry`：Windows 上杀软/索引器会短暂占用
site-packages 文件（WinError 32），不重试整条打包链直接失败（本轮实测踩到两次）。

**修复 6：`clawd_code.egg-info` 残留导致版本一致性假失败**
`pip wheel .` 在仓库根留下 `clawd_code.egg-info/PKG-INFO`（版本 0.76.6），而 cwd 在 sys.path 上，
`importlib.metadata.version("clawd-code")` 会优先命中它 → 明明装的是 0.76.7 却报 0.76.6。
已清理该制品（`.gitignore` 本就忽略 `*.egg-info/`），并在 known-issues 记录这个坑。

**桌面端 0.76.7（含 prompts 修复）实测证据**
- `desktop/dist/latest.yml` → `version: 0.76.7`，产物 `Clawd Desktop Setup 0.76.7.exe`(160.3M) /
  `ClawdDesktop-Portable-0.76.7.exe`(160.0M)；旧 0.76.6 产物已删
- 打包内 `resources/host/pyproject.toml` → `version = "0.76.7"`；`resources/host/prompts/agents/` **33 个 .md**
- 用**打包自带的 python** 实跑：`python/python.exe -m src --version` → `Clawd Code v0.76.7`；
  `available_review_roles()` → **9 个角色**（修复前是 `ModuleNotFoundError: prompts`）
- 仍未签名（无证书，`signing is skipped`）

**说明**：本轮确实发起了真实 LLM 调用（e2e 冒烟 5 步 + 引擎验证 3 次 run + 评审 2 次共 5 次调用）。
按你"不必担心预算"的授权执行，次数与开销在此列明。

---

## [v0.76.6] (2026-10-29) — P1-14 收口（真并行评审）+ 讲人话入口 + 桌面端 0.76.5 重建

v0.76.5 把"假成功"清完之后，本轮补的是**功能面缺口**，同样每条都有实跑证据。

**1. 多角色并行评审（P1-14 收口）**
`src/agent/review_team.py` + `clawd review`：仓库原有 34 个 prompt 模板 / 6 个 REVIEW 角色定义，
但生产侧只有 `get_prompt()` 一个调用方，实际评审是单点 `AuditorAgent` 扫全文件 —— "review 面有名无实"。
现在 `ReviewTeam` 用 `asyncio.gather` **真并行**跑 4 个角色（code/security/performance/style），
裁决由确定性正则解析（`VERDICT: APPROVE|NEEDS_FIX` + `CRITICAL/HIGH/MEDIUM/LOW`）：

- 任一角色报错/超时/不给裁决 → 整体 `INCOMPLETE`（**不会**把"没评审"算成"没问题"）
- 只报 CRITICAL 却漏写 VERDICT → 仍判 `NEEDS_FIX`
- 退出码：0=APPROVE · 1=NEEDS_FIX · 2=INCOMPLETE
- `--json` 给 CI 用；`provider_factory` 可注入，18 个测试全程假 provider（**零付费调用**）

**2. `clawd explain`（讲人话入口）**
P3 缺口：CLI 没有 explain/why，用户只能自己翻 JSONL。新增零成本解释器：目标/模型/轮次/用量、
每次工具调用及成败、失败原始片段、最终回答。**没有记录就写"没有记录"**（缺结果 ≠ 成功）。
13 个测试覆盖原生 function calling 与 legacy 存储两种格式。

**3. 桌面端安装包随版本重建（P2-3/P2-4 版本一致性）**
`prepare_host_bundle.py` 刷新 host（275MB）→ `electron-builder --win nsis portable` 产出
`Clawd Desktop Setup <ver>.exe` / `ClawdDesktop-Portable-<ver>.exe`，`latest.yml` 的
`version` 与 `sha512` 与产物一致，`dist/win-unpacked/resources/host/pyproject.toml` 版本同步。
**仍未签名**（无证书，构建日志 `signing is skipped`，P2-4 属外部条件）。

**4. 技能文档与路径适配**
9 个从 oh-my-codex 移植的技能（doctor/skill/hud/worker/autopilot/...）文中 `~/.codex/...`
在 clawd 下**不存在**；统一加了"clawd 路径适配"说明块（真实路径是 `<项目>/skills/` 与 `.clawd/`），
不改其原有步骤。

**5. 评测覆盖（P2-5）**
`smoke.json` 3 → 7 条（补 equals 精确匹配、错误必须被暴露、中文不得夹英文套话、不得谎报创建）；
新增 `honesty.json` 专门演示三态：1 pass / 1 fail / 2 UNKNOWN，用来检查"没测"没被伪装成数字。

**6. 文档**
`docs/getting-started.md` 重写为**产品上手教程**（安装→配置→第一个任务→看懂发生了什么→权限挂机→多引擎→常见失败定位）；
原"技能怎么分发给别的 agent"移到 `docs/skills-distribution.md`。新增 ADR 0019：
`src/hooks/`（2,541 行、10 模块、全部不可达）保留为参考快照**不接线**，逐模块列出与仓库现实现的重复关系。

**验证（实跑）**
- `py -3.10 -m pytest tests/agent tests/cli tests/eval tests/mcp tests/backends -q -m "not slow"` →
  **1403 passed / 0 failed**（931.80s）
- 新增用例：review_team 18 + review CLI 6 + explain 15 + eval honesty 4 = 43
- 门禁：`F821/F811/E9` 全过 · 静默吞异常 **162**（≤162）· 生产可达 **482**（≥443）· 收集 **5166 / 0 errors**
- 打包验证（非 editable 安装的真实缺口）：`pip wheel .` 产出的 wheel 里
  `prompts/agents/*.md` **34 个**齐全（pyproject 原来只 `include = ["src*"]`，
  `clawd review` 在安装态会报「找不到角色模板」）
- 桌面构建退出码 0，`latest.yml` 的 version/sha512 与产物一致（签名仍被跳过：无证书）

**仍未闭环**
- 代码签名证书（需 `CSC_LINK` + 密码；当前 `signing is skipped`）
- `src/hooks/` 的 omx 语义若要采用，需改写成本项目自己的契约（见 ADR 0019）
- `scripts/e2e_smoke.py` 未跑：真实 LLM 端点属付费红线

---

## [v0.76.5] (2026-10-29) — 审计 P0/P1 清零：P0 ralplan 默认路径崩溃 + 9 项假成功/坏承诺

按 `参考的结果计划指南.md` 的 P0/P1 台账逐条修，**每条都有实跑证据**。本轮不动架构，只修"说得到做不到"。

**P0（阻塞）**
1. **`clawd workflow ralplan` 用默认参数必崩**：`CriticAgent.__init__` 用 `AgentRole.CRITIC`，
   而枚举里没有该成员 → `AttributeError: CRITIC`；`enable_critic_challenge` 默认为 True。
   已补 `CRITIC` 成员 + 角色描述 + 系统提示，并加"所有 `AgentRole.X` 引用必须真实存在"的静态测试。

**P1（假成功 / 坏承诺 / 造了没接）**
2. **worktree 合并假成功**：`strategy="integrator"` 只打日志就 `return True`（"keep" 同样）。
   现在真的把改动落到目标工作区（文件级，全有或全无）；冲突不覆盖目标并返回 False；
   无改动返回 False。8 个测试用真实临时 git 仓库验证。
3. **四个 MCP server 起不来**：生成的配置指向 `src.core.mcp.{state,memory,trace,team}_server`，
   但这些模块没有 `__main__` → `python -m` 静默 exit 0、零输出。新增通用
   `src/core/mcp/stdio_server.py`（initialize/tools/list/tools/call/ping，UTF-8 逐行 flush），
   四个模块各补 `main()`；生成配置的 `command` 从裸 `"python"` 改为 `sys.executable`。
   真实 spawn 验证：四台全部握手成功，`set_surface`/`get_surface`/`create_entity`/`search_memory` 完成往返。
4. **工具名拼写错误** `sumsummarize_trace` → `summarize_trace`（客户端调用必失败）。
5. **`clawd_project_map` 100% 失效**：`RepoMap(root=...)` + `get_map()` 两处签名不匹配 →
   永远走降级分支只吐文件清单。改用真实签名后返回 8.8k 字符符号图谱。
6. **悬空依赖静默忽略**：任务依赖指向不存在的 id 时只 `logger.warning` 就继续拓扑排序。
   现在抛 `ValueError` 并列出两侧。
7. **质量门只看第一项**：`QualityGate.overall` 返回 `results[0].result`，
   第 2 项之后失败也放行。改为走 `_calculate_overall` 聚合。
8. **技能不可发现 + 静默截断**：`discover_skills` 只做一层 `glob('*/SKILL.md')` →
   `skills/reverse/*` 的 51 个子技能一个都扫不到（实测 63 → 递归后 113）；`MAX_SKILL_BODY_CHARS=20000`
   而 4 个技能正文 20,550~23,159 字符 → 尾部指令被静默砍掉。改为 `rglob` + 上限 26,000 + 截断告警。
9. **富 HUD 空壳 + 最终答案不打印**：`RichLiveHud` 全部方法 `pass`、`render_full_layout()` 返回常量 `""`；
   `_run_task_rich` 从不输出结果。现在实现真实 rich 渲染（迭代/步骤/流式尾巴实时刷新），
   `Live(screen=True)` 退出后单独打印最终答案。
10. **评测假成功 + 无法表达"没测"**：`--baseline 不存在的路径` 曾打印"基线比对通过"并 EXIT=0；
    缺 `recorded`/非法 regex/缺工具记录一律判 FAIL。现在：基线缺失 → EXIT=2 明确报错（`--save` 时允许首次建立）；
    评测改为三态（pass/fail/**unknown**），通过率只在已判定用例里算；未判定增加视为回归；
    `smoke.json` 的工具名对齐运行期真实类名 `FileReadTool`/`FileEditTool`。
11. **hooks 造了没接**：`src/hooks/` + `hook_registry` 2.5k 行在引擎里零调用点。
    引擎现在在 `SESSION_START`/`SESSION_END`/`PRE_TOOL_USE`（可 DENY，拒绝则不执行工具）/
    `POST_TOOL_USE`/`TOOL_ERROR` 五点接线；未注册 hook 时零额外开销。
12. **上手引导零调用点**：新增 `clawd onboard [--json]`，`chat` 启动时做一次体检
    （只在真的没有任何密钥时提示）；`start_oauth_flow` 不再假装"正在打开浏览器"。
13. **辩论模式输出占位符**：缺 orchestrator 时曾返回 `"[模拟 CRITIC 响应] ..."` 当辩论总结。
    现在抛 `DebateUnavailable`，调用方按失败处理。
14. **重复实现漂移**：`src/core/mcp/` 定为唯一真相源，`src/mcp/{memory,state,trace}_server.py`
    冻结为 legacy（文件头标注 + `docs/adr/0018` 记录判断依据）。

**验证（实跑）**
- `pytest tests/backends tests/core tests/mcp tests/eval tests/cli -q -m "not slow"` → **1500 passed**
- `pytest tests/agent tests/workflow -q -m "not slow"` → **1208 passed**（1 项并发锁 flaky，单跑通过）
- 四个 MCP server 真实 spawn 握手 + tools/call 往返全通过
- 门禁：`F821/F811/E9` 全过、静默吞异常 162（≤162）、生产可达 480（≥443）、收集 5021 / 0 errors

**仍未闭环（需外部条件，不伪造）**
- 代码签名证书（P2-4，需 `CSC_LINK`）；桌面安装包未重跑（版本号仍 0.76.4）
- P1-14 剩余部分：34 个 review prompt 模板仍无并行调度器（本轮只修了"假响应"）
- 价格数据、桌面实装验证等需网络/用户确认的项保持原状

---

## [v0.76.4] (2026-10-29) — 桌面安装包重建：P2-3 已修，自动更新元数据恢复真实

**修复前**：`desktop/host` 内嵌的是 **v0.60.10** 的源码（落后 16 个版本），
成品名 `0.1.0`、`latest.yml` 也指向 0.1.0 —— 自动更新"检查到新版本"却下载到老包，事实失效（P2-3）。

**已修**：
1. 重跑 `scripts/prepare_host_bundle.py` → host 从 **v0.60.10 → v0.76.3**（235MB，含 collaborate/native 等新模块）
2. 重跑 `electron-builder --win nsis portable` →
   - `Clawd Desktop Setup 0.76.3.exe`（168MB）
   - `ClawdDesktop-Portable-0.76.3.exe`（146MB）
3. `latest.yml` 现为 `version: 0.76.3` + 对应 sha512 → 更新元数据与产物一致
4. 清理旧的 0.1.0 产物（避免"latest.yml 指向老包"的混淆）

**验证（静态确认）**：`desktop/dist/win-unpacked/resources/host/pyproject.toml` → `version = "0.76.3"`；
`latest.yml` 的 url/sha512 与新建安装包一致。

**仍未闭环**：`no signing info identified, signing is skipped` —— **无代码签名证书**（P2-4），
安装时仍会 SmartScreen"未知发布者"；需要证书文件 + `CSC_LINK`/`CSC_KEY_PASSWORD`（外部条件）。
本轮**未实跑安装流程**（安装会修改用户系统，需你确认后再做）。

---

## [v0.76.2/v0.76.3] (2026-10-29) — 指令文件保鲜 + skill 陷阱整改 + 测试提速

### 指令文件过期修复（最关键）
项目 `CLAUDE.md` 仍写着 `fail_under=47` / 静默≤172 / 3261 用例 / 覆盖率 47.44%，
而实际早已是 62% / 162 / 5007。**指令文件写错会让后续会话按错基线办事**，已按 baseline 实测刷新。

### 按 skills/clawd-change-workflow 陷阱清单自查（2 条命中）
- **缺 `__init__.py` + 重名测试文件**：补齐 `tests/mcp`、`plugins`、`reasoning`、`reverse_tools`、`security`
  五个目录的 `__init__.py` —— 本项目有 8 组重名测试文件（`test_engine.py` 等），这是 `import file mismatch` 的经典成因
- **同步调用 async**：`NativeBackend.run` 增加事件循环守卫（已在 loop 中时改用线程跑），
  避免 `asyncio.run()` 在运行中的 loop 里抛 RuntimeError（实测 async 上下文调用正确返回）

### P2-10 测试耗时：根因定位在**我自己的测试**上
`--durations=25` 实测最慢 5 个里 3 个是上一轮写的：用 120,000 字符假文本跑正则（共 ~121s）。
改用 `min_tokens=1` 小阈值后 **121s → 1.33s**；套件总时长 **840s → 665s**。

### 其他
- **P2-9** desktop `playwright` 从 `dependencies` 移到 `devDependencies`（只被 `*.mjs` E2E 脚本使用）
- **P3-5** 清理 4 个历史 coverage 产物（16MB，已 gitignore）
- **P3-4 核查为误报**：`x/`、`test-run/` 已在 `.gitignore:98` 覆盖
- **ADR 索引补齐**：`docs/adr/README.md` 此前只覆盖 0001~0006，新增 0009~0017 索引表（9 条）
- **修 1 个 flaky 测试**：`test_load_returns_none_when_file_changed` 依赖 mtime 精度，
  改为显式 `os.utime(+10s)`；连跑 3 次稳定 76 passed

### 覆盖率门禁实测复核
`pytest --cov=src` → **62.49% ≥ 60%**，`Required test coverage of 60.0% reached`——
P1-5 收紧后的门禁真实生效且当前通过（旧门禁 47 下掉 15 个点也全绿）。

---

## [v0.76.1] (2026-10-29) — 门禁自纠：v0.76.0 引入 1 处静默吞异常已修

**诚实记录**：v0.76.0 提交信息写"静默异常门禁 162/162 通过"，但提交后复跑发现 **163 > 162 FAILED**
—— 收紧后的门禁立刻抓到了我自己在同一批改动里新加的 1 处 `except (OSError, ValueError): pass`
（`entrypoint` 的 hooks 提示节流代码）。

- 修复：该处改为记 `logging.debug`（提示节流失败不影响主流程，但要留痕）
- 复跑：`check_silent_except` **162 / 162 通过**；`tests/cli/test_entrypoint_commands.py` 48 passed
- 意义：这正是 P1-6 收紧门禁的**实际价值**——旧门禁（172）下这个回归会被静默放过

---

## [v0.76.0] (2026-10-29) — 执行项目自身审计（v4 指南）P1 全清零 + 门禁收紧

按 `计划书/下一步改进指南.md`（v4，另一会话产出的实测审计）的 P1 清单逐条修复：

### P1 全清零（6 条）
| ID | 问题 | 修复 |
|---|---|---|
| P1-1 | Hook 注册表 1:1 字典 + 静默覆盖 → 配置里第二个 hook 永远不生效，日志却报 "Loaded N hooks" | `_REGISTRY` 改 **1:N**；`register_hook(replace=)` 显式替换、同名替换同项；`execute_hook` 依次执行全部规格、DENY 短路；新增 `get_hook_point_specs` / `get_registered_hook_lists`，旧 API 返回最后一项保持兼容 |
| P1-2 | `HookPoint` 值是 `auto()` 生成的 `'1'..'48'`，日志不可读、按名配置永不匹配 | `_generate_next_value_` 返回小写枚举名；实测 `HookPoint.SESSION_START == "session_start"` |
| P1-3 | 测试把 `<MagicMock name='mock.goal'>` 写进真实 `.clawd/sessions/`（37 个会话 17 个脏） | `_persist_session` 在 `PYTEST_CURRENT_TEST` 下不落盘（另支持 `CLAWD_DISABLE_SESSION_PERSIST=1`）；清理 17 个脏会话，实测跑测试前后 20→20 |
| P1-4 | hooks 配置以 `shell=True` 执行 + 启动自动加载 CWD 配置（克隆仓库即执行=活的 RCE 面） | 去掉 `shell=True`（改 `shlex.split` 直 exec，需 shell 须显式 `CLAWD_HOOKS_ALLOW_SHELL=1`）；启动**默认不加载** hooks 配置，需 `CLAWD_ENABLE_HOOKS_CONFIG=1` |
| P1-5 | 覆盖率门禁 `fail_under=47` 远低于实际 62.39% → 掉 15 点仍全绿（尺子失效） | **47 → 60** |
| P1-6 | 静默异常门禁 172 比实际 162 松 10 处 | **172 → 162**（`hard_metrics` + `baseline-silent.json` + CLAUDE.md 同步） |

### P2 修复（4 条）
- **P2-1 CLI 噪音 5~8 行 → 1 行**：渠道缓存初始化 `info→trace`；定价过期提示 24h 节流（`CLAWD_PRICING_WARN=always/never`）；hooks 未加载提示 24h 节流
- **P2-7** `celery[redis]` / `redis` 补进 `pyproject.dependencies`（`src/background/*` 硬 import，干净环境不再缺包）
- **P2-8** 删除 3 个只剩 `__pycache__` 的幽灵包目录（`src/autoresearch`/`src/openclaw`/`src/templates`）
- **P2-6（部分）** 新增 `[lsp]` extra 并同步 requirements.txt；**lock 文件未引入**（需决策工具）

### 验证
- `tests/core/test_hook_registry_multi.py` **12 passed**（含"两个 hook 都真的执行"、"DENY 短路"、"旧 API 兼容"）
- `tests/cli/test_entrypoint_commands.py` **48 passed**（含新增"安全默认不自动加载 hooks"回归）
- 全量回归、IMPORT、ruff 硬指标见下

### 未修（如实披露）
- P2-3/4/5/9 桌面端打包版本/签名/publish 域名/playwright 归类 —— 需重打包 + 代码签名证书（外部条件）
- P2-2 定价数据仍过期 171 天（需联网核对官方价，不伪造）
- P2-10 全量测试耗时波动（8~14 分钟），根因待专项分析

---

## [v0.75.0] (2026-10-29) — 多引擎协同 + 两处误判更正 + REPL 多轮记忆

### 一、两处"未闭环"其实是**我测错了**（更正）
| 之前我写的 | 实测真相 | 结论 |
|---|---|---|
| Codex 多轮 MCP 工具循环受网关 Responses 续传限制 | **只是慢**。`--dangerously-bypass-approvals-and-sandbox` + 900s 超时后：`mcp_calls: 2`、`clawd_tool_list status=completed`、最终答 `19` | **已跑通** |
| OpenCode 凭据未配置 | 真因是 `ProviderModelNotFoundError`：模型未注册。在 `opencode.json` 注册自定义模型（baseURL 用 `{env:OPENAI_BASE_URL}`，不落密钥）后 `opencode run` 返回 `PONG` | **已跑通** |

CLI 全链路验证：`clawd codex --with-clawd-tools --bypass-approvals "用 clawd_grep 搜索 'clawd-domain'"`
→ 正确返回 `tests/mcp/test_domain_server.py`、`src/mcp/domain_server.py`。

### 二、多引擎协同（用户要的"合成一个"）
新增 `src/workflow/collaborate.py` + `src/backends/native.py` + `clawd collaborate`：

```
规划(planner) → 执行(executor) → 独立审查(reviewer) → 不合格返工 → 再审查
```
- **引擎可混搭**：`--planner codex --executor native --reviewer opencode`；默认全用内置引擎
- **判定确定性**：审查者必须输出 `VERDICT: APPROVE` / `VERDICT: NEEDS_FIX`，正则解析；
  **两种都写判不通过**、**无标记判 UNKNOWN（不误放行）**
- **返工有上限**（`--rounds`，默认 1），实测 `max_repair_rounds=2` 只跑 2 轮
- **引擎实例按名字缓存**：实测三阶段各建一次引擎 → 世界模型重复初始化 3 次；缓存后跨阶段复用

### 三、REPL 多轮记忆 + `chat --resume`
此前 REPL 每轮 `engine.run_stream(goal)` 都是**无状态**的——对话没有记忆。
- `ReplSession` 自攒 `_history`（user + assistant），每轮作为 `prior_messages` 带入
- 历史过长自动压成检查点摘要（Pi 阈值 + Codex 检查点）
- 新命令：`clawd chat --resume <会话ID>`（载入历史续聊）

### 四、验证
- `tests/workflow/test_collaborate.py` **15 passed**（结论解析/三阶段顺序/返工上限/规划失败中止/异常记录/引擎缓存/CLI）
- `tests/cli/test_repl_history.py` **9 passed**（历史累积/空结果不记/续聊载入/缺失会话不崩/长历史压缩/CLI 选项）
- `clawd codex --with-clawd-tools` 真实链路：Codex 用我们的 `clawd_grep` 返回正确文件
- `opencode run` 真实链路：返回 `PONG` / `OK`
- **`clawd collaborate` 真实链路（部分）**：规划+执行阶段跑通 —— 执行者确实创建了
  `collab_done.txt` 且内容为 `collab-ok`；**但三阶段（含审查结论）在 880s 窗口内未跑完**，
  瓶颈是网关每轮约 3 分钟（27k+ prompt tokens）。所以协同的**机制**已由 15 个确定性测试覆盖，
  **端到端三阶段**仍属"待完整验证"（需更快端点或更长窗口）
- 全量回归、IMPORT、ruff 硬指标见下

### 五、边界
- 协同是**串行**流水线，不是并行多智能体辩论
- 每阶段重新起一次 agent 调用（只靠 prompt 传计划与结果，无跨阶段状态）
- 真实 E2E 单阶段约 2-3 分钟（网关 27k+ prompt tokens/轮），三阶段+返工耗时长
- 审查者仍是被提示词约束的同一模型族，不替代测试与人工验收

---

## [v0.74.0] (2026-10-29) — 工程卫生回归修复（ruff -70 / 静默异常 -6）+ 第三条红线

### 背景：自己跑基线抓到的两个回归
```
静默吞异常  156 → 168（新代码带入）
ruff src    319 → 410（+91，主因 78 条 unused-noqa）
```

### 修复
1. **清理 78 条未使用 noqa**（项目未启用 BLE 规则，`# noqa: BLE001` 全是 RUF100）
   → ruff src **410 → 374（-36，实测）**
2. **新模块里的 8 处静默 `except: pass` 改为 debug 日志**（LSP 关闭/进程强杀/源文件统计）
   → 静默吞异常 **168 → 162**（门禁 ≤172 ✅）
3. 对 `src/cli/repl.py` 的"向后兼容导出"块**主动恢复 `# noqa: F401` 并加"勿删"注释**
   —— 防止未来有人跑 `ruff --fix` 又把整块删掉（历史事故）

### 第三条 ruff 红线（已写入 .agent/memory/decisions.md）
- 第一版我用"整仓正则 + 去尾随空白"批量删 noqa，**改坏 8 个文件**（语法错误），
  靠 `git checkout -- src/` 全量回退
- 最终边界：只允许**纯空白** + **非 unsafe 的 F401**；**禁止** I001（引发循环导入）、
  **禁止** RUF100 批量删（解除 noqa 保护）；任何批量改写必须**逐文件 AST 校验 + 失败回退**

### 验证
- 全量回归、IMPORT 0、ruff 硬指标（F821/F811/E9）全过
- repl 相关 69 passed（确认兼容导出的 noqa 未破坏）

---

## [v0.73.0] (2026-10-29) — 挂机可干预：预授权 / 叫停 / 审计查看

### 解决的问题
挂机最大的顾虑是"跑偏了没法管"。之前只有"中断进程"一条路，太粗暴。
现在提供三条轻量通道，全部中文：

| 场景 | 命令 |
|:---|:---|
| 挂机**前**授权某命令（否则挂机时会因无人审批被跳过） | `clawd autonomy allow "npm test"` |
| 取消授权 / 查看清单 | `clawd autonomy revoke "npm test"` / `clawd autonomy list` |
| 挂机**中**叫停（下一检查点停下并保留进度） | `clawd autonomy stop` |
| 撤销叫停 | `clawd autonomy resume` |
| 事后看它做过哪些自主决定 | `clawd autonomy log -n 20` |

实现：`.clawd/autonomy/allow.json`（命令前缀白名单，**每次决策重读**，支持挂机中途追加）
+ `.clawd/autonomy/STOP`（检查点检测）+ `decisions.jsonl`（中文审计）。

### 语义细节
- 预授权按**前缀从命令开头**匹配：`npm test` 命中 `npm test --watch`，
  但 `echo npm test` 不命中（防止借 shell 拼接绕过）
- STOP 一旦存在，`check_stop` 立刻返回停止并保留进度；删掉文件即恢复
- 预授权优先级高于"策略要求审批但无人可批 → 跳过"

### 验证
- `tests/agent/test_autonomy.py` **42 passed**（新增 9 个：预授权命中/不命中/前缀边界/
  缺失文件安全、STOP 检测与 CLI stop/resume、CLI allow/list/revoke 往返、log 中文输出与空态）
- 全量回归、IMPORT、ruff 硬指标见下

### 顺带修掉一个不稳定测试
`test_scrape_ssrf.py::test_urllib_redirect_handler_allows_public_target` 依赖真实 DNS
（`getaddrinfo`），全量跑时偶发失败、单独跑又通过。已改为 monkeypatch 固定解析到公网 IP。

---

## [v0.72.0] (2026-10-29) — 挂机细化：半挂机按策略分级 + 成本护栏真正生效

### 修复（两个"看起来有其实没有"）
1. **成本护栏从未生效**：`check_stop` 读的是 `session.total_cost`，但 `AgentSession` 根本没有
   这个字段 → `getattr(..., 0.0)` 恒为 0，挂机烧多少钱都不会停。
   改为从 `config._cost_estimator.get_total_cost()` 取（读失败不影响其它护栏项）。
2. **半挂机退化**：原先 `semi` 的高风险 = 受保护路径 + 禁命令，导致"所有 shell 命令都算高风险"
   ≈ 退化成"每条命令都问"。现在按命令策略分级：
   - 策略**明确允许**（`policy=allow`，如 `git status`）→ 自决放行
   - 策略**要求审批**或未命中任何规则 → 高风险，问你
   - 普通文件写入 → 自决放行

### 挂机链路机制验证（确定性，不经 LLM）
`ToolManager(autonomy=全挂机)` → `FileEditTool` 写 `demo_out/hello.txt`：
**success=True，文件内容正确，审计留痕** → 决策/放行/审计全链路真实可用。

### 挂机端到端实测的瓶颈（外部限制，如实披露）
真跑"创建文件并结束"任务：模型每轮要 ~3 分钟（本地网关 + 27k+ prompt tokens），
6 轮 > 18 分钟，测试窗口内跑不完。**机制没问题，是端点响应速度限制**。
建议：挂机跑长任务时把 `max_iterations` 与预算配对设置，并接受低吞吐。

### 验证
- `tests/agent/test_autonomy.py` **33 passed**（新增 3 个：半挂机按策略分级）
- 全量回归、IMPORT、ruff 硬指标见下

---

## [v0.71.0] (2026-10-29) — 挂机自主决策引擎 + 权限全中文表达（ADR-0016）

### 一、权限全部中文化（不用懂英文枚举）
每层都给出中文名 + 行为解释 + 风险提示：
- 审批模式：**计划模式（只读）/ 默认模式（改前确认）/ 自动编辑模式（改文件不问跑命令问）/ 全自动模式（都不问）**
- 权限结论 `Effect`：**放行 / 拒绝 / 需确认**
- 命令策略结论：**允许执行 / 需审批 / 禁止执行**
- 挂机级别：**有人盯 / 半挂机 / 全挂机**
- 新命令 `clawd permissions [--rules]`：一屏中文讲清四层概念 + 受保护路径 + 全部内置命令规则

### 二、挂机自主决策引擎（`src/agent/autonomy.py`）
三级：`supervised`（有人盯，默认，行为不变）/ `semi`（只问高风险）/ `unattended`（不打扰自决）

`unattended` 自决规则：
| 情形 | 决定 |
|---|---|
| 只读 | 放行 |
| 写工作区内非保护路径 | 放行（记中文审计） |
| 写受保护路径（.git / 密钥 / token） | **跳过**，理由回灌模型 |
| 执行被禁止的命令 | **跳过** |
| 执行需审批的命令 | **跳过**（无人可批，绝不能默认放行） |

护栏（每轮迭代前检查）：连续跳过 5 次 / 迭代 40 步 / 连续失败 5 次 / 成本 $5 / 时长 120 分钟
→ 触发即停止并返回中文理由，护栏自身异常不阻断任务。

接线：`ToolManager(autonomy=...)` 处理 ASK 分支；`CLAWD_AUTONOMY` 环境变量；
`clawd run --autonomy unattended|semi|supervised`；审计写 `.clawd/autonomy/decisions.jsonl`（字段全中文）。

### 真实 E2E 抓到的三个问题（已修）
1. **策略"允许"的命令被误跳过**：`PermissionEngine` 的 exec ALLOW 只表示"不禁止"，
   下游仍是 ASK，分不清"策略允许"与"策略要求审批" → `Decision` 新增 `policy` 字段，
   挂机据此决定放行/跳过
2. **模型不知道能用什么命令**：反复试 `pwd; ls -la`、`find ... | head`（复合/管道被保守跳过），
   白烧迭代 → 新增 `allowed_command_hint()` 中文清单并在挂机时注入系统提示；
   同时扩充只读安全清单（find/head/tail/wc/tree/du/which/date/mkdir、git branch/rev-parse）
3. **`.clawd/` 被文件工具自身拒绝**：既有保护（存运行时状态），合理不改，
   但已在 ADR 写明"挂机也无法通过工具改 .clawd 内部文件"

### 验证
- `tests/agent/test_autonomy.py` **30 passed**（三级行为、保护路径/禁命令跳过、
  **需审批命令绝不自动放行**、五类护栏、中文审计字段、ToolManager 集成、`clawd permissions` 输出）
- `tests/agent/` 全量 **658 passed**（既有审批契约无回归）

### 边界
- `semi` 的高风险判定复用"受保护路径 + 禁命令"，未按工具类别细分（如删库 SQL、转账）
- 自决只做权限层面的放行/跳过/中止，不替模型做方案取舍
- 挂机期间人工介入只能中断进程，未做"运行中插入确认"通道
- 成本护栏依赖 session.total_cost 有值，无成本统计路径上该项不生效

---

## [v0.70.0] (2026-10-29) — 续跑自动压缩（把 ADR-0012 的检查点串进 ADR-0015 的续跑）

### 关闭自己上一版标注的边界
v0.69.0 写了"续跑会把整段历史塞进上下文，需配合检查点压缩（已实现，未自动串联）"。本轮串上：

- `src/agent/compaction.py` 新增 `prepare_resume_messages()`：
  - 用 **Pi 的准入阈值**（`MIN_COMPACT_TOKENS=30_000`）判断"值不值得压"
  - 超过阈值 → 用 **Codex 的检查点语义**压成单条 system 摘要（保留目标/决策/文件/工具/错误/待办）
  - 未超阈值 → 原样返回，不做无谓有损处理
- `clawd session resume` 自动调用：压缩了就提示"历史较长（N 条），已压缩为检查点摘要"

### 验证
- `tests/agent/test_session_resume.py` **13 passed**（新增 3 个：短历史不动、
  长历史压成单条 system 且关键事实保留、CLI 端到端确认压缩后只传 1 条）
- 全量回归、E2E 冒烟、doctor 均通过（见下）

### 边界
- 压缩是**确定性抽取**（无 LLM）；要自然语言摘要需传 summarizer（接口已留）
- 交互式 `clawd chat` 仍无 `--resume`（repl_task 每轮维护消息列表，工作量大且易回归）

---

## [v0.69.0] (2026-10-29) — 会话续跑打通（prior_messages 注入 + `session resume`）

### 补齐 ADR-0015 里如实标注的边界
上一版明确写了"`clawd chat --resume` 未接通：`_run_agent_core` 固定 `messages=[]`"。
本轮把它接上：

- `AgentLoopConfig.prior_messages`：续跑时把历史消息**插在 system 与本轮新目标之间**
  （构造逻辑抽成 `build_initial_messages()`，可单测，不必真跑 LLM）
- `AgentEngine.run(goal, prior_messages=...)`：接受字典或 LLMMessage 列表；
  `_normalize_prior_messages()` 做归一化——旧格式的 `unknown` 角色按 `user` 处理，
  空内容条目直接丢弃（不因一条脏历史炸掉整轮续跑）
- 新命令 **`clawd session resume <会话ID> "<本次目标>"`**：载入历史 → 注入 → 继续执行

### 验证
- `tests/agent/test_session_resume.py` **10 passed**
  （无历史时 [system,user]；有历史时 [system,*prior,user] 顺序正确；空 prior 条目跳过；
   字典→LLMMessage 转换；unknown 角色归一；None/空列表返回 None；
   **CLI resume 确实把历史传进 engine.run(prior_messages=...)**；缺失会话 exit 1）
- 全量回归见下；IMPORT / ruff 硬指标通过

### 边界（继续如实标注）
- `clawd chat`（交互式 REPL）尚未暴露 `--resume`：它的任务路径在 `repl_task.py`，
  接续需要每轮维护消息列表，比一次性 `session resume` 复杂；本轮只做非交互续跑
- 续跑会把整段历史塞进上下文，长会话需配合 ADR-0012 的检查点压缩（已实现，未自动串联）

---

## [v0.68.0] (2026-10-29) — 会话真正落盘 + 会话管理 CLI

### 发现并修复的连环缺口（三个叠在一起）
1. **两套会话存储并存、schema 不兼容**，且都写同一目录 `.clawd/sessions/*.json`：
   - `src/memory/session_manager.py`（引擎侧：`messages: [{role, content, timestamp}]` + status）
   - `src/core/session_store.py`（早期：`messages: ["u","a"]` 字符串元组 + tokens/cost）
   → 只读其中一套的实现看不到另一套写的数据
2. **两套都没人写盘**：`.clawd/sessions/` 实测为空 —— `clawd session list` 永远是"暂无"
3. **CLI 完全没有入口**：持久化能力存在但用户摸不到

### 修复与新增
- `src/core/session_bridge.py`：**按文件内容自动识别格式**的统一桥接层
  （engine / legacy 双向可读；写盘统一用引擎格式，与 Agent 运行时同源）
- **引擎运行时落盘**：`AgentEngine.run()/run_stream()` 完成后
  `_persist_session()` 写入 `.clawd/sessions/sess-<时间戳>.json`
  （goal / steps / final_result / tokens）；失败只告警不阻断主流程
- 新增 `clawd session` 命令组：`list [--json]` / `show <id>`（含分叉链）/ `fork <父> <新> [--title]` / `title <id> <标题>`

### 验证
- `tests/cli/test_session_commands.py` **13 passed**（含 4 个关键回归：
  引擎落盘后 CLI 能看见、桥接读引擎格式、桥接读旧格式、从旧格式分叉写出新格式且不改父）
- `tests/core/test_session_fork.py` **11 passed**
- 真实 CLI 实跑：建会话 → `list` 显示"演示会话 2 轮 · tokens 500/120" → `fork` → `show` 链 `["demo2","demo1"]`

### 边界
- `clawd chat --resume <id>` 仍未接通：消息持久化现在带 role 了，但 REPL 需要把历史回灌进
  agent 循环（`_run_agent_core` 目前固定 `messages=[]`），属下一步
- 旧格式会话只能被"读"和"分叉"，不会被原地改写（避免误伤历史文件）

---

## [v0.67.0] (2026-10-29) — 命令执行策略 + 会话分叉元数据（ADR-0014）

### 1. 命令执行策略（来自 Codex `execpolicy`，Rust/Apache-2.0）
`src/core/exec_policy.py`：命令**前缀匹配** + `Allow/Prompt/Forbidden` + **最长匹配获胜**
+ 三档拒绝文案（与 Codex 逐字对齐）；用户可用 `.clawd/exec_policy.json` 覆盖（同前缀用户优先）
- 内置直接禁：`rm -rf`、`git push --force`、`git reset --hard`、`git clean -fd`、
  `terraform destroy`、`dd`、`mkfs`、`shutdown/reboot`
- 内置需审批：`curl/wget`、`pip install`、`npm publish`、`chmod 777`、`docker rm`、`python -c`
- 内置放行：`git status/diff/log/show/add/commit`、`ls/cat/grep/rg/pwd/echo`
- 接入 `PermissionEngine`（exec 类先过策略）

**实测回归修正**：初版让策略 `ALLOW` 直接放行 → `AUTO_EDIT/DEFAULT` 下 `echo` 永不再问，
破坏既有契约（10 项失败）。正确语义：`ALLOW` 只表示"不禁止"，不越过 `ApprovalMode` 的询问；
`PROMPT` 则**跳过会话授权**（命令级审批每次问）。

### 2. 会话分叉与元数据（来自 OpenCode `internal/session/session.go`）
`StoredSession` 新增 `parent_session_id` / `title` / `summary_message_id`；
新增 `fork_session()`（分叉保留历史、不改父）、`update_session_meta()`、`session_chain()`（带环形保护）。
向后兼容：老会话文件缺字段按空值读，不崩。

### 3. Pi 的 `quoteShellArgument` —— 已有等价实现，未重复造
`src/utils/string_utils.py` 已有 `quote_shell_arg` / `quote_powershell_arg`。

### 验证
- `tests/core/test_exec_policy.py` **32 passed**（YOLO 也挡 `rm -rf` 与强推；PLAN 连 `ls` 也拒）
- `tests/core/test_session_fork.py` **11 passed**
- `tests/agent/` **645 passed**（既有审批契约无回归）
- IMPORT 621/621；ruff 硬指标 All passed

### 边界
- 策略只做前缀匹配，**不解析 shell 语法**（`bash -c "rm -rf /"` 这类包装未识别）
- 未实现 Codex 的 Starlark 策略格式，改用 JSON
- 会话分叉是浅复制历史，未做消息级 parent 链

---

## [v0.66.0] (2026-10-29) — 权限决策引擎：会话授权 / 拒绝理由回灌 / 写入边界（ADR-0013）

延续源码级借鉴，补齐审批链路的三个真实缺口（此前只有粗粒度 `ApprovalMode`）：

### 1. 会话级细粒度授权（来自 OpenCode `internal/permission/`，Go/MIT）
- `SessionGrants`：授权键 `(session_id, tool, action, 父目录)`
- **批准一次即记住**：同一会话内对同目录的同类写操作不再重复询问；换目录会重新问
- 解决的真实体验问题：粒度太粗时用户会直接切 YOLO（反而更不安全）

### 2. 拒绝带理由回灌给模型（来自 Codex `apply_patch.rs` / `exec_policy.rs`，Rust/Apache-2.0)
- `ToolApprovalDeniedError` 新增 `reason`：文案变为 `` `{tool}` rejected: {reason} ``，并写入 `details`
- 该异常是 `ToolExecutionError` 子类 → `engine_loop` 转成 `ToolResult(error=...)` **回灌模型**
  （已验证路径 `engine_loop.py:693`），模型能看到"为什么被拒"从而换方案，而不是原样重试

### 3. 写入边界（Pi `readonly-boundary.ts` 思路；其 OS 沙箱 Windows 无原语，未采纳）
- 硬保护：`.git/` 内路径、`*.pem/*.key/*.pfx/*.p12`、`id_rsa*/*id_ed25519*`、`.clawd_host_port`
- **默认即使 YOLO 也拒绝**（密钥与版本库不该因"全自动"就能被改）；可 `protect_even_in_yolo=False` 显式放宽
- 有意**不**保护 `.env`（首次配置与用户脚本会合法写它）——取舍已写入 ADR

### 决策顺序（先硬后软）
`read 放行 → 保护路径拒绝(带理由) → 会话已授权放行 → 按 ApprovalMode 询问 → 通过后记入会话授权`

### 验证
- 新增 `tests/agent/test_permissions.py` **41 passed**
  （保护路径识别/误伤、会话授权作用域、决策顺序、Codex 风格文案、路径键差异、ToolManager 集成：
  无回调也拒保护路径、YOLO 也拒、批准一次后同目录免问、换目录重问、拒绝理由可达模型）
- 既有审批相关 83 项测试全过（无回归）

### 边界
- 保护路径按字面片段匹配，不解析符号链接/`..`（需在工具实现层再做真实路径校验）
- 会话授权是进程内的，重启失效（符合会话语义）
- exec 类无明确路径时以 `cwd/_` 为作用域，粒度偏粗
- 未做 Codex 完整的 `exec_policy` 命令前缀策略引擎

---

## [v0.65.0] (2026-10-29) — 定向汲优补缺：LSP / 检查点压缩 / 笔记本（ADR-0012）

三家开源项目的源码级借鉴（直接读代码提取，非转述）：

### 1. LSP 代码智能（来自 OpenCode `internal/lsp/`，Go/MIT）
- `src/lsp/client.py` + `src/tools_runtime/lsp_tool.py`：`diagnostics` / `definition` / `hover`
- **对外 1-based、内部 0-based** 行号换算；客户端按 (root, language) 复用，避免每次重启语言服务器
- 实测修掉 3 个真实坑：
  1. 必须走**二进制流**（文本流会换行转换+本地编码，导致 Content-Length 与字节数不符）
  2. `shutil.which` 找不到 venv 里的服务器 → 改查「PATH + 解释器同目录」
  3. pylsp 缺 `pyflakes`/`jedi` 时会**静默不报诊断**（表现为"LSP 没反应"）
- 真实 E2E：`undefined_name` 检出（第 5 行）、`definition` 命中 `mod.py`、
  `hover` 返回 `helper(x: int) -> int`

### 2. 上下文检查点压缩（来自 Codex `core/src/compact.rs`，Rust/Apache-2.0）
- 原实现是"超预算就丢弃旧条目 + 一句占位"——信息全丢
- 新增 `src/agent/compaction.py`：四段式 handoff 摘要（进展决策/上下文约束/待办/关键数据）
  + `SUMMARY_PREFIX` 防重复劳动 + 摘要长度上限
- **默认不依赖 LLM**（确定性抽取目标/决策/文件/工具/错误/待办），LLM 失败自动降级
- 接入 `HistoryProcessor`：丢弃区段 → 结构化检查点，且检查点 **pinned**（否则下一轮又被压）

### 3. 笔记本 + 两级删除（来自 Pi `handoff/eligibility.ts` + `notebook/`，TS/MIT）
- `src/memory/notebook.py` + `src/tools_runtime/notebook_tool.py`
- 页面（topic→slug，可跨轮次持久）、`active_topic` + **boundary hint**（换主题时提示）
- **两级式删除**：`prepare_discard`（只算计划+留快照）→ `commit_discard`（压缩成功后才真删）
  → `abort_discard`，避免压缩失败丢页面
- 借用 Pi 的**最小压缩阈值**洞见：`MIN_COMPACT_TOKENS=30_000` + `is_compaction_eligible()`
  （上下文太小时压缩是净损失）；usage 未知时如实说"未知"，不猜

### 落地形态
三项全部是**内置原生工具**（非 MCP）：`LSPTool`(read) / `WorldModelTool`(read) /
`ProjectMapTool`(read) / `NotebookTool`(**write，需审批**)，引擎装配时自动就位。

### 验证
- `tests/tools_runtime/test_lsp_tool.py` **20 passed**（含真实 pylsp E2E + 假服务器分帧单测）
- `tests/agent/test_compaction.py` **16 passed**
- `tests/memory/test_notebook.py` **26 passed**（含 Pi 准入阈值与两级删除安全模型）
- 依赖补充：`python-lsp-server` + `pyflakes` + `jedi`（LSP 真实运行所需）

### 边界
- LSP 仅覆盖 .py/.go/.ts/.tsx/.js/.jsx/.rs；未装服务器时明确报"未安装"
- 确定性摘要只保事实骨架，不如 LLM 摘要自然（接 LLM 时才有段落文本）
- 笔记本 commit 后不可撤销（风险靠两级 + 快照控制，快照仅在内存）
- 未做 Codex 的远端压缩端点（我们网关不支持 `/responses/compact`）

---

## [v0.64.1] (2026-10-28) — 领域能力改为"内置优先" + 索引自动预热（ADR-0011）

### 架构纠正（推翻自己上一版的做法）
上一版把领域能力主要做成 MCP 工具，等于让我们**自己的 agent 也绕一层进程+JSON 序列化**。
MCP 只该用于**外部引擎**（Codex/OpenCode 在别的进程，只能走协议）。现在分层：

| 调用方 | 路径 |
|---|---|
| 我们自己的 agent | **原生工具**（零进程、零序列化、共享进程内缓存） |
| 外部引擎 | MCP（跨进程唯一方式） |

### 新增
- `src/tools_runtime/domain_tools.py`
  - `WorldModelTool`：action = `stats` / `context` / `predict`，带路径穿越防护与 `wait_seconds` 控制
  - `ProjectMapTool`：Aider 风格符号地图（轻量、秒级、不依赖世界模型索引）
- `src/brain/warmup.py`：世界模型**后台自动预热**（`ensure_warm`，非阻塞，幂等）
- 引擎装配 `_load_extended_tools()` 时自动注册领域工具并触发预热

### 大仓库保护（实测驱动）
实测本仓库 600+ 模块：**全量索引 >4 分钟仍未完成** → 默认跳过（`skipped_large`），
附真实原因与替代方案；覆盖方式 `CLAWD_WM_FORCE=1` / `CLAWD_WM_MAX_FILES=<n>`。
轻量替代始终可用：`ProjectMapTool` / 原生 grep。

### 修复：多进程在非主线程必失败（真因）
`src/rag/code_graph.py` 用 `ProcessPoolExecutor`，而预热跑在后台线程，Windows(spawn) 下报
`An attempt has been made to start a new process before the current process has finished its
bootstrapping phase` → **世界模型永远卡在 indexing 永不完成**。
修复 `_parse_batch()`：非主线程用线程池 → 进程池异常回退线程池 → 再退串行，全程有日志不静默。

### MCP server 同步补齐
`src/mcp/domain_server.py` 增加 3 个世界模型工具 + 可配置超时（`CLAWD_WM_TIMEOUT`），
并修正提示——此前错误提示里写了**不存在的命令** `clawd brain index`，已改为真实可用的替代方案。

### 验证（真实执行）
- `tests/tools_runtime/test_domain_tools.py` → **25 passed**
- `tests/mcp + tests/backends` → **99 passed**
- 真实仓库：`ensure_warm` **1.69s** 返回 `skipped_large`（不烧 CPU）；`stats` **0.00s** 诚实报因；
  `project_map` **4.73s** 给 30 文件图谱

### 边界
- 大仓库默认不做世界模型索引（设计取舍非 bug）；强制需接受数分钟索引时间
- `skipped_large` 为终态，同进程内改 `CLAWD_WM_FORCE` 需重启

---

## [v0.64.0] (2026-10-28) — 多引擎整合 + MCP 领域工具反向供给

### 事实纠正（先纠正前提，再谈方案）
"把 Codex / Grok / OpenCode / OpenClaw / Hermes / Pi 六个项目合并成一个"在技术上不成立：
Rust/Go/TS 三套运行时、协议互不兼容。实测分类：
- **引擎**：Codex（Rust，0.165.0 ✅）、OpenCode（Go，1.19.5 ✅）、OpenClaw（TS，Node 版本不兼容本机 ⚠️）
- **非引擎**：Grok = 模型代理（属 provider 层）；Pi = 插件/上下文原语包（属能力层）
- **无源码**：Hermes（参考库空目录）

### 新增：三层整合
1. **引擎层统一驱动**（`src/backends/base.py` + `registry.py`）
   - `CliBackend`：子进程管理 + JSONL 归一化 + 硬超时 + **进程树强杀**
   - `EngineProbe`：真实探活（ready / incompatible / not_installed / error），**不假装支持**
   - 新增引擎只需一份 `CliEngineProfile`，不复制驱动逻辑
   - `clawd engines [--json] [--run "..."]`：多引擎总览 + 用首个可用引擎执行
2. **模型层**：Grok 等模型代理不进引擎表，只作 provider
3. **领域层（关键）**：`src/mcp/domain_server.py` 把我们的能力暴露成标准 MCP server
   - `clawd_read_file` / `clawd_grep` / `clawd_project_map` / `clawd_tool_list`
   - Codex 侧注入：`CodexBackend(mcp_servers={"clawd": {...}})`

### 实测中修掉的 4 个真 bug（只有真实往返才暴露）
1. **MCP stdio 必须显式 UTF-8**：中文被 GBK 写出 → 客户端 UTF-8 解码失败 → 读任务死掉 → 全部请求超时
2. **`for line in stdin` 预读缓冲**导致交互协议死锁 → 改 `readline()`
3. **通知（无 id）不得回响应**，否则客户端视为协议违规
4. **JSON error 事件必须计入 errors**，否则引擎失败被当成"无输出成功"（静默失败）

### 验证（真实执行）
- `pytest tests/backends tests/mcp` → **93 passed**（含真实 MCP 客户端子进程往返）
- `clawd engines` 实测：codex `ready` / opencode `ready` / openclaw `incompatible`
- **Codex 确实发现并调用了我们的 MCP 工具**：
  `mcp_tool_call {"server":"clawd","tool":"clawd_grep","arguments":{"pattern":"clawd-domain"}}`
- OpenCode 经统一适配层：协议跑通（返回 sessionID + JSON 事件），凭据未配置时 **ok=False 且错误可见**

### 未闭环（如实披露）
1. **Codex 内完整多轮 MCP 工具循环**受网关限制：`previous_response_id ... only supported on
   Responses WebSocket v2` —— 需支持 Responses 续传的端点（网关能力问题，非适配层）
2. **OpenClaw 本机跑不了**：Node 25.8.1 不在其支持区间（换 Node 会影响 Electron 构建，未擅自切换）
3. **OpenCode 凭据未配置**：需 `opencode auth` 登录后用真实模型复验
4. **Hermes 无源码**，未集成
5. **World Model 未暴露为 MCP 工具**（当前只暴露项目图谱/grep/读文件）

---

## [v0.63.0] (2026-10-28) — 接入 OpenAI Codex 作为外部 agent 内核后端

### 决策（ADR-0009）
`D:\参考项目` 1678 个开源项目实测评估后，采用 **OpenAI Codex**（Rust 内核 + TS 启动器，Apache-2.0）
作为外部 agent 后端：**协议适配接入，不 fork 其循环、不搬 105k 行源码进主仓**。
理由：独立进程边界天然隔离故障；升级 Codex 不必改我们代码；事件流可回放定位问题。
（备选 LongHorizon-Harness / SWE-agent 均为 Python+MIT，但循环/工具层与现有实现重叠。）

### 新增
- `src/backends/codex.py`：`CodexBackend` + `parse_events`
  - `build_argv()`：模型/提供方/端点/沙箱/额外 `-c` 覆盖的完整映射
  - `run()`：JSONL 事件流归一化（文本/命令/用量/错误/thread_id）、硬超时、**进程树强杀**
  - `version()` / `available()`：可用性与版本探测
- CLI：`clawd codex "<任务>" [--cd] [--model] [--provider] [--base-url] [--sandbox] [--timeout] [--json]`
- `scripts/soak_backend.py`：稳定性/内存泄漏检测（RSS / 句柄 / 线程 / 残留子进程）
- `docs/adr/0009-adopt-codex-as-backend.md`：决策、许可、实测约束与边界

### 实测中处理的真实约束
1. Codex **禁止覆盖内置 provider**（`model_providers ... reserved built-in provider IDs: openai`）
   → 自定义端点注册为 `<provider>-custom`
2. Codex 0.165 **废弃 `wire_api="chat"`**，只支持 `responses` → 端点必须支持 Responses API
3. Windows npm 全局装的是 `codex.cmd` → 二进制解析依次尝试 `.cmd/.exe/.bat`
4. codex 会拉起子进程 → 超时用 `taskkill /T /F` 杀进程树，避免残留进程累积

### 验证（真实 E2E + 稳定性，全部实跑）
- `clawd codex "只回复 PONG"` → **PONG**，tokens 27,189 in / 86 out（经自有网关）
- `clawd codex "读取 readme.txt 并只回复文件里那个单词"` → **probe**，执行 1 条命令，缓存命中 17,408
- `scripts/soak_backend.py --iters 40` → **PASS**：RSS +0.9MB（平稳）、句柄 +3、线程 +0、残留子进程 0
- `tests/backends` **19 passed**（假进程注入 JSONL，零网络）
- codex CLI 版本：0.165.0；许可 Apache-2.0（未复制源码，无衍生作品义务）

### 边界（未闭环，如实披露）
- 未验证 >1h 长程连续运行（soak 只覆盖进程生命周期，不覆盖长会话上下文）
- 未验证 `danger-full-access` 在 Windows 的真实隔离强度
- Codex 使用**自己的工具集**，暂未与我们 ToolRegistry 互通（互通需把我们的工具暴露成 MCP server）

---

## [v0.62.1] (2026-10-28) — 桌面端功能真相修复：设置 / 插件市场 / 版本 / 更新

### 修复（5 个"看起来有、其实不能用"的缺陷）

1. **设置按钮是假按钮** → 点击只打印"设置面板将在后续版本提供"。
   现已实现真实设置面板：版本 / Python / 工作目录 / API Key 状态（脱敏）、
   provider / model / base_url 可编辑、RAG 与原生 function-calling 开关；
   保存写 `.clawd/ui_settings.json` **并同步运行期配置**（引擎立即用上新值；provider/model/base_url 需重启 Host）
2. **插件市场列不出用户插件** → `_plugin_manager` 恒 None，`.clawd/plugins/` 的插件永远不出现，
   与 UI 承诺"放进去即可出现"矛盾。现 Host 真实发现 `.clawd/plugins/*/pyproject.toml`
   （只读 manifest、不执行插件代码），坏 manifest 显示为 error 条目而非静默丢弃
3. **更新状态传不到 UI** → `contextIsolation: true` 却无 preload，`webContents.send('update-status')` 无接收方。
   新增 `desktop/electron/preload.js` 暴露 `window.clawdDesktop`（onUpdateStatus / checkForUpdates / appInfo）
   + `ipcMain` 处理 `clawd:check-updates`、`clawd:app-info`
4. **UI 无应用版本信息** → 新增侧栏版本栏（来源 Host `/api/info`，单一真相源 `pyproject.toml`）；
   桌面壳 `package.json` 版本从 `0.1.0` 同步到与框架一致
5. **更新源是占位域名且静默失败** → 默认 `https://updates.clawd.cn/desktop/` 不可用却不告知。
   现支持 `CLAWD_UPDATE_URL` 覆盖；未配置时 UI 与日志**明确提示"更新源未配置"**并给出配置方式，
   对 portable 版明确提示"不支持自动更新"

### 新增 API / 协议
- `GET /api/info` — 版本 / Python / 平台 / 工作目录 / provider / model / base_url / **api_key_set（布尔，绝不回显密钥）**
- WS `settings_get` / `settings_set` — 白名单键（provider/model/base_url/enable_rag/native_tools），
  未知键与 `api_key` 一律拒绝（密钥只能经 .env / 环境变量设置）
- `ConfigInjector.get_runtime_override()` — 区分"用户刚保存的运行期覆盖"与".env 配置"，避免设置面板显示错值

### 验证（真实 E2E，非桩）
- **浏览器 E2E** `desktop/ui_settings_e2e.mjs`：**17/17 PASS**
  （版本栏、设置面板打开与回填、保存→持久化→重读一致、插件市场列出用户插件 9.9.9、搜索过滤、检查更新反馈）
- **Electron E2E** `desktop/electron_bridge_e2e.mjs`：**10/10 PASS**
  （preload 桥注入、appInfo 版本、壳/框架版本一致、UI 版本栏、检查更新状态、设置面板、插件市场渲染）
- `tests/server` 50 passed（新增 13 项：设置读写白名单/密钥拒绝/持久化/插件发现/坏 manifest/内置包）
- 全量 4627 passed / 0 failed；IMPORT 607/607；ruff 硬指标 All passed；E2E 冒烟 5/5

### 已知边界（未闭环，如实披露）
- **在线下载 → 自动安装** 的完整链路只能验证到「下载开始」：本轮用真实 electron-updater 指向本地
  真实 HTTP feed（`desktop/update_feed_e2e.mjs`），实测请求链 `latest.yml → .exe.blockmap → .exe`
  全部命中，版本识别与状态上报均正常；**静默安装需要真实发布环境与已签名安装包**，
  且本轮 `desktop/dist` 现有产物仍是旧版本 0.1.0 构建，需在发布时用 v0.62.1 重新打包后再验安装
- 顺带修掉一个会让 UI 永久卡在"正在检查更新…"的缺陷：未打包状态下 electron-updater 默认
  **不发任何请求**（需 `dev-app-update.yml` + `forceDevUpdateConfig`），且失败时无兜底事件；
  现已自动写开发态配置并在 20s 无事件时明确报错

---

## [v0.62.0] (2026-10-28) — Agent 评测 harness（W8 缺口闭环）+ 假开关接线

### 新增：`src/eval/` 评测 harness
- **`clawd eval <dataset> [--baseline B] [--save] [--live] [--tolerance T]`**
- **replay 模式（默认，零成本）**：使用数据集里录制的输出做确定性断言，可直接进 CI 做 agent 行为回归
- **live 模式双闸**：`--live` + `CLAWD_EVAL_ALLOW_PAID=1` 缺一即拒绝（exit 2），守住付费 API 红线
- 五类确定性断言：`equals` / `contains` / `not_contains` / `regex` / `tool_sequence`（工具调用序列）
- 基线比对：`pass_rate` 下降（可配 `--tolerance`）或"用例由通过转失败"→ exit 1；
  新增用例不计为回归
- 数据集校验前置：空 expect / 未知断言类型 / 类型不符 / JSON 损坏 → 显式报错（不静默跳过）
- 单用例执行异常记为失败用例，不中断整轮
- 示例数据集 `src/eval/datasets/smoke.json`（3 用例，含"禁止假成功"用例）

### 修复：`--dimension/-d` 假开关接线
- CLI 帮助承诺 `creative/adversarial/audit` 维度引导，但 `src/workflow/dimensions.py`
  的 `resolve_dimensions`/`get_dimensions_prompt` **从未被调用**（谎称功能存在）
- `WorkflowEngine._inject_dimension_guidance()` 在 `run()` 入口读取运行期配置并注入引导词；
  无维度/未知维度/解析异常均降级为原样返回，不破坏主流程

### 文档
- 决策记录：55 个不可达模块由"待拍板"收敛为**明确保留 + 接线条件**（`计划书/死代码判定-2026-10-28.md §九`）
- ruff 自动化边界与两条红线（unsafe-fixes 删 noqa / I001 引入循环导入）写入 `.agent/memory/decisions.md`
- 挂机扫描 backlog 轮次 2（4 条新实践，DIRECT 证据）

### 验证（实跑）
- `tests/eval` **33 passed**；`clawd eval src/eval/datasets/smoke.json` → `3/3 passed (100.0%)` exit 0
- 全量回归 **4594 passed / 0 failed**；覆盖率 **60.33%**；IMPORT 602/602；ruff 硬指标 All passed
- E2E 5/5；doctor 0 FAIL

---

## [v0.61.3] (2026-10-28) — 覆盖率达成 60% + 8 个真实缺陷修复

### 覆盖率（W5 目标闭环）
- **49.89%（陈旧）→ 52.72% → 54.87% → 58.47% → 60.33%**（32,643 / 54,103 语句），`fail_under=47` 之外再跨 60% 里程碑
- 新增 **883 个测试用例**（3,692 → 4,575 收集；执行 4,491 passed / 7 skipped / 12 xfailed）
- 模块级提升：`notification/formatter` 14%→99%、`notification/config` 17%→100%、`config/generator` 15%→99%、`core/config/generator` 0%→高覆盖、`tools_runtime/watch_tool` 15%→99%、`workflow/pipeline` 45%→高覆盖、`workflow/worktree_isolation` 0%→、`workflow/team/state/locks` 0%→、`cli/textual_dashboard`+`dashboard/thinking`+`dashboard_widgets/telemetry` 0%→、`agent/swarm/{engine,auditor}` 42%/26%→

### 修复（8 个真实缺陷，全部由覆盖率测试暴露，非测试问题）
1. **`FullNotificationPayload` 缺 `tmux_tail`/`agent_name`/`agent_type`** → formatter 读取时 **20/38 事件类型必然 AttributeError**（SESSION_END、全部 TASK_*/AGENT_*/PIPELINE_*/WORKER_*/AUDIT_*/REVIEW_*/BLOCKED）。修复后实测 38/38 事件全部可格式化
2. **`format_session_start` 用 `float(timestamp)`**，而 notifier 传 ISO-8601 → `send_session_start_notification()` 必定 ValueError。新增 `_parse_timestamp()` 兼容 epoch 与 ISO
3. **`WatchTool.get_changes(path=...)` 把 `set` 直接 `json.dumps`** → 带 path 调用必抛 TypeError（空集合亦然）。改 `list(...)`
4. **`workflow/pipeline.py` 引用不存在的 `ErrorCode.INVALID_PARAMETER`（:184）/`TASK_FAILED`（:390）** → 契约承诺的 ClawdError 从未抛出（实际 AttributeError，调用方 `except ClawdError` 收不到）。改 `CONFIG_MISSING` / `WORKFLOW_EXECUTION_ERROR`
5. **`pipeline.run()` 不回写 artifacts** → `get_artifact()` 恒 None、状态文件 artifacts 恒空（与 docstring 承诺不符）。回写并持久化
6. **`clawd chat` 永远退出码 1**：`raise typer.Exit()` 被 `except Exception` 吞掉（`typer.Exit` 是 Exception 子类），成功路径也变成失败。try 只包 `start_repl`，`except typer.Exit: raise` 透传
7. **`clawd config --report` 单向开关** → 无法关闭报告（`--no-report` 报 No such option）。改 `--report/--no-report`
8. **`hooks/extensibility/sdk.py` except 窄化遗漏 `UnicodeDecodeError`** → 补入 `ValueError`

### 工程卫生（W7）
- ruff（src 口径）**433 → 319**（-114）：仅空白字符 101 + 安全未用导入 11，**禁用 `--unsafe-fixes` 全量**
- 踩坑记录：`ruff --fix --unsafe-fixes` 会删除 `# noqa` 注释，进而让 F401 删掉"故意保留的向后兼容 re-export"块（曾致 `tests/cli/test_repl_core.py` 收集 ImportError，已回退重做）
- 静默吞异常 **174 → 156**（门禁 ≤172）

### 验证（实跑）
- 全量快速回归 **4,491 passed / 0 failed**；收集 4,575 / 0 errors；IMPORT 602/602 0 fail/0 missing；ruff 硬指标 All passed；可达 455 ≥ 443
- 真实 E2E 冒烟 5/5 PASS；doctor 0 FAIL；压测 100 并发 QPS 3839 / P95 14.4ms、300 并发 QPS 1265 / P95 10.8ms，错误率均 0%

---

## [v0.61.2] (2026-10-28) — 死码清理 + 导入链路修复 + 独立审查修复

### 修复（3 个真实 bug，IMPORT 642+3fail+7missing → 649/649 全绿）
- `src/background/tasks` celery_app 相对导入错误（`.` → `..`）；`task_revoked` 信号签名改 `**kwargs`（celery 5 要求）
- `src/core/tracing/otel.py` OTLP exporter 导入路径（`trace.exporter` → `trace_exporter`）
- `pyproject.toml` / `requirements.txt` 补声明 `opentelemetry-instrumentation-logging`

### 新增
- **mime 白名单**（NR-3）：静态托管显式 18 后缀映射，白名单外 403；路径穿越检查收紧为 `is_relative_to`；mime 判断先行省无效 IO
- **死代码判定报告**（`计划书/死代码判定-2026-10-28.md`）：127 不可达模块三问判定（66 删 / 6 留 / 55 拍板）+ 动态导入盲区核验

### 移除（死码删除批次 P1+P2，用户批准）
- **47 文件 / 10,685 行**零引用孤岛（cli 仪表盘、core 杂项、llm 孤儿、孤岛互引链、autoresearch/templates/model_info 全包）；保守跳过 core.security（测试契约）等 4 组争议项；55 个待拍板模块保留
- 生产可达 **455 不变**（删除全部为生产与测试均不可达代码）

### 独立审查修复（1 轮，Required×2 + Suggestion×4）
- ralplan skip 语义恢复：删除事故引入的假 hint 文件方案 → 就地内联恢复原 PRD 解析（`$team/$ralph` 命令），7 行为锁定测试 + 5 用例对照原实现等价性 diff（顺带修原实现 `None.strip()` 潜在 bug）
- sdk.py except 窄化补 `UnicodeDecodeError`（并入 ValueError）

### 验证（实跑）
- 快速回归 **3692 passed / 0 failed**；收集 3703/0 errors；IMPORT 0/0；可达 455≥443；E2E 5/5；doctor 0 FAIL；静默异常 172 门禁过
- 压测（本地 WS Host）：100c QPS 3839 / P95 14.4ms；300c QPS 1265 / P95 10.8ms；错误率均 0%

---

## [v0.61.1] (2026-10-28) — 收口修复：红线回归 + 测试环境治理 + 计划文档清理

### 修复
- **静默吞异常回归**：`src/hooks/extensibility/sdk.py` 6 处裸 `except Exception: pass` 窄化为 `(OSError, json.JSONDecodeError)` 并输出 stderr 日志；静默吞异常计数 **174 → 168**（红线 ≤172），门禁 `check_silent_except --fail-over 172` exit 0
- **测试收集错误清零**：`py -3.10` 环境补装 `mcp` 包，`tests/mcp/` 2 个收集错误消除；收集 **3702 / 0 errors / 5.6s**

### 验证（2026-10-28 实测）
- E2E 冒烟 **5/5 PASS**（exit 0，base=step-5-preview）
- ruff 硬指标（F821,F811,E9）All passed；IMPORT-FAIL 0 / IMPORT-EXIT 0；生产可达 455 ≥ 443
- 快速回归 `pytest -m "not slow"` 全绿（见 workflow_status.md 验证日志）

### 文档清理（用户确认后执行）
- 删除 2 份已归档历史计划文档：`参考的结果计划指南.md`、`reports/plan-audit-2026-10-19.md`
  （归档副本 `docs/archive/plans/20261028/` 经 diff 逐字节一致验证，manifest 已更新删除执行记录与回滚方式）

### 依赖
- `py -3.10` 测试环境补装 `mcp`（MCP 官方 SDK，tests/mcp 收集依赖；venv 已有）

---

## [v0.61.0] (2026-10-28) — 超级智能体增强 + DSH 式桌面端全链路

### 新增
- **MCP Client 桥接层**（stdio+HTTP 双传输）+ 工具签名检疫审批（防 tool poisoning）
- **4 推理模式**（reflexion/plan-execute/lats/debate）+ `clawd reason` CLI
- **8 个逆向原生工具**（Ghidra 桥/strings/熵/hexdump/objdump/binwalk 等）
- **安全工具 YAML catalog**（scope 授权门禁 + 注入拦截 + dangerous 双重确认）
- **51 个逆向场景 SKILL.md** 知识库 + 4 个 Ghidra 分析脚本
- **插件体系**（manifest/DI Context/工具与 Prompt 接入面/插件市场 API）
- **上下文工程**（观察截断引导 + 历史滑动窗口压缩）

### 桌面端（DSH 模式，Electron）
- Python Host（`clawd serve`）：WS + 端口文件 + 同端口 Web UI 托管
- DSH 设计规范 UI（三阶深灰/#536dfe/侧栏工作台/插件市场毛玻璃弹窗）
- Electron 壳（spawn Host/托盘/单实例/崩溃自愈/TF 定制图标）
- **NSIS + Portable 双产物** + electron-updater 自动更新 + 首次配置引导窗
- **安装版真机终测 PASS**（配置引导→连接→真实 LLM 对话→工具调用）

### 修复（含独立审查 4 项阻塞问题）
- system prompt 注入工具参数 schema（修模型猜参数名）
- 原生 function calling 默认开启（文本协议被现代模型无视）
- 事件实时广播（sync handler + 服务 loop threadsafe 调度）
- scope 门禁后缀绕过（域名加 `.` 边界）
- MCP stdio connect 半途失败子进程泄漏（回滚 context manager）
- 插件 sys.path 污染（spec_from_file_location 隔离命名空间）

### 验证
- 205+ 测试全绿 · 契约 39 passed · ruff All passed · IMPORT-FAIL=0
- 真实 API E2E 双 PASS · Playwright UI E2E PASS
- 压测 200 并发：QPS 1418 / P95 10.5ms / 错误率 0%
- 安装版真机终测 PASS（提交 `1261b64` → 审查修复 `f02321e`）

---

### v0.60.10 (2026-10-23) — 覆盖率补测（+265 用例）与 12 个生产缺陷修复

本轮只做一件事：**给低覆盖的生产可达模块补行为测试**。
结果是——测试写下去，模块自己就崩了 12 次。以下缺陷全部是"读代码看不出来、
一跑就炸"的类型。

#### 修复的缺陷（全部有回归测试锁定）

| # | 模块 | 缺陷 | 严重度 |
|:---|:---|:---|:---|
| 1 | `workflow/mode_state.py` | `from .keyword_registry import …` —— `src/workflow/keyword_registry.py` **不存在**（真身在 `src/agent/`），`update_skill_state()` 一调用即 `ImportError`，技能状态更新整体不可用 | P1 |
| 2 | `workflow/mode_state.py` | `detect_primary_keyword()` 返回**字符串**，却被当作 `KeywordTrigger` 用（`match.skill`）→ `AttributeError` | P1 |
| 3 | `workflow/mode_state.py` | 注册表登记 `deep_interview`（下划线），状态读取方只认 `deep-interview`（连字符）→ 输入锁写进去后**无人识别** | P1 |
| 4 | `workflow/mode_state.py` | `activated_at` 未回写到 `extracted_state` → 重新激活时间丢失 | P2 |
| 5 | `workflow/mode_state.py` | `can_resume() -> bool` 实际返回 `str`（`and` 链尾是 `started_at`） | P2 |
| 6 | `memory/manager.py` | `SemanticPattern(**dict(row))` —— 库里的 `target_skills` 是 JSON 字符串，还原后变 `str`，调用方迭代会**逐字符遍历** | P1 |
| 7 | `memory/manager.py` | `get_status()` 调 `self.storage.get_storage_size()`，而**默认 SQLite 后端没有该方法** → `AttributeError` | P1 |
| 8 | `memory/manager.py` | `await self.storage.list_episodic()`，SQLite 版是**同步**返回 → `await list` `TypeError` | P1 |
| 9 | `memory/manager.py` | `entry.id in e.tags` —— `EpisodicMemory` 根本没有 `tags`/`metadata` 字段 → `AttributeError` | P1 |
| 10 | `memory/manager.py` | 导出时 `write_text` 缺 `encoding` → Windows GBK 下写中文崩 | P2 |
| 11 | `rag/repo_map.py` | `def` 签名解析写成 `'(' + '('`，且把整个 `name(args)` 当函数名 → repo map 输出的签名全错 | P2 |
| 12 | `agent/swarm/quality_gate.py` | `GateResult` **没有 `severity` 字段**，而 `pipeline` 用 `r.severity == 'critical'` 判定 → 任何一次门禁失败都抛 `AttributeError`，报错方向完全失真 | P1 |

> 第 1、2、6~9 条的共同点：**模块有测试、但测试从没走到那条路径**。
> 覆盖率的价值不在于数字，而在于"逼你把每条分支都执行一次"。

#### 新增测试

| 文件 | 用例 | 目标模块 |
|:---|---:|:---|
| `tests/workflow/test_mode_state_deep.py` | 71 | mode_state（46% → 显著提升） |
| `tests/core/test_budget_guard_deep.py` | 62 | budget_guard（36% → 显著提升） |
| `tests/rag/test_repo_map_deep.py` | 67 | repo_map（49% → 显著提升） |
| `tests/memory/test_memory_manager_deep.py` | 52 | memory/manager（26% → 显著提升） |
| `tests/agent/swarm/test_pipeline_flow.py` | 13 | swarm/pipeline（0% → 56%） |

合计 **265 个新测试函数**（parametrize 展开后收集数更多）。

> **合并说明**：本条目由负责覆盖率补测的会话编写；`v0.60.9` 的死码删除与
> 判定判据收紧由另一个会话完成。两者在同一工作区并行，最终由后者一并提交为
> **0.60.10**，因为全量回归（3551 passed / 0 failed）是在两者合并状态下跑的，
> 单独发布任一方的版本号都会与内容集不符。

#### 验证（2026-10-23 实跑）

| 项 | 命令 | 结果 |
|:---|:---|:---|
| 全量回归 | `py -3.10 -m pytest tests/ -q --cov=src` | ✅ **3551 passed / 5 skipped / 2 xfailed / 0 failed**（663s） |
| 覆盖率 | `coverage-final2.json` totals | **49.89%**（28,175 / 56,469），较本轮起点 47.44% **+2.45pp** |
| 静态硬指标 | `ruff --select F821,F811,E9` | All checks passed |
| 导入完整性 | `import_sweep --strict-exit` | IMPORT-FAIL 0 / IMPORT-EXIT 0 / DEP-MISSING 7（均可选 extras） |
| 生产可达 | `reachability.py` | **443**（删除 8 个死模块后不变） |
| 静默吞异常 | `check_silent_except.py --no-gate` | **172**（未新增） |
| 真实 E2E | `e2e_smoke.py` / `e2e_production.py` | **5/5** 与 **8/8**，退出码 0 |
| 并发压测 | `stress_test.py --n 200` | **5/5**，137 req/s，无死锁/错配 |

---

### v0.60.9 (2026-10-23) — 死代码第一批删除 + 判定判据第三次收紧

这是第一次**真正删除**代码（前几轮只出判定报告）。删了 8 个模块 / 407 行，
全部零引用、非包门面；删后生产可达数 **443 不变**。

#### 删了什么

`src/core/config/validator.py`（74 行）· `src/core/snapshot.py`（68）·
`src/workflow/mode_context.py`（63）· `src/core/telemetry/tracer.py`（53）·
`src/core/durable/schemas/schema_validator.py`（50）· `src/core/lease.py`（44）·
`src/core/parallel_executor.py`（43）· `src/tools_runtime/diff_utils.py`（12）

三方核验后才删：全限定导入零命中、父包 `__init__` 相对导入零命中、
同级模块相对导入零命中、无 `importlib`/`__import__`/`globals()` 字符串引用。

#### 判据第三次收紧 —— 门禁抓住了我自己的误判

`deadcode_triage` 的判据至今改了三版：

| 版本 | 判据 | 结果 |
|:---|:---|:---|
| v1 | 末段标识符匹配 | 135/135 全判"有引用"（ADR-0001 陷阱重现） |
| v2 | + 父包 `__init__` 相对导入 | NO_REFS 112（**仍漏**） |
| v3（本版） | + **同包内任意模块**的相对导入 | NO_REFS 55 |

**实证过程**（这正是四道门禁的直接价值）：

1. 首轮按 v2 名单删了 10 个，`import_sweep --strict-exit` **立刻返回 1**，
   报 4 个 IMPORT-FAIL：`vault` / `pipeline_stages` / `ralph_verify` / `team_exec`。
2. 根因：`src/core/secrets/vault.py:11 from .base import SecretStore`、
   `src/workflow/pipeline_stages/ralph_verify.py:11 from .types import ...`
   —— 是**同级**相对导入，不是父包 `__init__`。
3. 恢复 `base.py` / `types.py`，其余 8 个保留删除；复验 `import_sweep=0`、可达数仍 443。

**结论：机械判据只能"提名候选"，删除必须由 `import_sweep` 兜底。**
如果上一轮没有把这条门禁做出来，这次误删会直接进主干。

#### 不变量（删前 → 删后）

| 项 | 删前 | 删后 |
|:---|:---|:---|
| 生产可达 | 443 | **443**（未下降） |
| 模块数 | 642 | 634 |
| 完全不可达 | 134 | 126 |
| `import_sweep --strict-exit` | 0 | **0** |
| collect | 3558 / 0 errors | 3558 / 0 errors |
| ruff F821/F811/E9 | All passed | **All passed** |
| 定向回归 `tests/{core,workflow,tools_runtime,contracts}` | — | **1289 passed / 0 failed** |

#### 剩余

完全不可达 126 个；三问判定 **NO_REFS 55 / DOC_ONLY 6 / HAS_REFS 65**。
剩余 55 个候选逐批处理（每批 ≤20 + 同一套不变量验证）。

#### 本轮实测验收

| 项 | 结果 |
|:---|:---|
| 全量回归 | **3551 passed / 0 failed / 5 skipped / 2 xfailed / 623.24s** |
| 真实 E2E 冒烟 | **5/5 PASS，exit 0**（v0.60.9 实跑：PONG / get_weather Berlin / 391） |
| 生产路径 E2E | **8/8 PASS，exit 0**（chat / chat_stream 11 thinking chunks / 工具解析 / 上游失败不静默降级） |
| 定向回归 | 1289 passed / 0 failed（47.63s） |

#### 关于并发会话（诚实披露）

本仓库目录下**同时有另一个会话在工作**，它正在做覆盖率补测，并在工作区留下：
- 4 个 `src/` 缺陷修复（`quality_gate.py` 缺 `severity` 字段导致 `AttributeError`、
  `memory/manager.py` 的 `target_skills` JSON 反序列化类型错误、`repo_map.py` 签名解析、
  `mode_state.py` 的 deep-interview 技能名别名与相对导入）
- 5 个新测试文件（`test_pipeline_flow` / `test_budget_guard_deep` /
  `test_memory_manager_deep` / `test_repo_map_deep` / `test_mode_state_deep`）

**这些改动未经本会话审查，因此未纳入本提交**（本提交是精确 add，只含 4 个文档/配置
文件）。上面的全量 3551 passed 是在**含这些工作区改动**的状态下跑的，所以它们至少
"没有破坏现有测试"；但它们的正确性需要它们自己的审查闭环。

版本号说明：本会话最初按 **0.60.9** 收口（死码删除），提交前发现该会话的
**0.60.10 工作已完整落地**（12 个缺陷修复 + 265 个新测试，CHANGELOG 条目已写好、
全量 3551 passed 已包含）。为避免"版本号与实际内容不符"以及两条提交互相踩踏，
最终**合并为 0.60.10 一起收口**：版本号 = 内容集 = 死码删除 + 覆盖率补测 + 12 个缺陷修复。

### v0.60.8 (2026-10-23) — 独立审查 5 个阻塞项收口

独立审查（只读）对本轮改动给出 **Request Changes**，逐条附了可复现证据。
这一版把它们全部关闭——其中 C-2/C-3 是"我自己的度量工具在说谎"，
C-5 是"归因方向完全相反且会被 CI 升级成阻断"。

#### C-1 干净环境 `pytest --collect-only` 直接失败（CI 新门禁首跑必红）

`tests/memory/test_faiss_store.py` 顶层 `import numpy`，但 `numpy` 从未在任何
依赖清单里声明。本机因系统 Python 装过 numpy 而看不见；venv / ubuntu 干净环境
实测 `3259 collected, 1 error, exit=2` → 新增的 collect 门禁第一次推送就会红，
且报错方向错误（说是"1 个收集错误"，实际是"缺依赖"）。
**修复**：`numpy>=1.24` 进 `[project.optional-dependencies].dev`。

#### C-2 / C-3 `baseline.py` 在说谎：三个指标恒 `null`，而 `null` 被判为通过

- `import_sweep` 的 `IMPORT-FAIL / IMPORT-EXIT / DEP-MISSING` **永远解析成 None**：
  汇总行在 stdout 顶部，642 次 import 的 loguru 日志在 stderr，拼接后取末 6 行
  只剩噪音。实测 `fail/import_exit/dep_missing` 全 null，真实值是 `0/0/7`。
- `reachable` **恒 None**：按中文锚点解析 GBK 输出的子进程 stdout。
- 旧 `hard_fail` 写 `fail not in (0, None)` → **None 算通过**；且不含 collect /
  reachability / 覆盖率。实测出现过 `collect exit_code=2` 但脚本 `exit=0`。
- 在 ubuntu 上 `venv/Scripts/python.exe` 不存在 → 被吞成 `status:"error"`，
  此时只剩 pyproject 一个版本来源 → `consistent` 变成同义反复的 True。

**修复**：
- `reachability.py` 新增 `--json`；`baseline.py` 改为**消费 JSON**而非抠中文 stdout；
- `_run` 强制 `PYTHONUTF8=1 / PYTHONIOENCODING=utf-8`，输出尾部 6 → 20 行；
- 门禁语义重写为 `_hard_fail_reasons()`：**`None`（没测到）一律算失败**，
  并把 collect 退出码、reachability 缺失、覆盖率低于阈值全部纳入；
- `_interp_runtime()`：venv 不在时回退当前解释器，不再静默 error；
- 新增 `tests/scripts/test_baseline_gate.py`（14 例）锁死"None = 失败"。

#### C-4 `deadcode_triage` 的 NO_REFS 有 35% 假阴性（不认相对导入）

判据只认全限定名与 `import src.a.b`，没覆盖 `from .architect import X`。
`src/agent/modes/__init__.py:17` 就有一行，于是 `src.agent.modes.architect`
被判成"零引用"——按那份名单删会让 `import src.agent.modes` 直接 ImportError。
**修复**：新增 `_parent_package_references_leaf()` 覆盖三种相对导入写法；
搜索范围补 `skills/ prompts/ hooks/ references/ .claude/`；并排除脚本自身
（它 docstring 里的示例会把自己扫描成"动态引用"）。
**结果**：NO_REFS **112 → 71**，HAS_REFS 16 → 57。

#### C-5 `classify()` 把与 `src/` 子目录同名的第三方包判成代码缺陷

`(SRC / top).exists()` 这条启发式让 `mcp` / `config` / `runtime` 全部判成
`IMPORT-FAIL`——而 `mcp` 正是本批刚写进依赖的第三方包。叠加 `--strict-exit`
后，"没装 mcp"会变成"构建失败：项目内有代码缺陷"，方向完全相反。
**修复**：新增 `_declared_distributions()` 读 pyproject 的已声明依赖，
判定顺序改为「`src.` 前缀 → 已声明依赖 → `src/<top>` 存在 → 其余」。
实测：`mcp/numpy/pathspec/loguru → DEP-MISSING`，`config/runtime/src.nope → IMPORT-FAIL`。

#### 其他收口

- 阈值**唯一来源** `scripts/hard_metrics.py`（此前同一阈值散落 4 处、两处不同值）：
  `reachability` / `check_silent_except` / `baseline` 全部 import，CI 不再传数值；
  `check_silent_except` 不传参即门禁（新增 `--no-gate` 走纯统计），
  避免"CI 忘写参数就静默全绿"。
- `reachability.main()` 改为复用 `compute_reachability()`（此前有两套实现，
  注释却声称"所有脚本共用同一口径"）。
- `requirements.txt` 补 `psutil / fastapi / uvicorn`（此前只在 pyproject，
  按 CHANGELOG 自己的"硬 import"论证，`pip install -r` 的用户仍会崩）。
- 文档残留：`workflow_status` 的 `137,443→137,468` 与 `3190→3261`；
  README 的 Ruff 全量数字改为"跑 --statistics 看当前值"（它已连续三次漂移）；
  `.agent/memory/verified-scope.md` 的旧阈值写法。

**验证**：`pytest tests/scripts` 49 passed；`py -3.10 -m ruff check src/ tests/ --select F821,F811,E9`
All checks passed；`venv collect` **3261 / 0 errors**（修 C-1 前为 3259 / 1 error）。

### v0.60.7 (2026-10-23) — 把度量从"人工纪律"变成"CI 门禁"

主题不是加功能，而是**让"它到底好不好"这件事可被自动判定**。
本轮之前：四条硬指标里两条靠人记着跑、覆盖率阈值是死配置、全量回归数周没在单轮内跑完、
三份文档对同一版本给出三个数字。

#### 新增：四道 CI 门禁（此前全靠人工纪律）

| 门禁 | 命令 | 拦住的真实事故 |
|:---|:---|:---|
| 收集 | `pytest tests/ --collect-only -q` | 缺 `__init__.py` 导致的 import file mismatch |
| 导入完整性 | `import_sweep.py --strict-exit` | 新增 `--strict-exit`：`IMPORT-EXIT > 0` 即失败，堵住"用 `sys.exit` 绕过红线" |
| 生产可达 | `reachability.py --min-reachable 443` | 新增参数：删码/改 import 形式导致模块从生产图消失 |
| 静默吞异常 | `check_silent_except.py --fail-over 172` | 新增基线文件 `.clawd/baseline-silent.json`，只降不升 |

#### 修复：覆盖率阈值从未生效（v0.53.0 起的静默失效）

- `fail_under = 60` 写在 `[tool.coverage.run]`，coverage 会当作未知配置项忽略
  （实测 warning：`Unrecognized option '[tool.coverage.run] fail_under='`）。
  真正生效的是 CI 里硬编码的 `--cov-fail-under=45`。
- 已移到 `[tool.coverage.report]`，设为 **47**（实测基线 47.44%），CI 不再传参 →
  **单一来源、真实生效**。相对此前真正生效的 45 是提高，目标仍为 60（分批 47→50→55→60）。

#### 修复：flaky 并发测试（契约写错，不是实现缺陷）

- `tests/test_state/test_authority.py::test_acquire_release_thread_safe` 断言
  "10 线程并发 acquire 同一租约都不出错"，但 `AuthorityLease` 是 **Exactly-One 互斥租约**，
  竞争者必然被拒。该测试只在"恰好串行调度"时通过 → 高负载下必挂。
- 按 ADR-0005 **不放宽断言**，改为更强的真实契约：恰好 1 成功 / 9 被
  `LeaseAcquisitionFailed` 拒绝 / 0 非预期异常 / 释放后可再获取。
  用 `Barrier` 最大化竞态窗口，成功者不释放保证确定性。连续 5 次绿。

#### 新增：单一取数入口与死代码判定工具

- `scripts/baseline.py`：一条命令输出全部硬指标 JSON（版本一致性、模块数、收集数、
  ruff 硬/全量、导入扫描、可达性、覆盖率、静默异常），任何一步失败如实记 `failed`。
- `scripts/deadcode_triage.py`：对"完全不可达"模块做三问机械筛查
  （静态引用 / 动态导入 / 文档引用），产出 `计划书/死代码判定-2026-10-23.md`。
  **只判定不删除**——112 个"零引用"里仍有对外导入路径与未接线能力，删需产品决策。

#### 修复：可达性口径漏算 `python -m src` 入口

- `src.__main__` 是 `python -m src` 的规范入口，但不在种子列表里，被算进"完全不可达"，
  差点被当死代码删掉。种子已收敛为 `reachability.PROD_SEED_MODULES` 单一来源 +
  `compute_reachability()`，其他脚本禁止各自复制。
- 影响：生产可达 442 → **443**，完全不可达 135 → **134**。属口径修正，非新增功能。

#### 测试分层（按实测耗时，不按结果）

- 9 个用例打 `slow`（合计约 410s，占全量 53%）：`not slow` 快速层 **237s**，
  全量 **767s**。红线：`slow` 只能按耗时标，禁止用来隐藏失败用例。

#### 本轮实测验收

| 项 | 结果 |
|:---|:---|
| 全量回归 | **3254 passed / 0 failed / 5 skipped / 2 xfailed / 639.98s**（首轮 3200 passed + 1 flaky，已修为强契约断言） |
| 快速层 | 3245 passed / 237.23s |
| 覆盖率 | 46.15% → **47.44%**（26,861 / 56,624） |
| 真实 E2E | `e2e_smoke` **5/5** · `e2e_production` **8/8**，退出码 0 |
| 并发压测 | 200 并发 **5/5**，128 req/s，无死锁/错配 |
| 静态硬指标 | F821/F811/E9 All checks passed · IMPORT-FAIL 0 · IMPORT-EXIT 0 |

**未达成**：覆盖率 60%、死模块 ≤20（需产品决策）、快速层 <180s、远端 CI/Docker/Release（本机无 `gh`/`docker`）。

### 未发布 (2026-10-23) — 度量真实性、依赖声明与环境收敛

本批不改业务逻辑，改的是"我们怎么知道它是好的"：
四条硬指标里有两条是失真的，而真实端点 E2E 一跑就暴露 3 个未声明的生产依赖。

#### 修复：指标失真

- `scripts/import_sweep.py` 的 `classify()` 把导入期 `SystemExit` 兜底判为代码缺陷，
  导致 `IMPORT-FAIL = 0` 这条红线可被一个 `sys.exit` 轻易污染。新增 `IMPORT-EXIT`
  分类（不计入缺陷、单独列出待复核）。
- `src/cli/surface_viewer.py` 去掉模块级 `sys.exit(1)`。去掉后发现该模块**从未被成功导入**：
  函数注解在模块级求值，而 `SurfaceManager` 来自可能失败的 `try` 块，
  立即抛 `NameError`。已加 `from __future__ import annotations`。
  —— 一个 `except` 掩盖了整块不可用，这比缺一个可选依赖严重。

#### 修复：4 个生产路径依赖从未声明（`pip install -e .` 装出来的环境跑不了）

| 包 | 使用者 | 后果 |
|:---|:---|:---|
| `litellm` | `src/llm/litellm_singleton`、`lazy_litellm`、`exception_handler` | 项目 LLM 栈完全不可用 |
| `mcp` | litellm ≥1.100 的 function-calling 路径 | 工具调用抛 `ModuleNotFoundError` |
| `psutil` | `src/core/resource_monitor.py`（硬 import）、`budget_guard`、`memory_guard` | `liveness`/`swarm.engine` 导入即崩 |
| `fastapi` / `uvicorn` | `src/cli/web_config.py`（硬 import） | `clawd config` 的 Web 界面崩溃 |

均已补进 `pyproject.toml`，`mcp` 同时补进 `requirements.txt`。
修复后：`e2e_smoke` 5/5、`e2e_production` 8/8、`import_sweep` FAIL 0 / DEP-MISSING 7（全为可选 extras）。

#### 新增：护栏

- `tests/scripts/test_import_sweep_classify.py`（10 例）：锁定归因语义。
- `tests/scripts/test_check_silent_except.py`（7 例）：锁定静默吞异常口径。
- `tests/core/test_version_consistency.py`（2 例）：pyproject / dist-info / `src.__version__` 三者一致。
- `scripts/check_silent_except.py`：AST 口径统计（实测 172），`--baseline` 可做趋势断言。

#### 文档校准

10 处过时断言已修（版本号、用例数、覆盖率、收集耗时、命令解释器）。
`workflow_status.md` 顶部新增"当前状态"区块，历史轮次数据全部标注为快照。
新增 `计划书/下一阶段执行计划-2026-10-23.md`（W0-W6）。

#### 环境

`venv` 补装 `.[dev]`：pytest 9.1.1 / ruff 0.17.2 / coverage 7.16.2，dist-info 同步到 0.60.6。
本机 `python` 命令不存在，测试统一用 `py -3.10`（同一份测试在 `py` 默认 3.14 下会报 68 个假错误）。

---

### v0.60.6 (2026-10-20) — 第三轮审查收口：生产持久化、测试强度、证据修正

第三轮独立审查（reviewer-round3）判定 Request Changes，阻塞点为 C1（修复落在
生产不可达模块）与 C2（并发测试被降强度）。本轮逐项关闭。

#### C1：生产持久化

- 确认 `src/core/state_impl.py` 在 `reachability --prod --list` 中属于
  **生产不加载**（391 行）；v0.60.4 的修复只提升了一致性，不等于生产已修复。
- 真正生产可达的 `src/core/persistence/run_state.py`（被 `workflow/engine.py`、
  `status_dashboard.py` 等使用）存在同类问题：
  - `_write_atomic` 使用固定 `<name>.tmp`、无锁、无 fsync，且先 move 目标再 replace；
  - `record_evidence_event` 的 JSONL 追加无锁、无 fsync；
  - `update_task` 的 OCC 检查与写入不在同一临界区。
  已改为 `file_lock + atomic_write`、锁内读改写、备份先 copy 再覆盖。
- 新增生产函数并发回归：`tests/core/test_run_state_concurrency.py`
  （4 线程更新任务不丢、4×10 事件追加 40 行且每行合法 JSON）。

#### C2：测试强度

- 恢复 `test_state_persistence_semantics.py` 的原并发强度：
  atomic write 20 次、mode_state 10 次、progress 10 次、读改写 25 次（断言 100）。
  `timeout=60` 保留（审查实测原参数可通过）。

#### 证据修正

- 收集基线改为实测 **3171 tests / 0 errors / 64.84s**。
- HTML 报告题数说明改为 9 题；正文证据更新为 v0.60.5/3163 passed/2773s。
- `.agent/memory` 的收集数字与“未达成”矛盾已清理；补充 async 重入限制条目。

---

### v0.60.5 (2026-10-20) — 持久化持久性与锁等待

- `atomic_write` 增加 `flush + fsync`：掉电后不再出现“文件存在但内容为空/半截”。
- `state_impl` / `state.persistence` 的状态写入锁等待上限提高到 30s：
  全量测试高负载 + fsync 下，10s 会偶发 `TimeoutError`（实测）。
- HTML 变更报告更新到 v0.60.4/0.60.5，测验扩为 9 题（真实浏览器 9/9 通过）。
- 并行负载复验：`tests/core` 669 + `tests/workflow` 226，0 failed。
- 熔断器半开测试改为有界轮询等待：固定 `sleep(timeout + 0.05)` 在高负载下
  偶发踩边界（全量实测），轮询不改变“必须迁移到 HALF_OPEN”的断言。

#### 验证

- `pytest tests/core/test_state_persistence_windows_safe.py -q` 连续 5 次通过。
- 并行跑 core/workflow 无锁超时。

---

### v0.60.4 (2026-10-20) — 终审补充：跨平台状态持久化

- `src/core/state_impl.py`（**生产不可达**的平行实现）的 `save_snapshot`
  曾在函数内 `import fcntl`；该模块在 Windows 上会保存失败。已改用
  `file_lock + atomic_write`，但**不宣称生产受此缺陷影响**。
- `src/core/state/persistence.py`：快照/事件原子写；`append_event` 加锁。
  该模块在 `src/` 中无调用方（`append_event` 也无生产调用方），属一致性修复。
- 生产路径 `src/core/persistence/run_state.py` 的同类问题在 v0.60.6 修复。
- 新增回归：Windows 跨平台保存、4 线程 ×10 次并发追加（40 条不丢）。
- 收集基线复测：**3171 tests / 0 errors / 64.84s**（收集 <120s 已达成）。

#### 验证

`pytest tests/core/test_state_persistence_windows_safe.py -q` → 2 passed；
`pytest tests/core/test_run_state_manager.py tests/integration/test_phase2_integration.py -q` → 21 passed。

---

### v0.60.3 (2026-10-19) — 终局审计：启动链路、核心依赖、测试套件退出、执行骨架

把项目当成真实交付物做终检，发现并修复以下问题。

#### P0：核心安装/启动链路

- `requirements.txt` 含不存在的 `braintrust>=0.50.0`，`pip install -r` 整体失败；
  该 processor 也未移植，已移除。
- `start.bat` 依赖 PATH 中不存在的 `python`；改为 `py -3.10` → `py -3` → `python`。
- 启动脚本安装全部 `requirements.txt`（含 celery/redis 等非必需）且失败仍报“成功”；
  改为 `pip install -e .`，失败 `exit /b 1`。
- venv 缺 `wheel` 导致 editable 构建失败；脚本先装 `setuptools wheel` 并使用
  `--no-build-isolation`。
- `src/utils/__init__.py` 急切导入可选依赖 `pathspec`，核心安装后 CLI 直接崩溃；
  改为可选导入 + 明确降级提示。
- `loguru`、`toml` 被核心模块直接 import 但未在 `pyproject.toml` 声明；
  已补进核心依赖（否则命令组整体失效）。

#### P1/P2

- `atexit` 阶段重导入导致 `can't register atexit after shutdown` traceback；
  清理函数捕获并降级为 debug。
- `doctor` 版本正则只认中文冒号，README 写成英文冒号时显示“无法提取”；已兼容。
- 测试套件无法退出：`test_goalx_integration.py` 是无超时的真实 LLM E2E，
  改为 `RUN_GOALX_E2E=1` opt-in；`test_agent_engine_refactor.py` 启动 WorldModel
  进程池导致 pytest 挂起，fixture 改为 tmp_path 并禁用后台初始化。
- 删除无任何测试函数的 `tests/test_slop_data.py`。

#### 执行骨架与文档

- 新增 `.agent/skills/`（9 个）、`.agent/memory/`（7 个）、`.agent/rules.md`。
- 新增 `reports/change-report-2026-10-19.html`（9 题测验，真实浏览器 9/9 通过）
  与 `reports/plan-audit-2026-10-19.md`。
- 计划文档审计：三份文档仍含未闭环项或为维护依据，**未删除、未归档**。
- 更新 `计划书/下一步改进指南.md` 顶部状态表为 v0.60.3 实测。

#### 验证

- `start.bat doctor` 端到端退出码 0（89s，诊断全 PASS）。
- `venv/Scripts/python.exe -m src --version` → v0.60.3，无缺失依赖/traceback。
- 根目录测试 270 passed / 1 skipped（76.5s，正常退出）。
- 全量测试结果见 `test_ledger.md`。

---

### v0.60.2 (2026-10-19) — 复审收口：过滤调用 id、生产读改写锁、安全测试真实性、版本解析

第二轮独立审查（reviewer-round2）仍判定 Request Changes；本轮逐项关闭。

#### 原生工具调用

- **被 `max_repeat_calls` 过滤的调用也补 `role=tool` 消息**：此前过滤后
  assistant 的 `tool_calls` 留下悬空 id，下一轮会 400。
- `tool_call_id` 改为**按调用顺序**与 `tool_calls` 一一对应，不再按
  (name,args) 签名映射（同名同参会拿到彼此的 id）。
- 新增“重复调用被过滤后无悬空 id”的回归测试。

#### 状态持久化

- `ModeStateManager.cancel_mode` 的 read→modify→write 整体加锁。
- `team_persistence` 的 `add_team_member` / `remove_team_member` /
  `update_member_status` / `add_team_message` 统一走
  `_mutate_team_state`（锁内读改写）。
- 新增直接针对生产函数的并发回归：`ModeStateManager.update_state`、
  `add_progress_entry`。
- `file_lock` 的 `stale_after` 默认提高到 300s；owner 写入失败时保留锁目录
  等待回收，不再冒险删除他人锁。

#### 安全

- `SafeRedirectHandler` 提到模块级；测试直接导入生产实现并断言拦截，
  不再在测试里复制一份逻辑（消除虚假覆盖）。

#### 版本与可观测性

- `src.__version__` 改为 **pyproject.toml 优先**：editable 安装元数据滞后时，
  不同解释器也能显示同一版本。
- tracing 恢复逐 provider 异常隔离（一个 provider 失败不影响另一个）。

#### 验证

- 全量：**3162 passed, 4 skipped, 1 xfailed, 0 failed**（1531s）。
- 定向：1383 passed / 1 xfailed。
- E2E：`e2e_smoke` 5/5、`e2e_production` 8/8；压测 5/5。

---

### v0.60.1 (2026-10-19) — 独立审查修复：CI 门禁、原生调用协议、SSRF 前置校验、锁语义

独立审查（reviewer-round1）判定 Request Changes；以下为逐项修复。

#### 阻塞项

- **CI lint 真实通过**：`ruff check src/ tests/ --select F821,F811,E9` 此前有
  4 个 F811（全部在 `tests/`）。已修复，CI 同款命令现在 `All checks passed`。
  `evidence/B1-ci-gates.json` 已更正为此前只跑 `src/` 的错误证据。
- **CI 依赖可复现**：`dev` 额外依赖补 `ruff` 与 `pytest-cov`，干净环境可执行
  lint 与 `--cov`。

#### 原生工具调用协议

- 参数解析失败时补一条 `role=tool` 消息，避免 assistant 的 `tool_calls`
  留下悬空 id（否则下一轮 400）。
- 被 `max_repeat_calls` 过滤的调用同样补 `role=tool` 消息；id 与调用顺序
  一一对应（不再按签名映射，避免同名同参错配）。
- 同名同参的重复调用按**队列**分配 `tool_call_id`，不再复用同一 id。
- 流式路径启用开关时显式告警并回退文本协议，不再静默无效。

#### 安全

- Scrape 的三种后端改为**重定向前置校验**：httpx 手动逐跳、urllib 自定义
  `HTTPRedirectHandler`、Playwright `page.route` 拦截。
- `validate` 阶段不再做同步 DNS，避免阻塞事件循环；DNS 在真正抓取时校验。
- DNS rebinding TOCTOU 仍未消除，已在 evidence limitations 中披露。

#### 持久化与可观测性

- `file_lock` 改为可重入 + owner token + 原子回收陈旧锁；`update_state` /
  `add_progress_entry` / `cancel_mode` / `team_persistence` 的读改写整体加锁，
  修复丢失更新。
- 新增直接针对生产函数的并发回归：`ModeStateManager.update_state` 与
  `add_progress_entry`。
- `atomic_write` 的 Windows 重试提高到 8 次 / 50ms，并发测试连续 3 次稳定。
- tracing 的 `_setup_*` 返回 bool，跳过时不再谎报“已初始化”；`setup_tracing()`
  接入 `initialize()`，功能不再是无调用点的死代码。

#### 其他

- `SafeRedirectHandler` 提到模块级，安全测试直接测生产实现（不再复制逻辑）。
- `src.__version__` 改为 **pyproject.toml 优先**，避免 editable 元数据滞后
  导致不同解释器显示不同版本。
- `atomic_write` 的 Windows 重试提高到 8 次 / 50ms。

#### 验证

全量回归、E2E、SSRF/状态/原生调用回归见 `test_ledger.md` 与 `evidence/`。

---

### v0.60.0 (2026-10-19) — 参考对标落地：CI 门禁、持久化语义、工具策略、Skill 接线、原生工具调用

本轮基于 `参考的结果计划指南.md` 的 Phase A 审计，按 P0/P1 批次落地。

#### P0

- **CI 门禁修复**：移除无效的 `--fail-on-incremental`；lint 分为
  “硬错误阻塞（F821/F811/E9）+ 全量非阻塞报告”；覆盖率阈值按实测基线
  分阶段设为 45%（目标 60% 保留在 `pyproject.toml`）。
- **tracing 移植残留**：`src/core/tracing/setup.py` 不再绝对导入 `onyx.*`；
  Braintrust processor 未移植时明确告警并跳过；Langfuse 改用项目内
  `TraceProvider.register_processor`。`pyproject.toml` 新增 `tracing` 可选依赖。
- **能力可见性**：`clawd doctor` 新增 RAG / World Model / WebSocket 服务端
  的启用状态；RAG 默认关闭并提示 `CLAWD_ENABLE_RAG=1`。
- **Agent 错误路径**：修复 `publish_task_error()` 方法体内混入 `__init__`
  尾部赋值的问题。

#### P0-5 状态持久化语义

- 新增 `file_lock` / `locked_atomic_write_json`（跨平台目录锁 + 原子写）。
- `PipelineState` 写入增加 `schema_version` / `attempt` / `updated_at` /
  `working_path`；`save(expected_attempt=...)` 提供乐观并发检查，
  不匹配抛 `StaleStateError`；更高 schema 版本拒绝恢复。
- `mode_state` / `team_persistence` / `ralph_ledger` 的 JSON 写入统一为
  加锁原子写，避免并发丢写与半截文件。

#### P1

- **工具风险策略**：`BaseTool.risk_kind` 显式声明 read/write/exec；
  `classify_tool()` 优先使用声明，名称启发式仅作兜底。
  默认工具（Bash/FileEdit/FileRead/Glob/Grep/HotFiles/Scrape/UDiff/Clipboard 等）已声明。
- **Scrape SSRF 加固**：仅 http/https；默认拒绝 localhost/元数据域名/
  私网/回环/链路本地/保留地址；DNS 解析结果同样校验；重定向后二次校验；
  `CLAWD_SCRAPE_ALLOW_PRIVATE=1` 仅供本地测试。
- **Skill 渐进披露**：新增 `skill_loader` 与 `SkillTool`；系统提示注入
  name + description 清单，正文按需读取；默认工具池新增 `SkillTool`。
- **WebSocket 入口**：新增 `clawd server` 命令（host/port/token/developer-mode），
  未配置 `AGENT_SERVER_TOKEN` 时生成本次一次性令牌。
- **原生工具调用（可选）**：`LLMResponse` 支持 `tool_calls`；
  OpenAI 兼容 provider 解析原生调用；Agent 循环优先原生、回退文本；
  设置 `CLAWD_NATIVE_TOOLS=1` 启用，默认关闭。
- **测试收集**：`pyproject.toml` 禁用与本项目无关的 pytest 插件
  （langsmith/seleniumbase/faker/flask）。

#### 验证

见 `test_ledger.md` 与本轮 `evidence/`。未达成的指标（覆盖率 60%、
收集 <120s、死模块 ≤20）在 `workflow_status.md` 中如实披露。

---### v0.59.0 (2026-10-19) — 审查阻塞项：pipeline 阶段去占位、验证目录修正

独立审查（review-d）判定 REQUEST_CHANGES，两条阻塞项经复现后修复；
处理过程中又发现两个"从未能工作"的占位阶段。

#### 1. `ralplan` / `team-exec` 是占位实现（返回 `<未实现>` 却报 SUCCESS）

`pipeline.py` 的这两个阶段此前不调用任何引擎，直接返回占位字符串并把
阶段标成 SUCCESS —— 调用方会以为"计划已产出、worker 已执行"。

现接真实引擎：
- `RalplanStage` → `RalplanEngine.run()`，产物含 plan/prd/tasks/confidence；异常 → FAILED
- `TeamExecStage` → `SwarmEngine.run()`，产物含 execution_result/errors；
  swarm 失败 → FAILED

#### 2. `precontext-intake` 导入不存在的模块，永远"成功"地什么都没做

`from .intake import IntakeGate` —— `src/workflow/intake.py` **从未存在**。
异常被捕获后仍返回 SUCCESS。

现改为**真实的最小扫描**：统计目标目录的 `.py` 文件数/行数、给出最大的若干文件；
失败时返回 SKIPPED（而不是 SUCCESS）。

#### 3. `stages/ralph_verify_stage.py` 用错验证目录（审查阻塞项）

`Path(self._config.cwd)` 默认 `"."`，忽略了 `ctx.cwd` —— 若挂进管道，
会在**进程当前目录**跑测试，可能对另一个项目报 passed。
现改为 `Path(ctx.cwd)`，并把"失败后原样重试同一命令最多 10 次"改为**不重试**
（没有重新实现步骤，重试没有意义）。

#### 4. `search_replace` 修复补齐回归测试（审查阻塞项）

`try_strategy` 的策略级异常回退此前无任何测试（原有 28 个用例都不进入 git 策略）。
新增 `tests/tools_runtime/test_search_replace_strategy_fallback.py`：
- 普通异常 → 返回失败且 error 带异常类型（不再一律"未找到匹配"）
- `MemoryError` / `RecursionError` → 仍向上抛（资源级问题不得降级）
- 非 git 目录 → 回退矩阵不中断

#### 5. 其他审查项

- 非法 `CLAWD_VERIFY_COMMAND`（未闭合引号）此前会让 `ValueError` 穿透 →
  现返回 `status="error"`（模块承诺所有失败都有结构化状态）
- `pipeline.py` 工厂 docstring 声称"持久循环"但实现只跑一次 → 已更正，
  并在 artifacts 里记录 `max_iterations` 仅作配置保留
- `docs/MAINTENANCE.md` 仍写"验证阶段是桩""覆盖率 ~20%" → 已同步真实状态

#### 验证

```
pytest tests/workflow/test_pipeline_stage_factories.py      → 7 passed
pytest tests/workflow/test_verification_runner.py           → 15 passed
pytest tests/tools_runtime/test_search_replace_strategy_fallback.py → 7 passed
pytest tests/tools_runtime/test_udiff_parser.py             → 15 passed
真实 pipeline（ralph-verify）                                → SUCCESS, verified=True
```

---

### v0.58.0 (2026-10-18) — 验证阶段变为真实现；修正覆盖率口径

#### 1. 验证阶段不再只是"诚实"，而是**真的执行**

新增 `src/workflow/verification_runner.py`：

- 默认命令：若 `<cwd>/tests/` 存在 → `python -m pytest -q --tb=short tests`
- 可用 `CLAWD_VERIFY_COMMAND` 覆盖（Windows 引号/反斜杠已处理）
- **以退出码判定**，保留命令、耗时、输出尾部作为证据
- 状态语义：`passed` / `failed` / `timeout` / `error` / `not_configured`
- 未配置时返回 `not_configured`，**绝不冒充通过**

接线：
- `pipeline.py` 的 `ralph-verify`：passed→SUCCESS，failed/timeout/error→FAILED，
  not_configured→SKIPPED
- `stages/ralph_verify_stage.py`：`_verify_implementation` 接同一执行器；
  未通过时返回 `failed`（此前恒返回 `completed`），未配置时提前结束迭代

#### 2. 所有 pipeline 阶段真实执行时崩溃（P0）

4 个内嵌阶段类都用 `self._logger`，但基类 `PipelineStage` **没有该属性** ——
一旦真正执行，第一个阶段就 `AttributeError`。此前只测过注册与构造，
从未真正跑过阶段，所以一直没暴露。

修复：4 个阶段类补 `_logger = logger` 类属性。已用真实 pipeline 端到端验证。

#### 3. 两处编辑核心的真实缺陷（覆盖率工作发现）

| 位置 | 问题 | 后果 |
|:---|:---|:---|
| `udiff_parser._directly_apply_hunk` | 从 `search_replace` 导入 **不存在** 的 `SearchTextNotUnique`（该名字定义在本模块） | `apply_hunks` 的直接应用分支**永远 ImportError** |
| `search_replace.try_strategy` | 只捕获 `(ValueError, IndexError, OSError)`；`InvalidGitRepositoryError` 会穿透 | **非 git 目录下**多策略回退矩阵直接中断，编辑失败 |

修复后新增 `tests/tools_runtime/test_udiff_parser.py`（15 用例）。

#### 4. 覆盖率口径修正

此前文档长期写"覆盖率 ~20%"，来自 2026-10-15 的陈旧 `coverage.json`。
本轮用 `pytest --cov=src` 全量实测（48 分钟；补齐用例后全量为 3079 passed）：

```
覆盖率      46.15%（25,877 / 56,072 行，插桩运行时测得）
```

仍低于 `pyproject.toml` 的 `fail_under = 60`，但**不是 20%**。
README / workflow_status / 指南中的旧数字已更正。

同时修掉一个计时脆弱测试（`test_sleeper_sync_sleep` 在覆盖率插桩下
100ms 睡眠被拖到 1.6s）——保留"确实等待了"的下界，放宽上界。

#### 5. 部署验证边界

- **本地安装部署已验证**：`pip install -e . --no-deps --no-build-isolation`
  成功；`clawd.exe --version / agent keywords / catalog reload` 全部实跑通过。
- **容器部署未验证**：本机未安装 Docker，`docker compose build/up` 无法执行。
  已在 `docs/MAINTENANCE.md` 明确写清缺失条件与恢复验证步骤，不冒充已部署。
- 本项目是 CLI/库，无常驻服务进程；"线上热更新"没有可验证的落地路径。

#### 验证

```
pytest tests/tools_runtime/test_udiff_parser.py tests/test_search_replace.py   → 43 passed
pytest tests/workflow/test_verification_runner.py                              → 13 passed
pytest tests/core/utils/test_sleep.py                                          → 9 passed
真实 pipeline 端到端（ralph-verify，CLAWD_VERIFY_COMMAND 控制退出码）          → SUCCESS/verified=True
pip install -e . + clawd.exe --version/agent/catalog                          → 通过
```

---

### v0.57.3 (2026-10-18) — 审查补充项：`pipeline` 命令与若干静默失败

#### `clawd pipeline` 同样"注册成功但运行即崩"

原实现三处错位，实测第一条就抛 `TypeError`：

```python
PipelineConfig(use_team=..., use_ralph=..., budget=...)   # 三个参数都不存在
PipelineOrchestrator(Path.cwd(), config)                  # 参数顺序反了
await orchestrator.execute(goal)                          # 方法不存在
```

重写为真实 API（`create_ralplan_stage/create_team_exec_stage/create_ralph_verify_stage`
+ `create_autopilot_pipeline_config` + `PipelineOrchestrator(config, cwd)`），
并新增 wiring 测试。`--budget` 在编排器上未实现，命令**明确提示不生效**而不是静默忽略。

#### 锁文件损坏不再静默覆盖

`LockStore.acquire()` 解析锁文件失败时 `except Exception: pass`，随后直接覆盖写 ——
两个 owner 可能同时认为自己持锁，正是锁要防的事。
现改为：`logger.error` + 把损坏文件隔离为 `*.corrupt-<ts>` 再重建（可见且不deadlock）。
`release()` 失败也不再静默吞掉。

#### 其他

- `HookPluginDispatchResult.duration_ms` 声明了两次（后者把必填字段静默改成可选）→ 去重。
- `sanitize_plugin_id()` 用 `str.replace(r"...")` 做"正则清洗"，实际是字面量替换，
  完全不生效 → 改为 `re.sub`。实测 `My Plugin!@#.py` → `my-plugin`。
- `memory_server.search()` 读到损坏 JSON 时静默跳过 → 增加 `logger.warning`（带路径）。

#### 验证

```
pytest tests/cli tests/workflow tests/core -q  → 1081 passed
ruff --select F821,F811                       → All checks passed
python -m src pipeline --help                 → 正常
python -m src catalog list / reload           → 正常
```

---

### v0.57.2 (2026-10-18) — 独立审查发现的 5 个阻塞项

v0.57.0/0.57.1 的独立审查线程回传了结论（REQUEST_CHANGES）。以下问题
**全部经复现确认**，均已修复。

#### 1. `workflow` 组四个命令"注册成功但运行即崩"

`--help` 能显示只说明 Typer 注册成功，**函数体**引用的是不存在的符号：

| 命令 | 原引用 | 真实 API |
|:---|:---|:---|
| `ralph` | `SwarmOrchestrator.execute_task()`、`RalphLedger` | `SwarmEngine.run()`、`RalphProgressLedger` |
| `team` | `SwarmOrchestrator.coordinate_task()` | `SwarmEngine.run()` |
| `ralplan` | `RalplanWorkflow.execute()` | `RalplanEngine.run()` |
| `autopilot` | `from .workflow_commands import create_autopilot_pipeline_config`（**从自身模块导入从未定义的名字**） | `workflow.pipeline_orchestrator.create_autopilot_pipeline_config` |

四个命令体全部重写为真实 API。`ralph` 的 `--verify` 不再假装"已验证通过"——
本项目的验证阶段仍是桩，命令会明确打印这一点。

新增 `tests/cli/test_workflow_commands_wiring.py`（4 用例）：
用替身驱动命令体，断言"不抛 ImportError/AttributeError、退出码正确、产物落盘"。

#### 2. `explore` 的只读引擎构建必然失败

原实现导入 `src.tools_runtime.tool_manager.create_readonly_tool_manager`
—— 模块与函数**都不存在**；且 `AgentEngine.__init__` 根本不接受 `tool_manager`
（内部自建）。改为：构造期间临时注入 `APPROVAL_MODE=plan`（真实只读门禁，
PLAN 会拒绝一切 write/exec），构造后还原；门禁未生效时显式告警。

#### 3. `catalog list/reload` 运行即崩

- `src/catalog/manifest.py:111` 给 `SkillDefinition` 传了不存在的
  `internal_required=True` → `TypeError`，`get_catalog()` 整体失败。
- `catalog_commands` 调用 `CatalogManifest.get_counts()`，该方法从未存在
  → `AttributeError`。

修复：去掉多余参数（状态已是 `INTERNAL`）；补齐 `CatalogCounts` +
`get_counts()`。实测 `catalog list` 正常、`catalog reload` 输出
"技能数 39（活跃 23）/ Agent 数 30（活跃 18）"。

#### 4. 断点续跑从未生效（三处叠加）

1. `run()` 先 `start_mode()`（写 index=0）再 `can_resume()` → 永远读到 0。
2. `_complete_pipeline("failed")` 写 `active=False` + phase `"failed"`，
   而 `can_resume()` 排除 `"failed"` → 失败后永不可恢复。
3. 失败阶段写 `index=i+1` → 恢复会跳过失败阶段。

修复：先读状态再初始化；失败时 `active=True`、phase=`stage:<name>:failed`；
失败阶段保持 `index=i`（重试该阶段）。恢复测试实测：
`calls s1=1, s2=2, s3=1`（s1 不重跑、s2 重试）。

#### 5. `PipelineState` 往返丢字段

`save` 写 `pipeline_stages` 但 `load` 不读回 → `load→save` 后 `can_resume`
由 True 变 False；`artifacts` 则两边都不处理。已补：
`stage_names`、`artifacts` 双向持久化；artifacts 做 JSON 归一化
（阶段把 `ctx.cwd` 放进 artifacts 时不再让整份状态写入失败）。

#### 同时修复（审查的非阻塞项）

- **`BudgetGuard` 跨轮状态泄漏**：复用实例后，第二次 `run()` 继承上轮
  `accumulated_cost/is_exhausted/start_time`。新增 `reset_for_run()` 并在
  `run()` 中调用（保留 config 与注入的替身）。附回归测试。
- `_resolved_dimensions` 在本次未配置维度时未清空 → 同一 engine 二次运行沿用旧维度。
- `create_pipeline(cwd=...)` 只影响阶段、不影响状态目录 → 对齐。
- `memory_server` 模块 docstring 与 MCP 工具描述仍称"语义搜索"，
  实际是子串匹配（score 恒 1.0）→ 如实改为关键词检索。
- `types.py` 去重后残留 4 个孤立 `@dataclass` 装饰器 → 清理。
- 测试文件未使用的 import → 清理。

#### 验证

```
pytest tests/ -q --tb=no                                → 3051 passed / 0 failed
pytest tests/cli tests/workflow tests/core -q           → 1080 passed
pytest tests/workflow/test_pipeline_orchestrator.py -q  → 30 passed
pytest tests/cli/test_workflow_commands_wiring.py -q    → 4 passed
ruff --select F821,F811                                 → All checks passed
scripts/import_sweep.py                                 → 0 缺陷（639 模块）
scripts/reachability.py                                 → 429（与基线一致）
python -m src catalog list / reload                     → 正常（39 技能 / 30 Agent）
python -m src agent keywords                            → 11 个关键词
scripts/verify_html_report.py                           → 10 题全部通过（真实浏览器）
```

---

### v0.57.1 (2026-10-18) — 启动耗时与循环导入

v0.57.0 发布后继续追查可用性时发现的两个问题。

#### 启动耗时：消除导入期重依赖

`litellm` 实测**导入本身约 34 秒**（连带 openai / httpx / pydantic 的大量子模块）。
它原本在 `src/llm/litellm_singleton/__init__.py` 顶层导入，而导入链是：

```
src.main → src.cli_handlers → src.workflow.cli_handler → src.workflow
  → src.workflow.experience_bank → src.core.experience_bank
  → src.memory.enterprise_ltm → src.llm.litellm_singleton → litellm
```

结果是 **`clawd --version` 也要先等几十秒**。四处改为惰性：

| 文件 | 改法 |
|:---|:---|
| `src/llm/litellm_singleton/__init__.py` | 顶层不 import litellm；PEP 562 `__getattr__` 保留 `from ... import completion` 兼容 |
| `src/__init__.py` | `CostEstimator` / `Event` / `ClawdError` 等改为按需导入；`__version__` 仍即时 |
| `src/agent/__init__.py` | 整个 Agent 栈改为按需导入 |
| `src/main.py` | `cli_handlers` 与 `cost_estimator` 移入实际使用点 |

实测（本机，数字受磁盘/杀软波动影响）：

```
import src             6.8s → 1.6s
import src.main       50.9s → ~8s
```

> `import src.cli.entrypoint` 仍有 ~20s：剩余成本来自
> `src.workflow`（experience_bank → llm）与 `src.core.__init__` 的急切再导出。
> 继续优化需要把 `src/core/__init__.py`（约 60 个再导出）与
> `src/llm/__init__.py` 一并惰性化 —— 属独立工程，不在本轮硬做。

#### 顺带修复：一个被掩盖的循环导入（P0）

`src/__init__` 惰性化后暴露：

```
src.utils.__init__ → diff_utils → src.core.patch.diff_engine
  → src.core.__init__ → args_parser → from ..utils import get_logger
  → ImportError: partially initialized module 'src.utils'
```

此前它被 `src/__init__` 的急切导入顺序掩盖。受影响的是**以
`from src.utils import ...` 作为进程第一个导入**的任何调用方
（包括 `CodeGraph.build` 的 `ProcessPoolExecutor` 子进程 ——
实测会抛 `BrokenProcessPool`）。

修复（两步，缺一不可）：

1. **在 `src/utils/__init__.py` 中提前绑定 `get_logger`**（只绑这一个名字，
   放在 `from . import deprecated_args, diff_utils, ...` 之前），破掉环。
   **不能**把整行 `from .logger import ... debug ...` 提前 ——
   随后导入 `.debug` 子模块会把包属性 `utils.debug` 覆盖成**模块对象**，
   调用时报 `TypeError: 'module' object is not callable`（第一版修复踩了这个坑，
   全量测试 56 红）。完整导出仍保留在 `.debug` 之后。
2. `src/core/args_parser.py` / `evolution.py` / `memory_guard.py`
   改为直接从 `..utils.logger` 导入，减少对包级 `__init__` 的依赖。

配套更新 `tests/test_main.py` 的 patch 目标：
`src.main.get_command_handler` → `src.cli_handlers.get_command_handler`，
`src.main.log_pricing_check` → `src.core.cost_estimator.cost_estimator.log_pricing_check`
（实现已改为在函数内导入，patch 必须指向**提供者模块**）。

---

### v0.57.0 (2026-10-17) — 静态缺陷清零、重复定义收敛、测试基线转绿

本轮把《下一步改进指南》里 v0.51 段的硬指标真正跑通，并修掉了一批
"只有跑测试才会暴露"的真实缺陷。

#### 硬指标（验收命令实跑）

| 指标 | 之前 | 现在 |
|:---|:---|:---|
| `ruff --select F821`（未定义名称） | **40 errors** | **All checks passed** |
| `ruff --select F811`（重复定义） | **19 errors** | **All checks passed** |
| 全库导入扫描 | 16 个模块导入即崩 | **0 个** |
| 全量测试 | 2999 passed / **31 failed** | **3033 passed / 0 failed** |
| 契约测试 | 39 passed | 39 passed |

#### 40 个未定义名称：多数是真实运行期 NameError

不是"注解写错"那么简单。逐类说明：

| 位置 | 问题 | 后果 |
|:---|:---|:---|
| `cli/commands/workflow_commands.py:328` | `Progress/SpinnerColumn/TextColumn` 未导入 | `clawd workflow autopilot` 运行即崩 |
| `cli/commands/catalog_commands.py:99` | `catalog` 未定义（应为 `new_catalog`） | `catalog reload` 崩 |
| `cli/config_enhancer.py:80` | `toil` 拼写错误 | 工具探测永远为假 |
| `core/quality_gate.py:314` | `console` 未定义 | 质量门 CLI 崩 |
| `utils/truncation.py:49` | `estimate_tokens` 未导入 | 大输出截断路径崩 |
| `tools_runtime/sandbox/docker.py:154` | `subprocess` 未导入 | Docker 沙箱关闭时崩 |
| `workflow/team/state/dispatch_lock.py:136` | `ClawdError/ErrorCode` 未导入 | 分发锁失败路径崩 |
| 其余（`Any` / `Path` / `ClassVar` / `Dict` / `Optional` / `T` / `Literal`） | 注解符号未导入 | 静态检查失败，`get_type_hints` 崩 |

`autoresearch` 的 `"a" | "b"` 写法一并改为 `Literal[...]`（字符串按位或，导入即 TypeError）。

#### 19 个重复定义：删除前一份，保留运行时生效的后一份

- `src/core/exceptions.py`：13 个异常类**逐字重复**（AST 比对确认 IDENTICAL），删除整段 150 行
- `src/hooks/extensibility/types.py`：4 个 dataclass 完全重复
- `src/templates/manifest.py`：`TemplateLoader` 重复
- `src/core/config/settings.py`：`load_settings` 先导入后被包装函数覆盖（有意为之，改为别名导入）
- `src/runtime/engine.py`：`derive_readiness` 重复定义
- `src/hooks/extensibility/loader.py`：`HookPluginDescriptor` 与 `types.py` 各定义一份
  —— **两个同名类，`isinstance` 互不为真**。统一到 `types`。

#### 四个"测试从未通过"背后的真实缺陷

`tests/workflow/test_pipeline_orchestrator.py` 从初始提交起就没绿过
（引用 `StageStatus.COMPLETED`、`PipelineConfig(state_file=...)` 等不存在的 API）。
追查后发现实现侧确实有 5 个真问题：

1. **`ReadinessSnapshot.ready` 字段被同名 classmethod 覆盖**
   实测 `ReadinessSnapshot().ready` 是 `<bound method>`，`if snap.ready:` 恒为真，
   `RuntimeSnapshot.ready()` 恒返回真。→ classmethod 改名 `all_ready()`。
2. **`_deserialize_result` 不把 status 字符串还原成枚举**
   恢复出来的失败阶段 `== StageStatus.FAILED` 恒为 False，断点续跑会当成正常。
   同时丢失 `skipped_reason`。
3. **`_deserialize_event` 遍历 dataclass 字段字典用 `f.name`**
   `'str' object has no attribute 'name'` —— 持久化恢复必崩。
4. **`PipelineState.save(state_file)` 完全忽略参数**
   调用方传入路径后文件不会出现在那里。`can_resume()` 也因阶段列表永远存空而恒为 False。
5. **`PipelineConfig.cwd` 从未生效**；`create_pipeline()` 不接受裸函数；
   `stage.can_skip` 未做存在性判断。

另有两个：
6. **`BudgetGuard` 在 `run()` 里被整个替换** → 外部注入的预算策略被静默丢弃。
7. **`spawn_platform_command_sync(spawn_fn=subprocess.run)` 是定义时绑定**
   → 全局 monkeypatch 无效，测试实际启动了真实子进程。

#### 工程基建

新增 `scripts/import_sweep.py`：逐个 import 全部模块，区分「项目内代码缺陷」
与「第三方依赖缺失」，补上 `reachability.py` 的盲区（**可达 ≠ 可导入**）。

新增 `scripts/verify_html_report.py`：用真实浏览器验证交付的报告与测验
（答对全部 → 判定通过；错一题 → 判定未通过；选项标色正确）。

#### CLI 调用闭环

| 问题 | 后果 | 修复 |
|:---|:---|:---|
| 顶层命令 `workflow` 与同名**命令组**共存 | 组遮蔽命令，`clawd workflow "目标"` 把目标当子命令解析，永远跑不到 5 阶段引擎 | 顶层命令改名 **`run`** |
| 命令组注册**不幂等**（模块导入 + `main()` 各注册一次） | `registered_groups` 出现重复项（实测 8 项 / 4 个名字） | 加 `_REGISTERED_GROUPS` 护栏 |
| `python -m src.main` 与 `clawd` 是**两套不同 CLI** | 同一个 `workflow` 在两个入口下语义不同 | 新增 `src/__main__.py`，`python -m src` 与 `clawd` 完全一致；`src.main` 标记为历史入口 |
| README 有两条**不存在的命令**示例（`workflow run --goal`、`budget status`） | 用户照抄即失败 | 改为实跑验证过的命令，并逐条验证 |

#### `--dimension/-d` 断链

CLI 一直支持 `-d creative --dimension adversarial`，实现是
`set_config("dimensions", [...])`。但**全仓库没有任何代码读取这个键** ——
参数被接受、被存储、然后被遗忘。

现在：`WorkflowEngine.run()` 解析运行时配置 → 生成维度引导文本 →
注入 `HealableExecutor` 的提示词（Swarm 与常规策略两条路径），
并挂到 `WorkflowTask.dimensions` 随状态持久化。

顺带确认：`src/workflow/dimensions.py`（英文内置库）**生产不可达**，
真正有效的是 `src/core/config/dimensions.py`（中文内置库）。接线使用后者。

#### RAG 增量扫描性能

`UnifiedScanner.scan_directory` 原对**每个**文件都 `run_in_executor`。
增量扫描时 1000 个文件全部缓存命中，但 1000 次线程池调度 + 1000 个 coroutine
的开销远大于工作本身：

```
全量扫描        13.20s
纯串行缓存命中   0.73s
原增量扫描       2.20s   ← 比串行还慢
```

改为"缓存命中走同步快路径，只把未命中交给线程池"，
增量扫描降到 ~0.7s，`tests/performance/test_rag_pressure.py` 转绿。

#### 文档清理

删除 16 个来自早期 AI 会话的陈旧报告（`FINAL_SUMMARY.md`、`INTEGRATION_*.md`、
`QUICK_REFERENCE.md` 等）。它们互相引用、互称"已完成"，但与仓库真实状态不符
（例如声称覆盖率 ~50%，实测 ~20%）。git 历史仍可追溯。

仓库根目录现在只保留：
`README.md` / `CHANGELOG.md` / `CONTRIBUTING.md` / `ARCHITECTURE.md` /
`AGENTS.md` / `CLAUDE.md` / `workflow_status.md`。

#### 验证

| 命令 | 结果 |
|:---|:---|
| `pytest tests/ -q` | **3035 passed / 0 failed** |
| `pytest tests/contracts -q` | 39 passed |
| `ruff check src/ --select F821` | All checks passed |
| `ruff check src/ --select F811` | All checks passed |
| `python scripts/import_sweep.py` | 0 缺陷（638 模块） |
| `python scripts/reachability.py` | 429 生产可达（未变） |
| `python -m src --version` | `Clawd Code v0.57.0` |
| `python scripts/e2e_production.py` | 8/8 |
| `python scripts/verify_html_report.py` | 6 项断言全过（真实浏览器） |

---

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

# 🚀 Clawd Code：AI 编程代理框架

> **"让 AI 像交响乐团一样协作，让编程像呼吸一样自然。"**

**当前版本**: v0.66.0 | **测试**: 见 `test_ledger.md` 与 `scripts/e2e_smoke.py` | **覆盖率**: 见 `coverage.json`（由 `pytest --cov=src` 生成） | **质量工具**: ruff, mypy, pytest-cov | **CI/CD**: GitHub Actions

> 版本号以 `pyproject.toml` 为唯一真相源，`src.__version__` 自动读取，不再手工维护。
> 具体数字请以命令输出为准，避免文档与代码漂移。

---

## 🖥️ Clawd Desktop（桌面端，v0.61.0 新增）

DSH 式桌面客户端，**双击即用**：

| 形态 | 获取 |
|------|------|
| NSIS 安装程序（带自动更新） | [GitHub Release](https://github.com/lza6/claw-code-tingfeng/releases/tag/v0.61.0) → `Clawd Desktop Setup 0.1.0.exe` |
| Portable 免安装 | 同 Release → `ClawdDesktop-Portable-0.1.0.exe` |
| 开发模式 | `cd desktop && npm run dev` |

- **DSH 设计规范 UI**：三阶深灰 + 品牌蓝，侧栏工作台、插件市场（毛玻璃弹窗）、工具调用实时折叠行
- **架构**：Electron 壳（窗口/托盘/单实例/崩溃自愈）→ spawn Python Host（`clawd serve`）→ WS 同端口托管 Web UI；壳内不造 IPC
- **插件市场**：`.clawd/plugins/*/pyproject.toml` 的插件会真实出现在市场（Host 只发现 manifest 不执行代码）；
  内置能力包（逆向工具集/安全工具目录/MCP 桥接/推理模式）一并展示；支持搜索与状态标注
- **设置面板**：实时显示版本 / Python / 工作目录 / API Key 状态（**不回显密钥**），
  可改 provider / model / base_url 与 RAG、原生 function-calling 开关；保存写入 `.clawd/ui_settings.json`，
  同时写入运行期配置（引擎立即生效，provider/model/base_url 需重启 Host）
- **版本与更新**：侧栏显示真实版本（单一来源 `pyproject.toml`，桌面壳 `package.json` 与之同步）；
  「检查更新」经 preload IPC 桥把状态回传 UI（检查中 / 下载中 / 已最新 / 就绪 / 出错 / 不支持）
- **自动更新**：仅安装版支持（portable 版明确提示不支持）。更新源默认是占位地址，
  必须用环境变量 `CLAWD_UPDATE_URL`（或改 `desktop/package.json` 的 `build.publish`）指向真实发布源，
  否则 UI 会明确告知"更新源未配置"，不静默失败
- **首次启动**：图形化引导配置 LLM API（OpenAI 兼容），配置存本机 userData
- 详见 `docs/ENHANCEMENT_GUIDE.md`（使用/排障）与 `docs/RELEASE_UPDATES.md`（发布/更新）

> **桌面端 E2E**（真实浏览器 + 真实 Electron + 真实更新源，非桩）：
> - `cd desktop && node ui_settings_e2e.mjs` — 浏览器驱动 UI，17 项（设置/市场/版本/搜索）
> - `node electron_bridge_e2e.mjs` — 真实 Electron 壳，10 项（preload 桥/版本一致性/各面板）
> - `node update_feed_e2e.mjs` — 真实 electron-updater 拉本地 feed，4 项（feed 请求/版本识别/状态上报/URL 覆盖）
>
> 更新链路已验证到「请求 feed → 识别新版本 → 开始下载」；**静默安装**需要真实发布环境与已签名安装包，见 `docs/RELEASE_UPDATES.md`。

## ⚡ 超级智能体能力（v0.61.0 新增）

| 能力 | 入口 | 说明 |
|------|------|------|
| 推理模式 | `clawd reason reflexion\|plan-execute\|lats\|debate "任务"` | 四种反推循环：反思修正/计划重排/假设树/对抗审查 |
| MCP 桥接 | `.clawd/mcp_servers.json` + `ToolGovernor().approve()` | 外部 MCP server 工具自动进 Agent 工具池；签名+检疫审批防投毒 |
| 逆向工具 | Agent 内直接调用 | Ghidra HTTP 桥、strings/熵/hexdump、objdump/binwalk 等 8 个 |
| 安全工具 | `SafeCatalogRunner` | YAML 目录 + scope 授权门禁 + 注入拦截（仅限授权测试目标） |
| 逆向知识库 | `skills/reverse/` | 51 个场景 SKILL.md（固件/Ghidra/IDA/恶意软件/协议/pwn/CTF） |
| 插件开发 | `.agent/skills/clawd-extension-sop.md` | 四件套 SOP（manifest/DI/接入面/CLI） |

## 🧩 多引擎整合（v0.64.0 新增）

**不合并源码**（Rust/Go/TS 三套运行时合并必崩），而是**统一驱动 + MCP 领域工具反向供给**：

```bash
clawd engines                 # 多引擎总览（真实探活，不含水分）
clawd engines --json          # 机器可读
clawd engines --run "任务"     # 用首个可用引擎执行
```

| 项 | 真实性质 | 本机实测 |
|---|---|---|
| Codex | Agent CLI（Rust 内核，Apache-2.0） | ✅ ready 0.165.0 |
| OpenCode | Agent CLI（Go） | ✅ ready 1.19.5（凭据需自行登录） |
| OpenClaw | Agent CLI（TS） | ⚠️ incompatible（Node 版本区间不符） |
| Grok | **模型代理**，不是引擎 | 归属 provider 层 |
| Pi | **插件/上下文原语包**，不是引擎 | 归属能力层 |
| Hermes | 参考库无源码 | 未集成 |

**领域能力分两条路（v0.64.1 起）**：

| 调用方 | 路径 | 说明 |
|---|---|---|
| 我们自己的 agent | **原生工具**（`WorldModelTool` / `ProjectMapTool`） | 零进程、零序列化、共享进程内缓存；索引后台自动预热 |
| 外部引擎（Codex/OpenCode…） | **MCP**（`src/mcp/domain_server.py`） | 跨进程只能走协议 |

> 世界模型索引在引擎启动时**自动后台预热**（非阻塞，实测启动开销 0.00s）。
> 大仓库（源文件 >300）默认跳过全量索引并如实告知原因，用 `CLAWD_WM_FORCE=1` /
> `CLAWD_WM_MAX_FILES=<n>` 覆盖；轻量替代始终可用（`ProjectMapTool` / 原生 grep）。

**让我们自己的工具长进别人的内核里**（`src/mcp/domain_server.py`）：

```bash
# 任何支持 MCP 的引擎都能挂载（Codex 示例已内置于适配层）
python -m src.mcp.domain_server --root .
```

暴露工具：`clawd_read_file`（只读+越界防护）、`clawd_grep`（rg 优先）、
`clawd_project_map`（代码库符号地图）、`clawd_tool_list`（发现我们的领域工具）。

> 实测：Codex 已能发现并调用这些工具
> （`mcp_tool_call {"server":"clawd","tool":"clawd_grep"}`）；完整多轮循环受网关
> Responses 续传能力限制，见 `docs/adr/0010-multi-engine-integration.md`。

## 🔌 外部内核后端：Codex（v0.63.0 新增）

不自研重复造轮子——把成熟 agent 内核当后端接进来，我们只做适配与管控：

```bash
# 安装官方 Codex（Rust 内核，Apache-2.0）
npm i -g @openai/codex

# 用 Codex 内核执行任务（沙箱 + 事件流 + 用量统计）
clawd codex "读取 readme.txt 并只回复文件里那个单词" --cd . --sandbox workspace-write
clawd codex "只回复 PONG" --json          # 输出归一化 JSON（events/commands/usage/errors）
```

- **协议适配而非 fork**：走 `codex exec --json` 的 JSONL 事件流，Codex 升级无需改我们代码
- **进程管控**：硬超时 + `taskkill /T /F` 进程树强杀，避免残留进程累积
- **稳定性实测**：`scripts/soak_backend.py --iters 40` → RSS 平稳、句柄/线程无增长、残留子进程 0
- **端点要求**：Codex 0.165 只支持 `responses` wire API（我们自有网关已支持）；
  自定义端点在适配层注册为 `<provider>-custom`（Codex 禁止覆盖内置 provider）
- 决策与边界见 `docs/adr/0009-adopt-codex-as-backend.md`

## 🧪 Agent 评测与回归（v0.62.0 新增）

默认 **replay 模式**（零成本、确定性）：用数据集里录制的输出做断言，可直接放进 CI 做 agent 行为回归。

```bash
# 跑示例数据集（3 用例，四类断言）
python -m src eval src/eval/datasets/smoke.json

# 与基线比对（pass_rate 下降或用例由通过转失败 → exit 1）
python -m src eval my_dataset.json --baseline .clawd/eval_baseline.json

# 把当前结果存为新基线
python -m src eval my_dataset.json --save --baseline .clawd/eval_baseline.json
```

断言类型：`equals` / `contains` / `not_contains` / `regex` / `tool_sequence`（工具调用序列完全一致）。

数据集格式：
```json
{"version": 1, "cases": [
  {"id": "c1", "input": "读取 config.yaml 并改 timeout",
   "expect": {"tool_sequence": ["read_file", "edit_file"], "contains": ["timeout"]},
   "recorded": {"output": "已改为 30", "tools": ["read_file", "edit_file"]}}
]}
```

> **付费红线**：真实调用需 `--live` + 环境变量 `CLAWD_EVAL_ALLOW_PAID=1` 双闸，否则直接拒绝（exit 2）。
> 默认路径不发起任何 LLM 调用。

---

## 📋 目录

- [核心功能](#-核心功能)
- [快速开始](#-快速开始)
- [Aider 风格命令](#-aider-风格命令)
- [Swarm 角色定义](#-swarm-角色定义)
- [世界模型 (World Model)](#-世界模型-world-model)
- [GoalX 增强特性](#-goalx-增强特性)
- [架构概览](#-架构概览)
- [API 参考](#-api-参考)
- [部署指南](#-部署指南)
- [测试与质量](#-测试与质量)

---

## 🧠 核心功能

### 1. Swarm 多代理协作
将复杂任务分解，由专业 Agent 协同处理：
- **Orchestrator**: 意图路由与任务分发。
- **Worker (Coder/Architect)**: 专注代码实现与架构设计。
- **Auditor**: 基于五轴标准的严苛代码审计。
- **Integrator**: 跨分支/工作树的结果集成。

### 2. 世界模型 (World Model)
代码库全景感知，集成了 Aider 风格的 RepoMap 与 Tree-sitter 语法解析，提供语义级的上下文注入。

### 3. 预算守卫 (Budget Guard)
业内领先的资源安全监控，实时追踪 CPU、内存(RSS)、PSI 压力及 API Token 消耗，支持动态熔断。

### 4. 隔离执行 (Isolation)
基于 Git Worktree 的物理隔离运行环境，支持多任务并行开发而互不干扰。

### 5. 智能意图路由系统
借鉴 oh-my-codex 的五意图分类与关键词检测机制：
- **意图分类**: 自动识别 DELIVER/EXPLORE/EVOLVE/IMPLEMENT/DEBATE 五种任务类型
- **关键词注册表**: 40+ 技能关键词（`$ralph`, `$team`, `$pipeline` 等）触发专用工作流
- **执行门控**: ralplan-first Gate 确保重度编排任务经过规划审批
- **任务规模检测**: small/medium/large/heavy 四级分类 + Agent 智能推荐
- **Well-Specified 检测**: 15+ 正则模式验证提示完整性，避免模糊指令

---

## 🚀 快速开始

### 环境要求
- Python 3.10+
- Git 2.30+
- OpenAI, Anthropic 或 OpenRouter API Key

### 一键启动
```bash
# 安装依赖
pip install -e .

# 运行 REPL / Chat 模式（推荐入口，与安装后的 `clawd` 完全一致）
python -m src chat
# 或
clawd chat

# 运行一键诊断
python -m src doctor

# 启动 WebSocket 服务端（远程会话；未配置令牌时会生成本次一次性令牌）
python -m src server --port 8765
```

### 可选能力开关

| 环境变量 | 默认 | 作用 |
|:---|:---|:---|
| `CLAWD_ENABLE_RAG` | 关闭 | 为工作目录建立惰性文本索引，首轮注入相关上下文；`doctor` 会显示状态 |
| `CLAWD_NATIVE_TOOLS` | 关闭 | 使用 OpenAI 兼容原生 function calling；关闭时走 `<tool>{json}</tool>` 文本协议 |
| `CLAWD_SCRAPE_ALLOW_PRIVATE` | 关闭 | 仅本地测试用：放开 ScrapeTool 的私网限制（生产禁止） |

> **关于入口**：`python -m src` 与 `clawd` 是**同一个 Typer CLI**。
> 历史上还存在一个 argparse 入口 `python -m src.main`，它的命令集更小、
> 且 `workflow` 语义不同。该入口保留用于兼容，但**不再推荐**。


---

## ⌨️ Aider 风格命令

Clawd Code 集成了强大的 Aider 风格命令系统，方便您在 REPL 中高效操作：
- **文件操作**: `/add`, `/drop`, `/read`, `/edit`
- **代码执行**: `/run`, `/test`, `/lint`, `/shell`
- **Git 管理**: `/diff`, `/commit`, `/undo`
- **高级功能**: `/tokens`, `/model`, `/browse`, `/thinking`

详细手册请参阅 [Aider 命令手册](./docs/aider_commands.md)。

## 🤖 Swarm 角色定义

系统通过多代理协作完成复杂工程任务，支持核心角色与动态合成：
- **Orchestrator/Planner**: 负责任务编排与路径规划。
- **Worker/Auditor/Reviewer**: 负责编码、严苛审计与架构审查。
- **Diagnostician**: 负责深度故障根因分析。
- **Synthesized**: **v0.50.0 新增**，支持根据上下文动态合成特定专家。

角色详情与自定义指南请参阅 [Swarm 协作指南](./docs/swarm_roles.md)。

## 🧠 世界模型 (World Model)

代码库的"意识"层，提供精准的上下文感知：
- **模式检测**: 自动识别 Singleton, Factory, Observer 等设计模式。
- **依赖预测**: 基于代码图谱预测受影响的文件。
- **语义索引**: 基于 Trigram 的语义级检索。

技术细节请参阅 [世界模型说明](./docs/world_model.md)。

---

## 🛡️ GoalX 增强特性

Clawd Code v0.50.0 深度集成了 **GoalX** 的持久化认知能力：

- **持久化认知表面 (Durable Surfaces)**: 维护 9 个规范化 JSON 表面（Charter, Objective, Evidence 等），确保任务执行过程可追踪、可审计、可恢复。
- **意图路由 (Intent Routing)**: 自动识别 5 种意图类型（DELIVER, EXPLORE, EVOLVE, IMPLEMENT, DEBATE），结合关键词注册表实现技能自动激活和最优路径选择。
- **关键词检测系统**: 40+ 技能关键词（`$ralph`, `$team`, `$pipeline`, `$deep-interview` 等）+ 执行门控（ralplan-first Gate）+ well-specified 信号检测。
- **任务规模检测**: small/medium/large/heavy 四级自动分类 + Agent 推荐，避免过度编排小任务。
- **辩论模式 (Debate Mode)**: 支持多模型对同一问题进行证据驱动的辩论，通过交叉验证确保输出质量。
- **内存种子与晋升 (Memory Seed & Promote)**: 从项目启动内存到长期经验存储的自动转化机制。

---

## 🏗️ 架构概览

详细架构说明请参考 [ARCHITECTURE.md](./ARCHITECTURE.md)。

```text
┌─────────────────────────────────────────────────────────┐
│                     用户交互层 (CLI/TUI)                  │
├─────────────────────────────────────────────────────────┤
│  Intent Routing  │  Worktree Manager  │  Budget Guard     │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                     核心引擎层                             │
├─────────────────────────────────────────────────────────┤
│  SwarmEngine  │  WorldModel (RAG)  │  Self-Healing       │
└─────────────────────────────────────────────────────────┘
        │                    │                    │
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│   Agent 表面  │  │   认知存储     │  │   工具运行时   │
├───────────────┤  ├───────────────┤  ├───────────────┤
│ Charter       │  │ EnterpriseLTM │  │ Bash/Git      │
│ Objective     │  │ Trigram Index │  │ Patch Engine  │
│ Evidence      │  │ RepoMap (AST) │  │ Sandbox       │
└───────────────┘  └───────────────┘  └───────────────┘
```

---

## 📚 API 参考

### 运行工作流

```bash
# 5 阶段工作流引擎（识别 → 规划 → 执行 → 审查 → 发现）
python -m src run "重构认证模块" --intent evolve --budget 5usd

# 管道式命令组：ralph / ralplan / team / autopilot
python -m src workflow autopilot "实现用户登录"
python -m src workflow ralph "修复所有 lint 问题"
```

### 查看成本

```bash
# 注：Typer CLI 没有独立的 budget 子命令；预算通过 --budget 传入 run/workflow。
python -m src run "分析依赖" --budget 10usd
```

---

## 🧪 测试与质量

### 运行测试
```bash
make test           # 运行全量 pytest
make coverage       # 生成覆盖率报告

# 真实端到端冒烟测试（需要 .env 中配置可用的 LLM 端点）
python scripts/e2e_smoke.py
```

### 工作流真实验证（v0.58.0）

`ralph-verify` 阶段现在会**真正执行一条验证命令并以退出码判定**：

```bash
# 自定义验证命令（优先级最高）
export CLAWD_VERIFY_COMMAND="python -m pytest tests/ -q"

# 未设置时：工作目录有 tests/ → 自动跑 pytest；两者都没有 → 标记 skipped（未验证）
```

状态语义：`passed` → 阶段成功；`failed/timeout/error` → 阶段失败（管道停止）；
`not_configured` → 阶段 skipped，**绝不冒充通过**。

### 真实 E2E 冒烟测试

`scripts/e2e_smoke.py` 用**项目自身的 LLM 栈**（而非裸 SDK）打真实端点，
覆盖五步：读取配置 → 应用可导入 → 真实对话 → 工具调用 → 推理内容解析。
退出码 0 表示全部通过。

它存在的理由：静态检查（`ruff` 的 `F821` 只看名称、不查属性）发现不了
「属性名漂移」类缺陷。v0.51.0 修复的 11 个阻塞问题中，有 5 个只有在把
真实请求完整打通时才会逐层暴露。

### 质量基线（2026-10-23 实测）

| 指标 | 当前 | 说明 |
|:---|:---|:---|
| 测试用例 | **3254 passed / 0 failed / 5 skipped / 2 xfailed**（单进程一次跑完 639.98s） | `py -3.10 -m pytest tests/ -q` |
| 快速层（不含 slow） | **3245 passed / 237.23s**（slow 层 9 个用例占 410s） | `py -3.10 -m pytest tests/ -q -m "not slow"` |
| 用例收集 | **3261 / 0 errors**（含新增用例；热缓存 3.6s） | `py -3.10 -m pytest tests/ --collect-only -q` |
| 契约测试 | 39 passed | `pytest tests/contracts -q`（历史值，本轮含在全量内） |
| 覆盖率 | **47.44%**（26,861 / 56,624 行），数据 2026-10-23 | `py -3.10 -m pytest tests/ -q --cov=src` |
| 覆盖率门禁 | `fail_under = 47`（**已生效**；原先 60 写在 `[tool.coverage.run]`，coverage 不识别 → 从未生效） | 见 `pyproject.toml` 注释 |
| Ruff `F821` / `F811` | **0 / 0** | `py -3.10 -m ruff check src/ tests/ --select F821,F811,E9` |
| 导入期缺陷 | **IMPORT-FAIL 0 / IMPORT-EXIT 0**（642 模块，635 OK，DEP-MISSING 7 均为可选 extras） | `scripts/import_sweep.py --strict-exit` |
| 生产可达模块 | **443**（补入 `src.__main__` 种子后的口径修正；此前 442） | `scripts/reachability.py --min-reachable 443` |
| 死模块 | 199（完全不可达 134 / 24,667 行）；三问判定：NO_REFS 112 / DOC_ONLY 6 / HAS_REFS 16 | `计划书/死代码判定-2026-10-23.md`，**删除需产品决策** |
| Ruff 全量违规 | 会随批次波动（2026-10-23 实测 **432**） | 跑 `py -3.10 -m ruff check src/ --statistics` 看当前值；硬指标只看 F821/F811/E9 |
| 第三方依赖缺失 | 7（celery / opentelemetry / pathspec 等可选 extras） | `scripts/import_sweep.py` 的 DEP-MISSING，属环境非缺陷 |
| 静默吞异常 | **172**（AST 口径），基线文件 `.clawd/baseline-silent.json`，CI 门禁 `--fail-over 172` | `scripts/check_silent_except.py --fail-over 172` |
| 真实 E2E | `e2e_smoke` **5/5** · `e2e_production` **8/8** | 2026-10-23 实跑，退出码 0 |
| 并发压测 | 200 并发 **5/5**，128 req/s，无死锁/错配 | `scripts/stress_test.py --n 200`（纯本地状态机） |

> 本表数字随批次更新；每次改动前请按 `docs/MAINTENANCE.md` §0 重新取数。

> 覆盖率爬升与死代码收敛计划见 `计划书/下一步改进指南.md`。
> **注意**：删死代码会让覆盖率*百分比*上升但绝对覆盖行数不变，
> 因此必须同时跟踪「已覆盖语句数」，防止分母变小造成的假象。

### 三条硬指标（回归红线）

```bash
python -m ruff check src/ --select F821,F811   # 必须 All checks passed
python scripts/import_sweep.py                 # 必须 IMPORT-FAIL = 0
python scripts/reachability.py                 # 删代码前后可达数必须不变
```

### 质量标准
- 函数长度 < 50 行
- 嵌套深度 < 4 层
- 强制类型注解
- 测试覆盖率最低要求 80% (核心模块)

---

## 📄 许可证
MIT License

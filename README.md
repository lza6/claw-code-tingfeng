# 🚀 Clawd Code：AI 编程代理框架

> **"让 AI 像交响乐团一样协作，让编程像呼吸一样自然。"**

**当前版本**: v0.89.1 | **测试**: 见 `test_ledger.md` 与 `scripts/e2e_smoke.py` | **覆盖率**: 见 `coverage.json`（由 `pytest --cov=src` 生成） | **质量工具**: ruff, mypy, pytest-cov | **CI/CD**: GitHub Actions

> 版本号以 `pyproject.toml` 为唯一真相源，`src.__version__` 自动读取，不再手工维护。
> 具体数字请以命令输出为准，避免文档与代码漂移。

---

## 🖥️ Clawd Desktop（桌面端）

DSH 式桌面客户端，**双击即用**：

| 形态 | 获取 |
|------|------|
| NSIS 安装程序（带自动更新） | GitHub Release → `Clawd Desktop Setup <version>.exe` |
| Portable 免安装 | 同 Release → `ClawdDesktop-Portable-<version>.exe` |
| 开发模式 | `cd desktop && npm run dev` |
| 签名构建 | `pwsh -File scripts/build_desktop_signed.ps1 -SelfSigned`（验证签名管线）/ `-Pfx <证书> -Password <口令>`（正式） |

**工作台（照参考客户端结构实现，后端用我们自己的）**
- **项目侧栏**：列出项目、点击切换（当前高亮）、`✕` 从列表移除（**不删文件**）；
  存 `<数据目录>/projects.json`。新会话的工作目录 = 当前项目。
  `＋` 添加项目：原生文件夹选择器（纯网页环境降级为粘贴路径）或从 URL `git clone --depth 1`。
- **会话按项目分组**：历史会话按 `workdir` 归组，组标题是项目名、右侧显示条数，
  未关联项目的会话沉到最下面；会话 metadata 同时记 persona / model / provider。
- **模型选择器**：composer 左侧「模型 ⌄」——搜索、按 provider 分组的模型列表、
  5 档推理强度（低/中/高/极高/最大 → temperature 0.9→0.0）、快速模式（`max_tokens ≤ 1024`）。
- **上下文面板**：实时显示已用 token / 窗口上限 / 占比条与分段明细。
- **用量统计**：KPI（请求数/输入输出 token/成本/缓存命中率）+ 按小时柱状图 + 按模型/调用方汇总 + 最近请求表。
  调用方维度区分 `cli` / `desktop`，成本按 provider 单价估算。
- **能停下来**：模型卡住时发送键变 `■`（停止），点一下就打断本轮并解锁；同一连接不会并发跑两轮（返回 `E_BUSY`）
- **续聊不碎**：点开历史继续聊会回传 `session_id`，Host 追加到**同一会话**，侧栏不会堆出几十条同名记录
- **正文只说人话**：模型写出的 `<tool>{...}` 协议、注入给模型的附件说明、错误码与堆栈都不会显示在气泡里
- **工具调用折叠**：连续工具调用合成一行「运行 N 命令 和 编辑 M 文件」，点开逐条看参数与结果；
  每轮显示「工作了 32m 3s」「思考了 7s」。
- **消息渲染**：完整 Markdown（标题/列表/表格/引用/代码块/行内码）+ 内联图片（本地 `/api/file?path=` 与 http(s)）；
  图片可直接粘贴上传（存 `<数据目录>/uploads`）。
- **图片能"看"了**（v0.87.0，v0.88.4 实测校准）：模型支持视觉时（`gpt-4o`/`claude-3|4`/`gemini`/
  `qwen-vl`/`glm-4v`…），图片以 `image_url` 内容块随消息发送，模型直接读图回答；
  不支持视觉的模型老实告知"看不到图"（路径仍写给它，绝不让它猜）。`CLAWD_VISION=1/0` 可强制开/关。
  带图请求被端点拒绝时（有些端点直接断连而不是返回 400）会**自动降级为纯文本重试一次**，
  不会把整轮任务打挂。实测：当前 `step-5-preview` 端点不支持图像输入（纯文本 PONG 正常，
  带 `image_url` 立刻断连），链路与回退均已验证。
- **多 provider**：设置页可配置多个 OpenAI 兼容 provider（id/名称/模型/base_url/密钥来源），
  选一个设为默认；密钥只显示掩码（`sk-ab…1234`）或环境变量名，**永不回显明文**。
- **更新提示走右下角 toast**：单条贯穿 检查中 → 下载中 → 已就绪，就绪时给「重启安装 / 稍后」；
  侧栏那行文字只做就地状态显示，不抢正文。

**架构**
- Electron 壳（窗口/托盘/单实例/崩溃自愈，**无原生菜单栏**，快捷键走 `before-input-event`）
  → spawn Python Host（`clawd serve`）→ WS 同端口托管 Web UI；壳内不造业务 IPC，只做外壳能力
- **数据目录分离**：桌面端数据放 `app.getPath('userData')/data`（`CLAWD_DATA_DIR` 注入），
  与安装目录解耦 → **升级/重装不丢配置、用量、会话**；启动时一次性迁移旧 `.clawd`
- **存储选型**：高频聚合（用量）走 SQLite；低频、可手改的配置（`providers.json` / `projects.json`）走 JSON，
  原子替换（写临时文件 + `os.replace`）
- **插件市场**：`.clawd/plugins/*/pyproject.toml` 的插件会真实出现在市场（Host 只发现 manifest 不执行代码）
- **自动更新**：仅安装版支持（portable 版明确提示不支持）。更新源必须用环境变量 `CLAWD_UPDATE_URL`
  （或改 `desktop/package.json` 的 `build.publish`）指向真实发布源，否则 UI 明确告知"更新源未配置"，不静默失败
- 详见 `docs/ENHANCEMENT_GUIDE.md`（使用/排障）、`docs/RELEASE_UPDATES.md`（发布/更新）、`docs/adr/`（决策记录）

> **桌面端 E2E**（真实浏览器 + 真实 Electron + 真实安装包，非桩）：
> - `node ui_console_e2e.mjs` — 浏览器驱动装好的 Host，**32 项**（滚动/Markdown+图片/会话分组/toast/视觉能力标注/布局可见性/停止生成/协议剥离/会话管理/
>   工具折叠/上下文/用量/provider/项目/模型选择器）
> - `node ui_stream_persona_e2e.mjs` — 真流式 + 角色库 + 无顶栏
> - `node ui_settings_e2e.mjs`（18 项）、`node electron_bridge_e2e.mjs`（10 项）、
>   `node update_feed_e2e.mjs`（4 项）
> - 装机全链路：`%TEMP%\clawd-install-e2e.ps1` —— 静默安装 → 32 项浏览器断言 → 重启后
>   provider 与会话接口仍在 → 卸载 → 残留清理
> - 静态防回归：`tests/test_electron_main_static.py`（7 条：electron 符号必须解构导入、
>   同一函数内不得先用后声明、无默认菜单、preload 不透 Node 能力）

## ⚡ 超级智能体能力（v0.61.0 新增）

| 能力 | 入口 | 说明 |
|------|------|------|
| 推理模式 | `clawd reason reflexion\|plan-execute\|lats\|debate "任务"` | 四种反推循环：反思修正/计划重排/假设树/对抗审查 |
| MCP 桥接 | `.clawd/mcp_servers.json` + `ToolGovernor().approve()` | 外部 MCP server 工具自动进 Agent 工具池；签名+检疫审批防投毒 |
| 逆向工具 | Agent 内直接调用 | Ghidra HTTP 桥、strings/熵/hexdump、objdump/binwalk 等 8 个 |
| 安全工具 | `SafeCatalogRunner` | YAML 目录 + scope 授权门禁 + 注入拦截（仅限授权测试目标） |
| 逆向知识库 | `skills/reverse/` | 51 个场景 SKILL.md（固件/Ghidra/IDA/恶意软件/协议/pwn/CTF） |
| 插件开发 | `.agent/skills/clawd-extension-sop.md` | 四件套 SOP（manifest/DI/接入面/CLI） |

## 🤝 多引擎协同（v0.75.0 新增）

不只是"能分别接上引擎"，而是**让它们合起来跑一件事**：

```bash
# 默认全用内置引擎；也可混搭
clawd collaborate "实现登录接口并补测试"   --planner codex --executor native --reviewer opencode --rounds 1
```

流程：**规划 → 执行 → 独立审查 → 不合格返工 → 再审查**

- 审查者必须输出 `VERDICT: APPROVE` 或 `VERDICT: NEEDS_FIX`（**确定性解析**，两种都写判不通过、无标记判 UNKNOWN 不放行）
- 返工有上限（`--rounds`，默认 1），不会两引擎互相挑刺无限循环
- 换另一个引擎来审，能抓出"自己审自己"放过的问题
- 引擎实例按名字缓存，三阶段共用同一个引擎（避免重复初始化世界模型）

**把我们自己的领域工具交给外部引擎**（Codex 实测可用）：
```bash
clawd codex --with-clawd-tools --bypass-approvals   "用 clawd MCP 的 clawd_grep 搜索 'clawd-domain'，只回复文件名"
# → 真实返回 tests/mcp/test_domain_server.py、src/mcp/domain_server.py
```

**续聊（会话记忆）**：
```bash
clawd chat --resume <会话ID>     # 载入历史续聊；REPL 多轮已自动累积上下文
clawd session resume <会话ID> "<本次目标>"   # 非交互续跑
```

**看懂它做了什么 / 让它被别人审**（v0.76.6–v0.76.8 新增）：
```bash
clawd explain                    # 中文解释最近一轮：模型/用量/工具调用成败/失败片段（零 LLM 调用）
clawd explain <会话ID> --json     # 机器可读
clawd review src/app.py          # 4 个评审角色**并行**（code/security/performance/style）
clawd review --json              # 给 CI；裁决 VERDICT: APPROVE|NEEDS_FIX，任一角色失败=INCOMPLETE
clawd onboard                    # 上手体检：检测密钥 + 推荐模型 + 下一步
clawd role list                  # 角色库（系统提示词模板，不用自己写提示词）
clawd role show reviewer         # 打印某角色的完整系统提示词（可审计）
clawd chat --role concise        # 用指定角色开聊；桌面端在输入框左侧下拉切换
```

> `clawd review` 的裁决是确定性解析出来的（不是让模型自己说"通过"），
> 角色模板来自 `prompts/agents/*.md`（已随 wheel 与桌面安装包一起发布）；
> `.env` / `*.pem` / `id_rsa` 等密钥类文件**不会**发给模型。

**脚本/CI 消费输出（`--json` 契约，v0.89.0 覆盖全部查询类命令）**：
```bash
clawd agent list --json        # 30 个 agent 的机器可读清单
clawd catalog list --json      # 技能/Agent 清单
clawd permissions --json       # 审批模式 / 挂机级别 / 命令策略 / 受保护路径
clawd config --json            # 配置优先级链
clawd explore "<目标>" --json  # 只读探索结果（findings 是纯文本字段）
clawd pipeline "<目标>" --json # 三阶段流水线的状态/耗时/各阶段结果
clawd ralplan "<目标>" --json  # 共识计划（confidence/tasks/risks/方案）
clawd quality-gate --json      # 质量门：overall + 逐项结果（失败项只带尾部 20 行）
clawd eval <数据集> --json      # 评测汇总（pass_rate/failures/unknowns/基线回归）
clawd autonomy list|log --json # 挂机预授权与决策审计
clawd doctor --json            # 环境体检
```

> 统一契约 `{ok, code, ...业务字段}`，**退出码等于 `code`**；错误也输出合法 JSON
> （`ok=false` + `code>=1`），所以 `clawd <cmd> --json | jq` 任何时候都不会崩。
> 输出要求见 `docs/MAINTENANCE.md` §3.4。**只读/长任务/变更类命令**（`chat`/`run`/`serve`/
> `collaborate`/`workflow *`/`session fork|title|resume`）**故意不提供** `--json`：
> 它们是交互式或长驻进程，没有"一次性结果"可序列化。

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
| 我们自己的 agent | **原生工具**（`WorldModelTool` / `ProjectMapTool` / `MemoryTool` / `StateTool` / `TraceTool` / `TeamTool`） | 零进程、零序列化、共享进程内缓存；能力工具与 `core/mcp` 的 Server 类**同源实现** |
| 外部引擎（Codex/OpenCode…） | **MCP**（`src/mcp/domain_server.py`、`src/core/mcp/*_server.py`） | 跨进程只能走协议 |

> v0.80.0 起，**状态/记忆/追踪/团队**也内建成原生工具（`action` 子命令），
> 不再需要为自家 agent 起 MCP 进程；MCP 只留给外部引擎跨进程使用。

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

### 质量基线（2026-10-29 实测；每轮只更新**本轮真的跑过**的项）

| 指标 | 当前 | 说明 |
|:---|:---|:---|
| 测试用例 | **5440 passed / 7 skipped / 8 xfailed / 0 failed**（2026-10-31 v0.89.0 实测，375.04s） | `py -3.10 -m pytest tests/ -q -m "not slow"` |
| 快速层（不含 slow） | **5440 passed / 0 failed / 6 分 15 秒**（同一命令，v0.89.0 实测） | `py -3.10 -m pytest tests/ -q -m "not slow"` |
| 用例收集 | **5467 / 0 errors**（2026-10-31 v0.89.1 实测） | `py -3.10 -m pytest tests/ --collect-only -q` |
| 契约测试 | **39 passed**（本轮实测） | `py -3.10 -m pytest tests/contracts -q` |
| 覆盖率 | **66.29%**（2026-10-31 v0.89.1 实测，38741/58439 行） | `py -3.10 -m pytest tests/ -q --cov=src` |
| 覆盖率门禁 | `fail_under = 60`（**已生效**，2026-10-29 由 47 收紧） | 见 `pyproject.toml` 注释 |
| Ruff `F821` / `F811` | **0 / 0** | `py -3.10 -m ruff check src/ tests/ --select F821,F811,E9` |
| 导入期缺陷 | **IMPORT-FAIL 0 / IMPORT-EXIT 0**（624 模块，624 OK，DEP-MISSING 0；2026-10-29 实测） | `scripts/import_sweep.py --strict-exit` |
| 生产可达模块 | **503**（2026-10-31 v0.89.0 实测；门槛 443） | `scripts/reachability.py --min-reachable 443` |
| 死模块 | **64 个完全不可达**（不可达合计 147 个 / 31,318 行；已删 47 文件 10,685 行，另有裁定保留待接线） | `scripts/reachability.py --min-reachable 443 --list` |
| Ruff 全量违规 | 会随批次波动（2026-10-29 实测 **374**） | 跑 `py -3.10 -m ruff check src/ --statistics` 看当前值；硬指标只看 F821/F811/E9 |
| 第三方依赖缺失 | **0**（2026-10-29 补齐 celery/opentelemetry/pathspec 等） | `scripts/import_sweep.py` 的 DEP-MISSING |
| 静默吞异常 | **154**（AST 口径，门禁 ≤154），基线文件 `scripts/baseline-silent.json` | `scripts/check_silent_except.py --fail-over 154` |
| 真实 E2E | `e2e_smoke` **5/5** · `e2e_production` **8/8** | v0.89.0 实跑（退出码 0；真实端点按 policy.md 最小配额） |
| 并发压测 | 200 并发 **5/5**，128 req/s，无死锁/错配 | `scripts/stress_test.py --n 200`（纯本地状态机） |

> 本表数字随批次更新；每次改动前请按 `docs/MAINTENANCE.md` §0 重新取数。

> 覆盖率爬升与死代码收敛计划见 `计划书/下一步改进指南.md`（现行 v4）。
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

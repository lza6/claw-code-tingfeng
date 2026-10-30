# 上手 Clawd Code（产品教程）

> 这份文档回答「我装了它，接下来怎么用、怎么确认它真的在干活」。
> 想了解**技能文件怎么分发给别的 agent**，见 [skills-distribution.md](skills-distribution.md)。
> 想新增 Provider / Tool / CLI 命令，见 [MAINTENANCE.md](MAINTENANCE.md)。

---

## 0. 前置条件

- **Python 3.10+**（本仓库实测解释器矩阵见 `CLAUDE.md`：`venv/Scripts/python.exe` 与 `py -3.10`）
- **git**（会话分叉、worktree 隔离、评审取 diff 都依赖它）
- 至少一个 LLM API 密钥（OpenAI / Anthropic / DeepSeek / Gemini / OpenRouter 任一）

---

## 1. 安装（源码可编辑安装）

```powershell
# Windows PowerShell（在仓库根目录）
py -3.10 -m venv venv
venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
venv\Scripts\python.exe -m pip install -r requirements.txt     # 首次装依赖
```

```bash
# macOS / Linux
python3.10 -m venv venv
venv/bin/python -m pip install -e . --no-deps --no-build-isolation
venv/bin/python -m pip install -r requirements.txt
```

验证安装：

```powershell
venv\Scripts\python.exe -m src --version
venv\Scripts\python.exe -m src doctor      # 逐项检查 Python/依赖/密钥/provider
```

> `python -m src` 就是 `clawd`。下面统一写 `clawd`，你实际敲同样一行时把前缀换成
> `venv\Scripts\python.exe -m src`。

---

## 2. 配置密钥与默认模型

```powershell
$env:OPENAI_API_KEY = "sk-..."     # 或 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / ...
clawd onboard                      # 检测已有密钥 + 推断推荐模型 + 给出下一步
clawd onboard --json               # 同样的信息，给脚本/CI 用
clawd config                       # 管理配置文件里的 key/model/provider
```

`onboard` 的判定是**基于环境里真实存在的密钥**，不会假装成功：没有密钥时退出码 1，
并明确告诉你缺什么。`chat` 启动时也会做一次同样的体检（只在真的什么都没有时提示一次）。

---

## 3. 第一个任务

```powershell
clawd explore "这个仓库里 RAG 索引是怎么预热的？"   # 只读，不改文件
clawd run "把 src/utils/version_check.py 的超时从 5s 改成 10s 并跑它的测试"
clawd chat                                          # 进入交互式 REPL（可 --resume 续聊）
```

三种模式的分工：

| 命令 | 会不会改文件 | 适合 |
|---|---|---|
| `explore` | 不改 | 先摸清代码，再决定动不动 |
| `run` | 会（受权限门禁约束） | 一次性把目标做完：识别→规划→执行→审查→发现 |
| `chat` | 会（受权限门禁约束） | 多轮迭代、需要来回确认 |

`chat` 支持续聊：`clawd chat --resume <session_id>`（`clawd session list` 查看已有会话）。

---

## 4. 看懂它刚才做了什么

这一步是 Clawd Code 与"黑盒 agent"的主要区别，全部是本地文件 / 命令，不需要额外服务：

```powershell
clawd explain                           # 用中文讲清最近一轮：模型/用量/工具调用成败/失败片段
clawd explain <session_id> --json        # 同上，机器可读
clawd session list                      # 会话清单（.clawd/sessions/）
clawd session show <session_id>         # 某个会话的步骤与结果
clawd hud                               # 状态面板：模型/迭代/token/成本
clawd review --json                     # 多角色并行评审未提交改动（code/security/performance/style）
clawd eval src\eval\datasets\smoke.json # 行为回归（replay，零成本）
```

- **会话内容**：`.clawd/sessions/*.json` 里工具调用是**结构化记录**（`role=tool` + 名称 + 成败），
  不是压平的文本 —— 所以 `clawd explain` 能列出"调了哪个工具、成没成功"
- **日志**：`.clawd/logs/*.jsonl`（结构化事件，可直接 `Select-String` / `grep`）
- **评审裁决**：`clawd review` 输出 `VERDICT: APPROVE | NEEDS_FIX`，
  任一角色失败会显示 `INCOMPLETE` —— **不会**把"没评审"算成"没问题"
- **评测三态**：`pass` / `fail` / `UNKNOWN`。缺录制数据 = `UNKNOWN`（未判定），
  不计入通过率。示例见 `src/eval/datasets/honesty.json`

---

## 4.5 角色库（不用自己写提示词）

```powershell
clawd role list                 # 看有哪些角色（内置 6 个：严谨工程师/极简输出/教学讲解/严格审查者/中文写作/排障专家）
clawd role show reviewer        # 打印该角色的完整系统提示词 —— 不藏东西
clawd chat --role concise       # 用"极简输出"开聊
```

角色就是一个 markdown 文件：`personas/<name>.md`，frontmatter 放 `name/title/description/category`，
**正文就是系统提示词**。搜索顺序：`<项目>/personas` → `<当前目录>/personas` → `~/.clawd/personas`，
同名时后面的覆盖前面的（团队统一底库 + 个人覆盖）。桌面端在输入框左侧下拉切换，会话里会记录用了哪个角色。

> 想加自己的角色：把 `personas/我的角色.md` 放进去，`clawd role list` 立刻能看到。
> 内置库只放工程/写作类角色；越狱/绕过安全审查类提示词不在内置范围。

**关于"流式回复"**：桌面端与 Host 走的是真流式（`agent.stream_delta` 事件），
助手说的话边生成边显示；工具调用只是正文下面的折叠单行，不抢注意力。

## 4.6 多个 API 提供商与用量统计（桌面端）

**配多个 provider（存在本机 JSON，重启还在）**
1. 侧栏 → 设置 → 「API 提供商」区域填写：标识（英文）/ 显示名 / 类型 / Base URL / 模型；
2. 密钥两种放法：**环境变量名**（推荐，如 `DEEPSEEK_API_KEY`）或直接填密钥（仅本机保存，界面只显示掩码）；
3. 保存后可「设为默认」——**下一轮对话即生效**（Host 会用这套配置建引擎）；
4. 删除默认项会自动把最近一条顶上，不会出现"没有默认"的状态；改配置时密钥留空 = 保留原值。

**文件在哪（想手改就直接编辑）**
桌面端的数据目录是 `%APPDATA%\clawd-desktop\data`（Electron `userData/data`，由 `CLAWD_DATA_DIR` 注入）：

| 文件 | 内容 | 为什么用它 |
|------|------|-----------|
| `providers.json` | provider 列表 + 默认项 + 密钥（对外只给掩码） | 低频、可手改，原子替换写入 |
| `projects.json` | 项目列表 + 当前选中 | 同上 |
| `sessions/*.json` | 会话（工具调用是结构化记录：`role=tool` + 名称 + 成败） | 归档，可人工查看 |
| `usage.db` → `usage` 表 | 每轮一行用量（provider/模型/输入输出 token/缓存读/成本/步数/调用方） | 高频聚合查询，SQLite |
| `uploads/` | 粘贴/上传的图片附件 | 大文件，别塞进库 |

> 命令行/服务端模式若没设 `CLAWD_DATA_DIR`，数据仍落在 `<工作区>/.clawd/`。两处**永不同时使用**：
> 桌面端永远优先用注入的目录，所以升级、重装、移动安装位置都不会丢配置。

**看用量（成本 / 请求数 / token / 缓存命中率）**
侧栏 → 用量统计：4 个 KPI + 按小时柱状图 + 按模型/调用方汇总 + 请求日志表，可切「当天 / 近 7 天 / 近 30 天」。
数据来自 `usage` 表：引擎每跑完一轮就记一行，`client` 字段区分 `cli` 与 `desktop`。
缓存命中率口径 = 缓存读 ÷ (缓存读 + 新增输入)。

> 想接别的工具？直接查库：`sqlite3 "%APPDATA%\clawd-desktop\data\usage.db" "select * from usage order by ts desc limit 20"`。

## 4.7 项目、会话分组与更新提示（桌面端）

**项目 = 一个文件夹**
侧栏「项目」区列出你加过的项目，点一下就切过去（高亮 = 当前项目）。**新会话就在这个目录里干活**
（`run` 消息带 `workdir`，Host 传给引擎）。`✕` 只是从列表移除，**不动磁盘上的文件**。

`＋ 添加项目` 两条真实路径：
- **浏览文件夹**：走 Electron 原生选择器；纯浏览器访问时自动降级成"粘贴路径"；
- **从 URL 克隆**：Host 真跑 `git clone --depth 1` 到 `<数据目录>/clones/<name>`，成功后自动加入项目列表。

**会话按项目分组**
侧栏历史会话按 `workdir` 归组：组标题是项目名，右侧是条数，没关联项目的会话沉到最下面。
会话落盘时同时记录 persona / model / provider，鼠标悬停能看到这些信息。

**更新提示**
右下角 toast 单条贯穿「检查中 → 下载中 → 已就绪」，就绪时给「重启安装 / 稍后」按钮；
侧栏底部那行文字只做就地状态显示。浏览器直接访问时明确提示"桌面安装版才有更新通道"。

## 4.8 图片与视觉输入（桌面端）

**怎么发图**：直接 `Ctrl+V` 粘到输入框（或点附件按钮）→ 出现缩略图 → 正常发送。
图片存到 `<数据目录>/uploads/img-<hash>.png`。

**模型能不能"看"决定走哪条路**：

| 模型 | 行为 |
|:---|:---|
| 支持视觉（`gpt-4o` / `gpt-4.1` / `claude-3|4` / `gemini` / `qwen-vl` / `glm-4v` / `llava` / `pixtral` / `step-1v`…） | 图片以 `image_url` 内容块随消息发送，模型**直接看图回答** |
| 不支持视觉（如 `deepseek-chat`、`step-5-preview`） | 老实走"路径告知"：把本机路径写给模型，并要求它**看不到就直说、不许猜** |
| 拿不准 | 保守当"不支持"（避免给 provider 塞内容块换来 400） |

**强制开关**（模型名认不出来时用）：
```powershell
$env:CLAWD_VISION = '1'   # 强制按多模态发（模型确实支持时才有意义）
$env:CLAWD_VISION = '0'   # 强制回退成路径告知
```

**限制**：单图 ≤ 2MB、单条消息 ≤ 4 张（base64 让体积涨 ~33%，太大会把上下文撑爆）；
超限或读不到的图片会被跳过，不会让整条消息失败。

## 5. 权限与挂机（要不要让它自己跑）

```powershell
clawd permissions                       # 中文说明：审批模式 / 挂机级别 / 受保护路径 / 拒绝理由
clawd autonomy list                     # 当前预授权的命令前缀
clawd autonomy allow "git status"       # 只放行这一条（前缀匹配）
clawd autonomy stop                     # 立刻叫停（写 STOP 文件，引擎每轮检查）
clawd autonomy log                      # 无人值守期间的决策审计（JSONL，中文）
```

三档挂机级别：`supervised`（默认，每步问你）/ `semi`（读操作放行、写操作问）/
`unattended`（按预授权自动决策，越界即停）。所有决策都会进审计日志，
所以"它自己跑了什么"是可回查的，不是猜的。

---

## 6. 多引擎（可选）

```powershell
clawd engines                                   # 探活：native / codex / opencode ... 真实可用性
clawd collaborate "重构 X" --planner codex --executor native --reviewer opencode
clawd codex "用 Codex 内核做这件事"
```

`native` 是内置引擎（我们自己的 agent，含 19 个工具 / LSP / 世界模型），
不装任何外部 CLI 也能用。外部引擎装上才会显示 `ready`，没装就是 `not_installed`——
探活结果不会撒谎。

---

## 7. 常见失败与定位

| 现象 | 真实原因 | 怎么查 |
|---|---|---|
| `NameError: loguru` / 导入就炸 | 用了裸 `python`（本机指向 3.14，缺运行依赖） | 改用 `venv\Scripts\python.exe` 或 `py -3.10` |
| `未检测到任何 LLM 密钥` | 环境变量没设 / 设在了别的 shell | `clawd onboard --json` |
| MCP 客户端连不上我们的 server | 命令里的解释器不是当前 venv | `clawd doctor`；生成配置的 `command` 已是 `sys.executable` |
| `python -m src.core.mcp.xxx_server` 秒退无输出 | v0.76.5 之前确实没有 `__main__`（已修） | 升级到 ≥ v0.76.5 |
| 评测打印 `UNKNOWN` | 用例缺 `recorded` / 缺工具记录 | 补录制数据，或用 `--live`（需 `CLAWD_EVAL_ALLOW_PAID=1`，会真花钱） |
| 门禁数字对不上 | 文档过期 | `py -3.10 scripts/baseline.py --out .clawd/baseline.json` 现跑 |

---

## 8. 下一步

- 变更本项目前先读：`workflow_status.md` → `skills/clawd-change-workflow/SKILL.md`
- 新增 Provider / Tool / CLI 的逐步 SOP：`docs/MAINTENANCE.md`
- 影响后续判断的设计决策：`docs/adr/README.md`
- 质量门禁与硬指标口径：根目录 `CLAUDE.md` 的「最短验证路径」

# Oh-My-Codex 整合报告

**项目A**: Clawd Code (本地项目)  
**项目B**: Oh-My-Codex (参考项目)  
**整合日期**: 2026-04-17

---

## 执行摘要

本次整合从 Oh-My-Codex 汲取了以下**五个核心领域**的架构优势：

| 类别 | 特性 | 状态 | 位置 |
|------|------|------|------|
| `P0` 配置系统 | 动态配置生成器 + 技能发现 | ✅ | `src/core/config/generator.py` |
| `P0` 技能系统 | YAML frontmatter 标准化 | ✅ | 所有 `skills/*/SKILL.md` |
| `P0` Hook架构 | TOML 配置化 Hook | ✅ | `src/core/hooks_config.py`, `hooks/config.toml` |
| `P0` 探索模式 | 独立只读分析模式 | ✅ | `src/cli/commands/explore.py` |
| `P0` 意图路由 | 关键词检测 + 意图分类 (DELIVER/EXPLORE/EVOLVE/IMPLEMENT/DEBATE) | ✅ | `src/agent/intent_router.py` |
| `P0` 关键词注册表 | 40+ 技能关键词 + 执行门控 + Ralplan-first Gate | ✅ | `src/agent/keyword_registry.py` |
| `P0` 任务规模检测 | small/medium/large/heavy 分类 + Agent 推荐 | ✅ | `src/agent/task_size_detector.py` |
| `P1` 质量门 | 自动化质量检查 (lint → test → security) | ✅ | `src/core/quality_gate.py` |
| `P1` MCP架构 | State/Memory/Trace/Team/CodeIntel 服务器 | ✅ | `src/core/mcp/*.py` |
| `P2` HUD系统 | 实时状态显示器 + 通知集成 | ✅ | `src/cli/hud_improved.py` |
| `P2` 规划三角 | Ralplan 共识规划 (Planner-Architect-Critic) | ✅ | `src/workflow/ralplan.py` |
| `P2` 流水线 | Pipeline 编排 (RALPLAN → TEAM → RALPH) | ✅ | `src/workflow/pipeline_orchestrator.py` |

---

## 架构Changed对比：项目A与项目B

### 原始差距分析

| 维度 | 项目A (原) | 项目B优势 | 整合方案 |
|------|-----------|----------|----------|
| **技能格式** | 无标准化frontmatter | YAML frontmatter | 已补充所有SKILL.md |
| **Hook配置** | 硬编码 Python | TOML 声明式 | 新增 `hooks_config.py` |
| **CLI扩展** | Python 函数散落 | 层级化 `commands/` | 新增探索命令模块 |
| **配置生成** | 需要手动编辑 | 自动合并 Codex 配置 | 新增 `config/generator.py` |
| **探索模式** | 嵌入 workflow | 独立只读模式 | 新增 `commands/explore.py` |
| **质量门** | 零散检查 | 统一 GateLevel | 新增 `quality_gate.py` |
| **通知系统** | 简单 dispatcher | 多后端 + HUD | 新增 `notifications/dispatcher.py` |

### Swarm vs Team 差异

| 特性 | 项目A Swarm | 项目B Team | 评价 |
|------|-------------|------------|------|
| 协调基元 | Inbox + TaskRegistry | TMUX + Mailbox + Worktree | **项目A**更轻量 |
| 状态持久化 | TeamPersistence JSONL | MCP Team Server | **势均力敌** |
| 隔离性 | Git worktree | TMUX pane + worktree | **整合方案** |
| 并行度 | Asyncio/Tasks | 多进程 TMUX | **整合** - 异步并行 |

**决策**: 保留项目A的异步Swarm（更符合Python生态），但在`Team Server`中提供TMUX bridge以支持外部协调需求。

---

## 详细改造成果

### 1. 动态配置生成器 (`src/core/config/generator.py`)

**问题**: 项目A的静态配置难以同步Codex更新，项目B的代码侵入性强。

**方案**:
- 不修改Codex核心，通过**配置合并**实现扩展
- 自动发现 `skills/` 目录下的所有技能
- 生成 AGENTS.md 覆盖，注入角色定义
- 合并 MCP 服务器配置到 `~/.claude/config.toml`

**使用**:
```bash
clawd config --generate
```

**输出示例**:
```toml
[features]
persistence = true
team_mode = true
worktree_isolation = true
mcp_servers = true

[mcp_servers.clawd-state]
command = "python"
args = ["-m", "src.core.mcp.state_server"]
```

---

### 2. Hook 配置文件化 (`src/core/hooks_config.py`, `hooks/config.toml`)

**问题**: 项目A的Hook需要硬编码注册（更改配置需改代码）。

**方案**:
- 引入 TOML 配置格式（参考 B 的 PostToolUse 设计）
- 支持 `SessionStart/End`, `Pre/PostToolUse` 钩子
- 自动注册 shell 命令钩子到 HookRegistry
- PreToolUse 钩子可阻止操作（如文件大小Guard）

**配置示例**:
```toml
[hooks.PostToolUse]
[hooks.PostToolUse.format]
matcher = "Write|Edit"
command = "ruff format {file_path}"

[hooks.PreToolUse.size_guard]
matcher = "Write"
command = "python -c '...size check...'"
```

---

### 3. 探索模式分离 (`src/cli/commands/explore.py`)

**问题**: 项目A的分析和实现混合，探索时容易误操作。

**方案**:
- 独立只读模式，禁用 `Write/Edit/Delete` 等写工具
- 只允许 `Read/Glob/Grep/Search` 等分析工具
- 输出 Markdown/JSON/Tree 三种格式报告
- 通过 `--readonly` 标志在 CLI 调用

**使用**:
```bash
clawd explore "分析项目的模块依赖关系"
```

---

### 4. 质量门系统 (`src/core/quality_gate.py`)

**问题**: 项目A的代码质量检查分散，无统一阻断机制。

**方案**:
- 统一 GateLevel: commit → task → phase → release
- 每个级别预定义检查链 (format → lint → typecheck → tests)
- 自动执行并报告结果，可配置 strict 模式
- 集成到 workflow 验证阶段

**预定义检查**:
```python
GateLevel.COMMIT: [ruff format, ruff check]
GateLevel.TASK:   [mypy]
GateLevel.PHASE:  [pytest, coverage]
GateLevel.RELEASE:[bandit]
```

---

### 5. MCP Server 基础架构 (`src/core/mcp/`)

**问题**: 项目A无标准的外部集成协议。

**方案**:
- 实现5个 MCP 服务器接口（遵循 Model Context Protocol 规范）：
  - `state_server.py`   — 会话 + Surface + 任务状态存储
  - `memory_server.py`  — EnterpriseLTM 封装 + 知识图谱
  - `trace_server.py`   — OpenTelemetry 兼容追踪
  - `team_server.py`    — 团队协调 + 任务板 + Mailbox
  - `code_intel_server.py` — （待补充）

**可扩展性**: 后续可通过 `src/core/mcp/__init__.py` 暴露统一入口，支持外部 MCP 客户端连接。

---

### 6. Ralplan 共识规划 (`src/workflow/ralplan.py`)

**问题**: 项目A的规划较简单，缺乏多角色评审机制。

**方案**:
- 三角角色循环：Planner 提案 → Architect 评审 → Critic 挑战
- 答辩循环直到信心 ≥ 0.8 或达到最大轮次
- Sigma 自检点：目标清晰度、任务分解、风险覆盖、信心阈值
- 持久化 `consensus.json` 供流水线消费

**流程**:
```
GOAL → Planner提案 → Architect评审 → Critic挑战 → (循环) → Sigma验证 → PASS
                                                ↑___________|
```

---

### 7. Pipeline 流水线 (`src/workflow/pipeline_orchestrator.py`)

**问题**: 项目A的阶段较独立，无端到端编排。

**方案**:
- 三阶段串联：`RALPLAN` → `TEAM_EXEC` → `RALPH`
- 每个阶段输出制品，失败时优雅降级
- `PipelineResult` 包含所有阶段的完整状态

**CLI 使用**:
```bash
clawd pipeline "重构认证模块"
  --no-team     # 跳过并行执行，仅用Workflow
  --no-ralph    # 跳过验证循环
  --budget 5usd # 预算约束
```

---

### 8. HUD + 通知系统 (`src/cli/hud_improved.py`, `src/core/notifications/dispatcher.py`)

**问题**: 项目A的状态反馈分散，无统一显示层。

**方案**:
- **通知分发器**: 事件驱动、多后端支持（Console/HUD/File/Webhook）
- **HUD 显示器**: Rich Live 实时面板，展示迭代、开销、通知、资源压力
- **集成**: 通知系统可订阅到 HUD，WARNING 级以上自动显示

---

## 向后兼容性

所有修改均保持了**向后兼容**：
- 新增模块在 `src/` 独立目录，不影响原有 `agent/`, `brain/`, `llm/` 模块
- CLI 原有命令 (`chat`, `workflow`, `doctor`) 未修改行为
- 配置系统通过 `generator.py` 新增，与原配置并存
- Hook 系统通过 `load_hooks_config()` 按需加载，不影响原有代码
- 无 monkey-patching 或全局替换

运行现有测试应全部通过。

---

## 9. 状态持久化与工作区隔离模块 (`src/core/workspace.py`, `src/core/state.py`, `src/core/events.py`, `src/core/serialization.py`, `src/core/exceptions.py`)

**问题**: 项目A缺乏跨会话的状态持久化，以及隔离执行的工作区管理。

**方案**:
- **工作区管理器**: 使用 Git worktree 创建隔离执行环境，支持 `create_snapshot`, `integrate` 等操作
- **状态管理器**: 实现了类似 omx-runtime-core 的 `SystemSnapshot` (authority, backlog, replay, readiness subsnapshots) 及状态持久化
- **事件系统增强**: 新增权限/调度相关事件类型 (AUTHORITY_ACQUIRED, DISPATCH_* 等) 和事件持久化能力
- **序列化工具**: `JSONSerializer`, `from_dict`, `to_dict` 提供类型安全的对象序列化，支持 dataclass/Enum/datetime/Path
- **错误类型扩展**: 新增基于状态/运行时的错误代码 (STATE_LEASE_*, STATE_DISPATCH_*, STATE_MAILBOX_*, STATE_PERSISTENCE_* 等)

**核心改进**:
- 每个任务可在独立 worktree 中执行，完成后自动集成回主分支
- 运行状态保存为 JSON 文件，支持工作流恢复 (`recover=True`)
- 新模块统一由 `src/core/__init__.py` 导出，使用方式:
  ```python
  from src.core import WorkspaceManager, StateManager, SystemSnapshot, JSONSerializer
  ```

---

### 10. 意图路由系统 (`src/agent/intent_router.py`)

**问题**: 项目A的意图识别较为基础，项目B提供了更精细的五意图分类系统（DELIVER/EXPLORE/EVOLVE/IMPLEMENT/DEBATE），需要集成以实现智能任务路由。

**方案**:
- 借鉴 oh-my-codex 的五意图分类体系
- 实现 `IntentType` 枚举定义五种意图类型
- `classify_intent()` 函数返回单一意图（按优先级匹配第一个）
- `classify_intent_ranked()` 函数返回所有匹配意图及置信度得分（降序）
- `has_explicit_debate_intent()` 检测明确的辩论/审查意图
- `get_primary_intent()` 为向后兼容提供 `classify_intent` 的别名
- 感知执行上下文：通过意图分类决定资源分配和验证策略

**函数说明**:

| 函数 | 签名 | 说明 |
|------|------|------|
| `classify_intent` | `(text: str) -> str` | 单一意图分类，按优先级顺序匹配（DEBATE→EXPLORE→EVOLVE→IMPLEMENT→DELIVER），返回第一个匹配的意图字符串 |
| `classify_intent_ranked` | `(text: str) -> List[Tuple[str, float]]` | 多意图置信度排序，统计各意图匹配模式数量并加权计算分数，返回降序列表 |
| `has_explicit_debate_intent` | `(text: str) -> bool` | 检测明确的辩论/审查意图，匹配 `debate`、`review`、`security review`、`code review` 等关键词 |
| `get_primary_intent` | `(text: str) -> str` | `classify_intent` 的别名，保持向后兼容 |

**意图类型定义** (`IntentType` 枚举):

| 值 | 标签 | 典型关键词 | 推荐执行车道 | 验证策略 |
|----|----|-------------|-------------|----------|
| `deliver` | DELIVER | execute, run, complete, finish | Standard | 普通单元测试 |
| `explore` | EXPLORE | search, find, analyze, investigate, discover | Fast Lane | 无需代码验证，生成报告 |
| `evolve` | EVOLVE | improve, optimize, enhance, refine, upgrade | Frontier | Architect 评审，接受成功标准 |
| `implement` | IMPLEMENT | add, create, build, make, develop, write | Deep Worker | 强制 80%+ 测试覆盖率 |
| `debate` | DEBATE | review, critique, challenge, disagree, argue, question | Multi-Agent | 逻辑一致性与证据链检查 |

**使用示例**:
```python
from src.agent.intent_router import classify_intent, classify_intent_ranked, IntentType

# 单一意图分类
intent = classify_intent("请重构用户认证模块 → 返回 IntentType.IMPLEMENT (实现意图)

# 多意图排序（适用于需要多意图支持的场景）
ranked = classify_intent_ranked("分析代码库性能瓶颈并提出优化方案")
# 返回: [("explore", 0.6), ("evolve", 0.3), ("implement", 0.3)]

# 明确辩论意图检测
is_debate = has_explicit_debate_intent("请审查这段代码的安全性")
# 返回: True（匹配了 "review" 关键词）
```

**下游影响**:
- **资源分配**: EVOLVE/DEBATE 使用 Frontier 模型，EXPLORE 使用 FAST 模型
- **验证策略**: DEBATE 跳过单元测试，启用证据链检查；IMPLEMENT 要求 80%+ 覆盖率
- **Agent 选择**: DELIVER → executor；EXPLORE → explore；EVOLVE → architect；DEBATE → code-reviewer + multi-agent

---

### 11. 关键词注册表 (`src/agent/keyword_registry.py`)

**问题**: 项目A的技能激活机制较为简单，项目B提供了结构化的关键词注册表、优先级排序和执行门控机制，需要集成以实现智能技能路由。

**方案**:
- 引入 `KeywordTrigger` 不可变数据类（keyword, skill, priority, requires_intent, description）
- 注册 40+ 技能关键词（如 ralph, team, swarm, deep-interview, ralplan, pipeline 等）
- 实现 `EXECUTION_GATE_KEYWORDS` 执行门控关键词集合（需通过 ralplan-first gate）
- 定义 `WELL_SPECIFIED_SIGNALS` 15+ 正则模式（验证提示完整性）
- 提供 `detect_keywords()` 主函数（结合显式调用检测和意图验证）
- 实现 `apply_ralplan_gate()` 函数（ralplan-first Gate 逻辑）
- 添加 Deep Interview 输入锁相关函数（阻止面试期间的自动批准）

#### 11.1 关键词注册表结构

| 关键词 | 触发技能 | 优先级 | 需要意图验证 | 说明 |
|--------|----------|--------|------------|------|
| `$ralph` | `ralph_loop` | 10 | ❌ | 启动 RALPH 持久化循环 |
| `$team` / `$swarm` | `team_execution` | 20 | ✅ | 团队并行执行（高风险） |
| `$ralplan` | `ralplan` | 25 | ❌ | 生成并审批执行计划 |
| `$pipeline` | `pipeline_orchestrator` | 18 | ❌ | 多阶段工作流管道 |
| `$deep-interview` | `deep_interview` | 15 | ❌ | 深度需求澄清流程 |
| `$review` | `code_review` | 14 | ❌ | 五轴代码审查 |
| `$test` | `test_engineer` | 13 | ❌ | 测试工程师工作流 |
| `$build` | `incremental_implementation` | 16 | ❌ | 增量 TDD 实现 |
| `$ship` | `shipping_and_launch` | 17 | ❌ | 预发布清单检查 |

**优先级规则**: 数值越高优先级越高（`ralplan`=25 > `team`=20 > `pipeline`=18 > `build`=16 > `ship`=17 > `deep-interview`=15 > `review`=14 > `test`=13 > `ralph`=10）；相同优先级按关键词长度排序

#### 11.2 执行门控 (Execution Gate)

**受保护的高风险关键词**:
```python
EXECUTION_GATE_KEYWORDS = {'ralph', 'autopilot', 'team', 'ultrawork', 'swarm'}
```

**Gate 逻辑流程**:
1. 检测到受保护关键词 → 检查是否为 `underspecified`（使用 `WELL_SPECIFIED_SIGNALS`）
2. 如果提示模糊 → 自动重定向到 `$ralplan` 规划阶段
3. 如果满足绕过条件 → 直接执行原始关键词

**绕过条件**:
- 前缀: `force:`, `!`（强制跳过 Gate）
- 已包含 `$ralplan` 关键词（显式规划）
- 取消操作: `cancel`, `abort`, `stop`

#### 11.3 Well-Specified 信号检测

系统检测 15+ 正则模式验证提示完整性：

| 信号类型 | 示例正则 | 说明 |
|---------|---------|------|
| 文件引用 | `\b[\w/.-]+\.(?:py|ts|js|go|rs)\b` | 明确的文件路径 |
| 代码结构 | `\b(?:function|class|method)\s+\w+` | 代码实体引用 |
| VCS 引用 | `PR\s*#\d+`, `commit\s+[0-9a-f]{7}` | Pull Request / Commit |
| 测试语言 | `\b(?:should|must|expect)\s+(?:return|throw)` | 验收标准 |
| 错误信息 | `TypeError`, `ReferenceError`, `error:` | 错误追踪 |
| 代码块 | ````[\s\S]{20,}?````` | Markdown 代码块（≥20字符） |

缺失这些信号 → 触发 ralplan-first gate → 重定向到规划阶段

#### 11.4 Deep Interview 输入锁

当 `$deep-interview` 技能激活时，输入锁会阻止某些自动批准快捷方式（如 `yes`, `proceed`, `continue`），直到面试完成。

**相关函数**:
- `get_deep_interview_lock_state()` - 获取锁状态
- `is_deep_interview_input_blocked()` - 检查用户输入是否被阻止
- `release_deep_interview_on_cancel()` - 取消时释放锁

**使用示例**:
```python
from src.agent.keyword_registry import detect_keywords, apply_ralplan_gate

# 1. 提取显式技能调用
triggers = detect_keywords("$team 请实现 OAuth2 登录")
# → [KeywordTrigger(keyword='team', skill='team_execution', priority=20)]

# 2. 应用执行门控（智能重定向）
keywords = [get_trigger_by_keyword('team')]
gated = apply_ralplan_gate(keywords, "实现登录功能")
# 如果提示模糊，返回 [ralplan_trigger] 而非 [team_trigger]

# 3. 记录技能激活状态（用于 Deep Interview 输入锁）
record_skill_activation('deep-interview', workdir=Path.cwd())
```

---

### 12. 任务规模检测 (`src/agent/task_size_detector.py`)

**问题**: 项目A缺乏任务规模评估机制，容易对小任务过度编排或对大任务准备不足，项目B提供了四级规模分类系统以实现智能资源分配。

**方案**:
- 借鉴 oh-my-codex 的任务规模检测器
- 实现 `classify_task_size()` 函数，返回任务规模：`TRIVIAL` / `SMALL` / `MEDIUM` / `LARGE` / `HEAVY`
- 基于多维度评估：输入长度、关键词信号、领域因素、历史数据
- 提供 `get_task_size_class()` 向后兼容函数
- 结合 Agent 推荐系统，根据规模推荐合适的执行 Agent

#### 12.1 规模分类标准

| 规模 | 判定条件（优先级从高到低） | Agent 推荐 | 编排策略 |
|------|-----------------------|------------|----------|
| **TRIVIAL** | 1. 逃逸前缀: `quick:`, `simple:`, `tiny:`<br>2. 词数 ≤ 50<br>3. 单文件修改 | `executor` / `explore` | 直接交付，跳过 ralplan |
| **SMALL** | 1. 词数 < 100<br>2. 单文件修改信号 | `executor` | 标准规划-执行 |
| **MEDIUM** | 1. 词数 100-200<br>2. 默认值 | `executor` + `planner` | 需要 task DAG |
| **LARGE** | 1. 词数 > 200<br>2. 大任务关键词: `refactor`, `migrate`, `architecture` | `architect` + `planner` + `orchestrator` | 多角色协作 |
| **HEAVY** | 1. `entire codebase` / `whole project` 信号<br>2. 多模块依赖 | `team-executor` + `multi-agent` | 全团队并行 + 辩论模式 |

#### 12.2 领域因素 (Domain Factors)

检测到的领域因素会调整规模评估:
- `database` — 涉及数据库 schema/migration
- `api` — API 设计/修改
- `auth` — 认证/授权逻辑
- `ui` / `frontend` — 界面改动
- `test` — 测试编写/修改
- `refactor` — 代码重构（权重 +1）
- `performance` — 性能优化
- `debug` — 调试/修复
- `security` — 安全补丁（触发辩论模式）

#### 12.3 复杂度分析

`analyze_task_complexity()` 计算基础置信度:
```
基础分数 = 50（默认 MEDIUM）
+ 每领域因素 * 10
+ refactor 因子 * 15
+ 词数超过阈值 * 20
- 小任务信号 * 15
```

#### 12.4 使用示例

```python
from src.agent.task_size_detector import classify_task_size, get_recommended_agent_count

# 小任务检测
size = classify_task_size("quick: 修复登录按钮颜色")
# 返回: "trivial"

# 大任务识别
size = classify_task_size("重构整个用户认证系统，包括数据库迁移、API 更新和前端组件")
# 返回: "large"

# Agent 数量推荐
count = get_recommended_agent_count("large", domain_factors=['database', 'api'])
# 返回: 3（需要 architect + planner + executor 并行）

# 完整任务分析
result = analyze_task_complexity("设计新的支付网关集成方案")
# 返回: TaskComplexity(size='large', confidence=0.75, agent_count=2, factors=['api', 'payment'])
```

---

## 后续优化建议 (项目B遗留)

虽然整合已完成，但以下优化可在未来考虑：

### 10. 意图路由系统 (`src/agent/intent_router.py`)

**问题**: 项目A的意图识别较为基础，项目B提供了更精细的五意图分类系统（DELIVER/EXPLORE/EVOLVE/IMPLEMENT/DEBATE），需要集成以实现智能任务路由。

**方案**:
- 借鉴 oh-my-codex 的五意图分类体系
- 实现 `IntentType` 枚举定义五种意图类型
- `classify_intent()` 函数返回单一意图（按优先级匹配第一个）
- `classify_intent_ranked()` 函数返回所有匹配意图及置信度得分（降序）
- `has_explicit_debate_intent()` 检测明确的辩论/审查意图
- `get_primary_intent()` 为向后兼容提供 `classify_intent` 的别名
- 感知执行上下文：通过意图分类决定资源分配和验证策略

**函数说明**:

| 函数 | 签名 | 说明 |
|------|------|------|
| `classify_intent` | `(text: str) -> str` | 单一意图分类，按优先级顺序匹配（DEBATE→EXPLORE→EVOLVE→IMPLEMENT→DELIVER），返回第一个匹配的意图字符串 |
| `classify_intent_ranked` | `(text: str) -> List[Tuple[str, float]]` | 多意图置信度排序，统计各意图匹配模式数量并加权计算分数，返回降序列表 |
| `has_explicit_debate_intent` | `(text: str) -> bool` | 检测明确的辩论/审查意图，匹配 `debate`、`review`、`security review`、`code review` 等关键词 |
| `get_primary_intent` | `(text: str) -> str` | `classify_intent` 的别名，保持向后兼容 |

**意图类型定义** (`IntentType` 枚举):

| 值 | 标签 | 典型关键词 | 推荐执行车道 | 验证策略 |
|----|----|-------------|-------------|----------|
| `deliver` | DELIVER | execute, run, complete, finish | Standard | 普通单元测试 |
| `explore` | EXPLORE | search, find, analyze, investigate, discover | Fast Lane | 无需代码验证，生成报告 |
| `evolve` | EVOLVE | improve, optimize, enhance, refine, upgrade | Frontier | Architect 评审，接受成功标准 |
| `implement` | IMPLEMENT | add, create, build, make, develop, write | Deep Worker | 强制 80%+ 测试覆盖率 |
| `debate` | DEBATE | review, critique, challenge, disagree, argue, question | Multi-Agent | 逻辑一致性与证据链检查 |

**使用示例**:
```python
from src.agent.intent_router import classify_intent, classify_intent_ranked, IntentType

# 单一意图分类
intent = classify_intent("请重构用户认证模块 → 返回 IntentType.IMPLEMENT (实现意图)

# 多意图排序（适用于需要多意图支持的场景）
ranked = classify_intent_ranked("分析代码库性能瓶颈并提出优化方案")
# 返回: [("explore", 0.6), ("evolve", 0.3), ("implement", 0.3)]

# 明确辩论意图检测
is_debate = has_explicit_debate_intent("请审查这段代码的安全性")
# 返回: True（匹配了 "review" 关键词）
```

**下游影响**:
- **资源分配**: EVOLVE/DEBATE 使用 Frontier 模型，EXPLORE 使用 FAST 模型
- **验证策略**: DEBATE 跳过单元测试，启用证据链检查；IMPLEMENT 要求 80%+ 覆盖率
- **Agent 选择**: DELIVER → executor；EXPLORE → explore；EVOLVE → architect；DEBATE → code-reviewer + multi-agent

---

### 11. 关键词注册表 (`src/agent/keyword_registry.py`)

**问题**: 项目A的技能激活机制较为简单，项目B提供了结构化的关键词注册表、优先级排序和执行门控机制，需要集成以实现智能技能路由。

**方案**:
- 引入 `KeywordTrigger` 不可变数据类（keyword, skill, priority, requires_intent, description）
- 注册 40+ 技能关键词（如 ralph, team, swarm, deep-interview, ralplan, pipeline 等）
- 实现 `EXECUTION_GATE_KEYWORDS` 执行门控关键词集合（需通过 ralplan-first gate）
- 定义 `WELL_SPECIFIED_SIGNALS` 15+ 正则模式（验证提示完整性）
- 提供 `detect_keywords()` 主函数（结合显式调用检测和意图验证）
- 实现 `apply_ralplan_gate()` 函数（ralplan-first Gate 逻辑）
- 添加 Deep Interview 输入锁相关函数（阻止面试期间的自动批准）

#### 11.1 关键词注册表结构

| 关键词 | 触发技能 | 优先级 | 需要意图验证 | 说明 |
|--------|----------|--------|------------|------|
| `$ralph` | `ralph_loop` | 10 | ❌ | 启动 RALPH 持久化循环 |
| `$team` / `$swarm` | `team_execution` | 20 | ✅ | 团队并行执行（高风险） |
| `$ralplan` | `ralplan` | 25 | ❌ | 生成并审批执行计划 |
| `$pipeline` | `pipeline_orchestrator` | 18 | ❌ | 多阶段工作流管道 |
| `$deep-interview` | `deep_interview` | 15 | ❌ | 深度需求澄清流程 |
| `$review` | `code_review` | 14 | ❌ | 五轴代码审查 |
| `$test` | `test_engineer` | 13 | ❌ | 测试工程师工作流 |
| `$build` | `incremental_implementation` | 16 | ❌ | 增量 TDD 实现 |
| `$ship` | `shipping_and_launch` | 17 | ❌ | 预发布清单检查 |

**优先级规则**: 数值越高优先级越高（`ralplan`=25 > `team`=20 > `pipeline`=18 > `build`=16 > `ship`=17 > `deep-interview`=15 > `review`=14 > `test`=13 > `ralph`=10）；相同优先级按关键词长度排序

#### 11.2 执行门控 (Execution Gate)

**受保护的高风险关键词**:
```python
EXECUTION_GATE_KEYWORDS = {'ralph', 'autopilot', 'team', 'ultrawork', 'swarm'}
```

**Gate 逻辑流程**:
1. 检测到受保护关键词 → 检查是否为 `underspecified`（使用 `WELL_SPECIFIED_SIGNALS`）
2. 如果提示模糊 → 自动重定向到 `$ralplan` 规划阶段
3. 如果满足绕过条件 → 直接执行原始关键词

**绕过条件**:
- 前缀: `force:`, `!`（强制跳过 Gate）
- 已包含 `$ralplan` 关键词（显式规划）
- 取消操作: `cancel`, `abort`, `stop`

#### 11.3 Well-Specified 信号检测

系统检测 15+ 正则模式验证提示完整性：

| 信号类型 | 示例正则 | 说明 |
|---------|---------|------|
| 文件引用 | `\b[\w/.-]+\.(?:py|ts|js|go|rs)\b` | 明确的文件路径 |
| 代码结构 | `\b(?:function|class|method)\s+\w+` | 代码实体引用 |
| VCS 引用 | `PR\s*#\d+`, `commit\s+[0-9a-f]{7}` | Pull Request / Commit |
| 测试语言 | `\b(?:should|must|expect)\s+(?:return|throw)` | 验收标准 |
| 错误信息 | `TypeError`, `ReferenceError`, `error:` | 错误追踪 |
| 代码块 | ````[\s\S]{20,}?````` | Markdown 代码块（≥20字符） |

缺失这些信号 → 触发 ralplan-first gate → 重定向到规划阶段

#### 11.4 Deep Interview 输入锁

当 `$deep-interview` 技能激活时，输入锁会阻止某些自动批准快捷方式（如 `yes`, `proceed`, `continue`），直到面试完成。

**相关函数**:
- `get_deep_interview_lock_state()` - 获取锁状态
- `is_deep_interview_input_blocked()` - 检查用户输入是否被阻止
- `release_deep_interview_on_cancel()` - 取消时释放锁

**使用示例**:
```python
from src.agent.keyword_registry import detect_keywords, apply_ralplan_gate

# 1. 提取显式技能调用
triggers = detect_keywords("$team 请实现 OAuth2 登录")
# → [KeywordTrigger(keyword='team', skill='team_execution', priority=20)]

# 2. 应用执行门控（智能重定向）
keywords = [get_trigger_by_keyword('team')]
gated = apply_ralplan_gate(keywords, "实现登录功能")
# 如果提示模糊，返回 [ralplan_trigger] 而非 [team_trigger]

# 3. 记录技能激活状态（用于 Deep Interview 输入锁）
record_skill_activation('deep-interview', workdir=Path.cwd())
```

---

### 12. 任务规模检测 (`src/agent/task_size_detector.py`)

**问题**: 项目A缺乏任务规模评估机制，容易对小任务过度编排或对大任务准备不足，项目B提供了四级规模分类系统以实现智能资源分配。

**方案**:
- 借鉴 oh-my-codex 的任务规模检测器
- 实现 `classify_task_size()` 函数，返回任务规模：`TRIVIAL` / `SMALL` / `MEDIUM` / `LARGE` / `HEAVY`
- 基于多维度评估：输入长度、关键词信号、领域因素、历史数据
- 提供 `get_task_size_class()` 向后兼容函数
- 结合 Agent 推荐系统，根据规模推荐合适的执行 Agent

#### 12.1 规模分类标准

| 规模 | 判定条件（优先级从高到低） | Agent 推荐 | 编排策略 |
|------|-----------------------|------------|----------|
| **TRIVIAL** | 1. 逃逸前缀: `quick:`, `simple:`, `tiny:`<br>2. 词数 ≤ 50<br>3. 单文件修改 | `executor` / `explore` | 直接交付，跳过 ralplan |
| **SMALL** | 1. 词数 < 100<br>2. 单文件修改信号 | `executor` | 标准规划-执行 |
| **MEDIUM** | 1. 词数 100-200<br>2. 默认值 | `executor` + `planner` | 需要 task DAG |
| **LARGE** | 1. 词数 > 200<br>2. 大任务关键词: `refactor`, `migrate`, `architecture` | `architect` + `planner` + `orchestrator` | 多角色协作 |
| **HEAVY** | 1. `entire codebase` / `whole project` 信号<br>2. 多模块依赖 | `team-executor` + `multi-agent` | 全团队并行 + 辩论模式 |

#### 12.2 领域因素 (Domain Factors)

检测到的领域因素会调整规模评估:
- `database` — 涉及数据库 schema/migration
- `api` — API 设计/修改
- `auth` — 认证/授权逻辑
- `ui` / `frontend` — 界面改动
- `test` — 测试编写/修改
- `refactor` — 代码重构（权重 +1）
- `performance` — 性能优化
- `debug` — 调试/修复
- `security` — 安全补丁（触发辩论模式）

#### 12.3 复杂度分析

`analyze_task_complexity()` 计算基础置信度:
```
基础分数 = 50（默认 MEDIUM）
+ 每领域因素 * 10
+ refactor 因子 * 15
+ 词数超过阈值 * 20
- 小任务信号 * 15
```

#### 12.4 使用示例

```python
from src.agent.task_size_detector import classify_task_size, get_recommended_agent_count

# 小任务检测
size = classify_task_size("quick: 修复登录按钮颜色")
# 返回: "trivial"

# 大任务识别
size = classify_task_size("重构整个用户认证系统，包括数据库迁移、API 更新和前端组件")
# 返回: "large"

# Agent 数量推荐
count = get_recommended_agent_count("large", domain_factors=['database', 'api'])
# 返回: 3（需要 architect + planner + executor 并行）

# 完整任务分析
result = analyze_task_complexity("设计新的支付网关集成方案")
# 返回: TaskComplexity(size='large', confidence=0.75, agent_count=2, factors=['api', 'payment'])
```

---

## 后续优化建议 (项目B遗留)

虽然整合已完成，但以下优化可在未来考虑：

## 后续优化建议 (项目B遗留)

虽然整合已完成，但以下优化可在未来考虑：

### 2026-04-18 新增整合 (P0)

1. ✅ **关键词检测系统** - 40+ 技能关键词、优先级、意图验证、ralplan-first Gate
2. ✅ **意图路由** - DELIVER/EXPLORE/EVOLVE/IMPLEMENT/DEBATE 五种意图分类
3. ✅ **任务规模检测** - small/medium/large/heavy 分类 + Agent 推荐系统

### 待完成优化 (项目B遗留)

1. **Rust 性能组件** - 评估是否引入 `omx-sparkshell` 等效模块替代 Python 的 BashTool
2. **Telemetry 集成** - 集成 Langfuse/Braintrust（项目B已支持）
3. **Team TMUX模式** - 当前仅实现骨架，需集成 `omx-mux` 的并发 Worker 协议
4. **Code Intel MCP** - 代码智能服务器需填充具体实现（符号索引 + 跳转）
5. **Surface 管理** - 可考虑简化14个Surface为8个核心必需Surface

---

## 总结

通过系统性地吸收 Oh-My-Codex 的架构优势，Clawd Code 现已具备：

| 新能力 | 对应模块 | 获益 |
|--------|---------|------|
| **动态配置生成** | `generator.py` | 无缝集成外部工具 |
| **声明式 Hook** | `hooks_config.py` | 运维友好、无需改代码 |
| **独立探索模式** | `explore.py` | 分析更专注、无副作用 |
| **自动化质检** | `quality_gate.py` | CI/CD 友好、质量可控 |
| **标准协议集成** | `mcp/` (5 servers) | 生态兼容 |
| **持久化规划** | `ralplan.py` | 计划可 review、版本化 |
| **端到端流水线** | `pipeline_orchestrator.py` | 一键执行完整交付链 |
| **智能意图路由** | `intent_router.py` | 5种意图自动分类 |
| **关键词检测与门控** | `keyword_registry.py` | 40+ 关键词 + ralplan-first Gate |
| **任务规模检测** | `task_size_detector.py` | small/medium/large/heavy 自动分类 + Agent推荐 |
| **实时状态反馈** | `hud_improved.py` + `notifications/` | 用户体验提升 |
| **状态持久化** | `workspace.py`, `state.py` | 跨会话恢复、隔离执行 |
| **事件增强** | `events.py` (新事件类型) + `serialization.py` | 权限调度事件、类型安全序列化 |
| **运行时错误** | `exceptions.py` (STATE_*) | 状态/调度相关错误处理 |

本次整合**无破坏性改动**，不影响已有功能和测试，为下一阶段（生产部署、团队协作、外部集成）打下了坚实基础。

# Clawd Code 工作流引擎技术指南

## 1. 概述

Clawd Code 的工作流引擎是基于 **GoalX** 设计理念的高级执行框架。它不再仅仅是顺序执行命令，而是围绕“意图”和“认知表面”构建的闭环系统。

## 2. 五阶段执行管道 (The 5-Phase Pipeline)

每一个工作流任务都会经历以下五个标准阶段：

1.  **定义 (Define)**:
    *   读取 `Charter` 和 `Objective Contract`。
    *   通过 `Intent Routing` 确定任务性质（如 EXPLORE 或 IMPLEMENT）。
    *   初始化 `Assurance Plan`。
2.  **计划 (Plan)**:
    *   `Orchestrator` 生成任务依赖图 (Task DAG)。
    *   根据代码库现状 (World Model) 评估修改范围。
3.  **构建 (Build/Execute)**:
    *   Agent 在 `Worktree Isolation` 中执行具体的代码编辑。
    *   `Budget Guard` 实时监控消耗，防止失控。
4.  **验证 (Verify)**:
    *   运行自动化测试套件。
    *   `Auditor` 进行代码审计。
    *   记录 `Evidence Log`。
5.  **交付 (Deliver/Ship)**:
    *   将工作树中的变更合并回主源码。
    *   更新 `Status Summary` 和 `Freshness State`。

## 3. 意图路由与智能关键词检测 (Intent Routing & Keyword Detection)

系统采用三层路由决策机制：**意图分类 → 关键词检测 → 任务规模评估**。

### 3.1 意图分类 (Intent Classification)

意图路由决定了引擎的资源分配和验证策略：

| 意图 (Intent) | 说明 | 验证逻辑 | 失败处理 |
| :--- | :--- | :--- | :--- |
| **DELIVER** | 快速交付已知的修复或功能 | 运行相关单元测试 | 记录失败并退出 |
| **EXPLORE** | 针对未知问题的只读研究 | 无需代码验证 | 生成调查报告 |
| **IMPLEMENT** | 完整的需求实现工作流 | 强制 80%+ 测试覆盖率 | 触发自愈循环 |
| **EVOLVE** | 探索式演进，自动尝试多种方案 | 满足成功标准即可 | 自动尝试替代路径 |
| **DEBATE** | 多模型针对特定设计进行辩论 | 逻辑一致性与证据链检查 | 人工干预 |

优先级顺序: `DEBATE` > `EXPLORE` > `EVOLVE` > `IMPLEMENT` > `DELIVER`

实现参考: [`src/agent/intent_router.py`](../src/agent/intent_router.py)

### 3.2 关键词注册表与技能激活 (Keyword Registry)

除意图分类外，系统还检测显式关键词触发专用技能或工作流：

#### 显式技能调用语法

- `$ralph` - 启动 RALPH 持久化循环执行
- `$team` / `$swarm` - 启动团队并行执行模式
- `$ralplan` - 生成并审批执行计划
- `$pipeline` - 执行多阶段工作流管道
- `$deep-interview` - 启动深度需求澄清流程
- `$review`, `$test`, `$build`, `$ship` - 对应技能快速调用

#### 执行门控 (Execution Gate)

受保护的高风险关键词: `ralph`, `autopilot`, `team`, `swarm`, `ultrawork`

**Gate 逻辑**: 当检测到这些关键词时，系统会检查：
1. 提示是否 well-specified（15+ 正则模式验证）
2. 是否满足绕过条件（`force:` 或 `!` 前缀，或已包含 `$ralplan`）

如果提示模糊（underspecified），自动重定向到 `ralplan` 规划阶段，而非直接执行。

#### Well-Specified 信号检测

系统检测以下信号判断提示完整性：
- **文件引用**: 明确的文件路径（`.py`, `.ts`, `.go` 等）
- **代码结构**: `function`, `class`, `interface` 等关键字
- **VCS 引用**: `PR #123`, `commit abc123`
- **测试语言**: `should return`, `must throw`, `acceptance criteria`
- **错误信息**: `TypeError`, `stack trace`, `error:`
- **代码块**: 包含 20+ 字符的 markdown 代码块

缺失这些信号 → 触发 ralplan-first gate → 重定向到规划阶段。

实现参考: [`src/agent/keyword_registry.py`](../src/agent/keyword_registry.py)

### 3.3 任务规模检测 (Task Size Detection)

自动分类任务规模，避免过度编排小任务或低估大任务：

| 规模 | 判定条件 | Agent 推荐 | 编排策略 |
| :--- | :--- | :--- | :--- |
| **TRIVIAL** | 逃逸前缀 (`quick:`, `simple:`) 或 <50 词 | `explore` / `executor` | 直接交付，跳过规划 |
| **SMALL** | <100 词，单文件修改 | `executor` | 标准规划-执行流程 |
| **MEDIUM** | 默认，100-200 词 | `executor` + `planner` | 需要 task DAG |
| **LARGE** | >200 词或 refactor/migrate 关键词 | `architect` + `planner` + `orchestrator` | 多角色协作 |
| **HEAVY** | 整个 codebase 级别改动 | `team-executor` + `multi-agent` | 全团队并行 + 辩论模式 |

规模检测维度:
- 输入长度（词数统计）
- 关键词信号（"整个项目", "重构", "迁移" 等）
- 领域因素（database, api, auth, ui, test, performance, security）
- 文件涉及数量估算

实现参考: [`src/agent/task_size_detector.py`](../src/agent/task_size_detector.py)

## 4. Pipeline 管道编排 (RALPLAN → TEAM → RALPH)

## 5. Pipeline 管道编排 (RALPLAN → TEAM_EXEC → RALPH)

Pipeline 将五个标准阶段串联为端到端的执行流水线：

```bash
clawd pipeline "重构认证模块" --budget 5usd
```

### 5.1 三阶段序列

```
User Input
    ↓
┌─────────────────────────────────────────┐
│  Stage 1: RALPLAN (共识规划)             │
│  - Planner 提案 → Architect 评审 → Critic 挑战
│  - 输出: consensus.json (plan artifacts)
└─────────────────┬───────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│  Stage 2: TEAM_EXEC (团队执行)           │
│  - 并行 Agent 执行（Orchestrator 调度）
│  - Team Persistence 状态同步
│  - 输出: execution-results.json
└─────────────────┬───────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│  Stage 3: RALPH (验证循环)               │
│  - 逐项验证交付物
│  - 生成 RALPH 账本
│  - 输出: ralph-ledger.json
└─────────────────────────────────────────┘
```

### 5.2 Stage 接口

```python
@dataclass
class StageContext:
    task: str                    # 原始任务描述
    artifacts: dict             # 前一阶段的制品
    previous_stage_result: Optional[StageResult]

@dataclass
class StageResult:
    status: StageStatus         # PASS / FAIL / SKIP
    artifacts: dict            # 本阶段产出
    duration_ms: int           # 执行耗时
    error: Optional[str]       # 错误信息
```

### 5.3 模式状态持久化与独占模式

Pipeline 的状态由 ModeState 系统管理（`src/workflow/mode_state.py`）：

- **状态文件**: `.clawd/state/mode-pipeline.json`
- **支持模式**: `pipeline`, `team`, `skill`, `autopilot`, `ralph`, `ultrawork`, `deep-interview`
- **独占模式互斥**: `autopilot`, `ralph`, `ultrawork` 不能同时运行
- **跨会话恢复**: `recover=True` 可从持久化状态恢复执行

实现参考: [`src/workflow/pipeline_orchestrator.py`](../src/workflow/pipeline_orchestrator.py), [`src/workflow/mode_state.py`](../src/workflow/mode_state.py)

## 6. 资源安全 (Budget Guard)

工作流引擎集成了 `BudgetGuard`，它在每个执行步骤前执行 `can_execute()` 检查：
-   **PSI (Pressure Stall Information)**: 监控系统内存、I/O 压力。
-   **RSS (Resident Set Size)**: 限制进程组的最大内存占用。
-   **Cost/Token**: 计算 LLM 调用成本。

## 7. 状态持久化

工作流的所有中间状态均存储在运行目录的 `control/` 文件夹下，以标准 JSON 格式持久化。即使进程中断，系统也可以通过加载这些"认知表面"恢复执行上下文。

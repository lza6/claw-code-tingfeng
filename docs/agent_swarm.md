# Clawd Code Swarm 多代理系统技术指南

## 1. 架构设计

Swarm 系统采用 **Orchestrator-Worker (Inbox)** 模式，灵感来自 GoalX 和 SlackBot 实现。

### 1.1 核心组件

-   **Orchestrator**: 任务分发中心，根据 `TaskRegistry` 决定将任务分发给哪个 Worker。
-   **Worker (Inbox)**: 接收来自 `PersistentMessageBus` (PMB) 的任务消息。
-   **MessageBus (Inbox)**: 基于 Git 或 SQLite 的持久化消息中间件。
-   **Debate Engine**: 支持多模型并行论证。

## 2. 智能路由层 (Intent Routing & Keyword Detection)

借鉴 oh-my-codex 的五意图分类与关键词检测系统，在 Swarm 调度前增加智能路由层：

### 2.1 意图路由 (Intent Routing)

系统自动将用户输入分类为五种意图类型：

| 意图 | 标识 | 典型关键词 | 推荐执行车道 | 下游影响 |
| :--- | :--- | :--- | :--- | :--- |
| **EXPLORE** | `explore` | search, find, analyze, list, show me | Fast Lane | 只读分析，生成 Markdown 报告 |
| **IMPLEMENT** | `implement` | add, create, build, write, develop | Deep Worker | 进入标准工作流 |
| **DELIVER** | `deliver` | execute, run, complete, finish | Standard | 直接执行，跳过规划 |
| **EVOLVE** | `evolve` | improve, optimize, enhance, upgrade | Frontier | 需要 Architect 评审 |
| **DEBATE** | `debate` | review, critique, challenge, question | Multi-Agent | 触发辩论模式 |

优先级顺序（高 → 低）: `DEBATE` > `EXPLORE` > `EVOLVE` > `IMPLEMENT` > `DELIVER`

实现参考: [`src/agent/intent_router.py`](../src/agent/intent_router.py)

### 2.2 关键词注册表 (Keyword Registry)

系统维护结构化关键词注册表，支持技能自动激活：

| 关键词 | 触发技能 | 优先级 | 需要意图验证 |
| :--- | :--- | :--- | :--- |
| `$ralph` | `ralph_loop` | 10 | ❌ |
| `$team` / `$swarm` | `team_execution` | 20 | ✅ |
| `$ralplan` | `ralplan` | 25 | ❌ |
| `$pipeline` | `pipeline_orchestrator` | 18 | ❌ |
| `$deep-interview` | `deep_interview` | 15 | ❌ |
| `$review`, `$test`, `$build`, `$ship` | 对应技能 | 12-17 | ❌ |

**执行门控 (Execution Gate)**:
- **受保护关键词**: `ralph`, `autopilot`, `team`, `swarm`, `ultrawork`
- **Gate 逻辑**: 高风险操作须通过 ralplan-first gate（除非明确绕过）
- **绕过方式**:
  - 前缀: `force:`, `!`（强制跳过）
  - 已包含 `$ralplan` 关键词
  - 取消操作: `cancel`, `abort`, `stop`

**Well-Specified 信号检测**:
系统检测 15+ 正则模式以验证提示完整性，包括文件引用、代码结构、VCS 引用、测试语言等。缺失信号 → 自动重定向到 `ralplan` 规划阶段。

实现参考: [`src/agent/keyword_registry.py`](../src/agent/keyword_registry.py)

### 2.3 任务规模检测 (Task Size Detection)

通过多维度分析自动分类任务规模，避免过度编排：

| 规模 | 判定条件 | Agent 推荐 | 编排策略 |
| :--- | :--- | :--- | :--- |
| **TRIVIAL** | 逃逸前缀 (`quick:`, `simple:`) 或 <50 词 | `explore` / `executor` | 直接交付 |
| **SMALL** | <100 词，单文件修改 | `executor` | 标准流程 |
| **MEDIUM** | 默认，100-200 词 | `executor` + `planner` | 规划 + 执行 |
| **LARGE** | >200 词或 refactor/migrate 关键词 | `architect` + `planner` + `orchestrator` | 多角色协作 |
| **HEAVY** | 整个 codebase 级别改动 | `team-executor` + `multi-agent` | 全团队并行 |

实现参考: [`src/agent/task_size_detector.py`](../src/agent/task_size_detector.py)

## 3. 消息通信协议

### 3.1 消息类型

```python
from src.agent.swarm.message_bus import MessageType

# 任务分配
MessageType.TASK_ASSIGN

# 任务就绪
MessageType.TASK_READY

# 中间进度
MessageType.PROGRESS

# 结果提交
MessageType.RESULT

# 审计请求
MessageType.AUDIT_REQUEST
```

### 3.2 Inbox 轮询机制

每个 Worker 维护一个本地 Inbox (JSON 文件)，通过定期轮询检查新任务：

```python
class Inbox:
    def poll_unread(self):
        """汲取 GoalX: 轮询持久化 Inbox 处理未读消息"""
        # 扫描 inbox/*.json
        # 按时间戳排序
        # 返回待处理消息列表
```

## 4. 角色与职责

| 角色 | 主要职责 | 使用的认知表面 |
| :--- | :--- | :--- |
| **Coder** | 代码实现、重构 | Objective Contract, Evidence Log |
| **Architect** | 系统设计、技术选型 | Charter, Obligation Model |
| **Auditor** | 代码审计、安全检查 | Assurance Plan, Control State |
| **Integrator** | 结果合并、冲突解决 | Status Summary, Coordination State |

### 4.1 精细化角色定义体系 (v0.50.0)

借鉴 oh-my-codex，每个 Agent 具有六维属性：

| 维度 | 选项 | 说明 |
| :--- | :--- | :--- |
| **推理级别** | LOW / MEDIUM / HIGH / XHIGH | 决定模型推理投入 |
| **Agent 姿态** | FRONTIER_ORCHESTRATOR / DEEP_WORKER / FAST_LANE | 角色定位 |
| **模型类别** | FRONTIER / STANDARD / FAST | 推荐模型层级 |
| **路由角色** | LEADER / SPECIALIST / EXECUTOR | 协调职责 |
| **工具访问** | READ_ONLY / ANALYSIS / EXECUTION / DATA | 能力边界 |
| **分类** | BUILD / REVIEW / DOMAIN / PRODUCT / COORDINATION | 功能分类 |

完整角色矩阵参见 [`src/agent/definitions.py`](../src/agent/definitions.py)

## 5. 任务生命周期

1.  **注册**: Task 注册到 `TaskRegistry`。
2.  **分发**: `Orchestrator` 根据技能匹配度分配消息到 Worker Inbox。
3.  **执行**: Worker 处理任务，更新 `Evidence Log`。
4.  **提交**: Worker 提交结果到 PMB。
5.  **集成**: `Integrator` 汇总结果，更新 `Control State`。

## 5. 辩论模式 (Debate Mode)

对于架构性决策或关键安全补丁，系统会自动启动辩论模式：

1.  **加载历史运行**: 从 `Evidence Log` 或 `status-summary.json` 加载上下文。
2.  **构建论据**: 正反双方基于代码现状构建证据链。
3.  **交叉质证**: LLM 互相挑战对方的方案假设。
4.  **最终投票**: 依据证据完整度选择最终方案。

## 6. 自愈与原子化回滚

当审计失败时：
-   `Self-Healing Engine` 分析错误根因。
-   自动生成修复补丁。
-   如果修复失败，通过 `WorktreeManager` 回滚到上一个已知的健康状态。
# Clawd Code 架构全景图 (Architecture Overview)

**最后更新日期：** 2026-04-14
**核心版本：** v0.50.0 (GoalX 集成版)

## 1. 核心架构设计

Clawd Code 采用 **"感知-决策-执行-验证" (Perception-Decision-Action-Verification)** 的闭环架构，专为高度自动化的 AI 编程场景优化，并集成了 **GoalX** 持久化认知表面。

### 1.1 分层模型

-   **意识层 (Consciousness - `src/brain/`)**: 负责代码库全量感知。通过 `WorldModel` 维护项目拓扑与语义索引，利用 **Enterprise-Grade RAG** 提供毫秒级的符号查找与依赖分析。
-   **决策层 (Orchestration - `src/agent/`)**: 采用 **Swarm 多代理集群**。由 `Orchestrator` 分解任务，Worker 代理执行具体指令。集成了 **Intent Routing (意图路由)** 机制（DELIVER, EXPLORE, EVOLVE 等）。
-   **执行层 (Execution - `src/tools_runtime/`)**: 集成 Aider 风格的高性能编辑引擎。支持多种原子化代码修改协议，并具备 **Worktree Isolation (工作树隔离)** 能力，确保并行任务互不干扰。
-   **自愈层 (Self-healing - `src/self_healing/`)**: 实时监控执行错误，结合 **Evidence Log (证据日志)** 进行故障诊断与自动修复。
-   **安全与资源层 (Safety & Budget - `src/core/`)**: **Budget Guard (预算守卫)** 实时监控 CPU、内存、Token 和时间消耗，确保系统运行在安全阈值内。

## 2. 关键核心技术 (GoalX 增强)

### 2.1 规范化认知表面 (Canonical Surfaces)
系统维护 9 个核心持久化表面，确保跨会话的认知一致性：
-   **Charter**: 项目宪章与约束。
-   **Objective Contract**: 明确的任务目标与成功标准。
-   **Assurance Plan**: 质量保证方案与测试策略。
-   **Control State**: 运行时的意图路由与状态管理。
-   **Freshness State**: 认知新鲜度跟踪。

### 2.2 预算守卫 (Budget Guard)
汲取 GoalX 资源安全机制，提供：
-   **实时熔断**: 当 Token 成本、时间或资源压力（PSI, RSS）超过预设时自动停止。
-   **动态调整**: 支持根据任务优先级动态扩展资源预算。

### 2.3 工作树隔离 (Worktree Isolation)
利用 Git Worktree 实现：
-   **并行执行**: 不同的 Agent 可以在独立的工作树中尝试不同方案。
-   **原子化合并**: 只有通过审计的修改才会被合并回主分支。

### 2.4 意图路由 (Intent Routing)
根据任务性质动态切换引擎模式：
-   **EXPLORE**: 只读调查模式，用于生成分析报告。
-   **IMPLEMENT**: 标准实现模式，针对明确需求进行代码修改。
-   **EVOLVE**: 演进模式，在给定预算内进行多次尝试，直至满足成功标准。
-   **DEBATE**: 辩论模式，基于历史运行证据进行多模型挑战。

### 2.5 意图澄清与脱水 (OMX 增强)
汲取 oh-my-codex 质量控制理念：
- **Clarify Gate**: 强制性苏格拉底意图澄清，明确 Non-goals 以防止过度交付。
- **Deslop Pass**: 自动代码脱水，剔除 AI 生成的语义冗余与自明性注释。
- **Consensus Planning**: 引入 Planner-Architect-Critic 三方博弈，通过“最强钢人论证”确保方案严谨。

## 3. 核心模块与设计模式

| 模块 | 设计模式 | 职责 |
| :--- | :--- | :--- |
| `OrchestratorAgent` | **Command / Strategy** | 任务分解与动态路由分发 |
| `PersistentMessageBus` | **Observer / Inbox** | 基于持久化 Inbox 的代理间异步通信 |
| `RepositoryWorldModel` | **Facade / Singleton** | 统一的代码库感知与 RAG 接口 |
| `BudgetGuard` | **Monitor / Interceptor** | 资源消耗实时监控与熔断 |
| `PatchEngine` | **Command / Memento** | 声明式补丁应用与事务性回滚 |

## 4. 进化目标
-   **自主能力演进**：通过 `Experience Retrieval` 提升代理对复杂重构的决策准确度。
-   **深度辩论机制**：强化 `Debate Mode`，实现基于多维证据链的代码自动博弈与选优。

---
*文档由 Clawd Code 自动生成，实时反映系统最新架构状态。*

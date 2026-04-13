# Clawd Code 架构全景图 (Architecture Overview)

## 1. 核心架构设计

Clawd Code 采用 **"感知-决策-执行" (Perception-Decision-Action)** 的闭环架构，专为高度自动化的 AI 编程场景优化。

### 1.1 分层模型
- **意识层 (Consciousness - `src/brain/`)**: 负责代码库全量感知。通过 `WorldModel` 维护项目拓扑与语义索引，支持毫秒级的设计模式检测与依赖预测。
- **决策层 (Orchestration - `src/agent/`)**: 采用 **Swarm 多代理集群**。由 `Orchestrator` 分解任务，Worker 代理执行具体指令，`Self-fission` 机制根据任务复杂度动态孵化专业代理。
- **执行层 (Execution - `src/tools_runtime/`)**: 集成 Aider 风格的高性能编辑引擎。支持 `editblock`、`udiff` 等多种原子化代码修改协议，并具备沙箱化（Sandbox）运行环境。
- **自愈层 (Self-healing - `src/self_healing/`)**: 实时监控执行错误。通过 `Diagnoser` 诊断异常并触发 AI 驱动的自动修复流程。

## 2. 关键核心技术

### 2.1 高性能 AST 扫描器
优化后的 `WorldModel` 采用单次遍历算法（O(N) 复杂度），结合 `lru_cache` 实现企业级超大规模代码库的实时模式分析。

### 2.2 拓扑任务调度 (TaskDAG)
任务编排器利用就绪队列（Ready Queue）管理任务依赖。在处理涉及数百个子任务的复杂重构时，其调度效率保持在 O(1)。

### 2.3 原子化代码补丁
通过 `AtomicPatcher` 确保每一次代码修改均为事务性操作。如果补丁应用失败，系统会自动回滚，确保代码库始终处于可编译状态。

## 3. 核心模块与设计模式

| 模块 | 设计模式 | 职责 |
| :--- | :--- | :--- |
| `OrchestratorAgent` | **Command / Strategy** | 任务分解与动态调度策略 |
| `MessageBus` | **Observer** | 代理间的异步通信与状态同步 |
| `RepositoryWorldModel` | **Facade / Singleton** | 统一的代码库感知接口 |
| `AtomicPatcher` | **Template Method** | 规范化的补丁应用流程 |

## 4. 进化目标
目前的系统已实现 60% 的测试覆盖率，未来的进化方向包括：
- **强化学习进化**：代理通过 `RL_Experience` 自主优化任务分解策略。
- **跨语言感知**：扩展 RAG 引擎以支持更深层的多语言依赖分析。

---
*文档由 Clawd Code 自动生成，实时反映系统最新架构状态。*

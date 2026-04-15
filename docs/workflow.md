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

## 3. 意图路由 (Intent Routing)

意图路由决定了引擎的资源分配和验证策略：

| 意图 (Intent) | 说明 | 验证逻辑 | 失败处理 |
| :--- | :--- | :--- | :--- |
| **DELIVER** | 快速交付已知的修复或功能 | 运行相关单元测试 | 记录失败并退出 |
| **EXPLORE** | 针对未知问题的只读研究 | 无需代码验证 | 生成调查报告 |
| **IMPLEMENT** | 完整的需求实现工作流 | 强制 80%+ 测试覆盖率 | 触发自愈循环 |
| **EVOLVE** | 探索式演进，自动尝试多种方案 | 满足成功标准即可 | 自动尝试替代路径 |
| **DEBATE** | 多模型针对特定设计进行辩论 | 逻辑一致性与证据链检查 | 人工干预 |

## 4. 资源安全 (Budget Guard)

工作流引擎集成了 `BudgetGuard`，它在每个执行步骤前执行 `can_execute()` 检查：
-   **PSI (Pressure Stall Information)**: 监控系统内存、I/O 压力。
-   **RSS (Resident Set Size)**: 限制进程组的最大内存占用。
-   **Cost/Token**: 计算 LLM 调用成本。

## 5. 状态持久化

工作流的所有中间状态均存储在运行目录的 `control/` 文件夹下，以标准 JSON 格式持久化。即使进程中断，系统也可以通过加载这些“认知表面”恢复执行上下文。

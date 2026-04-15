# Swarm 角色自定义与协作

Clawd Code 采用多 Agent 协作系统 (Swarm)，通过定义不同职责的角色来实现复杂的工程任务。

## 预定义角色 (Core Roles)

| 角色标识 (Role ID) | 名称 | 职责描述 |
| :--- | :--- | :--- |
| `orchestrator` | 编排器 | 任务分解、Agent 调度、进度协调。 |
| `planner` | 规划师 | 技术方案设计、风险评估、实施路径规划。 |
| `worker` | 执行者 | 代码编写、测试实现、文档更新。 |
| `auditor` | 审计师 | 极其严苛的代码质量、安全、规范强制检查。 |
| `reviewer` | 审查师 | 架构一致性、可维护性及整体设计审查。 |
| `diagnostician` | 诊断专家 | 深度故障回溯、错误根因分析 (RCA)、恢复路径建议。 |
| `synthesized` | 动态专家 | **v0.50.0 新增**。根据任务上下文实时合成的专项专家。 |

## 角色协作流程

1. **分解 (Decompose)**: `orchestrator` 将用户需求拆解为任务有向无环图 (DAG)。
2. **规划 (Plan)**: `planner` 为每个原子任务制定技术方案。
3. **执行 (Work)**: `worker` 根据计划实施代码修改并编写测试。
4. **审计 (Audit)**: `auditor` 进行静态分析、安全检查和规范验证（若失败则回退至 Worker）。
5. **诊断 (Diagnose)**: 若任务多次失败，`diagnostician` 介入分析根因并提供恢复建议。

## 动态角色合成 (v0.50.0)

利用 `AgentRole.SYNTHESIZED`，系统可以根据当前任务的特定技术栈（如：ClickHouse, Web3, iOS 原生等）动态注入身份指令和专项技能集，无需手动修改源代码定义新角色。

## 如何自定义角色

目前角色定义主要存储在 `src/agent/swarm/roles.py` 中。您可以：
1. 在 `AgentRole` 枚举中添加新角色常量。
2. 在 `ROLE_DESCRIPTIONS` 中添加中文描述。
3. 在 `ROLE_SYSTEM_PROMPTS` 中配置其系统提示词 (System Prompt)。

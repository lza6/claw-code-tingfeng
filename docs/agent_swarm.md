# Clawd Code Swarm 多代理系统技术指南

## 1. 架构设计

Swarm 系统采用 **Orchestrator-Worker (Inbox)** 模式，灵感来自 GoalX 和 SlackBot 实现。

### 1.1 核心组件

-   **Orchestrator**: 任务分发中心，根据 `TaskRegistry` 决定将任务分发给哪个 Worker。
-   **Worker (Inbox)**: 接收来自 `PersistentMessageBus` (PMB) 的任务消息。
-   **MessageBus (Inbox)**: 基于 Git 或 SQLite 的持久化消息中间件。
-   **Debate Engine**: 支持多模型并行论证。

## 2. 消息通信协议

### 2.1 消息类型

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

### 2.2 Inbox 轮询机制

每个 Worker 维护一个本地 Inbox (JSON 文件)，通过定期轮询检查新任务：

```python
class Inbox:
    def poll_unread(self):
        """汲取 GoalX: 轮询持久化 Inbox 处理未读消息"""
        # 扫描 inbox/*.json
        # 按时间戳排序
        # 返回待处理消息列表
```

## 3. 角色与职责

| 角色 | 主要职责 | 使用的认知表面 |
| :--- | :--- | :--- |
| **Coder** | 代码实现、重构 | Objective Contract, Evidence Log |
| **Architect** | 系统设计、技术选型 | Charter, Obligation Model |
| **Auditor** | 代码审计、安全检查 | Assurance Plan, Control State |
| **Integrator** | 结果合并、冲突解决 | Status Summary, Coordination State |

## 4. 任务生命周期

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
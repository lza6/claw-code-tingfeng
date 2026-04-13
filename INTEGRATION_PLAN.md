# GoalX → Clawd Code 整合建议清单

**生成时间**: 2026-04-13  
**目标**: 从 GoalX (Go) 汲取优秀设计，增强 Clawd Code (Python) 的自主性和持久化能力

---

## 📋 整合策略总览

### 核心原则
1. **避免重复造轮子**: 优先复用现有模块，仅在功能缺失时新增
2. **协议优先**: 学习 GoalX 的 protocol-driven 设计，强化 Clawd 的 prompt 模板系统
3. **持久化优先**: 引入 GoalX 的 durable surfaces 理念，减少对会话历史的依赖
4. **隔离边界**: 借鉴 worktree 隔离模式，增强 Clawd 的并行执行安全性

---

## 🎯 Phase 1: 持久化状态系统 (Durable State)

### 1.1 引入 Canonical Surfaces 机制
**目标**: 减少对 LLM 会话历史的依赖，建立机器可读的状态文件

**新增文件**:
```
src/core/durable/
├── __init__.py
├── surface_manager.py       # 管理所有 durable surfaces
├── surfaces/
│   ├── objective_contract.py   # 不可变的用户目标契约
│   ├── obligation_model.py     # 可变的必须满足的条件
│   ├── assurance_plan.py       # 验证策略
│   ├── evidence_log.py         # 验证证据记录
│   ├── coordination_state.py   # 会话协调状态
│   └── status_summary.py       # 运行状态摘要
└── schemas/                    # JSON Schema 验证
    ├── objective.schema.json
    ├── obligation.schema.json
    └── assurance.schema.json
```

**修改文件**:
- `src/workflow/engine.py`: 集成 surface_manager，在每个阶段更新 durable surfaces
- `src/agent/checkpoint.py`: 扩展检查点系统，保存 canonical surfaces
- `src/core/persistence/run_state.py`: 添加 surface 快照功能

**不重复造轮子**:
- ✅ 复用现有的 `src/core/persistence/` 基础设施
- ✅ 扩展现有的 `RunStateManager`，而非新建状态管理器

---

### 1.2 Control Inbox 消息系统
**目标**: 实现 master-worker 之间的持久化消息传递

**新增文件**:
```
src/agent/swarm/control/
├── __init__.py
├── inbox.py                 # JSONL append-only inbox
├── message.py               # 消息结构定义
├── cursor.py                # 读取游标管理
└── tell.py                  # 消息发送接口
```

**修改文件**:
- `src/agent/swarm/orchestrator.py`: 使用 inbox 替代内存中的 message_bus
- `src/agent/swarm/message_bus.py`: 重构为基于文件的持久化实现

**不重复造轮子**:
- ✅ 保留现有的 `MessageBus` 接口，仅改变底层实现
- ✅ 复用 `src/core/events/` 的事件系统作为补充

---

## 🎯 Phase 2: Worktree 隔离与并行执行

### 2.1 Git Worktree 管理器
**目标**: 为并行 agent 提供隔离的工作空间

**新增文件**:
```
src/core/git/worktree/
├── __init__.py
├── manager.py               # Worktree 生命周期管理
├── isolation.py             # 隔离策略
├── merge_strategy.py        # 合并策略 (keep/discard/partial)
└── safety.py                # 安全检查 (dirty state, conflicts)
```

**修改文件**:
- `src/agent/swarm/orchestrator.py`: 为每个 worker 分配独立 worktree
- `src/workflow/engine.py`: 在 worktree 中执行任务，完成后合并
- `src/core/git/operations.py`: 扩展 git 操作支持 worktree

**不重复造轮子**:
- ✅ 复用现有的 `src/core/git/` 模块
- ✅ 扩展 `GitOperations` 类，而非新建 git 封装

---

### 2.2 Session Coordination
**目标**: 跟踪哪些 session 负责哪些任务，避免冲突

**新增文件**:
```
src/agent/swarm/coordination/
├── __init__.py
├── coordinator.py           # 会话协调器
├── coverage_map.py          # 任务覆盖映射
├── decision_log.py          # 决策记录
└── surface_availability.py  # 资源可用性跟踪
```

**修改文件**:
- `src/agent/swarm/orchestrator.py`: 集成 coordinator
- `src/workflow/task_planner.py`: 使用 coverage_map 分配任务

**不重复造轮子**:
- ✅ 复用现有的 `TaskDAG` 依赖管理
- ✅ 扩展现有的任务分配逻辑

---

## 🎯 Phase 3: 运行时监控与恢复

### 3.1 Runtime Host & Lease System
**目标**: 后台监控长时间运行的 agent，支持崩溃恢复

**新增文件**:
```
src/core/runtime/
├── __init__.py
├── host.py                  # 运行时监控主机
├── lease.py                 # 心跳租约系统
├── supervisor.py            # 进程监督器
└── recovery.py              # 崩溃恢复逻辑
```

**修改文件**:
- `src/agent/engine_loop.py`: 集成 lease 心跳
- `src/workflow/engine.py`: 支持从中断点恢复
- `src/cli/repl.py`: 添加后台运行模式

**不重复造轮子**:
- ✅ 复用现有的 `src/agent/checkpoint.py` 检查点系统
- ✅ 扩展现有的异常恢复机制

---

### 3.2 Resource Monitoring
**目标**: 监控内存/CPU 使用，防止资源耗尽

**新增文件**:
```
src/core/monitoring/
├── __init__.py
├── resource_tracker.py      # 资源使用跟踪
├── admission_control.py     # 准入控制
└── alerts.py                # 资源告警
```

**修改文件**:
- `src/agent/engine_metrics.py`: 集成 resource_tracker
- `src/workflow/engine.py`: 添加资源检查门控

**不重复造轮子**:
- ✅ 复用现有的 `engine_metrics.py` 指标系统
- ✅ 扩展现有的监控能力

---

## 🎯 Phase 4: 协议驱动的 Agent 系统

### 4.1 Protocol Templates
**目标**: 学习 GoalX 的 master.md + program.md 模板系统

**新增文件**:
```
src/agent/protocols/
├── __init__.py
├── master_protocol.py       # Master agent 协议模板
├── worker_protocol.py       # Worker agent 协议模板
├── intent_router.py         # 意图路由 (deliver/explore/evolve/debate)
└── templates/
    ├── master.md.j2         # Jinja2 模板
    ├── worker.md.j2
    ├── deliver.md.j2
    ├── explore.md.j2
    ├── evolve.md.j2
    └── debate.md.j2
```

**修改文件**:
- `src/agent/swarm/orchestrator.py`: 使用 master_protocol 生成指令
- `src/agent/swarm/base_agent.py`: 使用 worker_protocol 生成指令
- `src/llm/prompts/`: 重构为基于模板的系统

**不重复造轮子**:
- ✅ 复用现有的 `src/llm/prompts/` 目录结构
- ✅ 扩展为更系统化的协议模板

---

### 4.2 Intent-Based Routing
**目标**: 支持不同的执行意图 (deliver/explore/evolve/debate/implement)

**新增文件**:
```
src/workflow/intents/
├── __init__.py
├── base_intent.py           # 意图基类
├── deliver_intent.py        # 交付结果路径
├── explore_intent.py        # 探索调研路径
├── evolve_intent.py         # 持续改进路径
├── debate_intent.py         # 挑战验证路径
└── implement_intent.py      # 实现路径
```

**修改文件**:
- `src/workflow/engine.py`: 根据 intent 选择执行策略
- `src/cli/commands/`: 添加 intent 参数

**不重复造轮子**:
- ✅ 复用现有的 `src/workflow/` 工作流引擎
- ✅ 扩展为支持多种意图

---

## 🎯 Phase 5: 长期记忆增强

### 5.1 Evidence-Gated Memory
**目标**: 防止幻觉进入长期记忆，所有记忆必须有证据支持

**新增文件**:
```
src/memory/evidence/
├── __init__.py
├── gate.py                  # 证据门控
├── proposal.py              # 记忆提案
├── promotion.py             # 提案晋升逻辑
└── validator.py             # 证据验证器
```

**修改文件**:
- `src/memory/long_term.py`: 集成 evidence gate
- `src/memory/manager.py`: 添加 proposal → canonical 流程

**不重复造轮子**:
- ✅ 复用现有的 `src/memory/` 企业级记忆系统
- ✅ 扩展为证据驱动的记忆管理

---

### 5.2 Memory Kinds & Selectors
**目标**: 分类记忆类型，支持选择器检索

**新增文件**:
```
src/memory/kinds/
├── __init__.py
├── fact.py                  # 事实记忆
├── procedure.py             # 过程记忆
├── pitfall.py               # 陷阱记忆
├── success_prior.py         # 成功先例
└── secret_ref.py            # 密钥引用
```

**修改文件**:
- `src/memory/storage.py`: 支持按 kind 存储和检索
- `src/memory/retrieval.py`: 添加 selector-based 检索

**不重复造轮子**:
- ✅ 复用现有的记忆存储基础设施
- ✅ 扩展分类和检索能力

---

## 🎯 Phase 6: 工具与命令增强

### 6.1 新增 GoalX 风格命令
**目标**: 添加 GoalX 的核心命令到 Clawd CLI

**新增文件**:
```
src/cli/commands/goalx/
├── __init__.py
├── run.py                   # goalx run "objective"
├── add.py                   # goalx add --worktree "task"
├── keep.py                  # goalx keep session-N
├── tell.py                  # goalx tell session-N "message"
├── wait.py                  # goalx wait --inbox master
├── integrate.py             # goalx integrate --method partial_adopt
└── extend.py                # goalx extend --budget +2h
```

**修改文件**:
- `src/cli/repl.py`: 注册新命令
- `src/cli/commands/__init__.py`: 导入 goalx 命令

**不重复造轮子**:
- ✅ 复用现有的 CLI 框架
- ✅ 添加新命令而非重写 CLI

---

### 6.2 Journal & Artifacts
**目标**: 结构化的执行日志和产物管理

**新增文件**:
```
src/core/artifacts/
├── __init__.py
├── journal.py               # 执行日志
├── artifact_manager.py      # 产物管理器
└── report_generator.py      # 报告生成器
```

**修改文件**:
- `src/workflow/engine.py`: 记录 journal 条目
- `src/agent/engine_loop.py`: 保存 artifacts

**不重复造轮子**:
- ✅ 复用现有的日志系统
- ✅ 扩展为结构化的 journal

---

## 📊 实施优先级

### P0 (立即实施 - 基础设施)
1. **Durable Surfaces** (Phase 1.1) - 核心持久化机制
2. **Control Inbox** (Phase 1.2) - 持久化消息系统
3. **Protocol Templates** (Phase 4.1) - 协议驱动基础

### P1 (短期实施 - 隔离与监控)
4. **Worktree Manager** (Phase 2.1) - 并行执行隔离
5. **Runtime Host** (Phase 3.1) - 运行时监控
6. **Session Coordination** (Phase 2.2) - 任务协调

### P2 (中期实施 - 增强功能)
7. **Intent Routing** (Phase 4.2) - 多意图支持
8. **Evidence-Gated Memory** (Phase 5.1) - 记忆质量保证
9. **Resource Monitoring** (Phase 3.2) - 资源管理

### P3 (长期实施 - 完善生态)
10. **GoalX Commands** (Phase 6.1) - 命令集扩展
11. **Memory Kinds** (Phase 5.2) - 记忆分类
12. **Journal & Artifacts** (Phase 6.2) - 产物管理

---

## 🔧 技术债务清理

### 需要重构的现有模块
1. `src/agent/swarm/message_bus.py` → 改为基于文件的持久化
2. `src/workflow/engine.py` → 集成 durable surfaces
3. `src/agent/checkpoint.py` → 扩展为支持 canonical surfaces
4. `src/core/git/operations.py` → 添加 worktree 支持
5. `src/llm/prompts/` → 重构为协议模板系统

### 需要删除的冗余代码
- 无 (GoalX 是 Go 项目，与 Python 代码库无重叠)

---

## 📈 预期收益

### 可靠性提升
- ✅ 崩溃后可恢复 (Runtime Host + Lease)
- ✅ 状态持久化 (Durable Surfaces)
- ✅ 并行执行隔离 (Worktree)

### 自主性增强
- ✅ 减少对会话历史依赖 (Canonical Surfaces)
- ✅ 多意图执行策略 (Intent Routing)
- ✅ 证据驱动的记忆 (Evidence Gate)

### 可维护性改进
- ✅ 协议驱动设计 (Protocol Templates)
- ✅ 结构化日志 (Journal)
- ✅ 清晰的任务协调 (Coordination)

---

## ⚠️ 风险与缓解

### 风险 1: 过度工程化
**缓解**: 分阶段实施，每个 Phase 独立验证价值

### 风险 2: 性能开销
**缓解**: 文件 I/O 使用异步，worktree 按需创建

### 风险 3: 兼容性破坏
**缓解**: 保持现有 API 不变，新功能作为可选扩展

---

## 📝 下一步行动

1. **Review**: 与团队 review 此清单，确认优先级
2. **Spike**: 对 P0 项目进行技术预研 (2-3 天)
3. **Implement**: 按优先级逐个实施
4. **Test**: 每个 Phase 完成后进行集成测试
5. **Document**: 更新 ARCHITECTURE.md 和 CLAUDE.md

---

**生成者**: Claude Opus 4.6  
**审核状态**: 待人工审核

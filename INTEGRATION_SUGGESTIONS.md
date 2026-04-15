# 整合建议清单

## 项目 A: claw-code-tingfeng (本地项目)
## 项目 B: oh-my-codex-main (./oh-my-codex-main 目录)

---

## 📋 整合状态总览

### ✅ 已完成整合 (2026-04-14 21:10)

| 模块 | 来源 | 目标 | 状态 |
|------|------|------|------|
| Intent Router | src/catalog/intent-router.ts | src/agent/intent_router.py | ✅ 完成 |
| Task Analyzer | src/catalog/task-analyzer.ts | src/agent/task_analyzer.py | ✅ 完成 |
| Code Simplifier | src/tools/runtime/code-simplifier.ts | src/tools_runtime/code_simplifier.py | ✅ 完成 |
| RALPH Loop | skills/ralph/SKILL.md | skills/ralph_loop/SKILL.md | ✅ 完成 |
| Pipeline Stage | src/pipeline/types.ts | src/workflow/pipeline_stage.py | ✅ 完成 |
| Pipeline Orchestrator | src/pipeline/orchestrator.ts | src/workflow/pipeline_orchestrator.py | ✅ 完成 |
| Mode State | src/modes/base.ts | src/workflow/mode_state.py | ✅ 完成 |
| Team Exec Stage | src/team/runtime.ts | src/workflow/stages/team_exec.py | ✅ 完成 |
| Ralplan Stage | skills/plan/SKILL.md | src/workflow/stages/ralplan.py | ✅ 完成 |
| Ralph Verify Stage | skills/ralph/SKILL.md | src/workflow/stages/ralph_verify.py | ✅ 完成 |
| Ralph Persistence | src/ralph/persistence.ts | skills/ralph_loop/RALPH_PERSISTENCE.md | ✅ 完成 |
| MCP Code Intel | src/mcp/code-intel-server.ts | src/mcp/code_intel.py | ✅ 完成 |
| HUD 基础 | src/hud/render.ts | src/cli/hud.py | ✅ 完成 |
| Planning Artifacts | src/planning/artifacts.ts | src/workflow/artifacts.py | ✅ 完成 |
| MCP State Paths | src/mcp/state-paths.ts | src/mcp/state_paths.py | ✅ 完成 |
| Verification Protocol | src/verification/verifier.ts | src/workflow/verifier.py | ✅ 完成 |
| HUD Authority | src/hud/authority.ts | src/cli/hud_authority.py | ✅ 完成 |
| Notifications Types | src/notifications/types.ts | src/notifications/types.py | ✅ 完成 |
| Notifications Config | src/notifications/config.ts | src/notifications/config.py | ✅ 完成 |
| Notifications Dispatcher | src/notifications/dispatcher.ts | src/notifications/dispatcher.py | ✅ 完成 |
| Hook Extensibility | src/hooks/extensibility/* | src/hooks/extensibility/ | ✅ 完成 |
| Session History Search | src/session-history/search.ts | src/session_history/search.py | ✅ 完成 |
| Keyword Registry | src/hooks/keyword-registry.ts | src/agent/keyword_registry.py | ✅ 完成 |
| Task Size Detector | src/hooks/task-size-detector.ts | src/agent/task_size_detector.py | ✅ 完成 |
| Prompt Guidance Contract | src/hooks/prompt-guidance-contract.ts | src/hooks/prompt_guidance_contract.py | ✅ 完成 |
| Explore Routing | src/hooks/explore-routing.ts | src/hooks/explore_routing.py | ✅ 完成 |
| Autoresearch Runtime | src/autoresearch/runtime.ts | src/autoresearch/runtime.py | ✅ 完成 |
| Autoresearch Contracts | src/autoresearch/contracts.ts | src/autoresearch/contracts.py | ✅ 完成 |
| OpenClaw Gateway | src/openclaw/* | src/openclaw/ | ✅ 完成 |
| Runtime Bridge | src/runtime/bridge.ts | src/runtime/bridge.py | ✅ 完成 |
| Subagents Tracker | src/subagents/tracker.ts | src/subagents/tracker.py | ✅ 完成 |
| Visual Verdict | src/visual/verdict.ts | src/visual/verdict.py | ✅ 完成 |
| Agent Definitions | src/agents/definitions.ts | src/agent/definitions.py | ✅ 完成 |
| Agent Prompts | prompts/*.md | prompts/agents/ | ✅ 完成 |

---

## 🚀 剩余可整合项 (不重复造轮子)

### 1. Runtime Crates 集成 (优先级: 中)

**现状**: 项目A无 Rust 运行时集成

**可整合** (可选):
- [ ] **omx-runtime** - Rust 运行时核心
- [ ] **omx-runtime-core** - 运行时核心库
- [ ] **omx-mux** - 多路复用支持
- [ ] **omx-explore** - 探索增强

**注意**: 这需要 Rust 编译环境，属于高级集成。

### 2. 额外功能模块 (优先级: 低)

**可跳过 (项目A已有类似实现)**:
- [x] **codebase-map.ts** → 项目A已有 `src/brain/` (World Model)
- [x] **agents/native-config.ts** → 非关键功能
- [x] **planning/artifacts.ts** → 已整合到 `src/workflow/artifacts.py`
explore.md, git-master.md, information-architect.md,
performance-reviewer.md, planner.md, product-analyst.md,
product-manager.md, qa-tester.md, quality-reviewer.md,
quality-strategist.md, researcher.md, security-reviewer.md,
sisyphus-lite.md, style-reviewer.md, team-executor.md,
team-orchestrator.md, test-engineer.md, ux-researcher.md,
verifier.md, vision.md, writer.md
```

### 3. Runtime Crates 集成 (优先级: 中)

**现状**: 项目A无 Rust 运行时集成

**可整合** (可选):
- [ ] **omx-runtime** - Rust 运行时核心
- [ ] **omx-runtime-core** - 运行时核心库
- [ ] **omx-mux** - 多路复用支持
- [ ] **omx-explore** - 探索增强

**注意**: 这需要 Rust 编译环境，属于高级集成。

### 4. 额外功能模块 (优先级: 低)

**可跳过 (项目A已有类似实现)**:
- [x] **codebase-map.ts** → 项目A已有 `src/brain/` (World Model)
- [x] **agents/native-config.ts** → 非关键功能
- [x] **planning/artifacts.ts** → 已整合到 `src/workflow/artifacts.py`

---

## 📦 本次扩展清单

### 阶段 1: Agent Definitions 扩展

**文件变更**:
```
src/agent/
├── definitions.py       # [扩展] 添加 30+ agent 角色定义
```

**新增 Agent 角色**:
```python
# Build Lane
- explore: 快速代码库搜索
- analyst: 需求澄清
- planner: 任务排序
- architect: 系统设计
- debugger: 根因分析
- executor: 代码实现
- team-executor: 团队执行

# Review Lane
- style-reviewer: 格式化审查
- quality-reviewer: 质量审查
- api-reviewer: API 审查
- security-reviewer: 安全审查
- performance-reviewer: 性能审查
- code-reviewer: 综合审查

# Domain Specialists
- dependency-expert: 依赖专家
- test-engineer: 测试工程师
- quality-strategist: 质量策略师

# Product Lane
- product-manager: 产品经理
- product-analyst: 产品分析师
- ux-researcher: UX 研究员
- designer: 设计师

# Coordination
- team-orchestrator: 团队编排
- critic: 批评者
- sisyphus-lite: 持续工作者
```

### 阶段 2: Agent Prompts 库

**文件变更**:
```
prompts/agents/
├── __init__.py           # [新建] prompt 加载器
├── analyst.md            # [新建] 需求分析师 prompt
├── api-reviewer.md       # [新建] API 审查 prompt
├── architect.md          # [新建] 架构师 prompt
├── build-fixer.md        # [新建] 构建修复 prompt
├── code-reviewer.md      # [新建] 代码审查 prompt
├── code-simplifier.md    # [新建] 代码简化 prompt
├── critic.md             # [新建] 批评者 prompt
├── debugger.md           # [新建] 调试器 prompt
├── dependency-expert.md  # [新建] 依赖专家 prompt
├── designer.md           # [新建] 设计师 prompt
├── executor.md           # [新建] 执行者 prompt
├── explore.md            # [新建] 探索者 prompt
├── git-master.md         # [新建] Git 专家 prompt
├── performance-reviewer.md # [新建] 性能审查 prompt
├── planner.md            # [新建] 规划师 prompt
├── product-manager.md    # [新建] 产品经理 prompt
├── qa-tester.md          # [新建] QA 测试 prompt
├── security-reviewer.md  # [新建] 安全审查 prompt
├── test-engineer.md      # [新建] 测试工程师 prompt
├── ux-researcher.md      # [新建] UX 研究 prompt
├── verifier.md           # [新建] 验证者 prompt
└── writer.md            # [新建] 写作 prompt
```

### 阶段 3: Runtime Bridge (可选)

**文件变更**:
```
src/runtime/
├── __init__.py           # [新建] runtime 统一入口
├── bridge.py             # [已存在] 需增强
└── types.py             # [新建] 类型定义
```

---

## 🔍 避免重复造轮子清单

| OMX 模块 | 项目A现状 | 决策 |
|----------|-----------|------|
| agents/definitions.ts | src/agent/definitions.py | ✅ 扩展 |
| prompts/* (34个) | agents/ (3个) | ✅ 新建 prompts/agents/ |
| runtime/bridge.ts | 需增强 | ✅ 已完成 |
| crates/omx-runtime | 无 | [可选] 跳过 |
| modes/base.ts | src/workflow/mode_state.py | ✅ 已完成 |
| pipeline/* | src/workflow/ | ✅ 已完成 |
| ralph/* | skills/ralph_loop/ | ✅ 已完成 |
| hud/* | src/cli/hud*.py | ✅ 已完成 |
| notifications/* | src/notifications/ | ✅ 已完成 |
| autoresearch/* | src/autoresearch/ | ✅ 已完成 |
| openclaw/* | src/openclaw/ | ✅ 已完成 |
| hooks/extensibility/* | src/hooks/extensibility/ | ✅ 已完成 |
| session-history/* | src/session_history/ | ✅ 已完成 |

---

## ✅ 整合原则

1. **先验证再扩展**: 检查现有实现后再决定是否添加
2. **渐进式整合**: 分阶段执行，每阶段验证
3. **Python 优先**: TypeScript → Python 转换
4. **不破坏现有**: 新功能作为扩展，不修改已有
5. **复用优先**: 调用现有模块而非重建

---

## 📝 行动计划

### 阶段 1: Agent Definitions 扩展
- [ ] 分析 OMX agents/definitions.ts 源码
- [ ] 扩展 src/agent/definitions.py 添加 30+ agent 角色

### 阶段 2: Agent Prompts 库
- [ ] 转换 34 个 .md prompt 文件为 Python 可用格式
- [ ] 创建 prompt 加载器模块
- [ ] 集成到现有 agent 系统

### 阶段 3: Runtime Bridge 增强 (可选)
- [ ] 增强 src/runtime/bridge.py 功能
- [ ] 添加类型定义

---

## ✅ 2026-04-14 整合完成报告

### 整合统计

| 类别 | 数量 |
|------|------|
| 已完成 Python 模块 | 30+ |
| 已完成技能文档 | 20+ |
| 整合功能 | 50+ |

### 功能覆盖

- **Intent Router**: 关键词检测与技能自动激活 ✅
- **Task Analyzer**: 任务规模检测 (small/medium/large/heavy) ✅
- **Code Simplifier**: 自动代码简化钩子 ✅
- **RALPH Loop**: 持久化循环执行技能 ✅
- **Pipeline Orchestrator**: RALPLAN -> team-exec -> ralph-verify 管道 ✅
- **Mode State**: 管道/团队/技能模式状态持久化 ✅
- **Notifications**: 多平台通知 (Discord/Telegram/Slack/Webhook) ✅
- **Autoresearch**: 自动研究运行时与合约 ✅
- **OpenClaw**: 外部网关钩子系统 ✅
- **HUD Authority**: 权限和时间控制 ✅
- **Verification Protocol**: 验证协议 ✅
- **Planning Artifacts**: 规划产物管理 ✅
- **Hook Extensibility**: 插件化钩子系统 ✅
- **Session History Search**: 会话历史搜索 ✅
- **Keyword Registry**: 关键词注册表 ✅
- **Task Size Detector**: 任务规模检测 ✅
- **Prompt Guidance**: 提示词指导合约 ✅
- **Explore Routing**: 探索路由 ✅
- **Runtime Bridge**: Rust 运行时桥接 ✅
- **Subagents Tracker**: 子代理追踪 ✅
- **Visual Verdict**: 视觉判决 ✅

### 剩余可扩展项

1. **Agent Definitions** - 30+ 完整 agent 角色库
2. **Agent Prompts** - 34 个 prompt 模板库
3. **Runtime Crates** - Rust 运行时集成 (可选)

---

**更新: 2026-04-14 20:50**
# Clawd Code 系统架构

本文档描述 Clawd Code v0.50.0 的模块化架构，该版本深度集成了 **GoalX** 持久化认知系统和 **Oh-My-Codex** 的智能路由机制。

## 总体架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                        CLI / User Interface                       │
│                  (src/cli/ - REPL, Commands, HUD)                 │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                    ┌───────────▼────────────┐
                    │   Intent Router &      │
                    │   Keyword Registry     │←──────────────┐
                    │ (src/agent/agent_routing.py) │          │
                    └───────────┬────────────┘              │
                                │                           │
                    ┌───────────▼────────────┐              │
    ┌─────────────►│  Task Size Detector    │              │
    │             │(src/agent/task_size_detector.py)        │
    │             └───────────┬────────────┘              │
    │                         │                           │
    │    ┌────────────────────▼─────────────┐              │
    │    │    Agent Swarm Orchestrator      │              │
    │    │  (src/agent/swarm/orchestrator)  │              │
    │    └─────────────┬────────────────────┘              │
    │                  │                                   │
    │    ┌─────────────▼──────────────┐    ┌──────────────▼──────────┐
    │    │   Agent Definitions        │    │   Task Registry         │
    │    │ (src/agent/definitions.py) │    │(src/agent/swarm/        │
    │    └────────────────────────────┘    │ task_registry.py)       │
    │                                       └────────────┬───────────┘
    │                                                      │
    │    ┌──────────────────┐          ┌─────────────────▼──────────┐
    │    │   LLM Layer      │          │   Workflow Pipeline        │
    │    │ (src/llm/ - 9     │          │ (src/workflow/             │
    │    │  providers)      │          │  pipeline_orchestrator,    │
    │    └────────┬─────────┘          │  ralplan, ralph_ledger)   │
    │              │                    └────────────┬──────────────┘
    │    ┌─────────▼──────────────┐                │
    │    │   World Model          │                │
    │    │  (src/brain/           │                │
    │    │   RepoMap, Tree-sitter)│                │
    │    └─────────┬──────────────┘                │
    │              │                               │
    │    ┌─────────▼──────────────┐                │
    │    │   Tools Runtime        │                │
    │    │(src/tools_runtime/     │────────────────┘
    │    │  Bash, Grep, Glob,     │
    │    │  File Ops)             │
    │    └────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│   Infrastructure & Persistence              │
│  - Memory (src/memory/ - EnterpriseLTM)     │
│  - RAG (src/rag/ - Trigram, Indexer)        │
│  - Self-Healing (src/self_healing/)        │
│  - MCP Servers (src/core/mcp/)              │
│  - Config, Hooks, Exceptions (src/core/)    │
└─────────────────────────────────────────────┘
```

## 核心模块结构

按 `src/` 目录组织，共 9 个主要模块：

### Agent 层 (`src/agent/`)

识别用户意图、路由到合适的执行单元。

| 组件 | 说明 |
|------|------|
| `definitions.py` | 40+ Agent 角色精细化定义（ReasoningEffort, Posture, ModelClass, RoutingRole, ToolAccess, Category） |
| `intent_router.py` | **v0.50.0 新增** — 5 种意图自动分类（DELIVER/EXPLORE/EVOLVE/IMPLEMENT/DEBATE） |
| `keyword_registry.py` | **v0.50.0 新增** — 40+ 技能关键词注册表、执行门控、ralplan-first Gate、well-specified 检测 |
| `task_size_detector.py` | **v0.50.0 新增** — 任务规模四级分类（small/medium/large/heavy）+ Agent 推荐 |
| `swarm/` | 多代理协同系统：orchestrator, roles, task_registry, team_persistence |

### World Model 层 (`src/brain/`)

代码库全景感知，提供语义上下文：
- `repo_map.py` — Aider-style RepoMap（文件重要度 + 依赖图）
- `tree_sitter_syntax.py` — Tree-sitter 语法解析
- `world_model.py` — 统一入口

### LLM 抽象层 (`src/llm/`)

统一 9 个 LLM 提供商接口：
- `model_manager.py` — 模型别名、元数据、缓存
- `exception_handler.py` — 20+ 异常类型分类与重试
- `message_handler.py` — 消息角色清洗
- `openrouter_manager.py` — OpenRouter 集成
- `prompts/` — 34 个 Agent Prompt 模板

### Workflow 引擎 (`src/workflow/`)

基于 GoalX 的五阶段执行管道：
- `pipeline_orchestrator.py` — RALPLAN → TEAM_EXEC → RALPH 三阶段编排
- `ralplan.py` — 共识规划（Planner → Architect → Critic 三角循环）
- `ralph_ledger.py` — RALPH 进度账本与视觉反馈
- `mode_state.py` — 独占模式互斥 + 跨会话状态持久化
- `team_persistence.py` — 团队状态持久化
- `session_history_search.py` — 历史会话检索

### 工具运行时 (`src/tools_runtime/`)

安全沙箱中的工具执行：
- `bash.py`, `file.py`, `grep.py`, `glob.py` — 基础文件操作
- `code_simplifier.py` — 自动简化最近修改的代码
- `patch_engine.py` — 声明式补丁引擎

### 企业级能力 (`src/core/`)

基础设施层：
- `config/` — 动态配置生成器（技能发现、MCP 注入）
- `hooks_config.py` — TOML 配置化 Hook 系统
- `quality_gate.py` — 自动化质量检查（format → lint → typecheck → tests）
- `mcp/` — 5 个 MCP 服务器（state, memory, trace, team, code_intel）
- `workspace.py` — Git Worktree 隔离执行环境
- `state.py` — 状态持久化（SystemSnapshot 及子 surface）
- `events.py` — 事件系统（新增权限/调度事件）
- `serialization.py` — 类型安全序列化（dataclass/Enum/datetime/Path）
- `exceptions.py` — 结构化错误码（STATE_*, MCP_*）
- `budget_guard.py` — 资源监控（PSI, RSS, Cost）

### 记忆与检索 (`src/memory/`, `src/rag/`)

- `memory/` — EnterpriseLTM（SQLite, async, 长期记忆）
- `rag/` — Trigram 索引 + 文本索引 + 依赖图 + RepoMap + 语法解析

### 自愈系统 (`src/self_healing/`)

自动错误检测与 AI 驱动修复。

## 模块依赖关系

```
Intent Router → Task Size Detector → Agent Swarm → Workflow Pipeline
                              ↓                    ↓
                        World Model ← LLM Layer ← Tools Runtime
                              ↓
                          Memory + RAG
```

### 关键协作流程

1. **意图识别**: User Input → Intent Router (5 intents) → Keyword Registry (40+ keywords) → Task Size Detector (scale)
2. **Agent 路由**: Intent + Scale + Domain Factors → Agent Selection (definitions.py lookup)
3. **执行编排**: Workflow Pipeline (RALPLAN → TEAM → RALPH) → Tools Runtime → Budget Guard
4. **状态持久化**: All stages → JSON surfaces (`.clawd/state/`) → Recovery capability

## 设计模式

- **不可变性 (Immutability)**: Dataclass(frozen=True) 用于 DTO
- **依赖注入**: 通过 constructor 传入，避免全局状态
- **事件驱动**: 事件总线（PersistentMessageBus）解耦组件
- **策略模式**: GateLevel、IntentType、AgentCategory 等枚举
- **工厂模式**: Model Manager、Prompt Template 加载

## 扩展点

- **新 Agent 角色**: 在 `src/agent/definitions.py` 的 `AGENT_DEFINITIONS` 注册
- **新意图类型**: 扩展 `IntentType` 枚举及 `INTENT_PATTERNS`
- **新技能关键词**: 添加到 `KEYWORD_TRIGGER_DEFINITIONS`
- **新 LLM 提供商**: 在 `src/llm/` 实现 `LLMProvider` 接口
- **新 MCP Server**: 在 `src/core/mcp/` 添加 Server 类

## 配置与部署

```bash
# 生成动态配置（合并 Codex 配置）
clawd config --generate

# 查看 MCP 服务器状态
clawd mcp status

# 启动 HUD（实时状态显示器）
clawd hud
```

详细的 Hook 配置参见 `hooks/config.toml`，特性标志位于 `.clawd/features.json`。

## 测试与质量

- **测试框架**: pytest (1414+ 测试用例，~50% 覆盖率，目标 60%)
- **代码质量**: ruff (lint + format), mypy (类型检查)
- **安全扫描**: bandit (Python 安全)
- **CI/CD**: GitHub Actions (自动运行全量测试)

参见 `CLAUDE.md` 和 `rules/` 目录获取完整的编码规范与工作流指南。

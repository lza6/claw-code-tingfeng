# 🚀 Clawd Code：AI 编程代理框架

> **"让 AI 像交响乐团一样协作，让编程像呼吸一样自然。"**

**当前版本**: v0.50.0 (GoalX Integration) | **测试**: ✅ 1414 个用例 | **覆盖率**: ~50% (目标 60%) | **质量工具**: ruff, mypy, pytest-cov | **CI/CD**: GitHub Actions

---

## 📋 目录

- [核心功能](#-核心功能)
- [快速开始](#-快速开始)
- [Aider 风格命令](#-aider-风格命令)
- [Swarm 角色定义](#-swarm-角色定义)
- [世界模型 (World Model)](#-世界模型-world-model)
- [GoalX 增强特性](#-goalx-增强特性)
- [架构概览](#-架构概览)
- [API 参考](#-api-参考)
- [部署指南](#-部署指南)
- [测试与质量](#-测试与质量)

---

## 🧠 核心功能

### 1. Swarm 多代理协作
将复杂任务分解，由专业 Agent 协同处理：
- **Orchestrator**: 意图路由与任务分发。
- **Worker (Coder/Architect)**: 专注代码实现与架构设计。
- **Auditor**: 基于五轴标准的严苛代码审计。
- **Integrator**: 跨分支/工作树的结果集成。

### 2. 世界模型 (World Model)
代码库全景感知，集成了 Aider 风格的 RepoMap 与 Tree-sitter 语法解析，提供语义级的上下文注入。

### 3. 预算守卫 (Budget Guard)
业内领先的资源安全监控，实时追踪 CPU、内存(RSS)、PSI 压力及 API Token 消耗，支持动态熔断。

### 4. 隔离执行 (Isolation)
基于 Git Worktree 的物理隔离运行环境，支持多任务并行开发而互不干扰。

---

## 🚀 快速开始

### 环境要求
- Python 3.10+
- Git 2.30+
- OpenAI, Anthropic 或 OpenRouter API Key

### 一键启动
```bash
# 安装依赖
pip install -e .

# 运行 REPL 模式
python -m src.main chat

# 运行一键诊断
python -m src.main doctor
```

---

## ⌨️ Aider 风格命令

Clawd Code 集成了强大的 Aider 风格命令系统，方便您在 REPL 中高效操作：
- **文件操作**: `/add`, `/drop`, `/read`, `/edit`
- **代码执行**: `/run`, `/test`, `/lint`, `/shell`
- **Git 管理**: `/diff`, `/commit`, `/undo`
- **高级功能**: `/tokens`, `/model`, `/browse`, `/thinking`

详细手册请参阅 [Aider 命令手册](./docs/aider_commands.md)。

## 🤖 Swarm 角色定义

系统通过多代理协作完成复杂工程任务，支持核心角色与动态合成：
- **Orchestrator/Planner**: 负责任务编排与路径规划。
- **Worker/Auditor/Reviewer**: 负责编码、严苛审计与架构审查。
- **Diagnostician**: 负责深度故障根因分析。
- **Synthesized**: **v0.50.0 新增**，支持根据上下文动态合成特定专家。

角色详情与自定义指南请参阅 [Swarm 协作指南](./docs/swarm_roles.md)。

## 🧠 世界模型 (World Model)

代码库的"意识"层，提供精准的上下文感知：
- **模式检测**: 自动识别 Singleton, Factory, Observer 等设计模式。
- **依赖预测**: 基于代码图谱预测受影响的文件。
- **语义索引**: 基于 Trigram 的语义级检索。

技术细节请参阅 [世界模型说明](./docs/world_model.md)。

---

## 🛡️ GoalX 增强特性

Clawd Code v0.50.0 深度集成了 **GoalX** 的持久化认知能力：

- **持久化认知表面 (Durable Surfaces)**: 维护 9 个规范化 JSON 表面（Charter, Objective, Evidence 等），确保任务执行过程可追踪、可审计、可恢复。
- **意图路由 (Intent Routing)**: 显式声明任务意图（DELIVER, EXPLORE, EVOLVE, DEBATE），系统自动选择最优执行路径。
- **辩论模式 (Debate Mode)**: 支持多模型对同一问题进行证据驱动的辩论，通过交叉验证确保输出质量。
- **内存种子与晋升 (Memory Seed & Promote)**: 从项目启动内存到长期经验存储的自动转化机制。

---

## 🏗️ 架构概览

详细架构说明请参考 [ARCHITECTURE.md](./ARCHITECTURE.md)。

```text
┌─────────────────────────────────────────────────────────┐
│                     用户交互层 (CLI/TUI)                  │
├─────────────────────────────────────────────────────────┤
│  Intent Routing  │  Worktree Manager  │  Budget Guard     │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                     核心引擎层                             │
├─────────────────────────────────────────────────────────┤
│  SwarmEngine  │  WorldModel (RAG)  │  Self-Healing       │
└─────────────────────────────────────────────────────────┘
        │                    │                    │
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│   Agent 表面  │  │   认知存储     │  │   工具运行时   │
├───────────────┤  ├───────────────┤  ├───────────────┤
│ Charter       │  │ EnterpriseLTM │  │ Bash/Git      │
│ Objective     │  │ Trigram Index │  │ Patch Engine  │
│ Evidence      │  │ RepoMap (AST) │  │ Sandbox       │
└───────────────┘  └───────────────┘  └───────────────┘
```

---

## 📚 API 参考

### 运行工作流
```bash
python -m src.main workflow run --goal "重构认证模块" --intent evolve --budget 5usd
```

### 资源监控
```bash
python -m src.main budget status
```

---

## 🧪 测试与质量

### 运行测试
```bash
make test           # 运行全量 pytest
make coverage       # 生成覆盖率报告
```

### 质量标准
- 函数长度 < 50 行
- 嵌套深度 < 4 层
- 强制类型注解
- 测试覆盖率最低要求 80% (核心模块)

---

## 📄 许可证
MIT License

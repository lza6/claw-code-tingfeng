# Clawd Code 项目规格书 (Project Specs)

## 1. 项目愿景
构建一个企业级的、具备自愈能力和深层代码感知能力（RepoMap）的 Python AI 编程代理框架。

## 2. 核心技术栈
- **语言**: Python 3.10+
- **模型支持**: 多供应商接入 (Anthropic, OpenAI, OpenRouter, LiteLLM 等)
- **核心组件**:
  - **World Model**: 负责代码库感知和依赖分析，整合 Aider RepoMap。
  - **Self-Healing**: 自动捕获错误并尝试修复，支持自动生成回归测试。
  - **Patch Engine**: 声明式代码修改引擎，支持 Aider 兼容的多种编辑格式。
  - **Swarm Intelligence**: 多 Agent 协作模式。

## 3. 当前架构状态 (2026-04-12)
- **CLI**: 全面集成 Aider v0.50.0 指令集，支持 TUI 仪表盘与流式 Markdown。
- **Core**: 核心基础设施已完成解耦，支持事件驱动架构 (Event-driven)。
- **Memory**: 企业级长效记忆系统 (Enterprise LTM)，支持语义/情景/工作记忆。
- **RAG**: 引入 Tree-sitter 语法解析与 Trigram 索引，支持跨文件符号跟踪。

## 4. 演进目标 (Architecture Evolution)
- [ ] **解耦 Aider 逻辑**: 将 Aider 原生逻辑抽象为 `Adapter` 模式，确保核心引擎的独立性。
- [ ] **统一补丁层**: 整合 `search_replace` 与 `udiff`，构建原子化的补丁执行器。
- [ ] **自愈闭环**: 实现 `Diagnoser` -> `Proposer` -> `Verifier` 的自动化闭环。
- [ ] **性能基线**: 实现 RAG 增量索引与 TUI 局部渲染优化。

## 5. 任务追踪
### 已完成
- [x] 重构 `src/core` 核心基础设施。
- [x] 实现结构化异常映射 (Task 01)。
- [x] 实现敏感数据过滤 (Task 02)。
- [x] 优化 RepoMap 缓存逻辑 (Task 03)。
- [x] 强化 History Compressor 保护机制 (Task 04)。
- [x] 优化 TechDebtManager 性能与原子性 (Task 14)。

### 进行中 (优先级排序)
- [ ] 执行四大热点文件拆分 (Task 06-09, 20-22)。
- [ ] 增强 BashExecutor 安全与资源限制 (Task 11)。
- [ ] 优化 TUI 渲染性能 (Task 15)。
- [ ] 构建原子补丁执行层 (Atomic Patch Layer)。
- [ ] 实现 RAG 增量索引机制 (Incremental Indexing)。

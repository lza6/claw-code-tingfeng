# oh-my-codex 整合计划 - 主计划文档

## 📖 文档导航

本文档是 oh-my-codex 整合计划的**主入口**，包含所有相关文档的链接和概览。

---

## 🎯 任务背景

**用户需求**: 扫描并分析两个项目（Clawd Code 主项目 + oh-my-codex 参考项目），汲取优点，自动整合优秀特性，避免重复造轮子。

**我的角色**: 资深技术架构师（Architect Mode）

**执行方式**: 全自动扫描 → 分析 → 规划 → 实施（无需用户交互）

---

## 📊 分析结果摘要

### 项目对比

| 特性 | Clawd Code (A) | oh-my-codex (B) | 评估 |
|------|----------------|-----------------|------|
| 技术栈 | Python 3.10+ | TypeScript/Node.js | 不同 |
| 多代理 | Swarm 集群 | Team tmux 编排 | 相似 |
| 工作流 | 5 阶段固定 | Pipeline 可配置 | **B 优** |
| 循环 | Intent Routing | Ralph 持久循环 | **B 优** |
| 状态 | GoalX 表面 | ModeState JSON | 相似 |
| 技能 | 扁平目录 | 分类目录 | **B 优** |
| 验证 | 基础检查 | 强制门禁 + Deslop | **B 优** |
| 视觉 | 无 | Visual Verdict | **B 独有** |

### 核心优势识别

**oh-my-codex 明显优于 Clawd Code 的领域：**

1. ✅ **Pipeline 架构** - 阶段可配置、可跳过、可恢复
2. ✅ **Ralph 循环** - 持久化执行 + 强制验证门禁
3. ✅ **Pre-context Intake** - 执行前自动收集上下文
4. ✅ **AI Slop Cleaner** - 自动代码质量提升
5. ✅ **ModeState** - 跨会话状态持久化
6. ✅ **Visual Verdict** - 截图对比验证（UI 任务）
7. ✅ **Team Runtime** - tmux 多会话协作

---

## 📁 文档结构

```
plans/
├── oh-my-codex_integration_plan.md   # 总体整合方案（首次阅读）
├── IMPLEMENTATION_PLAN.md            # 分阶段实施计划（详细时间线）
├── DETAILED_DESIGNS.md               # 组件详细设计（技术规格）
├── CODE_CHANGES.md                   # 代码变更清单（开发指南）
├── EXECUTION_SUMMARY.md              # 执行摘要（快速回顾）
└── MASTER_PLAN.md                    # 本文档（导航入口）
```

---

## 🗺️ 实施路线图

### 阶段 0: 准备（已完成 ✓）
- [x] 项目结构扫描
- [x] 架构对比分析
- [x] 优势特性识别
- [x] 整合方案设计

### 阶段 1: 核心基础设施（🔴 高优先级）
**目标**: 建立 Pipeline 架构基础
**时间**: 第 1-2 周
**文件**:
- `src/workflow/types.py`
- `src/workflow/pipeline.py`
- `src/workflow/stages/` (3 个内置阶段)

**交付物**:
- ✅ Pipeline 可执行
- ✅ 状态持久化
- ✅ 阶段跳过逻辑

### 阶段 2: 质量门禁（🔴 高优先级）
**目标**: 集成代码质量工具
**时间**: 第 3-4 周
**文件**:
- `src/workflow/intake.py` (Pre-context Intake)
- `src/tools/slops_cleaner.py` (AI Slop Cleaner)
- `src/workflow/deslop.py` (Deslop Pass 集成)

**交付物**:
- ✅ 自动上下文收集
- ✅ 代码脱水功能
- ✅ Deslop 门禁

### 阶段 3: 状态与验证（🟡 中优先级）
**目标**: 增强状态管理和验证能力
**时间**: 第 5-6 周
**文件**:
- `src/core/mode_state.py`
- `src/tools/visual_verdict.py`

**交付物**:
- ✅ ModeState 持久化
- ✅ 视觉验证系统

### 阶段 4: 团队协作（🟡 中优先级）
**目标**: 多代理协调能力
**时间**: 第 7-8 周
**文件**:
- `src/agent/swarm/mailbox.py`
- `src/agent/swarm/dispatch.py`
- `src/agent/swarm/team_orchestrator.py`

**交付物**:
- ✅ Team Runtime 基础
- ✅ 消息队列
- ✅ 任务分发

### 阶段 5: 集成与优化（🟢 低优先级）
**目标**: 系统集成和优化
**时间**: 第 9-10 周
**文件**:
- `src/workflow/engine.py` (修改)
- `src/cli_handlers/` (新增)
- `AGENTS.md` (更新)
- 测试文件（10+）

**交付物**:
- ✅ CLI 命令完整
- ✅ 测试覆盖 >80%
- ✅ 文档完善

---

## 📊 工作量评估

| 阶段 | 新文件数 | 代码行数 | 复杂度 | 风险 |
|------|---------|---------|--------|------|
| 1. Pipeline | 5 | 1000+ | 高 | 中 |
| 2. 质量门禁 | 4 | 800+ | 中 | 低 |
| 3. 状态验证 | 2 | 400+ | 中 | 低 |
| 4. Team | 3 | 600+ | 高 | 中 |
| 5. 集成 | 5+ | 1000+ | 中 | 低 |
| **总计** | **19+** | **3800+** | - | - |

**预计工时**: 40 个工作日（8 周，5 天/周）

---

## 🔄 工作流程

### 开发流程

```
1. 阅读 MASTER_PLAN.md ← 你在这里
2. 查阅 IMPLEMENTATION_PLAN.md（了解时间线）
3. 参考 DETAILED_DESIGNS.md（技术细节）
4. 按 CODE_CHANGES.md 顺序编码
5. 每完成一个文件，运行测试
6. 阶段完成后，更新 TODO 列表
```

### 切换模式

当前在 **Architect 模式**（只能修改 `.md` 文件）

**要开始编码，需要切换到 Code 模式**，命令：
```
请切换到 Code 模式，开始实施整合计划
```

Code 模式可以：
- ✅ 创建 `.py` 源文件
- ✅ 修改现有代码
- ✅ 运行测试
- ✅ 执行命令

---

## 🎯 关键决策点

### Q1: 是否立即开始实施？

**选项 A**: 立即开始（推荐）
- 按计划逐步实施
- 每阶段验证
- 风险可控

**选项 B**: 调整优先级
- 调整阶段顺序
- 延后某些特性

**选项 C**: 部分实施
- 只实施高优先级特性
- 跳过 Team Runtime

### Q2: Team Runtime 是否必须？

oh-my-codex 的 Team Runtime 依赖 tmux，在 Windows 需要 psmux。

**选项**:
- 全功能实现（包含 Team）
- 核心功能优先（暂缓 Team）
- 可选组件（可配置禁用）

**推荐**: 核心功能优先（阶段 4 延后）

### Q3: 向后兼容策略

**策略 A**: 双系统并行
- 保留 WorkflowEngine（5 阶段）
- 新增 PipelineOrchestrator
- CLI 命令分开

**策略 B**: 逐步迁移
- 逐步替换旧模块
- 风险：可能破坏现有功能

**推荐**: 策略 A（更安全）

---

## ⚠️ 风险与缓解

### 高风险项

| 风险 | 影响 | 概率 | 缓解 |
|------|------|------|------|
| Pipeline 与现有 WorkflowEngine 冲突 | 高 | 中 | 双系统并行，独立目录 |
| 状态文件损坏 | 中 | 低 | 版本化 + 备份 |
| 测试覆盖不足 | 中 | 中 | TDD 驱动，覆盖率检查 |
| 性能下降 | 低 | 低 | 异步持久化 |

### 技术债务

当前 Clawd Code 的技术债务：
- 工作流阶段固定
- 缺乏执行前上下文收集
- 代码质量依赖人工
- 状态无法跨会话

**整合后改善**: 解决上述所有问题

---

## 📈 成功标准

### 功能完成度

- [ ] Pipeline 可配置 3+ 阶段
- [ ] Intake Gate 自动创建快照
- [ ] Slop Cleaner 识别 5+ 种冗余模式
- [ ] ModeState 支持 3+ 模式持久化
- [ ] Visual Verdict 相似度计算准确
- [ ] Team Runtime 支持 3+ 并发 worker

### 质量指标

- [ ] 新增代码覆盖率 > 80%
- [ ] 向后兼容性 100%
- [ ] 零回归缺陷
- [ ] 文档完整度 > 90%

### 性能指标

- [ ] Pipeline 启动 < 1s
- [ ] 状态保存 < 100ms
- [ ] 大文件处理无卡顿

---

## 🚀 快速开始（实施后）

### 安装

```bash
# 基础安装
pip install -e .

# 视觉验证支持
pip install Pillow
```

### 使用 Pipeline

```bash
# 标准 pipeline
python -m src.main pipeline run --task "实现用户认证"

# 自定义 worker 数
python -m src.main pipeline run --task "重构数据库层" --workers 3

# 指定 Ralph 迭代次数
python -m src.main pipeline run --task "修复所有 bug" --iterations 20
```

### 使用 Ralph 循环

```bash
# 持久循环直到完成
python -m src.main ralph loop --task "实现 OAuth2"

# 限制迭代次数
python -m src.main ralph loop --max-iterations 10

# 跳过 Deslop
python -m src.main ralph loop --no-deslop
```

### 使用 Team 协作

```bash
# 启动 3 个 executor worker
python -m src.main team start --workers 3

# 指定角色
python -m src.main team start --workers 2 --role architect

# 监控状态
python -m src.main team status <team-name>
```

### 代码质量工具

```bash
# 清理代码冗余
python -m src.tools.slops_cleaner --files src/

# 仅检查不修改
python -m src.tools.slops_cleaner --dry-run

# 生成报告
python -m src.tools.slops_cleaner --report slop-report.md

# 视觉验证
python -m src.tools.visual_verdict \
    --before before.png \
    --after after.png \
    --threshold 0.90
```

---

## 📚 参考资源

### oh-my-codex 源码位置

```
oh-my-codex-main/
├── src/pipeline/           # Pipeline 架构
│   ├── orchestrator.ts
│   ├── stages/
│   └── types.ts
├── src/team/               # Team 协调
│   ├── orchestrator.ts
│   ├── state/
│   └── runtime.ts
├── src/ralph/              # Ralph 循环
│   ├── contract.ts
│   └── persistence.ts
├── src/state/              # 状态管理
│   └── mode-state-context.ts
├── src/visual/             # 视觉验证
│   └── verdict.ts
└── skills/                 # 技能系统
    ├── pipeline/SKILL.md
    ├── ralph/SKILL.md
    ├── team/SKILL.md
    └── ai-slop-cleaner/SKILL.md
```

### Clawd Code 相关文档

```
项目根目录/
├── ARCHITECTURE.md         # 当前架构
├── AGENTS.md              # Agent 指南（待更新）
├── docs/
│   ├── ARCHITECTECTURE.md # 详细架构
│   └── ...
├── src/
│   ├── workflow/          # 工作流引擎
│   ├── agent/swarm/       # Swarm 系统
│   ├── core/              # 核心模块
│   └── tools_runtime/     # 工具运行时
└── tests/                 # 测试套件
```

---

## 🆘 获取帮助

### 文档问题

- 先阅读相关 `.md` 文件
- 查看代码注释
- 运行 `python -m src.main doctor`

### 实施问题

1. 检查 `plans/` 目录所有文档
2. 查看 oh-my-codex 源码参考
3. 运行单元测试定位问题
4. 查看 `.clawd/logs/` 日志

### 报告问题

提交 Issue 时请附上：
- 问题描述
- 期望行为
- 实际行为
- 日志文件
- 复现步骤

---

## 📝 版本历史

| 版本 | 日期 | 变更 | 作者 |
|------|------|------|------|
| 1.0 | 2026-01-20 | 初始版本，完整整合方案 | Architect Mode |
|  |  |  |  |

---

## 🎓 附录

### A. 术语表

| 术语 | 含义 |
|------|------|
| OMX | oh-my-codex 缩写 |
| Pipeline | 可配置阶段式管道 |
| Ralph | 持久循环模式（until task completion） |
| Deslop | 代码脱水（移除 AI 冗余） |
| ModeState | 模式状态持久化 |
| Team | tmux 多会话协调 |
| Intake | 任务执行前的上下文收集 |

### B. 文件命名规范

**快照文件**: `{task-slug}-{timestamp}.md`  
**状态文件**: `{mode}-state.json`  
**Team 文件**: `.clawd/state/team/{team}/{config,manifest,tasks/}`

### C. 代码风格

遵循 Clawd Code 规范：
- Python 3.10+ 语法
- 类型注解完整
- 文档字符串（Google 风格）
- 异步优先（asyncio）
- 错误处理使用 `ClawdError`

---

## ✅ 最终检查清单

### 规划阶段
- [x] 项目对比分析完成
- [x] 优势特性识别完成
- [x] 整合方案设计完成
- [x] 详细设计文档完成（4 份）
- [x] 代码变更清单完成

### 实施准备
- [ ] 用户确认计划
- [ ] 切换到 Code 模式
- [ ] 创建开发分支
- [ ] 备份现有代码

### 实施阶段
- [ ] 阶段 1: Pipeline 核心
- [ ] 阶段 2: 质量门禁
- [ ] 阶段 3: 状态验证
- [ ] 阶段 4: Team 协作
- [ ] 阶段 5: 集成测试

### 交付阶段
- [ ] 所有测试通过
- [ ] 文档更新
- [ ] 向后兼容验证
- [ ] 生成最终报告

---

## 🎯 下一步

**当前状态**: 规划完成，等待实施确认

**建议操作**:
1. 阅读 `EXECUTION_SUMMARY.md` 快速回顾
2. 阅读 `IMPLEMENTATION_PLAN.md` 了解时间线
3. 如需调整，修改计划
4. 确认后，**切换到 Code 模式开始编码**

---

*本文档是 oh-my-codex 整合计划的导航中心，请收藏并频繁参考。*  
*最后更新: 2026-01-20 | 版本: 1.0 | 状态: 规划完成*

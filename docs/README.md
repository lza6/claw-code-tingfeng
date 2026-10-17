# 文档索引

> 本目录只放**仍在维护**的文档。历史报告已删除（git 历史可查）。

## 必读（按顺序）

| 文档 | 内容 | 何时读 |
|:---|:---|:---|
| [`../README.md`](../README.md) | 项目门面、安装、命令、质量基线 | 第一次接触 |
| [`../workflow_status.md`](../workflow_status.md) | 最近一轮改了什么、验证到哪、什么没做 | **每次动手前** |
| [`../skills/clawd-change-workflow/SKILL.md`](../skills/clawd-change-workflow/SKILL.md) | 变更流程、已知陷阱、验收标准 | **每次动手前** |
| [`MAINTENANCE.md`](MAINTENANCE.md) | 新增 Provider/Tool/CLI 的 SOP、发布检查单、排障索引 | 要加东西时 |
| [`adr/README.md`](adr/README.md) | 架构决策与理由 | 想改既有设计时 |
| [`../计划书/下一步改进指南.md`](../计划书/下一步改进指南.md) | 剩余路线图（顶部有实跑核验状态表） | 规划下一轮时 |

## 主题文档

| 文档 | 内容 |
|:---|:---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 分层架构 |
| [`workflow.md`](workflow.md) | 5 阶段工作流引擎 |
| [`agent_swarm.md`](agent_swarm.md) / [`swarm_roles.md`](swarm_roles.md) | 多智能体协作 |
| [`world_model.md`](world_model.md) / [`brain_world_model.md`](brain_world_model.md) | 代码库感知 |
| [`aider_commands.md`](aider_commands.md) | Aider 风格命令 |
| [`skill-anatomy.md`](skill-anatomy.md) | 技能文件结构 |
| [`getting-started.md`](getting-started.md) | 新手上手 |
| [`copilot-setup.md`](copilot-setup.md) 等 | 各家 AI 编辑器接入 |

## 待排期（不是"已完成"）

| 文档 | 状态 |
|:---|:---|
| [`notification-system-enhancement-plan.md`](notification-system-enhancement-plan.md) | **未实施**：计划中的 5 个模块全部不存在 |

## 文档保鲜规则

这些文档会过时。**任何具体断言都要用代码核实**：

```bash
# "X 尚未实现" → 查符号
grep -rn "def X\|class X" src/
# "覆盖率约 N%" → 看实测
python -m pytest tests/ --cov=src --cov-report=term | tail -3
# "文件在 Y" → 确认存在
ls Y
```

判定与实例见 `skills/clawd-change-workflow/SKILL.md` 的 Phase 1。

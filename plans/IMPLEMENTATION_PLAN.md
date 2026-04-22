# Clawd Code + oh-my-codex 整合实施计划

## 📋 执行摘要

本计划将 oh-my-codex (OMX) 的优秀特性整合到 Clawd Code 项目中，实现功能增强和架构升级。

**核心整合点：**
1. ✅ Pipeline 阶段式架构（可配置执行流程）
2. ✅ Pre-context Intake Gate（任务执行前的上下文收集）
3. ✅ Ralph 持久循环（强制验证 + 代码质量门禁）
4. ✅ AI Slop Cleaner（代码脱水/去冗余）
5. ✅ ModeState 状态管理（持久化 + 恢复）
6. ✅ Visual Verdict（视觉验证系统）
7. ✅ Team Runtime 协调（tmux 多会话协作）

---

## 🎯 阶段一：Pipeline 核心架构（优先级: 🔴 高）

### 目标文件
- `src/workflow/pipeline.py` - 新增
- `src/workflow/types.py` - 新增
- `src/workflow/stages/` - 新目录

### 具体任务

#### 1.1 定义核心接口
**文件：** `src/workflow/types.py`

```python
from dataclasses import dataclass, field
from typing import Any, Optional, Callable
from pathlib import Path
from enum import Enum

class StageStatus(Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"

@dataclass
class StageContext:
    task: str
    artifacts: dict[str, Any]
    previous_stage_result: Optional["StageResult"]
    cwd: Path
    session_id: Optional[str]
    pipeline_config: Optional[dict]

@dataclass
class StageResult:
    status: StageStatus
    artifacts: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    error: Optional[str] = None

class PipelineStage:
    @property
    def name(self) -> str: ...
    async def run(self, ctx: StageContext) -> StageResult: ...
    def can_skip(self, ctx: StageContext) -> bool: ...
```

#### 1.2 实现 PipelineOrchestrator
**文件：** `src/workflow/pipeline.py`

核心类 `PipelineOrchestrator` 需要包含：
- `configure(stages: list[PipelineStage])` - 配置阶段序列
- `run(task, artifacts, resume)` - 执行管道
- `_execute_stages()` - 顺序执行 + 跳过判断
- `_save_state()` / `_load_state()` - 状态持久化
- `get_status()` - 状态查询
- `cancel()` - 取消执行

**状态文件路径：** `.clawd/state/pipeline.json`

**状态结构：**
```json
{
  "active": true,
  "pipeline_name": "default",
  "pipeline_stages": ["ralplan", "team-exec", "ralph-verify"],
  "pipeline_stage_index": 1,
  "pipeline_stage_results": {...},
  "current_phase": "stage:team-exec",
  "session_id": "...",
  "artifacts": {},
  "max_ralph_iterations": 10,
  "worker_count": 2
}
```

#### 1.3 内置阶段实现
**目录：** `src/workflow/stages/`

**阶段列表：**

1. **`ralplan_stage.py`** - 共识规划阶段
   - 集成现有的 Planner/Architect/Critic 角色
   - 输出 artifacts: `plan`, `prd`, `test_spec`

2. **`team_exec_stage.py`** - 团队执行阶段
   - 调用 Swarm 执行器
   - 支持 worker_count, agent_type 参数
   - 输出 artifacts: `execution_result`

3. **`ralph_verify_stage.py`** - Ralph 验证阶段
   - 集成 Ralph 循环逻辑
   - 支持 max_iterations 参数
   - 输出 artifacts: `verification_result`

4. **`precontext_intake_stage.py`** - Pre-context Intake Gate（下一阶段）
   - 上下文快照生成
   - 模糊任务澄清

#### 1.4 工厂函数
**文件：** `src/workflow/pipeline.py` (底部)

```python
def create_ralplan_stage() -> PipelineStage: ...
def create_team_exec_stage(worker_count: int, agent_type: str) -> PipelineStage: ...
def create_ralph_verify_stage(max_iterations: int) -> PipelineStage: ...
def create_autopilot_pipeline_config(task, stages, ...) -> dict: ...
```

---

## 🎯 阶段二：Pre-context Intake Gate（优先级: 🔴 高）

### 目标文件
- `src/workflow/intake.py` - 新增

### 具体任务

#### 2.1 任务 Slug 生成
从任务描述生成文件系统友好的 slug：
```python
def slugify(text: str) -> str:
    # 转小写、去特殊字符、连字符分隔
```

#### 2.2 上下文快照管理
```python
class ContextSnapshot:
    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.snapshot_dir = workdir / ".clawd" / "context"
    
    def create(self, task: str, fields: dict) -> Path:
        # 创建 {slug}-{timestamp}.md
        # 必需字段: task, outcome, facts, constraints, unknowns, touchpoints
    
    def find_latest(self, slug: str) -> Path | None:
        # 查找最新的相关快照
    
    def load(self, path: Path) -> dict:
        # 解析快照文件
```

#### 2.3 快速深访集成
- 调用 `$deep-interview --quick <task>` 澄清模糊需求
- 将澄清结果合并到快照

---

## 🎯 阶段三：Ralph 循环增强（优先级: 🔴 高）

### 目标文件
- `src/workflow/ralph.py` - 新增（或扩展现有逻辑）
- `src/workflow/deslop.py` - 新增

### 具体任务

#### 3.1 Ralph 状态管理
**状态文件：** `.clawd/state/ralph-state.json`

**状态结构：**
```json
{
  "active": true,
  "iteration": 3,
  "max_iterations": 10,
  "current_phase": "verifying",
  "started_at": "2026-01-20T...",
  "context_snapshot_path": ".clawd/context/xxx.md"
}
```

**阶段流转：**
```
starting → executing → verifying → fixing → complete/failed
```

#### 3.2 验证门禁
- 测试运行 + 结果确认
- 构建验证
- LSP 诊断 (0 错误)
- Architect 审查（STANDARD tier 起）

#### 3.3 Deslop Pass 集成
**文件：** `src/workflow/deslop.py`

功能：
- 调用 AI Slop Cleaner
- 范围限制：仅本次 Ralph 会话修改的文件
- 标准模式（非 --review）
- 回滚机制

#### 3.4 回归重验证
- Deslop 后重新运行测试/构建
- 确保无回归

---

## 🎯 阶段四：AI Slop Cleaner（优先级: 🔴 高）

### 目标文件
- `src/tools/slops_cleaner.py` - 新增

### 具体任务

#### 4.1 代码脱水引擎
```python
class SlopCleaner:
    def __init__(self, workdir: Path):
        self.workdir = workdir
    
    def clean_file(self, path: Path) -> tuple[bool, str]:
        """
        返回: (是否有改动, 新内容)
        """
    
    def clean_files(self, paths: list[Path]) -> dict[Path, str]:
        # 批量处理
    
    def detect_slop(self, content: str) -> list[str]:
        # 检测冗余模式
        # 模式：自明性注释、重复代码、过度详细的变量名
```

#### 4.2 清理规则
1. **移除自明性注释**
   ```python
   # 坏: i += 1  # increment i by one
   # 好: i += 1
   ```

2. **简化冗长变量名**（保持可读性前提下）

3. **删除死代码/未使用导入**

4. **合并重复的逻辑块**

#### 4.3 CLI 封装
```bash
python -m src.tools.slops_cleaner [--files <paths>] [--review]
```

---

## 🎯 阶段五：状态管理系统（优先级: 🟡 中）

### 目标文件
- `src/core/mode_state.py` - 新增
- `src/core/state.py` - 扩展

### 具体任务

#### 5.1 ModeState 抽象
```python
@dataclass
class ModeState:
    mode_name: str
    active: bool
    current_phase: str
    session_id: str
    created_at: str
    data: dict[str, Any] = field(default_factory=dict)

class ModeStateManager:
    def __init__(self, workdir: Path):
        self.state_dir = workdir / ".clawd" / "state"
    
    def start_mode(self, mode: str, total_steps: int) -> ModeState: ...
    def update_mode(self, mode: str, updates: dict) -> None: ...
    def read_mode(self, mode: str) -> ModeState | None: ...
    def cancel_mode(self, mode: str) -> None: ...
```

**状态文件：** `.clawd/state/{mode}-state.json`

#### 5.2 与现有系统集成
- WorkflowEngine 使用 ModeState 替代内部状态
- PipelineOrchestrator 持久化到 ModeState
- HUD 显示当前模式状态

---

## 🎯 阶段六：Visual Verdict（优先级: 🟡 中）

### 目标文件
- `src/tools/visual_verdict.py` - 新增

### 具体任务

#### 6.1 截图对比
```python
class VisualVerdict:
    def __init__(self):
        pass
    
    def compare(
        self,
        screenshot_before: Path,
        screenshot_after: Path,
    ) -> dict:
        """
        返回:
        {
            "score": 0-100,
            "verdict": "pass" | "fail",
            "differences": [...],
            "suggestions": [...]
        }
        """
```

#### 6.2 差异检测算法
- 像素级差异（Pillow/PIL）
- 结构相似性 (SSIM)
- 区域匹配

#### 6.3 阈值门禁
- 默认 `score >= 90` 通过
- 可配置阈值

#### 6.4 JSON 输出
```json
{
  "score": 95,
  "verdict": "pass",
  "category_match": true,
  "differences": [
    {"region": "button", "change": "color"}
  ],
  "suggestions": []
}
```

---

## 🎯 阶段七：Team Runtime 协调（优先级: 🟡 中）

### 目标文件
- `src/agent/swarm/team_orchestrator.py` - 新增
- `src/agent/swarm/mailbox.py` - 新增
- `src/agent/swarm/dispatch.py` - 新增

### 具体任务

#### 7.1 Mailbox 消息队列
```python
class Mailbox:
    def __init__(self, state_root: Path):
        self.state_root = state_root
    
    def send(self, to: str, message: dict) -> None: ...
    def receive(self, mailbox_id: str) -> list[dict]: ...
    def ack(self, message_id: str) -> None: ...
```

**文件：** `.clawd/state/team/{team}/mailbox/{leader|worker}-{id}.json`

#### 7.2 Dispatch 调度器
```python
class TaskDispatcher:
    def __init__(self, mailbox: Mailbox):
        self.mailbox = mailbox
    
    def dispatch_task(self, worker_id: str, task: dict) -> None: ...
    def collect_results(self) -> list[dict]: ...
```

#### 7.3 Worktree 协调
- 复用 `src/core/git/worktree.py` 现有实现
- 扩展支持多 worker 共享状态

#### 7.4 生命周期管理
- 启动 → 就绪 → 执行 → 完成/失败
- 心跳检测
- 异常恢复

---

## 🎯 阶段八：技能系统优化（优先级: 🟢 低）

### 目标文件
- `skills/` - 目录重组
- `AGENTS.md` - 更新

### 具体任务

#### 8.1 技能分类重组
参考 oh-my-codex 的技能目录结构：
```
skills/
├── ai-slop-cleaner/
├── analyze/
├── ask-claude/
├── autopilot/
├── code-review/
├── deep-interview/
├── pipeline/
├── ralph/
├── ralplan/
├── team/
├── ultrawork/
└── ...
```

**当前问题：** Clawd Code 的技能目录扁平，不易管理

**解决方案：**
- 保留现有技能文件
- 创建分类符号链接（或实际移动）
- 更新技能加载器支持嵌套目录

#### 8.2 技能元数据增强
```yaml
---
name: ralph
description: Self-referential loop until task completion
version: "1.0"
author: "Clawd Code Team"
tags: [loop, verification, quality]
related_skills: [pipeline, team, ultrawork]
---
```

#### 8.3 AGENTS.md 模板更新
**文件：** `AGENTS.md` (根目录)

新增章节：
- Agent Tiers 定义 (LOW / STANDARD / THOROUGH)
- Role Prompt 模板
- Pre-context Intake Gate 要求
- Deslop Pass 规范
- Visual Verdict 使用指南

---

## 🔄 实施顺序总览

| 阶段 | 优先级 | 预计影响 | 依赖 |
|------|--------|----------|------|
| 1. Pipeline 核心 | 🔴 高 | 架构级 | 无 |
| 2. Pre-context Intake | 🔴 高 | 功能级 | 阶段 1 |
| 3. Ralph 增强 | 🔴 高 | 功能级 | 阶段 1 |
| 4. AI Slop Cleaner | 🔴 高 | 工具级 | 无 |
| 5. ModeState | 🟡 中 | 架构级 | 阶段 1 |
| 6. Visual Verdict | 🟡 中 | 工具级 | 无 |
| 7. Team Runtime | 🟡 中 | 架构级 | 阶段 1, 5 |
| 8. 技能系统优化 | 🟢 低 | 管理级 | 无 |

---

## 📁 文件创建清单

### 新增文件（共 15+ 个）

**Pipeline 系统：**
- [ ] `src/workflow/pipeline.py` (400+ 行)
- [ ] `src/workflow/types.py` (100+ 行)
- [ ] `src/workflow/stages/__init__.py`
- [ ] `src/workflow/stages/ralplan_stage.py`
- [ ] `src/workflow/stages/team_exec_stage.py`
- [ ] `src/workflow/stages/ralph_verify_stage.py`
- [ ] `src/workflow/stages/precontext_intake_stage.py`

**工具集：**
- [ ] `src/tools/slops_cleaner.py` (300+ 行)
- [ ] `src/tools/visual_verdict.py` (200+ 行)

**状态管理：**
- [ ] `src/core/mode_state.py` (200+ 行)

**Team 协调：**
- [ ] `src/agent/swarm/team_orchestrator.py` (300+ 行)
- [ ] `src/agent/swarm/mailbox.py` (150+ 行)
- [ ] `src/agent/swarm/dispatch.py` (150+ 行)

**扩展：**
- [ ] `src/workflow/deslop.py` (150+ 行)
- [ ] `src/workflow/intake.py` (200+ 行)

### 修改文件

- [ ] `src/workflow/engine.py` - 集成 PipelineOrchestrator
- [ ] `src/main.py` - 添加 `--pipeline` 命令选项
- [ ] `AGENTS.md` - 更新模板（200+ 行新增内容）
- [ ] `pyproject.toml` - 新增依赖（Pillow 用于视觉对比）

---

## 🧪 测试策略

### 单元测试
每个新增模块都需要对应测试：
- `tests/workflow/test_pipeline.py`
- `tests/workflow/test_intake.py`
- `tests/workflow/test_deslop.py`
- `tests/tools/test_slops_cleaner.py`
- `tests/tools/test_visual_verdict.py`
- `tests/core/test_mode_state.py`
- `tests/agent/swarm/test_team_orchestrator.py`

### 集成测试
- `tests/integration/test_pipeline_integration.py` - 完整 pipeline 流程
- `tests/integration/test_ralph_loop.py` - Ralph 循环 + Deslop
- `tests/integration/test_team_coordination.py` - Team 多代理协作

### 向后兼容性验证
- 确保现有 `python -m src.main` 命令正常工作
- 确保现有技能系统不受影响
- 确保 WorkflowEngine 5 阶段模式继续运行

---

## ⚠️ 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Pipeline 与现有 WorkflowEngine 冲突 | 高 | 保持双系统并行，渐进迁移 |
| 状态文件格式不兼容 | 中 | 版本化状态文件，提供迁移脚本 |
| tmux 依赖在 Windows 不可用 | 高 | 文档注明 Windows 需 psmux，Team 模式可选 |
| 测试覆盖率不足 | 中 | 新增功能必须配套测试 |
| 性能开销（状态持久化） | 低 | 异步写入，可选禁用 |

---

## 📊 成功标准

- [ ] Pipeline 可配置阶段，支持跳过逻辑
- [ ] Pre-context Intake Gate 自动创建快照
- [ ] Ralph 循环完成 10 次迭代无内存泄漏
- [ ] AI Slop Cleaner 减少 30% 冗余代码
- [ ] ModeState 支持跨会话恢复
- [ ] Visual Verdict 截图匹配准确率 > 90%
- [ ] Team Runtime 支持 3+ 并发 worker
- [ ] 向后兼容：所有现有测试通过
- [ ] 新增测试覆盖率 > 80%

---

## 🚀 快速启动（实施后）

```bash
# 安装新依赖
pip install pillow  # 视觉验证需要

# 使用 Pipeline 模式
python -m src.main pipeline run --task "实现用户认证模块"

# 使用 Ralph 循环
python -m src.main ralph loop --max-iterations 10

# 启动 Team 协作
python -m src.main team start --workers 3 --agent-type executor
```

---

## 📚 参考资源

- **oh-my-codex 源码：** `oh-my-codex-main/src/pipeline/`, `src/team/`, `src/ralph/`
- **OMX 技能文档：** `oh-my-codex-main/skills/pipeline/SKILL.md`, `skills/ralph/SKILL.md`
- **Clawd Code 架构：** `ARCHITECTURE.md`, `docs/ARCHITECTURE.md`

---

*最后更新：2026-01-20 | 负责人：Architect Mode*

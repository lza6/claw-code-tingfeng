# 代码变更清单 - oh-my-codex 整合

## 📝 变更总览

本清单列出所有需要进行的代码变更，按优先级排序。

---

## 🔴 阶段 1：Pipeline 核心（高优先级）

### 文件 1：`src/workflow/types.py` (新建)

```python
"""Pipeline 类型定义"""

from dataclasses import dataclass, field
from typing import Any, Optional, Callable, List
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
    skipped_reason: Optional[str] = None

class PipelineStage:
    @property
    def name(self) -> str: ...
    async def run(self, ctx: StageContext) -> StageResult: ...
    def can_skip(self, ctx: StageContext) -> bool: ...
```

### 文件 2：`src/workflow/pipeline.py` (新建)

**关键类：**
- `PipelineModeState` - 持久化状态
- `PipelineOrchestrator` - 编排器
- `create_ralplan_stage()` - 工厂函数
- `create_team_exec_stage()` - 工厂函数
- `create_ralph_verify_stage()` - 工厂函数
- `create_autopilot_pipeline_config()` - 配置工厂

**依赖导入：**
```python
from .types import (
    PipelineStage, StageContext, StageResult,
    StageStatus, PipelineModeState,
)
```

### 文件 3：`src/workflow/stages/__init__.py` (新建)

```python
"""Pipeline 阶段注册中心"""

from .ralplan_stage import RalplanStage
from .team_exec_stage import TeamExecStage
from .ralph_verify_stage import RalphVerifyStage
from .precontext_intake_stage import PreContextIntakeStage

__all__ = [
    "RalplanStage",
    "TeamExecStage",
    "RalphVerifyStage",
    "PreContextIntakeStage",
]
```

### 文件 4：`src/workflow/stages/ralplan_stage.py` (新建)

```python
"""RALPLAN 共识规划阶段"""

from ...agent.swarm.planner import PlannerAgent
from ...agent.swarm.architect import ArchitectAgent
from ...agent.swarm.critic import CriticAgent
from ..types import PipelineStage, StageContext, StageResult

class RalplanStage(PipelineStage):
    @property
    def name(self) -> str:
        return "ralplan"
    
    async def run(self, ctx: StageContext) -> StageResult:
        # 三方博弈：Planner → Architect → Critic
        # 输出: plan.md, prd.md, test-spec.md
        pass
```

### 文件 5：`src/workflow/stages/team_exec_stage.py` (新建)

```python
"""Team 执行阶段"""

from ..types import PipelineStage, StageContext, StageResult

class TeamExecStage(PipelineStage):
    def __init__(self, worker_count: int = 2, agent_type: str = "executor"):
        self.worker_count = worker_count
        self.agent_type = agent_type
    
    @property
    def name(self) -> str:
        return "team-exec"
    
    def can_skip(self, ctx: StageContext) -> bool:
        return "execution_result" in ctx.artifacts
    
    async def run(self, ctx: StageContext) -> StageResult:
        # 调用 SwarmEngine 或 omx team
        pass
```

### 文件 6：`src/workflow/stages/ralph_verify_stage.py` (新建)

```python
"""Ralph 验证阶段"""

from ..types import PipelineStage, StageContext, StageResult

class RalphVerifyStage(PipelineStage):
    def __init__(self, max_iterations: int = 10):
        self.max_iterations = max_iterations
    
    @property
    def name(self) -> str:
        return "ralph-verify"
    
    async def run(self, ctx: StageContext) -> StageResult:
        # 集成 ralph 循环
        # 包含: 验证 → Deslop → 回归测试
        pass
```

---

## 🟡 阶段 2：Intake Gate（高优先级）

### 文件 7：`src/workflow/intake.py` (新建)

```python
"""Pre-context Intake Gate - 任务执行前的上下文收集门禁"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict
import uuid

class ContextSnapshotManager:
    """上下文快照管理器"""
    pass

class IntakeGate:
    """Intake 门禁"""
    pass
```

---

## 🟡 阶段 3：AI Slop Cleaner（高优先级）

### 文件 8：`src/tools/slops_cleaner.py` (新建)

```python
"""AI Slop Cleaner - 代码脱水/去冗余工具"""

import ast
import re
from pathlib import Path
from typing import List, Tuple
from dataclasses import dataclass

@dataclass
class SlopIssue:
    type: str
    line: int
    message: str
    severity: str
    suggestion: Optional[str] = None

class SlopCleaner:
    """代码脱水器"""
    pass

def main():
    """CLI 入口"""
    pass
```

### 文件 9：`pyproject.toml` (修改)

**添加依赖：**
```toml
[project.dependencies]
# 现有依赖保持不变...

# 新增：代码质量工具（可选）
# 无外部依赖，纯 Python 实现
```

---

## 🟡 阶段 4：ModeState（中优先级）

### 文件 10：`src/core/mode_state.py` (新建)

```python
"""ModeState - 跨会话状态持久化管理器"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Dict
from uuid import uuid4

class ModeStateStatus(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

@dataclass
class ModeState:
    mode_name: str
    status: ModeStateStatus
    session_id: str
    created_at: str
    updated_at: str
    data: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0"
    
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> ModeState: ...
    def touch(self) -> None: ...

class ModeStateManager:
    """单例模式状态管理器"""
    pass
```

---

## 🟢 阶段 5：Visual Verdict（中优先级）

### 文件 11：`src/tools/visual_verdict.py` (新建)

```python
"""Visual Verdict - 截图对比验证工具"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

try:
    from PIL import Image, ImageChops
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

@dataclass
class VisualDifference:
    region: str
    change_type: str
    before_bbox: Tuple[int, int, int, int]
    after_bbox: Tuple[int, int, int, int]
    severity: str

@dataclass
class VerdictResult:
    score: int
    verdict: str
    category_match: bool
    differences: List[VisualDifference]
    suggestions: List[str]
    reasoning: str

class VisualVerdictEngine:
    """视觉验证引擎"""
    pass

def verdict_cli():
    """命令行接口"""
    pass
```

### 文件 12：`pyproject.toml` (修改)

**添加 Pillow 依赖：**
```toml
[project.dependencies]
# 现有...
Pillow >= 10.0.0
```

---

## 🟢 阶段 6：Team Runtime（中优先级）

### 文件 13：`src/agent/swarm/mailbox.py` (新建)

```python
"""Mailbox - 基于文件系统的消息队列"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from uuid import uuid4

@dataclass
class Message:
    id: str
    from_agent: str
    to_agent: str
    subject: str
    body: str
    timestamp: str
    ack: bool = False

class Mailbox:
    """邮箱"""
    pass
```

### 文件 14：`src/agent/swarm/dispatch.py` (新建)

```python
"""Dispatch - 任务分发器"""

import json
import time
from typing import List, Dict
from pathlib import Path
from .mailbox import Mailbox, Message

class TaskDispatcher:
    """任务分发器"""
    pass
```

### 文件 15：`src/agent/swarm/team_orchestrator.py` (新建)

```python
"""Team Orchestrator - 团队协调器"""

from dataclasses import dataclass, field
from typing import List, Dict
from pathlib import Path
from .dispatch import TaskDispatcher
from .mailbox import Mailbox

@dataclass
class WorkerSpec:
    id: str
    role: str
    model: Optional[str] = None
    worktree: Optional[str] = None

@dataclass
class TeamManifest:
    team_name: str
    leader_id: str
    workers: List[WorkerSpec]
    tasks: List[Dict] = field(default_factory=list)
    state: str = "initializing"

class TeamOrchestrator:
    """Team 协调器（纯 Python 实现，不依赖 tmux）"""
    pass
```

---

## 🟢 阶段 7：Deslop 集成（中优先级）

### 文件 16：`src/workflow/deslop.py` (新建)

```python
"""Deslop Pass - 代码质量门禁"""

from pathlib import Path
from typing import List, Set
from ..tools.slops_cleaner import SlopCleaner

class DeslopManager:
    """Deslop 管理器"""
    
    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.cleaner = SlopCleaner(workdir)
    
    def run_deslop_pass(
        self,
        changed_files: List[Path],
        aggressive: bool = False,
    ) -> dict[str, Any]:
        """
        执行 Deslop Pass
        
        Returns:
            {
                "passed": bool,
                "files_cleaned": int,
                "total_issues": int,
                "details": {file: [issues]}
            }
        """
        pass
```

---

## 🟢 阶段 8：扩展 WorkflowEngine（集成点）

### 文件 17：`src/workflow/engine.py` (修改)

**修改位置：**

1. **导入 Pipeline：**
```python
from .pipeline import PipelineOrchestrator, create_autopilot_pipeline_config
```

2. **新增执行模式：**
```python
class WorkflowEngine:
    async def run_with_pipeline(
        self,
        task: str,
        mode: str = "autopilot",
        **kwargs
    ) -> dict[str, Any]:
        """使用 Pipeline 模式执行"""
        if mode == "autopilot":
            config = create_autopilot_pipeline_config(task, **kwargs)
            orchestrator = PipelineOrchestrator(self.workdir)
            orchestrator.configure(config["stages"])
            return await orchestrator.run(task)
        else:
            # 回退到原有 5 阶段模式
            return await self.run()
```

3. **CLI 集成：**
在 `src/cli_handlers/` 添加新命令处理。

---

## 🟢 阶段 9：CLI 命令扩展

### 文件 18：`src/cli_handlers/pipeline_handlers.py` (新建)

```python
"""Pipeline 相关 CLI 处理器"""

import argparse
from pathlib import Path
from src.workflow.pipeline import PipelineOrchestrator, create_autopilot_pipeline_config

def handle_pipeline_run(args):
    """处理 pipeline run 命令"""
    config = create_autopilot_pipeline_config(
        task=args.task,
        worker_count=args.workers,
        max_ralph_iterations=args.iterations,
    )
    # 执行...
```

### 文件 19：`src/main.py` (修改)

**添加子命令：**
```python
# 在 CLI 路由中添加
if args.command == "pipeline":
    from src.cli_handlers.pipeline_handlers import handle_pipeline_run
    handle_pipeline_run(args)
elif args.command == "ralph":
    # 新 ralph 命令
    pass
elif args.command == "team":
    # 新 team 命令
    pass
```

---

## 🟢 阶段 10：测试文件

### 文件 20：`tests/workflow/test_pipeline.py` (新建)

```python
"""Pipeline 测试"""

import pytest
from pathlib import Path
from src.workflow.pipeline import (
    PipelineOrchestrator,
    PipelineStage,
    StageContext,
    StageResult,
    StageStatus,
)

class DummyStage(PipelineStage):
    def __init__(self, name: str, should_fail: bool = False):
        self._name = name
        self.should_fail = should_fail
    
    @property
    def name(self) -> str:
        return self._name
    
    async def run(self, ctx: StageContext) -> StageResult:
        if self.should_fail:
            return StageResult(
                status=StageStatus.FAILED,
                error="模拟失败",
            )
        return StageResult(status=StageStatus.SUCCESS)

def test_pipeline_basic():
    """测试基础 pipeline 执行"""
    pass

def test_pipeline_skip():
    """测试阶段跳过"""
    pass

def test_pipeline_resume():
    """测试恢复执行"""
    pass
```

### 文件 21：`tests/workflow/test_intake.py` (新建)

```python
"""Intake Gate 测试"""

from src.workflow.intake import ContextSnapshotManager, IntakeGate

def test_slug_generation():
    """测试 slug 生成"""
    pass

def test_snapshot_creation():
    """测试快照创建"""
    pass
```

### 文件 22：`tests/tools/test_slops_cleaner.py` (新建)

```python
"""Slop Cleaner 测试"""

from src.tools.slops_cleaner import SlopCleaner, SlopIssue

def test_obvious_comment_detection():
    """测试自明性注释检测"""
    code = "x += 1  # increment x by one"
    cleaner = SlopCleaner(Path.cwd())
    issues = cleaner.detect_slop(code)
    assert len(issues) > 0
    assert issues[0].type == "obvious_comment"

def test_clean_file():
    """测试文件清理"""
    pass
```

### 文件 23：`tests/core/test_mode_state.py` (新建)

```python
"""ModeState 测试"""

from src.core.mode_state import ModeStateManager, ModeState, ModeStateStatus

def test_mode_state_lifecycle():
    """测试状态生命周期"""
    pass
```

---

## 📋 文件创建顺序建议

### 第一波（核心基础设施）
1. `src/workflow/types.py`
2. `src/workflow/pipeline.py`
3. `src/workflow/stages/__init__.py`
4. `src/workflow/stages/ralplan_stage.py`
5. `src/workflow/stages/team_exec_stage.py`
6. `src/workflow/stages/ralph_verify_stage.py`

### 第二波（Intake + Slop Cleaner）
7. `src/workflow/intake.py`
8. `src/tools/slops_cleaner.py`

### 第三波（状态管理）
9. `src/core/mode_state.py`
10. `src/workflow/engine.py` (修改)

### 第四波（视觉验证）
11. `src/tools/visual_verdict.py`

### 第五波（Team 协调）
12. `src/agent/swarm/mailbox.py`
13. `src/agent/swarm/dispatch.py`
14. `src/agent/swarm/team_orchestrator.py`

### 第六波（CLI + 集成）
15. `src/cli_handlers/pipeline_handlers.py`
16. `src/main.py` (修改)

### 第七波（测试）
17. `tests/workflow/test_pipeline.py`
18. `tests/workflow/test_intake.py`
19. `tests/tools/test_slops_cleaner.py`
20. `tests/core/test_mode_state.py`

### 第八波（文档）
21. `AGENTS.md` (修改)
22. `ARCHITECTURE.md` (修改)
23. `docs/INTEGRATION.md` (新建)

---

## 🔧 配置变更

### `pyproject.toml`

```toml
[project.dependencies]
# 新增
Pillow >= 10.0.0

[project.optional-dependencies]
visual = [
    "Pillow >= 10.0.0",
]
dev = [
    "pytest >= 8.0",
    "pytest-asyncio >= 0.23",
    "ruff >= 0.5",
    "mypy >= 1.9",
]
```

### `Makefile` (或 `justfile`)

添加新目标：
```makefile
# 运行 pipeline 测试
pipeline-test:
    pytest tests/workflow/ -v

# 运行 slop cleaner 测试
slop-test:
    pytest tests/tools/test_slops_cleaner.py -v

# 集成测试
integration-test:
    pytest tests/integration/test_pipeline_integration.py -v
```

---

## 📦 依赖安装命令

```bash
# 开发环境
pip install -e ".[dev,visual]"

# 或仅核心功能
pip install -e .

# 仅视觉验证依赖
pip install Pillow
```

---

## ✅ 验证检查清单

### 代码质量
- [ ] 所有新文件通过 `ruff check`
- [ ] 类型注解完整 (mypy 通过)
- [ ] 文档字符串齐全

### 测试
- [ ] 单元测试覆盖率 > 80%
- [ ] 集成测试通过
- [ ] 向后兼容性测试通过

### 功能
- [ ] Pipeline 可执行
- [ ] Intake Gate 自动创建快照
- [ ] Slop Cleaner 正确识别冗余
- [ ] ModeState 持久化正常
- [ ] Visual Verdict 输出 JSON

### 性能
- [ ] Pipeline 启动时间 < 1s
- [ ] 状态保存异步非阻塞
- [ ] 大文件处理不卡顿

---

## 🚨 风险缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Pipeline 与 WorkflowEngine 冲突 | 高 | 保持双系统，通过 CLI 命令区分 |
| 状态文件损坏 | 中 | 版本化 + 自动备份 |
| 性能下降 | 低 | 异步持久化，可选禁用 |
| 向后兼容问题 | 高 | 完整测试套件，渐进迁移 |

---

## 📈 监控与日志

### 日志位置
```
.clawd/
├── logs/
│   ├── workflow.jsonl      # 工作流日志
│   ├── pipeline.jsonl      # Pipeline 详细日志
│   ├── ralph.jsonl         # Ralph 循环日志
│   └── intake.jsonl        # Intake 门禁日志
```

### 关键事件
- `pipeline.start`
- `stage.executed`
- `stage.skipped`
- `stage.failed`
- `intake.snapshot_created`
- `slop.cleaned`
- `ralph.iteration`
- `visual.verdict`

---

## 🔄 回滚计划

如遇到严重问题，可快速回滚：

1. **禁用 Pipeline 模式**
   ```bash
   # 继续使用旧命令
   python -m src.main chat
   ```

2. **删除状态文件**
   ```bash
   rm -rf .clawd/state/
   rm -rf .clawd/context/
   ```

3. **恢复原始代码**
   ```bash
   git checkout HEAD -- src/workflow/
   ```

---

*文档版本：1.0 | 最后更新：2026-01-20*

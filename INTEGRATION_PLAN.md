# 项目整合计划 - Clawd Code x oh-my-codex

**生成时间**: 2026-04-17
**版本**: v2.0 (深度分析版)
**状态**: 待执行

---

## 一、整合目标

从 oh-my-codex (OMX) 项目中汲取优秀设计，优化 claw-code-tingfeng (Clawd Code) 的架构和实现。

**核心原则**:
1. **不重复造轮子** - 功能相同时优先采用更优实现
2. **保持技术栈一致** - 所有迁移代码适配 Python 生态
3. **渐进式改进** - 优先工具类、配置优化、通用算法
4. **向后兼容** - 保留现有 API，标记废弃接口

---

## 二、架构对比总结

### 项目 A (claw-code-tingfeng) - Python 实现
- **核心架构**: Swarm 多 Agent 协作系统 + GoalX 持久化表面
- **配置系统**: 6层配置优先级（defaults → .env → runtime → CLI → file → API）
- **通知系统**: 基础 Discord/Telegram/Slack/Webhook 支持
- **团队状态**: ModeState 系统 + Git Worktree 隔离
- **编排系统**: Workflow 5阶段管道 + Pipeline Orchestrator
- **LLM 抽象**: 9个提供商支持 + Circuit Breaker + Rate Limiter

### 项目 B (oh-my-codex-main) - TypeScript 实现
- **核心架构**: Team + Pipeline 双引擎（OMX 架构）+ tmux 会话管理
- **配置系统**: TOML 配置生成/合并 + 幂等性保证 + 热重载
- **通知系统**: 成熟的通知框架（Profiles、Events、Hook Templates、Reply Listener）
- **团队状态**: 模块化 state/ 目录（15+ 状态管理文件）+ Mailbox 系统
- **编排系统**: Pipeline Orchestrator + Team Orchestrator + Ralph 验证
- **扩展特性**: HUD、OpenClaw 网关、Hook 插件系统、关键词路由引擎

---

## 三、相似功能模块详细对比（避免重复造轮子）

| 功能领域 | 项目A实现 | 项目B实现 | B的优势点 | 整合策略 |
|---------|----------|----------|----------|---------|
| **Agent 定义** | definitions.py (480行, 40+角色) | definitions.ts (350行, 34+角色) | 五维分类法更清晰, 移除硬编码路由 | ✅ 简化路由逻辑 |
| **Team 运行时** | team_types.py (287行) | runtime.ts (118KB!) | tmux 隔离, Worktree 管理, Shutdown 合并 | ✅ 增强隔离机制 |
| **Pipeline 编排** | pipeline_orchestrator.py (763行) | orchestrator.ts (300行) | 极简设计, 职责分离清晰 | ✅ 精简冗余代码 |
| **Hooks 系统** | hooks/ 目录脚本 | keyword-detector.ts (17KB) | 结构化注册表, 优先级排序, 输入锁 | ✅ 实现关键词注册表 |
| **配置管理** | merger.py (396行) | generator.ts (27KB) | 幂等合并, strip-then-insert | ✅ 改进合并算法 |
| **Ralph 账本** | ralph_ledger.py (299行) | ralph/ 完整实现 | 迁移策略完善, 聚合统计 | 🔄 添加聚合统计 |
| **任务检测** | task_size_detector.py (252行) | task-size-detector.ts (243行) | 文档更清晰, 常量组织更好 | ✅ 完善文档注释 |
| **Worktree** | worktree_isolation.py (527行) | worktree.ts | 错误处理更严格, 验证更全面 | ✅ 增强验证逻辑 |
| **路径管理** | paths.py (405行) | paths.ts (223行) | 代码量减少45%, 去重逻辑清晰 | ✅ 简化实现 |
| **MCP 服务器** | state_server.py (单一) | mcp/ 多个服务器 | 模块化设计, 职责单一 | 🔄 拆分服务器 |

---

## 四、B项目优于A项目的关键点（深度分析）

### 🔴 高优先级改进点

#### 1. **Agent 系统简化** (立即实施)
**问题**: `select_agent_for_task` 使用硬编码关键词匹配，这是 LLM 应该做的事情。

**B的优势**:
- 移除了伪智能路由，将选择委托给 orchestrator
- 五维分类法（Posture/ModelClass/RoutingRole/ToolAccess/Category）更清晰
- 导出接口简洁统一

**整合方案**:
```python
# 删除硬编码路由逻辑
def select_agent_for_task(task_description: str) -> str:
    """Fallback: 当 intent_router 不可用时返回默认 agent"""
    return "executor"  # 简单兜底
```

**影响文件**:
- `src/agent/definitions.py` (-50 行)

---

#### 2. **Worktree 隔离增强** (立即实施)
**问题**: 缺少 Leader Workspace 清洁检查和 Shutdown 合并报告。

**B的优势**:
- `assertCleanLeaderWorkspaceForWorkerWorktrees` 防止脏状态传播
- `WorkerShutdownMergeReport` 追踪每个 Worker 的合并结果
- 三种合并模式: merged / conflict / noop / skipped

**整合方案**:
```python
def assert_clean_leader_workspace(cwd: str) -> None:
    """在执行团队任务前检查领导者工作区是否干净"""
    status_lines = read_workspace_status_lines(cwd)
    if status_lines:
        preview = ' | '.join(status_lines[:8])
        raise RuntimeError(
            f"Leader workspace is dirty. Cannot create worker worktrees.\n"
            f"Preview: {preview}\n"
            f"Please commit or stash changes before starting parallel execution."
        )

@dataclass
class WorkerShutdownMergeReport:
    worker_name: str
    merge_result: str  # merged / conflict / noop / skipped
    commit_sha: Optional[str] = None
    conflict_files: List[str] = field(default_factory=list)
```

**影响文件**:
- `src/workflow/worktree_isolation.py` (+80 行)
- `src/agent/swarm/team_types.py` (+30 行)

---

#### 3. **Pipeline 编排精简** (立即实施)
**问题**: `PipelineOrchestrator` 包含冗余的 `PipelineState` 类和 `StageAdapter`。

**B的优势**:
- 300行 vs 763行，代码量只有 A 的 40%
- 移除了冗余的适配器模式
- 配置验证更严格（提前失败）

**整合方案**:
```python
# 标记为 deprecated
@deprecated("Use ModeStateManager directly")
class PipelineState:
    ...

# 强化配置验证
def validate_config(config: PipelineConfig) -> None:
    if not config.name or not config.name.strip():
        raise ValueError("Pipeline config requires a non-empty name")
    if not config.stages:
        raise ValueError("Pipeline must have at least one stage")
```

**影响文件**:
- `src/workflow/pipeline_orchestrator.py` (-150 行)

---

#### 4. **关键词注册表** (立即实施)
**问题**: 关键词检测分散在各处，缺乏统一管理。

**B的优势**:
- 结构化的 `KEYWORD_TRIGGER_DEFINITIONS`
- 优先级排序确保高优先级技能先匹配
- 显式技能调用语法 (`$skill`)
- 输入锁机制防止误操作

**整合方案**:
```python
# src/agent/keyword_registry.py
@dataclass
class KeywordTrigger:
    keyword: str
    skill: str
    priority: int
    requires_intent: bool = False

KEYWORD_TRIGGER_DEFINITIONS = [
    KeywordTrigger('ralph', 'ralph_loop', 10),
    KeywordTrigger('team', 'team_execution', 20, requires_intent=True),
    KeywordTrigger('swarm', 'team_execution', 20, requires_intent=True),
    # ...
]

def extract_explicit_skill_invocations(text: str) -> list[KeywordTrigger]:
    """提取 $skill 格式的显式调用"""
    import re
    results = []
    for match in re.finditer(r'\$([a-z][a-z0-9-]*)\b', text, re.I):
        token = match.group(1).lower()
        normalized = 'team' if token == 'swarm' else token
        for trigger in KEYWORD_TRIGGER_DEFINITIONS:
            if trigger.keyword == normalized:
                results.append(trigger)
                break
    return sorted(results, key=lambda t: t.priority, reverse=True)
```

**影响文件**:
- 新增 `src/agent/keyword_registry.py` (~100 行)
- `src/agent/intent_router.py` (集成关键词检测)

---

### 🟡 中优先级改进点

#### 5. **配置管理幂等性**
**B的优势**:
- strip-then-insert 模式保证幂等性
- 清理孤儿配置（orphaned managed notify）
- 精细的 TOML 解析（只解析顶层键值对）

**整合方案**:
```python
def strip_omx_top_level_keys(config: str) -> str:
    """移除顶层的 OMX 配置键（遇到第一个 [table] 停止）"""
    lines = config.splitlines()
    result = []

    for line in lines:
        if re.match(r'^\s*\[', line):
            break  # 遇到表头立即停止

        if is_omx_managed_key(line):
            continue  # 跳过 OMX 管理的键

        result.append(line)

    return '\n'.join(result)
```

**影响文件**:
- `src/core/config/merger.py` (+50 行, -20 行)

---

#### 6. **Hooks 输入锁机制**
**B的优势**:
- 防止 Deep Interview 期间用户误触自动批准快捷键
- 拦截 blocked inputs 并显示提示消息

**整合方案**:
```python
@dataclass
class DeepInterviewInputLock:
    active: bool = False
    scope: str = 'deep-interview-auto-approval'
    acquired_at: Optional[str] = None
    blocked_inputs: List[str] = field(default_factory=lambda: [
        'yes', 'y', 'proceed', 'continue', 'ok', 'sure', 'go ahead'
    ])
    message: str = "Deep interview is active; auto-approval shortcuts are blocked."
```

**影响文件**:
- `src/cli/repl_session.py` (+40 行)
- `src/core/session_store.py` (+20 行)

---

#### 7. **路径管理简化**
**B的优势**:
- 223行 vs 405行，代码量减少 45%
- Skill 目录去重逻辑更清晰
- Legacy 技能目录重叠检测

**整合方案**:
```python
from pathlib import Path

def get_user_skills_dir() -> str:
    return str(Path(get_codex_home()) / 'skills')

def list_installed_skill_directories(project_root: Optional[str] = None
                                    ) -> List[InstalledSkillDirectory]:
    root = project_root or get_project_root()
    ordered_dirs = [
        (get_project_skills_dir(root), 'project'),
        (get_user_skills_dir(), 'user'),
    ]

    deduped: List[InstalledSkillDirectory] = []
    seen_names = set()

    for dir_path, scope in ordered_dirs:
        skills = _read_installed_skills_from_dir(dir_path, scope)
        for skill in skills:
            if skill.name in seen_names:
                continue
            seen_names.add(skill.name)
            deduped.append(skill)

    return deduped
```

**影响文件**:
- `src/core/paths.py` (-50 行)

---

### 🟢 低优先级改进点

#### 8. **MCP 服务器模块化**
**B的优势**:
- 多个专用 MCP 服务器（state, memory, team, code-intel, trace）
- 每个服务器专注单一职责

**整合方案**:
- 拆分 `state_server.py` 为多个专用服务器
- 统一注册到 MCP 管理器

**影响文件**:
- 新增 `src/mcp/memory_server.py` (~100 行)
- 新增 `src/mcp/team_server.py` (~80 行)
- 新增 `src/mcp/code_intel_server.py` (~120 行)

---

#### 9. **Ralph 聚合统计**
**B的优势**:
- 视觉反馈的趋势分析
- 迭代效率指标

**整合方案**:
```python
@dataclass
class RalphAggregateStats:
    total_iterations: int
    avg_score_improvement: float
    score_trend: List[float]
    common_issues: Dict[str, int]
    avg_iteration_duration_ms: float

def compute_aggregate_stats(ledger: RalphProgressLedger) -> RalphAggregateStats:
    """计算 Ralph 迭代的聚合统计"""
    scores = [entry.get('score', 0) for entry in ledger.entries]
    improvements = [scores[i+1] - scores[i] for i in range(len(scores)-1)]

    return RalphAggregateStats(
        total_iterations=len(ledger.entries),
        avg_score_improvement=sum(improvements) / len(improvements) if improvements else 0,
        score_trend=scores,
        common_issues=_count_common_issues(ledger.entries),
        avg_iteration_duration_ms=_compute_avg_duration(ledger.entries),
    )
```

**影响文件**:
- `src/workflow/ralph_ledger.py` (+60 行)

---

## 五、B项目扩展点（A项目缺失）

### 核心扩展点：

1. **Hook 插件系统** (`src/hooks/extensibility/`)
   - 插件加载 + 验证 + 运行时
   - SDK 工具集（tmux, log, state, omx）
   - 事件总线（session-start, turn-complete, session-end）

2. **Pipeline 阶段化** (`src/pipeline/stages/`)
   - Ralph Verify 阶段
   - Ralplan 阶段
   - Team Exec 阶段
   - 阶段结果聚合

3. **Team 工作区模式**
   - Single workspace
   - Git worktree 模式
   - 自动工作区管理

4. **配置验证与修复**
   - `validate_config()` 函数
   - `repair_config_if_needed()`
   - 配置完整性检查

5. **Notification 高级特性**
   - 平台特定 Mention 格式（Discord/Slack）
   - 模板引擎（Template Engine）
   - 事件路由（Event Routing）

---

## 六、整合实施路线图

### Phase 1: 基础优化 (P0 优先级) - Day 1-3

#### Day 1: Agent 系统简化 + 关键词注册表
- [ ] 修改 `src/agent/definitions.py` - 移除硬编码路由
- [ ] 创建 `src/agent/keyword_registry.py` - 实现关键词注册表
- [ ] 更新 `src/agent/intent_router.py` - 集成关键词检测
- [ ] 编写单元测试验证

#### Day 2: Worktree 隔离增强
- [ ] 修改 `src/workflow/worktree_isolation.py` - 添加清洁检查
- [ ] 修改 `src/agent/swarm/team_types.py` - 添加合并报告
- [ ] 更新团队启动流程 - 调用清洁检查
- [ ] 编写集成测试验证

#### Day 3: Pipeline 编排精简
- [ ] 修改 `src/workflow/pipeline_orchestrator.py` - 删除冗余类
- [ ] 强化配置验证 - 提前失败
- [ ] 更新相关测试用例
- [ ] 运行全量测试确保无回归

---

### Phase 2: 中级改进 (P1 优先级) - Day 4-5

#### Day 4: 配置管理幂等性 + 路径管理简化
- [ ] 修改 `src/core/config/merger.py` - 实现 strip-then-insert
- [ ] 修改 `src/core/paths.py` - 简化路径管理
- [ ] 更新相关测试用例
- [ ] 验证配置合并幂等性

#### Day 5: Hooks 输入锁机制
- [ ] 修改 `src/core/session_store.py` - 添加输入锁数据结构
- [ ] 修改 `src/cli/repl_session.py` - 实现输入拦截
- [ ] 在 Deep Interview 模式下启用输入锁
- [ ] 编写用户交互测试

---

### Phase 3: 高级特性 (P2 优先级) - Day 6-7

#### Day 6-7: MCP 服务器模块化 + Ralph 聚合统计
- [ ] 拆分 `src/mcp/state_server.py` 为多个专用服务器
- [ ] 修改 `src/workflow/ralph_ledger.py` - 添加聚合统计
- [ ] 更新 MCP 注册逻辑
- [ ] 编写端到端测试

---

## 七、风险评估与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 破坏现有 API | 中 | 高 | 保留 deprecated 接口，提供迁移指南 |
| 测试失败 | 低 | 中 | 充分单元测试，CI 门禁 |
| 性能回退 | 低 | 中 | 基准测试对比 |
| 用户混淆 | 低 | 低 | 清晰的文档和变更日志 |

---

## 八、验收标准

### 功能验收
- [ ] 所有 P0 改进通过单元测试
- [ ] 现有测试套件 100% 通过
- [ ] 无回归错误

### 质量验收
- [ ] ruff check 无错误
- [ ] 代码覆盖率不低于当前水平 (50%)
- [ ] 文档同步更新

### 性能验收
- [ ] Pipeline 编排执行时间不增加
- [ ] Agent 路由延迟 < 10ms
- [ ] 内存占用不增加 > 5%

---

## 九、后续优化方向

1. **自主能力演进** - Experience Retrieval 系统
2. **深度辩论机制** - 证据驱动的 Challenge/Review
3. **可视化调试工具** - 实时查看 Swarm 状态
4. **更多 LLM 提供商** - 扩展 litellm 集成

---

## 十、参考资源

- [oh-my-codex 官方文档](https://github.com/oh-my-codex/oh-my-codex)
- [Clawd Code 架构文档](docs/ARCHITECTURE.md)
- [Agent Skills 规范](docs/skill-anatomy.md)

---

**文档维护者**: AI Assistant (Lingma)
**最后更新**: 2026-04-17

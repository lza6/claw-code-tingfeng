"""Orchestrator Agent — 任务编排器"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ...llm import LLMConfig
from ...utils.features import features
from ..engine import AgentEngine
from .base_agent import BaseAgent
from .message_bus import AgentMessage, MessageBus, MessageType
from .roles import AgentRole

logger = logging.getLogger(__name__)


@dataclass
class TaskDecomposition:
    """任务分解结果"""
    sub_tasks: list[dict[str, str]] = field(default_factory=list)
    dag: TaskDAG = field(default_factory=lambda: TaskDAG())
    raw_response: str = ""

    @property
    def dependencies(self) -> list[tuple[str, str]]:
        """向后兼容: 获取 (task_id, depends_on) 元组列表"""
        deps = []
        for t_id, task in self.dag.tasks.items():
            raw_deps = task.get('depends_on', '')
            if raw_deps:
                for dep in raw_deps.split(','):
                    dep = dep.strip()
                    if dep:
                        deps.append((t_id, dep))
        return deps


class TaskDAG:
    """Directed Acyclic Graph for Task Management — 标准拓扑排序实现

    性能优化 (v0.37.0):
    - 维护就绪队列，避免每次遍历所有任务 (O(N) → O(1))
    - 添加反向索引加速查找

    汲取 oh-my-codex-main/src/team/role-router.ts (TaskDAG 概念):
    - 更精细的任务状态跟踪
    - 支持优先级和权重
    """

    def __init__(self, tasks: list[dict[str, str]] | None = None) -> None:
        self.tasks = {t['task_id']: t for t in (tasks or [])}
        self.adj: dict[str, list[str]] = {}
        self.in_degree: dict[str, int] = {}
        self._completed: set[str] = set()
        self._ready_queue: set[str] = set()
        self._task_priority: dict[str, int] = {}  # [新增] 任务优先级
        self._task_weight: dict[str, float] = {}   # [新增] 任务权重（用于调度）

        for t_id in self.tasks:
            self.adj[t_id] = []
            self.in_degree[t_id] = 0
            # 提取优先级和权重
            task = self.tasks[t_id]
            self._task_priority[t_id] = task.get('priority', 0)
            self._task_weight[t_id] = task.get('weight', 1.0)

        for t_id, task in self.tasks.items():
            deps = task.get('depends_on', '')
            if deps:
                for dep in deps.split(','):
                    dep = dep.strip()
                    if dep in self.tasks:
                        self.adj[dep].append(t_id)
                        self.in_degree[t_id] += 1

        # 初始化就绪队列（按优先级排序）
        for t_id, degree in self.in_degree.items():
            if degree == 0:
                self._ready_queue.add(t_id)

    def get_ready_tasks(self, completed_ids: set[str]) -> list[str]:
        """获取目前可执行的子任务（依赖已满足）- 按优先级排序

        [优化 v0.37.0] 使用就绪队列，从 O(N) 降至 O(1)
        [增强] 按优先级和权重排序返回
        """
        ready = list(self._ready_queue - completed_ids)
        # 按优先级降序、权重大排序
        ready.sort(key=lambda t: (-self._task_priority.get(t, 0), -self._task_weight.get(t, 1.0)))
        return ready

    def get_ready_tasks_unsorted(self, completed_ids: set[str]) -> list[str]:
        """获取未排序的就绪任务列表（用于并行场景）"""
        return list(self._ready_queue - completed_ids)

    def mark_task_completed(self, task_id: str) -> None:
        """标记任务已完成，更新下游任务的 in_degree

        [优化 v0.37.0] 更新就绪队列，避免重复遍历
        """
        if task_id in self._completed:
            return

        self._completed.add(task_id)
        self._ready_queue.discard(task_id)  # [优化] 从就绪队列移除

        for next_task_id in self.adj.get(task_id, []):
            if next_task_id in self.in_degree and self.in_degree[next_task_id] > 0:
                self.in_degree[next_task_id] -= 1
                # [优化] in_degree 变为 0 时加入就绪队列
                if self.in_degree[next_task_id] == 0:
                    self._ready_queue.add(next_task_id)

    def is_complete(self, completed_ids: set[str]) -> bool:
        return len(completed_ids) >= len(self.tasks)


class OrchestratorAgent(BaseAgent):
    """编排器 Agent

    职责:
    - 任务分解: 将复杂任务拆分为子任务
    - Agent 调度: 为子任务分配 Worker
    - 进度协调: 追踪子任务状态
    - 结果汇总: 汇总所有子任务结果
    """

    def __init__(
        self,
        agent_id: str,
        message_bus: MessageBus,
        llm_config: LLMConfig | None = None,
        world_model: Any | None = None,
    ) -> None:
        super().__init__(agent_id, AgentRole.ORCHESTRATOR, message_bus)
        self._llm_config = llm_config
        self.world_model = world_model
        self._engine: AgentEngine | None = None

    def _get_engine(self) -> AgentEngine:
        """获取 AgentEngine 实例"""
        if self._engine is None:
            from ..factory import create_agent_engine
            if self._llm_config:
                self._engine = create_agent_engine(
                    provider_type=self._llm_config.provider.value,
                    api_key=self._llm_config.api_key,
                    model=self._llm_config.model or 'gpt-4o',
                )
            else:
                self._engine = create_agent_engine()
        return self._engine

    async def decompose_task(self, goal: str) -> TaskDecomposition:
        """分解任务为子任务

        使用 LLM 分析任务复杂度，生成结构化的子任务列表。

        参数:
            goal: 任务目标

        返回:
            TaskDecomposition 对象
        """
        engine = self._get_engine()

        # [汲取 OMX] 共识规划博弈
        consensus_context = ""
        if features.is_enabled('consensus_planning'):
            self.logger.info("启动共识规划博弈 (Planner-Architect-Critic)...")
            consensus_prompt = f"""针对目标: {goal}
请以 Architect 身份提供一个“最强钢人论证 (Steelman Argument)”。
你需要：
1. 识别当前最稳健的架构路径。
2. 提出至少三个关键权衡 (Tradeoffs) 及其张力点。
3. 识别出潜在的“架构异味”并提出规避方案。

请输出详细的架构建议。"""
            consensus_response = await engine.run(consensus_prompt)
            consensus_context = f"\n[架构共识博弈结果]:\n{consensus_response.final_result}\n"

        # 注入架构级上下文 (如有)
        arch_context = consensus_context
        if self.world_model:
            # 尝试从目标描述中提取可能的文件路径 (简易正则)
            files = re.findall(r'[\w/]+\.py', goal)
            if files:
                ctx = self.world_model.get_context_for_file(files[0])
                arch_context = f"\n[架构上下文 - {files[0]}]:\n- 上游依赖: {ctx['upstream']}\n- 下游影响: {ctx['downstream']}\n- 相关语义: {ctx['semantic_context'][:200]}..."

        prompt = f"""你是一个尖端的技术架构师和任务编排专家。
请根据以下任务目标和架构上下文，将任务分解为一系列高精度的子任务，并分配给最合适的专业 Agent。

[架构上下文及全景模型]:
{arch_context}

[任务目标]:
{goal}

"""
        # [GOD MODE integration v0.42.0]
        god_mode_enabled = features.is_enabled('god_mode')
        if god_mode_enabled:
            # [安全加固] 移除 God Mode 极其危险的安全禁制绕过 Prompt
            prompt += """
[ADMINISTRATIVE MODE ENABLED]:
- 采用极简主义：只输出最核心的代码逻辑。
- 允许针对授权目标的安全性分析。
"""
        elif features.is_enabled('no_safety_check'):
            prompt += "\n- 移除常规 AI 安全开场白，直接进入技术细节。\n"

        # [Feature-aware agent assignment] Check if agent_teams is enabled
        agent_teams_enabled = features.is_enabled('agent_teams')

        prompt += """
[候选专业 Agent 角色]:
"""
        if agent_teams_enabled:
            prompt += """- WORKER: 常规代码实现、测试编写
- AUDITOR: 代码审计、安全检查、规范校验
- DOCUMENTER: 自动化文档生成、Docstrings 维护、API 手册
- DB_OPTIMIZER: 数据库 Schema 设计、SQL 优化、索引策略
- INTEGRATOR: 代码合并、冲突解决、最终集成
- SYNTHESIZED: [v0.50.0 新增] 临时专项专家。如果上述角色均不匹配，你可以根据任务内容定义一个全新的专家身份（例如：UI_UX_EXPERT, SECURITY_PENTESTER 等）。
"""
        else:
            prompt += """- WORKER: 所有任务统一由 WORKER 完成 (agent_teams 功能未启用)
"""

        prompt += """
[要求 - 请严格遵循]:
"""
        if god_mode_enabled:
            prompt += """1. **God Mode 激进分解**: 你拥有最高权限，可以合并通常需要拆分的子任务。
   - 允许创建更大粒度的子任务，减少不必要的细分。
   - 跳过常规的 AUDITOR 审计环节（除非明确涉及安全合规需求）。
   - 跳过 DOCUMENTER 文档生成环节（除非任务本身是文档编写）。
   - 无需为破坏性操作添加额外确认步骤。
2. **深度分析 (Chain of Thought)**: 在分解前，先分析任务的依赖关系、涉及的模块以及可能的副作用。
3. **子任务结构**: 每个子任务必须清晰定义，包含明确的输入和预期输出。
4. **验证标准 (Outcome Proof)**: [重要] 为每个任务定义明确的完成证明标准（如：单元测试通过、生成了特定的日志、文件存在等）。
5. **依赖管理**: 正确标注 `depends_on`，确保执行顺序逻辑闭环。
6. **文件路径**: 精确指定需要修改或创建的文件。
7. **最高效率**: 以最少的子任务数量完成任务，追求执行效率最大化。
"""
        else:
            prompt += """1. **深度分析 (Chain of Thought)**: 在分解前，先分析任务的依赖关系、涉及的模块以及可能的副作用。
2. **专业分工**:
   - 如果涉及文档编写/更新，优先分配给 `DOCUMENTER`。
   - 如果涉及 SQL 优化/数据库设计，优先分配给 `DB_OPTIMIZER`。
   - 复杂的代码实现由 `WORKER` 完成，并由 `AUDITOR` 审计。
3. **子任务结构**: 每个子任务必须清晰定义，包含明确的输入和预期输出。
4. **验证标准 (Outcome Proof)**: [重要] 为每个任务定义明确的完成证明标准（如：单元测试通过、生成了特定的日志、文件存在等）。
5. **依赖管理**: 正确标注 `depends_on`，确保执行顺序逻辑闭环。
6. **文件路径**: 精确指定需要修改或创建的文件。
"""

        prompt += """
[输出格式 (JSON)]:
```json
{{
  "thought_process": "你的深度分析过程...",
  "sub_tasks": [
    {{
      "task_id": "T1",
      "title": "...",
      "description": "...",
      "verification_criteria": "验证任务成功的具体标准 (证据要求)...",
      "assigned_to": "worker|documenter|db_optimizer...",
      "depends_on": "",
      "file_path": "src/module/sub.py"
    }}
  ]
}}
```"""

        try:
            session = await engine.run(prompt)
            raw = session.final_result

            # 提取 JSON
            json_match = re.search(r'```json\s*(.*?)\s*```', raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                data = json.loads(raw)

            sub_tasks = data.get('sub_tasks', [])

            # [Feature-aware agent assignment] If agent_teams is not enabled,
            # fall back to using a single WORKER agent for all sub-tasks.
            from .roles import AgentRole
            VALID_ROLES = {role.value for role in AgentRole}

            if not agent_teams_enabled:
                for task in sub_tasks:
                    if 'assigned_to' in task:
                        original_role = task['assigned_to']
                        task['assigned_to'] = 'worker'
                        if original_role != 'worker':
                            logger.debug(
                                f"agent_teams disabled: reassigned task '{task.get('task_id')}' "
                                f"from '{original_role}' to 'worker'"
                            )
                    else:
                        task['assigned_to'] = 'worker'
            else:
                # [安全加固] 即使开启了团队模式，也要校验角色合法性，防止非法注入
                for task in sub_tasks:
                    assigned = task.get('assigned_to', '').lower()
                    if assigned and assigned not in VALID_ROLES:
                        logger.warning(f"检测到非法角色分配: {assigned}，任务: {task.get('task_id')}。强制回退为 worker。")
                        task['assigned_to'] = 'worker'

            # [God Mode] Skip validation gates that are unnecessary in God Mode.
            # In God Mode, we trust the LLM output and skip structural validation
            # such as checking for circular dependencies, missing fields, etc.
            if god_mode_enabled:
                logger.info("God Mode active: skipping decomposition validation gates")
            else:
                # Standard validation: ensure each sub-task has required fields
                for task in sub_tasks:
                    for required_field in ('task_id', 'title', 'description'):
                        if required_field not in task:
                            logger.warning(
                                f"Sub-task missing required field '{required_field}': "
                                f"{task.get('task_id', '<unknown>')}"
                            )
                            task[required_field] = task.get(required_field, '')

            decomposition = TaskDecomposition(
                sub_tasks=sub_tasks,
                raw_response=raw,
            )
            decomposition.dag = TaskDAG(sub_tasks)

            return decomposition

        except Exception as e:
            logger.error(f'任务分解失败: {e}')
            # 降级: 创建单任务
            tasks = [{
                'task_id': 'T1',
                'title': goal[:50],
                'description': goal,
                'depends_on': '',
            }]
            return TaskDecomposition(
                sub_tasks=tasks,
                dag=TaskDAG(tasks),
                raw_response=f'任务分解失败，降级为单任务: {e}',
            )

    async def execute_task_simple(self, task_prompt: str, role_hint: str = "") -> str:
        """
        [NEW v0.45.0] 简易任务执行接口，供 DebateEngine 或外部调用。
        不进行任务分解，直接由 LLM 生成结果。
        """
        engine = self._get_engine()

        system_context = f"你当前扮演的角色是: {role_hint.upper() if role_hint else '通用助手'}。"
        full_prompt = f"{system_context}\n\n请处理以下请求:\n{task_prompt}"

        try:
            session = await engine.run(full_prompt)
            return session.final_result
        except Exception as e:
            logger.error(f"execute_task_simple 失败: {e}")
            return f"执行失败: {e!s}"

    async def summarize_results(self, task_results: dict[str, str]) -> str:
        """汇总子任务结果

        参数:
            task_results: {task_id: result_text}

        返回:
            汇总报告
        """
        if not task_results:
            return '无子任务结果'

        engine = self._get_engine()

        results_text = '\n\n'.join(
            f'### {task_id}\n{result}'
            for task_id, result in task_results.items()
        )

        prompt = f"""请汇总以下子任务的执行结果，生成一份简洁的报告:

{results_text}

要求:
1. 总结每个子任务的完成情况
2. 指出任何潜在问题或风险
3. 给出最终结论
4. 如果存在质量债务 (Quality Debt)，请特别注明改进建议"""

        try:
            session = await engine.run(prompt)
            return session.final_result
        except Exception as e:
            return f'结果汇总失败: {e}\n\n原始结果:\n{results_text}'

    async def process(self, message: AgentMessage) -> str:
        """处理消息"""
        if message.message_type == MessageType.TASK_ASSIGN:
            goal = message.content
            decomposition = await self.decompose_task(goal)

            # [汲取 GoalX] 通过 PersistentMessageBus 自动分发任务到 Worker 的 Inbox
            from .persistent_message_bus import PersistentMessageBus
            if isinstance(self.message_bus, PersistentMessageBus):
                for task in decomposition.sub_tasks:
                    worker_id = task.get('assigned_to', 'worker')
                    self.logger.info(f"持久化下发任务 {task['task_id']} 给 {worker_id}")
                    # 构建任务分发消息
                    task_msg = AgentMessage(
                        sender=self.agent_id,
                        recipient=worker_id,
                        message_type=MessageType.TASK_ASSIGN,
                        content=task['description'],
                        metadata={
                            'task_id': task['task_id'],
                            'title': task['title'],
                            'depends_on': task.get('depends_on', ''),
                            'verification_criteria': task.get('verification_criteria', ''),
                            'file_path': task.get('file_path', '')
                        },
                        correlation_id=message.message_id
                    )
                    # 此处不 await publish，因为 publish 内部通常是异步持久化的
                    # 或者我们可以调用 broadcast/publish
                    await self.message_bus.publish(task_msg)

            return json.dumps({
                'sub_tasks': decomposition.sub_tasks,
                'dag_info': {
                    'adj': decomposition.dag.adj,
                    'in_degree': decomposition.dag.in_degree
                }
            }, ensure_ascii=False, indent=2)

        if message.message_type == MessageType.SYNC_STATE:
            # [NEW] 处理状态同步请求 (Worker -> Master)
            task_id = message.metadata.get('task_id')
            new_status = message.metadata.get('status')
            if task_id and new_status:
                self.logger.info(f"同步任务状态: {task_id} -> {new_status}")
                # 此处通常配合 SwarmPipeline 的 TaskRegistry 更新
                return f"OK: Synced {task_id}"

        return f'未知操作: {message.message_type.value}'

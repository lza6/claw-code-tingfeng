"""Architect Mode — 先分析后编辑模式（移植自 Aider architect_coder.py）

工作流程:
1. 用户描述需求
2. LLM 分析并输出修改计划（不执行任何修改）
3. 用户确认后，切换到编辑模式执行

使用场景:
- 大型重构需要先评估影响范围
- 不确定修改哪些文件的复杂任务
- 需要人工审批的敏感操作
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ArchitectPhase(str, Enum):
    """架构模式阶段"""
    ANALYZE = "analyze"    # 分析阶段
    CONFIRM = "confirm"    # 确认阶段
    EXECUTE = "execute"    # 执行阶段


@dataclass
class ArchitectPlan:
    """架构修改计划"""
    goal: str
    files_to_modify: list[str] = field(default_factory=list)
    files_to_create: list[str] = field(default_factory=list)
    files_to_delete: list[str] = field(default_factory=list)
    summary: str = ""
    risks: list[str] = field(default_factory=list)
    estimated_complexity: str = "medium"  # low/medium/high


@dataclass
class ArchitectResult:
    """架构模式执行结果"""
    plan: ArchitectPlan
    approved: bool = False
    execution_result: Any = None


ARCHITECT_SYSTEM_PROMPT = """你是一个架构分析助手。你的任务是分析用户的修改请求，并输出一个清晰的修改计划。

**重要**: 你不应该执行任何修改，只输出分析结果。

请按以下格式输出:

## 修改目标
(一句话描述修改目标)

## 需要修改的文件
- `path/to/file1.py`: (修改说明)
- `path/to/file2.py`: (修改说明)

## 需要创建的文件
- `path/to/new_file.py`: (创建说明)

## 风险评估
- (潜在风险1)
- (潜在风险2)

## 复杂度评估
(低/中/高)
"""


class ArchitectMode:
    """架构分析模式 — 先分析后编辑

    用法:
        mode = ArchitectMode(engine)
        result = await mode.run("添加用户登录功能")
        if result.approved:
            # 执行实际修改
            await mode.execute_plan(result.plan)
    """

    def __init__(
        self,
        engine: Any,
        *,
        auto_confirm: bool = False,
        confirm_callback: Callable[[ArchitectPlan], bool] | None = None,
    ) -> None:
        self.engine = engine
        self.auto_confirm = auto_confirm
        self.confirm_callback = confirm_callback
        self.phase = ArchitectPhase.ANALYZE
        self._current_plan: ArchitectPlan | None = None

    async def analyze(self, request: str) -> ArchitectPlan:
        """分析用户请求，生成修改计划"""
        self.phase = ArchitectPhase.ANALYZE

        # 构建分析提示
        messages = [
            {"role": "system", "content": ARCHITECT_SYSTEM_PROMPT},
            {"role": "user", "content": f"请分析以下修改请求:\n\n{request}"},
        ]

        # 调用 LLM 进行分析
        response = await self.engine.llm_provider.chat(
            messages,
            max_tokens=2048,
        )

        # 解析响应为结构化计划
        plan = self._parse_plan(response.content)
        plan.goal = request
        self._current_plan = plan

        return plan

    def _parse_plan(self, llm_response: str) -> ArchitectPlan:
        """解析 LLM 响应为结构化计划"""
        plan = ArchitectPlan(goal="")

        current_section = None
        for line in llm_response.split('\n'):
            line = line.strip()

            if '## 修改目标' in line or '## 目标' in line:
                current_section = 'goal'
            elif '## 需要修改的文件' in line or '## 修改文件' in line:
                current_section = 'modify'
            elif '## 需要创建的文件' in line or '## 创建文件' in line:
                current_section = 'create'
            elif '## 风险评估' in line or '## 风险' in line:
                current_section = 'risks'
            elif '## 复杂度' in line:
                current_section = 'complexity'
            elif line.startswith('- `') or line.startswith('- '):
                content = line.lstrip('- ').strip('`')
                if current_section == 'modify':
                    plan.files_to_modify.append(content)
                elif current_section == 'create':
                    plan.files_to_create.append(content)
                elif current_section == 'risks':
                    plan.risks.append(content)
            elif current_section == 'goal' and line and not line.startswith('#'):
                plan.summary = line
            elif current_section == 'complexity' and line:
                if '低' in line:
                    plan.estimated_complexity = 'low'
                elif '高' in line:
                    plan.estimated_complexity = 'high'
                else:
                    plan.estimated_complexity = 'medium'

        return plan

    async def confirm(self, plan: ArchitectPlan | None = None) -> bool:
        """确认修改计划"""
        self.phase = ArchitectPhase.CONFIRM
        plan = plan or self._current_plan

        if not plan:
            logger.warning('没有可确认的计划')
            return False

        if self.auto_confirm:
            return True

        if self.confirm_callback:
            return self.confirm_callback(plan)

        # 默认: 打印计划并请求用户确认
        self._print_plan(plan)
        response = input('\n确认执行此计划? [y/N]: ')
        return response.lower().startswith('y')

    def _print_plan(self, plan: ArchitectPlan) -> None:
        """打印修改计划"""
        print('\n' + '=' * 60)
        print('📋 修改计划')
        print('=' * 60)
        print(f'\n目标: {plan.summary or plan.goal}')

        if plan.files_to_modify:
            print('\n📝 需要修改的文件:')
            for f in plan.files_to_modify:
                print(f'  - {f}')

        if plan.files_to_create:
            print('\n📄 需要创建的文件:')
            for f in plan.files_to_create:
                print(f'  - {f}')

        if plan.risks:
            print('\n⚠️  风险评估:')
            for r in plan.risks:
                print(f'  - {r}')

        print(f'\n📊 复杂度: {plan.estimated_complexity}')
        print('=' * 60)

    async def run(self, request: str) -> ArchitectResult:
        """完整流程: 分析 -> 确认 -> (可选)执行"""
        plan = await self.analyze(request)
        approved = await self.confirm(plan)

        return ArchitectResult(
            plan=plan,
            approved=approved,
        )

    async def execute_plan(self, plan: ArchitectPlan) -> Any:
        """执行修改计划（委托给 engine）"""
        self.phase = ArchitectPhase.EXECUTE

        # 构建执行提示
        execution_request = f"""请执行以下修改计划:

目标: {plan.goal}

需要修改的文件:
{chr(10).join(f'- {f}' for f in plan.files_to_modify)}

需要创建的文件:
{chr(10).join(f'- {f}' for f in plan.files_to_create)}
"""
        # 委托给 engine 执行
        return await self.engine.run(execution_request)

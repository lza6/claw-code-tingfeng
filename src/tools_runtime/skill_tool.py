"""SkillTool — 按需读取技能正文。

配合 `_system_prompt.build_system_prompt()` 注入的 name + description 清单，
让 Agent 在需要时拉取完整 SKILL.md，而不是把所有技能正文常驻上下文。
"""
from __future__ import annotations

from pathlib import Path

from ..agent.skill_loader import discover_skills, load_skill_body
from .base import BaseTool, ParameterSchema, ToolResult


class SkillTool(BaseTool):
    """读取指定技能的完整说明。"""

    risk_kind = 'read'

    name = 'SkillTool'
    description = '读取指定技能的完整说明（SKILL.md）。用于按需加载技能细节。'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='name',
            param_type='str',
            required=True,
            description='技能名称（来自系统提示中的可用技能清单）',
            min_length=1,
            max_length=120,
        ),
    )

    def __init__(self, workdir: Path | None = None) -> None:
        super().__init__()
        self._workdir = workdir
        self._skills: dict | None = None

    def _get_skills(self) -> dict:
        """按实例缓存 skill 清单，避免每次调用都扫描目录。"""
        if self._skills is None:
            self._skills = {skill.name: skill for skill in discover_skills(self._workdir)}
        return self._skills

    def execute(self, **kwargs) -> ToolResult:
        name = str(kwargs.get('name', '')).strip()
        if not name:
            return ToolResult(success=False, output='', error='缺少参数 name', exit_code=1)

        # 只允许加载“发现清单”中的技能：避免用 ../ 或绝对路径读取任意文件。
        skills = self._get_skills()
        skill = skills.get(name)
        if skill is None:
            available = ', '.join(sorted(skills)[:20])
            return ToolResult(
                success=False,
                output='',
                error=f'未知技能: {name}。可用技能: {available or "(无)"}',
                exit_code=1,
            )

        try:
            body = load_skill_body(skill)
        except OSError as e:
            return ToolResult(success=False, output='', error=f'读取技能失败: {e}', exit_code=1)

        return ToolResult(success=True, output=body)

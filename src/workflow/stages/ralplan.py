"""
Ralplan Stage - 规划阶段

从 oh-my-codex-main 汲取的 RALPLAN 阶段。
实现 Planner -> Architect -> Critic 循环直到达成共识。

RALPLAN-DR 模式:
- Short (默认): 有界结构
- Deliberate: 用于高风险请求，扩展测试计划
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..pipeline_stage import PipelineStage, StageContext, StageResult

logger = logging.getLogger(__name__)


# ===== 已批准计划解析（原 src/workflow/artifacts.py 的最小本地保留版） =====
# 供 can_skip()/run() 判断是否已有已批准计划（.omx/plans/prd-*.md 中的 $team/$ralph 命令）。
# 2026-10-28 死码删除批次时 artifacts.py 整体不可达被删，仅 ralplan 消费此能力，故就地内联。

_PRD_PATTERN = re.compile(r'^prd-.*\.md$', re.IGNORECASE)
_TEST_SPEC_PATTERN = re.compile(r'^test-?spec-.*\.md$', re.IGNORECASE)
_DEEP_INTERVIEW_PATTERN = re.compile(r'^deep-interview-.*\.md$', re.IGNORECASE)
_PRD_SLUG = re.compile(r'^prd-(?P<slug>.*)\.md$', re.IGNORECASE)
_SPEC_SLUG = re.compile(r'^test-?spec-(?P<slug>.*)\.md$', re.IGNORECASE)
_INTERVIEW_SLUG = re.compile(r'^deep-interview-(?P<slug>.*)\.md$', re.IGNORECASE)

_TEAM_CMD = re.compile(
    r'(?P<command>(?:omx\s+team|\$team)\s+(?P<ralph>ralph\s+)?(?P<count>\d+)'
    r'(?::(?P<role>[a-z][a-z0-9-]*))?\s+(?P<task>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'))',
    re.IGNORECASE,
)
_RALPH_CMD = re.compile(
    r'(?P<command>(?:omx\s+ralph|\$ralph)\s+(?P<task>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'))',
    re.IGNORECASE,
)


def _read_matching_paths(dir_path: Path, pattern: re.Pattern) -> list[str]:
    try:
        return sorted(
            str(dir_path / f) for f in os.listdir(dir_path) if pattern.match(f)
        )
    except (OSError, PermissionError):
        return []


def _artifact_slug(path: str, prefix_pattern: re.Pattern) -> str | None:
    match = prefix_pattern.match(os.path.basename(path))
    return match.group('slug') if match else None


def _filter_for_slug(paths: list[str], prefix_pattern: re.Pattern, slug: str | None) -> list[str]:
    if not slug:
        return []
    return [p for p in paths if _artifact_slug(p, prefix_pattern) == slug]


def _decode_quoted_value(raw: str) -> str | None:
    """解码引号中的值（与原 artifacts.py 一致：JSON 优先，其次去引号）"""
    import json as _json

    normalized = raw.strip()
    if not normalized:
        return None
    try:
        return _json.loads(normalized)
    except _json.JSONDecodeError:
        pass
    if ((normalized.startswith('"') and normalized.endswith('"'))
            or (normalized.startswith("'") and normalized.endswith("'"))):
        return normalized[1:-1]
    return None


def _read_approved_execution_launch_hint(cwd: Path, mode: str = "team"):
    """从 .omx/plans/prd-*.md 解析已批准的执行启动提示（$team/$ralph 命令）。"""
    plans_dir = Path(cwd) / '.omx' / 'plans'
    specs_dir = Path(cwd) / '.omx' / 'specs'
    prd_paths = _read_matching_paths(plans_dir, _PRD_PATTERN)
    # 注意：原实现 test spec 与 PRD 同目录（.omx/plans），仅 deep-interview 在 .omx/specs
    test_spec_paths = _read_matching_paths(plans_dir, _TEST_SPEC_PATTERN)
    interview_paths = _read_matching_paths(specs_dir, _DEEP_INTERVIEW_PATTERN)

    # 规划完整性：PRD + test spec 均存在
    if not prd_paths or not test_spec_paths:
        return None

    latest_prd = prd_paths[-1]
    slug = _artifact_slug(latest_prd, _PRD_SLUG)
    if not slug:
        return None
    try:
        content = Path(latest_prd).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None

    ctx = SimpleNamespace(
        source_path=latest_prd,
        test_spec_paths=_filter_for_slug(test_spec_paths, _SPEC_SLUG, slug),
        deep_interview_spec_paths=_filter_for_slug(interview_paths, _INTERVIEW_SLUG, slug),
    )

    pattern = _TEAM_CMD if mode == "team" else _RALPH_CMD
    matches = list(pattern.finditer(content))
    if not matches:
        return None
    groups = matches[-1].groupdict()
    task = _decode_quoted_value(groups.get('task', ''))
    if not task:
        return None
    return SimpleNamespace(
        source_path=ctx.source_path,
        command=groups['command'],
        task=task,
        test_spec_paths=ctx.test_spec_paths,
        deep_interview_spec_paths=ctx.deep_interview_spec_paths,
        mode=mode,
        worker_count=int(groups['count']) if groups.get('count') else None,
        agent_type=groups.get('role'),
        linked_ralph=bool((groups.get('ralph') or '').strip()) if mode == "team" else False,
    )


# ===== 配置 =====
@dataclass
class RalplanConfig:
    """RALPLAN 配置"""
    mode: str = "short"  # 'short' | 'deliberate'
    max_iterations: int = 5
    interactive: bool = False
    cwd: str = "."


@dataclass
class RalplanDRSummary:
    """RALPLAN-DR 摘要"""
    principles: list[str] = field(default_factory=list)
    decision_drivers: list[str] = field(default_factory=list)
    viable_options: list[dict[str, Any]] = field(default_factory=list)
    invalidation_rationale: str = ""
    pre_mortem: list[str] = field(default_factory=list)  # 仅 deliberate 模式
    test_plan: dict[str, Any] = field(default_factory=dict)  # 仅 deliberate 模式


# ===== RALPLAN 阶段 =====
class RalplanStage(PipelineStage):
    """RALPLAN 规划阶段

    实现 Planner -> Architect -> Critic 循环直到达成共识。
    """

    def __init__(self, config: RalplanConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "ralplan"

    def can_skip(self, ctx: StageContext) -> bool:
        """检查是否可以跳过 RALPLAN 阶段（如果已有已批准的计划）"""
        # 从 artifacts 检查是否已有已批准的计划
        existing_hint = _read_approved_execution_launch_hint(ctx.cwd, mode="team")
        return existing_hint is not None

    async def run(self, ctx: StageContext) -> StageResult:
        """执行 RALPLAN 阶段"""
        logger.info(f"[Ralplan] Starting RALPLAN in {self._config.mode} mode")

        task = ctx.task
        cwd = self._config.cwd

        # 步骤 0: 检查是否已有已批准的计划 (从 artifacts 读取)
        existing_hint = _read_approved_execution_launch_hint(cwd, mode="team")
        if existing_hint:
            logger.info(f"[Ralplan] Found existing approved plan: {existing_hint.source_path}")
            return StageResult.completed(
                artifacts={
                    "plan": {
                        "task": task,
                        "source": "existing_approved_plan",
                        "command": existing_hint.command,
                        "test_specs": existing_hint.test_spec_paths,
                    },
                    "mode": "resume",
                    "source_path": existing_hint.source_path,
                },
            )

        # 步骤 1: Planner 创建初始计划
        plan_summary = await self._planner_create_plan(task)

        # 步骤 2: Architect 审查
        architect_review = await self._architect_review(plan_summary)

        # 步骤 3: Critic 评估
        critic_verdict = await self._critic_evaluate(plan_summary, architect_review)

        # 步骤 4: 循环直到达成共识或达到最大迭代
        iteration = 1
        while iteration < self._config.max_iterations and not critic_verdict["approved"]:
            # 收集反馈并重新规划
            feedback = {
                "architect": architect_review,
                "critic": critic_verdict,
            }
            plan_summary = await self._planner_revise_plan(task, feedback)
            architect_review = await self._architect_review(plan_summary)
            critic_verdict = await self._critic_evaluate(plan_summary, architect_review)
            iteration += 1

        # 步骤 5: 应用改进
        if critic_verdict.get("improvements"):
            plan_summary = self._apply_improvements(plan_summary, critic_verdict["improvements"])

        # 构建最终计划
        final_plan = self._build_final_plan(plan_summary, architect_review, critic_verdict)

        return StageResult.completed(
            artifacts={
                "plan": final_plan,
                "ralplan_summary": plan_summary,
                "iterations": iteration,
                "approved": critic_verdict.get("approved", False),
            },
        )

    async def _planner_create_plan(self, task: str) -> RalplanDRSummary:
        """Planner 创建初始计划"""
        # TODO: 实现真正的 Planner 逻辑
        # - 分析任务
        # - 生成原则
        # - 识别决策驱动因素
        # - 提出可行选项

        logger.info("[Ralplan] Planner creating initial plan")

        return RalplanDRSummary(
            principles=[
                "保持代码简洁性",
                "遵循现有架构模式",
                "确保测试覆盖",
            ],
            decision_drivers=[
                "代码质量",
                "开发效率",
                "可维护性",
            ],
            viable_options=[
                {"name": "方案A", "pros": ["简单"], "cons": ["功能有限"]},
                {"name": "方案B", "pros": ["灵活"], "cons": ["复杂"]},
            ],
        )

    async def _architect_review(self, summary: RalplanDRSummary) -> dict[str, Any]:
        """Architect 审查"""
        # TODO: 实现真正的 Architect 审查
        # - 架构合理性
        # - 权衡分析
        # - 反论点

        logger.info("[Ralplan] Architect reviewing plan")

        return {
            "approved": True,
            "counter_arguments": [],
            "tradeoffs": [],
            "synthesis": "方案 A 更适合当前场景",
        }

    async def _critic_evaluate(
        self,
        summary: RalplanDRSummary,
        architect_review: dict[str, Any],
    ) -> dict[str, Any]:
        """Critic 评估"""
        # TODO: 实现真正的 Critic 评估
        # - 原则-选项一致性
        # - 替代方案探索
        # - 风险缓解
        # - 验收标准

        logger.info("[Ralplan] Critic evaluating plan")

        return {
            "approved": True,
            "improvements": [],
            "issues": [],
        }

    async def _planner_revise_plan(
        self,
        task: str,
        feedback: dict[str, Any],
    ) -> RalplanDRSummary:
        """Planner 修订计划"""
        logger.info("[Ralplan] Planner revising plan based on feedback")
        # TODO: 实现修订逻辑
        return await self._planner_create_plan(task)

    def _apply_improvements(
        self,
        summary: RalplanDRSummary,
        improvements: list[dict[str, Any]],
    ) -> RalplanDRSummary:
        """应用改进到计划"""
        # TODO: 实现改进应用逻辑
        return summary

    def _build_final_plan(
        self,
        summary: RalplanDRSummary,
        architect_review: dict[str, Any],
        critic_verdict: dict[str, Any],
    ) -> dict[str, Any]:
        """构建最终计划"""
        return {
            "task": "task description",
            "principles": summary.principles,
            "decision_drivers": summary.decision_drivers,
            "selected_option": summary.viable_options[0] if summary.viable_options else None,
            "implementation_steps": [],
            "verification_steps": [],
            "risks": [],
            "architect_review": architect_review,
            "critic_verdict": critic_verdict,
        }


# ===== 构建函数 =====
def create_ralplan_stage(config: RalplanConfig = None, **options) -> PipelineStage:
    """创建 RALPLAN 阶段"""
    if config is None:
        config = RalplanConfig(**options)
    return RalplanStage(config)


# ===== 导出 =====
__all__ = [
    "RalplanConfig",
    "RalplanDRSummary",
    "RalplanStage",
    "create_ralplan_stage",
]

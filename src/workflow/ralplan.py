"""Ralplan 共识规划 - 三角色规划流程

借鉴 oh-my-codex-main 的共识规划机制:
    Planner (分解者) → Architect (评审者) → Critic (挑战者)

特性:
    -  Triangle推理模式
    - 计划强度评估 (0.0~1.0)
    - 挑战-回应循环 (challenge-response loop)
    - 结构化输出 (JSON) + 自检点
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.agent.engine import AgentEngine
from src.core.events import EventBus, EventType
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PlanOption:
    """方案选项 (用于权衡分析)"""
    name: str
    description: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    cost_estimate: str | None = None  # e.g., "4h", "2d"


@dataclass
class ConsensusPlan:
    """共识计划"""
    goal: str
    objective: str  # Single source of truth (扁平)
    context: dict[str, Any] = field(default_factory=dict)
    chosen_option: PlanOption | None = None
    tasks: list[dict[str, Any]] = field(default_factory=list)
    prd: dict | None = None  # Product Requirements Doc
    architecture: str = ""
    risks: list[str] = field(default_factory=list)
    mitigations: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0~1.0
    created_at: str = ""
    version: int = 1
    validator: str = "ralplan"  # 谁批准的?

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class RalplanEngine:
    """Ralplan 共识规划引擎

    流程 (5步):
        1. Planner 生成初始方案 + 权衡分析
        2. Architect 评审架构 + 检查边界
        3. Critic 挑战 + 模拟风险
        4. 答辩循环 (直到信心 ≥ 0.8 或 max_rounds)
        5. Sigma 检查 + 输出最终计划

    输出: 存储到 .clawd/plan/consensus.json
    """

    def __init__(
        self,
        workdir: Path,
        budget_guard=None,
        max_rounds: int = 3,
        min_confidence: float = 0.8,
    ):
        self.workdir = workdir
        self.budget_guard = budget_guard
        self.max_rounds = max_rounds
        self.min_confidence = min_confidence
        self.event_bus = EventBus()
        self.plan_file = workdir / ".clawd" / "plan" / "consensus.json"

    async def run(
        self,
        goal: str,
        context: dict | None = None,
    ) -> ConsensusPlan:
        """运行共识规划流程"""
        logger.info(f"Ralplan: Starting consensus planning for: {goal}")
        self.event_bus.publish(
            EventType.PLAN_START,
            {"goal": goal, "engine": "ralplan"},
        )

        # Phase 1: Planner提案
        planner_plan = await self._planner_propose(goal, context or {})

        # Phase 2: Architect评审
        architect_review = await self._architect_review(planner_plan)
        architect_plan = planner_plan
        if architect_review.get("needs_revision"):
            architect_plan = await self._apply_architect_changes(
                planner_plan, architect_review
            )

        # Phase 3: Critic挑战
        current_plan = architect_plan
        round_num = 0
        while round_num < self.max_rounds:
            critic_challenge = await self._critic_challenge(current_plan)
            if not critic_challenge.get("has_challenges"):
                break

            # Critic 提出反驳 → Architect回应
            architect_response = await self._architect_respond(
                current_plan, critic_challenge
            )
            current_plan = architect_response.get("revised_plan", current_plan)

            # 检查信心
            confidence = critic_challenge.get("confidence", 0.0)
            if confidence >= self.min_confidence:
                break

            round_num += 1

        # Phase 4: Sigma 验证 (最终自检)
        final_plan = await self._sigma_verify(current_plan)

        # 持久化
        self._persist_plan(final_plan)

        self.event_bus.publish(
            EventType.PLAN_COMPLETE,
            {"plan_id": final_plan.version, "confidence": final_plan.confidence},
        )

        logger.info(
            f"Ralplan: Consensus reached (confidence={final_plan.confidence:.2f})"
        )
        return final_plan

    async def _planner_propose(self, goal: str, context: dict) -> ConsensusPlan:
        """Planner 生成初始方案 + 权衡分析"""
        from src.agent.definitions import PLANNER_AGENT

        engine = AgentEngine(
            workdir=self.workdir,
            agent_role=PLANNER_AGENT,
        )

        prompt = (
            f"You are the PLANNER. Create a detailed implementation plan for:\n\n"
            f"GOAL: {goal}\n\n"
            f"Context: {json.dumps(context, ensure_ascii=False)}\n\n"
            "Output a JSON plan with:\n"
            "{\n"
            '  "objective": "single-sentence objective",\n'
            '  "chosen_option": {"name": "...", "pros": [...], "cons": [...]},\n'
            '  "tasks": [{"id": "T1", "title": "...", "estimate": "2h"}],\n'
            '  "risks": [...],\n'
            '  "confidence": 0.85\n'
            "}"
        )

        result = await engine.run(prompt, max_iterations=10)
        try:
            data = json.loads(result.final_result)
            plan = ConsensusPlan(
                goal=goal,
                objective=data.get("objective", goal),
                context=context,
                chosen_option=PlanOption(**data.get("chosen_option", {})),
                tasks=data.get("tasks", []),
                risks=data.get("risks", []),
                confidence=data.get("confidence", 0.5),
            )
            return plan
        except Exception as e:
            logger.error(f"Failed to parse planner output: {e}")
            # 返回兜底计划
            return ConsensusPlan(
                goal=goal,
                objective=goal,
                confidence=0.3,
            )

    async def _architect_review(self, plan: ConsensusPlan) -> dict[str, Any]:
        """Architect 评审架构"""
        from src.agent.definitions import ARCHITECT_AGENT

        engine = AgentEngine(
            workdir=self.workdir,
            agent_role=ARCHITECT_AGENT,
        )

        prompt = (
            "You are the ARCHITECT. Review this plan:\n\n"
            f"Objective: {plan.objective}\n"
            f"Tasks: {json.dumps(plan.tasks, ensure_ascii=False)}\n"
            f"Risks: {json.dumps(plan.risks, ensure_ascii=False)}\n\n"
            "Assess:\n"
            "1. Architectural soundness\n"
            "2. Boundary alignment\n"
            "3. Scalability implications\n"
            "4. Integration risks\n\n"
            "Output JSON:\n"
            "{\n"
            '  "needs_revision": true/false,\n'
            '  "revision_notes": "...",\n'
            '  "architectural_concerns": [...]\n'
            "}"
        )

        result = await engine.run(prompt, max_iterations=8)
        try:
            return json.loads(result.final_result)
        except Exception:
            return {"needs_revision": False}

    async def _apply_architect_changes(
        self,
        plan: ConsensusPlan,
        review: dict,
    ) -> ConsensusPlan:
        """应用 Architect 的修改建议"""
        # 创建修订版本
        revised = ConsensusPlan(
            **plan.__dict__,
            version=plan.version + 1,
        )
        revised.context["architect_notes"] = review.get("revision_notes", "")
        return revised

    async def _critic_challenge(self, plan: ConsensusPlan) -> dict[str, Any]:
        """Critic 挑战计划"""
        from src.agent.definitions import CRITIC_AGENT

        engine = AgentEngine(
            workdir=self.workdir,
            agent_role=CRITIC_AGENT,
        )

        prompt = (
            "You are the CRITIC. Challenge this plan adversarially:\n\n"
            f"Objective: {plan.objective}\n"
            f"Tasks: {json.dumps(plan.tasks, ensure_ascii=False)}\n\n"
            "Consider:\n"
            "- Hidden assumptions\n"
            "- Worst-case scenarios\n"
            "- What could go wrong?\n"
            "- Alternative approaches\n\n"
            "Output JSON:\n"
            "{\n"
            '  "has_challenges": true/false,\n'
            '  "challenges": [...],\n'
            '  "confidence": 0.0~1.0 (after considering your own bias)\n'
            "}"
        )

        result = await engine.run(prompt, max_iterations=8)
        try:
            return json.loads(result.final_result)
        except Exception:
            return {"has_challenges": False, "confidence": 0.5}

    async def _architect_respond(
        self,
        plan: ConsensusPlan,
        challenge: dict,
    ) -> dict[str, Any]:
        """Architect 回应 Critic 的挑战"""
        from src.agent.definitions import ARCHITECT_AGENT

        engine = AgentEngine(
            workdir=self.workdir,
            agent_role=ARCHITECT_AGENT,
        )

        prompt = (
            "You are the ARCHITECT. Respond to these challenges:\n\n"
            f"Plan: {plan.objective}\n"
            f"Challenges: {json.dumps(challenge.get('challenges', []), ensure_ascii=False)}\n\n"
            "Provide:\n"
            "1. Refutations (with evidence)\n"
            "2. Plan improvements (if any)\n"
            "3. Revised confidence estimate\n\n"
            "Output JSON:\n"
            "{\n"
            '  "revised_plan": { ... },\n'
            '  "confidence": 0.0~1.0\n'
            "}"
        )

        result = await engine.run(prompt, max_iterations=8)
        try:
            return json.loads(result.final_result)
        except Exception:
            return {"revised_plan": plan.__dict__, "confidence": 0.6}

    async def _sigma_verify(self, plan: ConsensusPlan) -> ConsensusPlan:
        """Sigma 最终验证 - 自检点"""
        checks = [
            self._check_objective_clear(plan),
            self._check_tasks_decomposed(plan),
            self._check_risks_mitigated(plan),
            self._check_confidence_threshold(plan),
        ]
        failures = [c for c in checks if not c["passed"]]

        if failures:
            logger.warning(f"Sigma verification failed: {failures}")
            # 降低信心
            plan.confidence = max(0.0, plan.confidence - 0.2)

        plan.context["sigma_verification"] = {
            "checks": checks,
            "passed": len(failures) == 0,
        }

        # 设置批准者
        plan.validator = "sigma"

        return plan

    def _check_objective_clear(self, plan: ConsensusPlan) -> dict:
        passed = len(plan.objective.strip()) > 10
        return {
            "check": "objective_clear",
            "passed": passed,
            "message": "目标表述清晰" if passed else "目标过于简单",
        }

    def _check_tasks_decomposed(self, plan: ConsensusPlan) -> dict:
        passed = len(plan.tasks) >= 2
        return {
            "check": "tasks_decomposed",
            "passed": passed,
            "message": f"任务已分解为 {len(plan.tasks)} 个" if passed else "任务分解不足",
        }

    def _check_risks_mitigated(self, plan: ConsensusPlan) -> dict:
        passed = len(plan.risks) <= 10  # 合理范围内
        return {
            "check": "risks_mitigated",
            "passed": passed,
            "message": "风险已识别" if passed else "风险列表过长",
        }

    def _check_confidence_threshold(self, plan: ConsensusPlan) -> dict:
        passed = plan.confidence >= self.min_confidence
        return {
            "check": "confidence_threshold",
            "passed": passed,
            "message": f"信心 {plan.confidence:.2f}/{self.min_confidence}",
        }

    def _persist_plan(self, plan: ConsensusPlan) -> None:
        """持久化共识计划"""
        self.plan_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": plan.version,
            "goal": plan.goal,
            "objective": plan.objective,
            "context": plan.context,
            "chosen_option": (
                plan.chosen_option.__dict__ if plan.chosen_option else None
            ),
            "tasks": plan.tasks,
            "prd": plan.prd,
            "architecture": plan.architecture,
            "risks": plan.risks,
            "mitigations": plan.mitigations,
            "confidence": plan.confidence,
            "created_at": plan.created_at,
            "validator": plan.validator,
            "sigma_verification": plan.context.get("sigma_verification", {}),
        }
        self.plan_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )
        logger.info(f"Consensus plan saved to {self.plan_file}")

    @classmethod
    def load_plan(cls, workdir: Path) -> ConsensusPlan | None:
        """加载现有共识计划"""
        plan_file = workdir / ".clawd" / "plan" / "consensus.json"
        if not plan_file.exists():
            return None
        data = json.loads(plan_file.read_text())
        return ConsensusPlan(
            goal=data["goal"],
            objective=data["objective"],
            context=data.get("context", {}),
            chosen_option=PlanOption(**data["chosen_option"])
            if data.get("chosen_option")
            else None,
            tasks=data.get("tasks", []),
            prd=data.get("prd"),
            architecture=data.get("architecture", ""),
            risks=data.get("risks", []),
            mitigations=data.get("mitigations", []),
            confidence=data.get("confidence", 0.0),
            created_at=data.get("created_at", ""),
            version=data.get("version", 1),
            validator=data.get("validator", "sigma"),
        )


# ==================== CLI 命令 ====================

async def ralplan_command(
    goal: str,
    workdir: Path | None = None,
    max_rounds: int = 3,
    min_confidence: float = 0.8,
) -> ConsensusPlan:
    """CLI: $ralplan <goal>"""
    workdir = workdir or Path.cwd()
    engine = RalplanEngine(
        workdir=workdir,
        max_rounds=max_rounds,
        min_confidence=min_confidence,
    )
    plan = await engine.run(goal)
    return plan


__all__ = [
    "ConsensusPlan",
    "PlanOption",
    "RalplanEngine",
    "ralplan_command",
]

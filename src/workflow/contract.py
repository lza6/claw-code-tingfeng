import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..llm.model_manager import ModelManager
from .models import (
    AssurancePlan,
    AssuranceProcedure,
    AssuranceVerificationMode,
    ObjectiveClause,
    ObjectiveClauseKind,
    ObjectiveContract,
    ObjectiveRequiredSurface,
)

logger = logging.getLogger("workflow.contract")

CONTRACT_PROMPT = """
你现在是一个高级系统架构师。你的任务是将用户的原始目标转化为一个严谨的“目标合同 (Objective Contract)”。

## 条款类型 (Kinds):
- delivery: 核心交付物。
- quality_bar: 质量标准。
- verification: 验证要求。
- guardrail: 约束和禁令 (借鉴 OMX: 明确 Non-goals)。
- operating_rule: 执行规则。
- constraint: 强约束（如必须使用特定库）。
- non_goal: 非目标（明确告诉 Agent 哪些不需要做）。

## 输出格式:
你必须输出一个纯 JSON 对象，结构如下:
{
  "clauses": [
    {
      "id": "c1",
      "text": "明确的条款内容...",
      "kind": "delivery|quality_bar|verification|guardrail|operating_rule|constraint|non_goal",
      "source_excerpt": "摘录自用户原始需求的相关部分",
      "required_surfaces": ["obligation", "assurance"],
      "evidence_required": true
    }
  ]
}

## 用户原始需求:
{user_goal}
"""

ASSURANCE_PROMPT = """
你现在是一个资深测试架构师。基于以下“目标合同”，你需要制定一个“保证计划 (Assurance Plan)”。
保证计划定义了如何验证每个条款是否已达成。

## 验证模式 (Verification Modes):
- unit_test: 单元测试
- integration_test: 集成测试
- e2e_test: 端到端测试
- manual_review: 人工审查（仅在自动化无法覆盖时使用）
- static_analysis: 静态分析
- evidence_check: 证据检查 (借鉴 OMX: 检查 Agent 运行时的证据，如读取的文件、运行的命令)

## 输出格式:
你必须输出一个纯 JSON 对象，结构如下:
{
  "procedures": [
    {
      "id": "ap1",
      "title": "简短的验证标题",
      "strategy": "详细的验证策略描述...",
      "verification_mode": "unit_test|integration_test|e2e_test|manual_review|static_analysis|evidence_check",
      "target_surface": "验证的目标代码文件或组件路径",
      "covers_clauses": ["c1", "c2"],
      "evidence_patterns": ["grep pattern to find in logs/outputs"]
    }
  ]
}

## 目标合同条款:
{clauses_text}
"""

class ContractManager:
    """契约与保证管理器 (汲取 GoalX & Ralph 核心设计)"""

    def __init__(self, model_manager: ModelManager, storage_dir: str = ".clawd/contracts"):
        self.model_manager = model_manager
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, objective_hash: str) -> Path:
        # 移除哈希前缀便于文件名安全
        safe_hash = objective_hash.replace("sha256:", "")[:16]
        return self.storage_dir / f"contract_{safe_hash}.json"

    async def sign_contract(self, user_goal: str) -> ObjectiveContract:
        """引导 AI 签署执行契约"""
        objective_hash = "sha256:" + hashlib.sha256(user_goal.strip().encode()).hexdigest()
        path = self._get_path(objective_hash)

        # 汲取 Ralph: 检查持久化存储
        if path.exists():
            logger.info(f"发现已存在的契约: {objective_hash[:8]}，正在尝试加载...")
            try:
                # 实际生产中应有完整的反序列化
                pass
            except Exception as e:
                logger.warning(f"加载现有契约失败: {e}")

        logger.info("开始生成执行契约 (Objective Contract)...")
        prompt = CONTRACT_PROMPT.format(user_goal=user_goal)
        try:
            response_json = await self.model_manager.generate_json(
                prompt=prompt,
                model_id="claude-sonnet-4-6"
            )
        except Exception as e:
            logger.error(f"LLM 生成契约失败: {e}")
            response_json = {"clauses": []}

        clauses_data = response_json.get("clauses", [])
        clauses = []
        for c in clauses_data:
            clauses.append(ObjectiveClause(
                id=c["id"],
                text=c["text"],
                kind=ObjectiveClauseKind(c["kind"]),
                source_excerpt=c["source_excerpt"],
                required_surfaces=[ObjectiveRequiredSurface(s) for s in c.get("required_surfaces", [])]
            ))

        objective_hash = "sha256:" + hashlib.sha256(user_goal.strip().encode()).hexdigest()
        contract = ObjectiveContract(
            version=1,
            objective_hash=objective_hash,
            state="locked",
            clauses=clauses,
            created_at=datetime.now().isoformat(),
            locked_at=datetime.now().isoformat()
        )
        return contract

    async def generate_assurance_plan(self, contract: ObjectiveContract) -> AssurancePlan:
        """为已签署的契约生成保证计划"""
        logger.info(f"正在为契约 {contract.objective_hash[:8]} 生成保证计划...")

        clauses_text = "\n".join([f"- [{c.id}] ({c.kind}) {c.text}" for c in contract.clauses])
        prompt = ASSURANCE_PROMPT.format(clauses_text=clauses_text)

        try:
            response_json = await self.model_manager.generate_json(
                prompt=prompt,
                model_id="claude-sonnet-4-6"
            )

            procedures_data = response_json.get("procedures", [])
            procedures = []
            for p in procedures_data:
                procedures.append(AssuranceProcedure(
                    id=p["id"],
                    title=p["title"],
                    strategy=p["strategy"],
                    verification_mode=AssuranceVerificationMode(p["verification_mode"]),
                    target_surface=p["target_surface"],
                    covers_clauses=p.get("covers_clauses", [])
                ))

            plan = AssurancePlan(
                version=1,
                objective_contract_hash=contract.objective_hash,
                procedures=procedures,
                created_at=datetime.now().isoformat()
            )
            logger.info(f"保证计划已生成: 包含 {len(plan.procedures)} 条验证程序。")
            return plan
        except Exception as e:
            logger.error(f"生成保证计划失败: {e}")
            return AssurancePlan(version=1, objective_contract_hash=contract.objective_hash, procedures=[])

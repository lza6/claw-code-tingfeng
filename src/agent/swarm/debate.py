from typing import List, Dict, Any, TYPE_CHECKING, Optional
from .base_agent import BaseAgent

if TYPE_CHECKING:
    from .orchestrator import OrchestratorAgent


class DebateRole:
    ADVOCATE = "advocate"
    CRITIC = "critic"
    MODERATOR = "moderator"


class DebateEngine:
    """辩论引擎 (汲取 GoalX Debate Mode)

    支持两种模式:
    1. 实时辩论: 基于当前上下文和提案进行辩论
    2. 保存运行辩论: 从保存的运行中加载证据，对已完成义务进行重新审视和挑战
    """

    def __init__(self, orchestrator: Optional['OrchestratorAgent'] = None):
        self.orchestrator = orchestrator
        self._saved_run_context: Optional[Dict[str, Any]] = None

    def load_saved_run(self, run_dir: str) -> None:
        """[汲取 GoalX] 从保存的运行中加载辩论上下文

        从运行目录加载 obligation_model, evidence_log 等持久化表面，
        为辩论提供历史证据基础。

        Args:
            run_dir: 保存的运行目录路径
        """
        import json
        from pathlib import Path

        run_path = Path(run_dir)
        context = {"run_dir": str(run_path), "evidence": [], "obligations": []}

        # 加载 ObligationModel
        obligation_path = run_path / "obligation-model.json"
        if obligation_path.exists():
            try:
                with open(obligation_path, "r", encoding="utf-8") as f:
                    context["obligations"] = json.load(f)
            except Exception:
                pass

        # 加载 EvidenceLog
        evidence_path = run_path / "evidence-log.jsonl"
        if evidence_path.exists():
            try:
                with open(evidence_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            context["evidence"].append(json.loads(line))
            except Exception:
                pass

        # 加载 Charter
        charter_path = run_path / "run-charter.json"
        if charter_path.exists():
            try:
                with open(charter_path, "r", encoding="utf-8") as f:
                    context["charter"] = json.load(f)
            except Exception:
                pass

        self._saved_run_context = context

    async def conduct_debate(self, context: str, proposal: str, quality_debt_report: Optional[str] = None) -> str:
        """
        主持一场辩论，引入质量债务作为输入，强制 Agent 关注未解决的问题。
        """
        debt_context = f"\n当前质量债务：\n{quality_debt_report}" if quality_debt_report else ""

        # 1. 倡导者阐述
        advocate_prompt = (
            f"你是倡导者。请根据以下背景和提案，阐述其优点并提供代码证据。"
            f"{debt_context}\n"
            f"注意：你必须说明该提案如何帮助减少或不增加质量债务。\n"
            f"背景：{context}\n提案：{proposal}"
        )
        advocate_response = await self._get_agent_response(DebateRole.ADVOCATE, advocate_prompt)

        # 2. 批评者挑战
        critic_prompt = (
            f"你是批评者。请挑战以下提案和倡导者的观点，寻找漏洞、风险和替代方案。"
            f"{debt_context}\n"
            f"注意：重点关注那些可能被忽略的边缘情况和长期维护债务。\n"
            f"提案：{proposal}\n倡导者观点：{advocate_response}"
        )
        critic_response = await self._get_agent_response(DebateRole.CRITIC, critic_prompt)

        # 3. 总结与共识
        moderator_prompt = (
            f"你是主持人。请总结倡导者和批评者的辩论，识别双方的共识点和争议点，并给出最终建议。"
            f"如果辩论中揭示了新的质量债务，请明确列出。\n"
            f"倡导者：{advocate_response}\n批评者：{critic_response}"
        )
        final_summary = await self._get_agent_response(DebateRole.MODERATOR, moderator_prompt)

        return final_summary

    async def conduct_debate_from_saved_run(self, challenge_focus: str, custom_proposal: Optional[str] = None) -> str:
        """[汲取 GoalX Debate Mode] 从保存的运行中发起辩论

        加载之前运行中完成的义务和证据，对其进行重新审视和挑战。
        这用于在保存运行后进行深度复盘或基于之前结果进行改进。

        Args:
            challenge_focus: 挑战的重点领域 (例如: "代码质量", "测试覆盖率", "架构设计")
            custom_proposal: 可选的自定义提案，为 None 时基于保存的运行自动生成

        Returns:
            辩论总结报告
        """
        if not self._saved_run_context:
            return "错误: 未加载保存的运行上下文，请先调用 load_saved_run()"

        context = self._saved_run_context
        obligations = context.get("obligations", {})
        evidence = context.get("evidence", [])
        charter = context.get("charter", {})

        # 构建辩论上下文
        run_summary = f"运行目录: {context['run_dir']}\n"
        if charter:
            run_summary += f"目标: {charter.get('objective', 'N/A')}\n"

        # 统计已完成 vs 未完成的义务
        required = obligations.get("required", [])
        completed_obligations = [o for o in required if o.get("state") == "claimed"]
        failed_obligations = [o for o in required if o.get("state") in ("open", "waived")]

        run_summary += f"\n已完成义务: {len(completed_obligations)}\n"
        run_summary += f"未完成义务: {len(failed_obligations)}\n"

        # 收集证据统计
        passed_evidence = [e for e in evidence if e.get("result", {}).get("passed", False)]
        failed_evidence = [e for e in evidence if not e.get("result", {}).get("passed", True)]

        run_summary += f"\n通过验证: {len(passed_evidence)}\n"
        run_summary += f"失败验证: {len(failed_evidence)}\n"

        # 自动生成提案 (如果未提供)
        if custom_proposal is None:
            # 基于失败的任务生成改进提案
            proposals = []
            for ob in failed_obligations:
                proposals.append(f"重新处理未完成任务: {ob.get('text', ob.get('id'))}")
            for ev in failed_evidence:
                proposals.append(f"修复验证失败: {ev.get('scenario_id', 'unknown')}")

            if not proposals:
                proposals = [f"继续优化挑战领域: {challenge_focus}"]

            proposal = f"基于之前运行的以下问题:\n" + "\n".join(f"- {p}" for p in proposals[:5])
        else:
            proposal = custom_proposal

        # 执行辩论
        debate_result = await self.conduct_debate(run_summary, proposal)

        # 构建最终报告
        report = f"""# 辩论报告 (From Saved Run)

## 运行概览
{run_summary}

## 挑战焦点
{challenge_focus}

## 辩论结果
{debate_result}

## 建议行动
"""

        # 从辩论结果中提取建议
        if "建议" in debate_result or "推荐" in debate_result:
            report += "\n根据辩论建议，请执行以下行动:\n"
            report += "- 审查上述失败的任务并重新处理\n"
            focus_msg = f"- 重点关注 {challenge_focus} 领域的改进\n"
            report += focus_msg

        return report

    async def get_completed_obligations_summary(self) -> str:
        """获取保存运行中已完成义务的摘要"""
        if not self._saved_run_context:
            return "未加载运行上下文"

        obligations = self._saved_run_context.get("obligations", {})
        required = obligations.get("required", [])

        summary_lines = ["## 已完成义务", ""]
        for ob in required:
            if ob.get("state") == "claimed":
                summary_lines.append(f"- [{ob.get('id')}] {ob.get('text')}")

        return "\n".join(summary_lines) if len(summary_lines) > 2 else "无已完成义务"

    async def get_failed_validations_summary(self) -> str:
        """获取保存运行中验证失败的摘要"""
        if not self._saved_run_context:
            return "未加载运行上下文"

        evidence = self._saved_run_context.get("evidence", [])
        failed = [e for e in evidence if not e.get("result", {}).get("passed", True)]

        summary_lines = ["## 验证失败记录", ""]
        for ev in failed:
            summary_lines.append(f"- {ev.get('scenario_id')}: {ev.get('result', {}).get('status')}")

        return "\n".join(summary_lines) if len(summary_lines) > 2 else "无失败验证"

    async def _get_agent_response(self, role: str, prompt: str) -> str:
        """
        真正通过 OrchestratorAgent 调用 LLM 产生角色响应
        """
        if not self.orchestrator:
            return f"[模拟 {role.upper()} 响应] 由于 Orchestrator 未就绪，无法生成真实辩论。提示词: {prompt[:30]}..."

        # 使用编排器创建一个临时任务并让 Agent 执行
        # 这里假设 OrchestratorAgent 有一个可以直接处理 prompt 的简易方法
        try:
            # 动态调整 Agent 的系统提示词以模拟角色
            response = await self.orchestrator.execute_task_simple(
                task_prompt=prompt,
                role_hint=role
            )
            return response
        except Exception as e:
            return f"[{role.upper()} 出错] {str(e)}"

"""Reasoning Patterns — 反推/推理循环模式库

从 all-agentic-architectures 的设计思想移植，适配 clawd 的工具执行体系
（execute_tool / ToolResult），不依赖 LangGraph。

提供四种推理循环 + 统一入口:
- ReflexionLoop:    假设→执行→反思→修正（逆向核心循环）
- PlanExecuteLoop:  计划分解→逐步执行→按结果重规划
- LATSPattern:      多分支假设树并行评估，择优展开
- DebatePattern:    多立场对抗审查结论，防误报
- run_reasoning():  统一入口
"""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ============ LLM 抽象（由调用方注入，便于测试与换模型） ============

@dataclass
class LLMResponse:
    text: str


LLMFn = Callable[[str, str], str]
"""LLMFn(system: str, user: str) -> str，由 llm 模块适配注入"""


DEFAULT_SYSTEM = (
    "你是逆向分析专家。基于证据推理，输出严格符合要求的 JSON。"
    "无法确定时明确标注不确定，禁止编造。"
)


def _extract_json(text: str) -> dict[str, Any]:
    """从 LLM 输出提取 JSON（容忍 markdown 代码块包裹）"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    text = text.strip()
    # 找第一个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


# ============ 数据结构 ============

@dataclass
class StepRecord:
    """单步执行记录"""
    step: int
    action: str
    observation: str
    reflection: str = ""
    is_final: bool = False


@dataclass
class ReasoningResult:
    """推理循环结果"""
    answer: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    total_tool_calls: int = 0
    iterations: int = 0
    confidence: float = 0.0
    pattern: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "pattern": self.pattern,
            "confidence": self.confidence,
            "iterations": self.iterations,
            "total_tool_calls": self.total_tool_calls,
            "steps": [
                {
                    "step": s.step,
                    "action": s.action,
                    "observation": s.observation[:2000],
                    "reflection": s.reflection[:2000],
                    "is_final": s.is_final,
                }
                for s in self.steps
            ],
        }


@dataclass
class ReasoningConfig:
    max_iterations: int = 8
    max_tool_calls: int = 30
    tool_timeout: int = 60


# ============ 工具执行器注入 ============

ToolExecutorFn = Callable[[str, dict[str, Any]], str]
"""ToolExecutorFn(tool_name, args) -> observation str"""


def _default_tool_executor() -> ToolExecutorFn:
    """默认用 clawd 的 execute_tool"""
    def _exec(tool_name: str, args: dict[str, Any]) -> str:
        from ..tools_runtime.tool_interface import execute_tool

        result = execute_tool(tool_name, args)
        if result.is_success:
            return result.output or ""
        return f"[工具错误] {result.error}"
    return _exec


# ============ 基类 ============

class BaseReasoningPattern(ABC):
    """推理模式基类"""

    pattern_name: str = "base"

    def __init__(
        self,
        llm: LLMFn,
        tool_executor: ToolExecutorFn | None = None,
        config: ReasoningConfig | None = None,
    ):
        self.llm = llm
        self.tool_executor = tool_executor or _default_tool_executor()
        self.config = config or ReasoningConfig()

    # -- 供子类使用的工具调用封装 --
    def call_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        self._tool_calls += 1
        if self._tool_calls > self.config.max_tool_calls:
            return "[已达工具调用上限]"
        try:
            return self.tool_executor(tool_name, args)
        except Exception as e:  # noqa: BLE001
            return f"[工具异常] {e}"

    @abstractmethod
    def run(self, task: str) -> ReasoningResult:
        """执行推理循环"""


# ============ 1. Reflexion（反思修正循环） ============

class ReflexionLoop(BaseReasoningPattern):
    """假设→执行→观察→反思→修正。逆向分析的核心循环：
    每次失败后强制生成结构化反思，避免重复同一失败路径。"""

    pattern_name = "reflexion"

    _ACTION_SCHEMA = (
        '输出 JSON: {"tool": "工具名或null", "args": {}, "final": false, "answer": ""}\n'
        "- 需要调用工具时 tool 非空，final=false\n"
        "- 得出结论时 tool=null，final=true，answer 填最终结论"
    )

    _REFLECT_SCHEMA = (
        "输出 JSON: {\"what_failed\": \"...\", \"why\": \"...\", "
        "\"next_hypothesis\": \"...\", \"avoid\": [\"应避免的做法\"]}"
    )

    def run(self, task: str) -> ReasoningResult:
        result = ReasoningResult(pattern=self.pattern_name)
        self._tool_calls = 0
        lessons: list[str] = []

        for i in range(1, self.config.max_iterations + 1):
            result.iterations = i
            lesson_ctx = (
                "\n\n历史教训（禁止重复这些失败路径）:\n"
                + "\n".join(f"- {l}" for l in lessons)
                if lessons
                else ""
            )
            prompt = (
                f"任务: {task}\n\n可用历史观察:\n"
                + "\n".join(
                    f"[step {s.step}] {s.action} → {s.observation[:500]}"
                    for s in result.steps[-5:]
                )
                + lesson_ctx
                + f"\n\n{_extract_json.__doc__ or ''}{self._ACTION_SCHEMA}"
            )
            try:
                decision = _extract_json(self.llm(DEFAULT_SYSTEM, prompt))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"reflexion 决策解析失败: {e}")
                # 格式错误反馈重试（SWE-agent 模式）
                result.steps.append(StepRecord(
                    step=i, action="解析失败重试",
                    observation=f"上次输出不是合法 JSON: {e}，请严格输出 JSON",
                ))
                lessons.append(f"step {i}: 输出格式错误，须为合法 JSON")
                continue

            if decision.get("final") or not decision.get("tool"):
                answer = decision.get("answer", "")
                result.answer = answer
                result.confidence = self._self_assess(task, answer)
                result.steps.append(StepRecord(
                    step=i, action="final", observation=answer, is_final=True
                ))
                return result

            tool, args = decision["tool"], decision.get("args", {})
            observation = self.call_tool(tool, args)
            result.total_tool_calls += 1
            result.steps.append(StepRecord(
                step=i, action=f"{tool}({json.dumps(args, ensure_ascii=False)[:200]})",
                observation=observation,
            ))

            # 失败观察 → 强制反思
            if observation.startswith("[工具") or not observation.strip():
                reflection = self._reflect(task, tool, observation, lessons)
                result.steps[-1].reflection = reflection
                lessons.append(
                    f"step {i} 调用 {tool} 失败: {reflection.get('why', '未知')}"
                    f"；下次假设: {reflection.get('next_hypothesis', '')}"
                )

        result.answer = f"达到最大迭代次数（{self.config.max_iterations}），未收敛。最后观察: {result.steps[-1].observation[:500] if result.steps else '无'}"
        return result

    def _reflect(self, task: str, tool: str, obs: str, lessons: list[str]) -> dict[str, Any]:
        prompt = (
            f"任务: {task}\n刚调用了工具 {tool}，得到失败观察: {obs[:800]}\n"
            f"已有教训: {lessons}\n\n{self._REFLECT_SCHEMA}"
        )
        try:
            return _extract_json(self.llm(DEFAULT_SYSTEM, prompt))
        except (json.JSONDecodeError, ValueError):
            return {"what_failed": tool, "why": "解析失败", "next_hypothesis": "", "avoid": []}

    def _self_assess(self, task: str, answer: str) -> float:
        try:
            out = self.llm(
                DEFAULT_SYSTEM,
                f"任务: {task}\n结论: {answer[:1500]}\n\n"
                '评估结论的证据支撑度，输出 JSON: {"confidence": 0.0到1.0之间的小数}',
            )
            return float(_extract_json(out).get("confidence", 0.0))
        except (json.JSONDecodeError, ValueError, TypeError):
            return 0.0


# ============ 2. Plan-and-Execute（计划分解执行） ============

class PlanExecuteLoop(BaseReasoningPattern):
    """先规划再执行，每步执行后按实际结果重规划。适合大型逆向任务分解。"""

    pattern_name = "plan-execute"

    _PLAN_SCHEMA = (
        '输出 JSON: {"steps": [{"id": 1, "goal": "...", "tool": "工具名或null(纯推理)", '
        '"args": {}, "done_if": "完成判据"}]}'
    )

    def run(self, task: str) -> ReasoningResult:
        result = ReasoningResult(pattern=self.pattern_name)
        self._tool_calls = 0
        findings: list[str] = []

        for i in range(1, self.config.max_iterations + 1):
            result.iterations = i
            ctx = (
                f"任务: {task}\n\n已知发现:\n" + "\n".join(f"- {f}" for f in findings)
                if findings
                else f"任务: {task}\n（尚无发现）"
            )
            try:
                plan = _extract_json(
                    self.llm(DEFAULT_SYSTEM, ctx + f"\n\n{self._PLAN_SCHEMA}")
                )
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"plan 解析失败: {e}")
                findings.append(f"[迭代 {i}] 计划生成失败，重试")
                continue

            steps = plan.get("steps", [])
            if not steps:
                result.answer = findings[-1] if findings else "计划为空，无法推进"
                break

            all_done = True
            for st in steps:
                goal, tool = st.get("goal", ""), st.get("tool")
                if tool:
                    obs = self.call_tool(tool, st.get("args", {}))
                    result.total_tool_calls += 1
                    findings.append(f"[{st.get('id', '?')}] {goal} → {obs[:600]}")
                    result.steps.append(StepRecord(
                        step=i, action=f"{tool}: {goal}", observation=obs
                    ))
                    # 失败则整体未完成，触发重规划
                    if obs.startswith("[工具"):
                        all_done = False
                else:
                    findings.append(f"[{st.get('id', '?')}] {goal}")
                    result.steps.append(StepRecord(step=i, action=f"推理: {goal}", observation=goal))

            if all_done:
                try:
                    final = self.llm(
                        DEFAULT_SYSTEM,
                        f"任务: {task}\n全部发现:\n" + "\n".join(findings)
                        + "\n\n综合所有发现给出最终结论（纯文本）",
                    )
                    result.answer = final
                except Exception as e:  # noqa: BLE001
                    result.answer = findings[-1]
                result.confidence = 0.8
                return result

        # 未收敛：保留最后一次已设置的 answer（如"计划为空"），否则给兜底
        if not result.answer:
            result.answer = "达到最大迭代，未完成全部计划。已有发现:\n" + "\n".join(findings[:10])
        return result


# ============ 3. LATS（语言代理树搜索，简化版） ============

class LATSPattern(BaseReasoningPattern):
    """多分支假设并行评估，择优展开。简化为逐层扩展：
    生成 k 个假设 → 各自验证 → 评分最高者进入下一层。"""

    pattern_name = "lats"

    _HYP_SCHEMA = (
        '输出 JSON: {"hypotheses": [{"id": 1, "statement": "...", '
        '"verification": {"tool": "...", "args": {}}}]}'
    )
    _SCORE_SCHEMA = (
        '输出 JSON: {"candidates": [{"id": 1, "score": 0.0到1.0, "evidence": "..."}]}'
    )

    def __init__(self, *args: Any, branching: int = 3, depth: int = 2, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.branching = branching
        self.depth = depth

    def run(self, task: str) -> ReasoningResult:
        result = ReasoningResult(pattern=self.pattern_name)
        self._tool_calls = 0
        evidence_pool: list[str] = []
        current_context = task

        for d in range(1, self.depth + 1):
            result.iterations = d
            try:
                hyp_out = _extract_json(self.llm(
                    DEFAULT_SYSTEM,
                    f"任务: {current_context}\n已有证据:\n" + "\n".join(evidence_pool[-6:])
                    + f"\n\n生成至多 {self.branching} 个候选假设，每个附验证方案。\n{self._HYP_SCHEMA}",
                ))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"lats 假设生成失败: {e}")
                break

            hyps = hyp_out.get("hypotheses", [])[: self.branching]
            if not hyps:
                break

            # 逐个假设执行验证
            scored: list[dict[str, Any]] = []
            for h in hyps:
                ver = h.get("verification") or {}
                obs = ""
                if ver.get("tool"):
                    obs = self.call_tool(ver["tool"], ver.get("args", {}))
                    result.total_tool_calls += 1
                evidence_pool.append(f"假设[{h.get('id')}] {h.get('statement')} → {obs[:400]}")
                result.steps.append(StepRecord(
                    step=d, action=f"假设: {h.get('statement')}", observation=obs or "(纯推理)"
                ))
                scored.append({"id": h.get("id"), "statement": h.get("statement"), "obs": obs})

            # deterministic-picker: LLM 打分，Python 排序取最大
            try:
                sc = _extract_json(self.llm(
                    DEFAULT_SYSTEM,
                    f"任务: {task}\n候选验证结果:\n" + json.dumps(
                        [{k: v[:400] if isinstance(v, str) else v for k, v in s.items()} for s in scored],
                        ensure_ascii=False,
                    )
                    + f"\n\n{self._SCORE_SCHEMA}",
                ))
                cand = sc.get("candidates", [])
            except (json.JSONDecodeError, ValueError):
                cand = []
            if cand:
                best = max(cand, key=lambda c: float(c.get("score", 0)))
                best_stmt = next(
                    (s["statement"] for s in scored if s["id"] == best.get("id")),
                    "",
                )
                result.confidence = float(best.get("score", 0))
                current_context = (
                    f"{task}\n（当前最优假设: {best_stmt}，证据: {best.get('evidence', '')[:300]}）"
                )

        # 最终综合
        try:
            result.answer = self.llm(
                DEFAULT_SYSTEM,
                f"任务: {task}\n全部证据:\n" + "\n".join(evidence_pool)
                + "\n\n综合全部证据给出最终结论（纯文本）",
            )
        except Exception as e:  # noqa: BLE001
            result.answer = f"综合失败: {e}；已有证据:\n" + "\n".join(evidence_pool[:5])
        return result


# ============ 4. Debate（对抗审查） ============

class DebatePattern(BaseReasoningPattern):
    """多立场对抗审查：一个结论，两个辩手（支持/质疑）+ 裁判。
    用于逆向结论的防误报审查。"""

    pattern_name = "debate"

    def __init__(self, *args: Any, rounds: int = 2, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.rounds = rounds

    def run(self, task: str, conclusion: str | None = None) -> ReasoningResult:
        """conclusion 为待审查结论；为 None 时先由 LLM 生成初步结论"""
        result = ReasoningResult(pattern=self.pattern_name)
        self._tool_calls = 0

        if conclusion is None:
            conclusion = self.llm(DEFAULT_SYSTEM, f"任务: {task}\n给出你的初步结论（纯文本）")

        transcript: list[str] = []
        current = conclusion
        revised_any = False

        for r in range(1, self.rounds + 1):
            result.iterations = r
            # 质疑方：找漏洞，可用工具验证
            critic_prompt = (
                f"任务: {task}\n待审查结论: {current}\n已有辩论记录:\n" + "\n".join(transcript)
                + "\n\n你是质疑方。找出该结论的漏洞、未验证的假设。"
                "如需证据可调用工具。输出 JSON: "
                '{"objection": "...", "tool": "验证工具名或null", "args": {}}'
            )
            try:
                obj = _extract_json(self.llm(DEFAULT_SYSTEM, critic_prompt))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"debate 质疑解析失败: {e}")
                break

            objection = obj.get("objection", "")
            obs = ""
            if obj.get("tool"):
                obs = self.call_tool(obj["tool"], obj.get("args", {}))
                result.total_tool_calls += 1
            transcript.append(f"[质疑 r{r}] {objection}\n[验证] {obs[:400]}")
            result.steps.append(StepRecord(step=r, action=f"质疑: {objection}", observation=obs or "(无验证)"))

            # 辩护方：回应质疑，必要时修正结论
            def_prompt = (
                f"任务: {task}\n结论: {current}\n质疑与验证:\n" + "\n".join(transcript)
                + "\n\n你是辩护方。回应质疑；若质疑成立则修正结论。输出 JSON: "
                '{"response": "...", "revised_conclusion": "...或null表示不修正"}'
            )
            try:
                df = _extract_json(self.llm(DEFAULT_SYSTEM, def_prompt))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"debate 辩护解析失败: {e}")
                break

            transcript.append(f"[辩护 r{r}] {df.get('response', '')}")
            revised = df.get("revised_conclusion")
            if revised:
                current = revised
                revised_any = True

        # 裁判（Python 决策：基于辩论轮次是否有修正来定置信度）
        result.answer = current
        result.confidence = 0.75 if not revised_any else 0.65
        return result


# ============ 统一入口 ============

PATTERNS: dict[str, type[BaseReasoningPattern]] = {
    "reflexion": ReflexionLoop,
    "plan-execute": PlanExecuteLoop,
    "lats": LATSPattern,
    "debate": DebatePattern,
}


def run_reasoning(
    pattern: str,
    task: str,
    llm: LLMFn,
    tool_executor: ToolExecutorFn | None = None,
    config: ReasoningConfig | None = None,
    **kwargs: Any,
) -> ReasoningResult:
    """统一推理入口

    pattern: reflexion | plan-execute | lats | debate
    """
    cls = PATTERNS.get(pattern)
    if cls is None:
        raise ValueError(f"未知推理模式: {pattern}，可选: {list(PATTERNS)}")
    return cls(llm=llm, tool_executor=tool_executor, config=config, **kwargs).run(task)

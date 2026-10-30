"""多引擎协同 —— 把"多个智能体"真正合成一条流水线

用户诉求：不要只是"能分别接上不同引擎"，而是**让它们合起来跑一件事**。

本模块实现的协同模型（与 ADR-0010 一致：不合并源码，只编排进程）：

    规划(planner) → 执行(executor) → 审查(reviewer) → 不合格则返工 → 再审查

关键设计：
- **引擎可混搭**：`--planner codex --executor native --reviewer opencode` 都行；
  默认全用 `native`（我们自己的 agent，含 19 工具/LSP/世界模型），不装外部 CLI 也能跑
- **判定必须确定性**：审查结论要求模型输出 `VERDICT: APPROVE` 或 `VERDICT: NEEDS_FIX`，
  我们用正则解析。不依赖模型"语气"，避免"看起来过了其实没过"
- **返工有上限**：默认 1 轮，避免两个引擎互相"挑刺"无限循环
- **全程留痕**：每个阶段的引擎、耗时、输出都可查，失败不静默

为什么值得：单个引擎容易"自己审自己"放过问题。换成"另一家引擎审你"能抓出真问题
（本项目实测就多次出现：本机模型自称完成、独立审查发现是假闭环）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

#: 审查结论标记（确定性解析，不靠语气判断）
VERDICT_APPROVE = "VERDICT: APPROVE"
VERDICT_NEEDS_FIX = "VERDICT: NEEDS_FIX"

PLAN_PROMPT = """你是规划者。请只做规划，不要执行、不要修改文件。

任务：{goal}

要求：
1. 拆成可执行的步骤（每步一句话，含要动的文件/命令）
2. 标出风险点与验收方式
3. 不要写代码实现，只给计划
"""

EXEC_PROMPT = """你是执行者。请按下面的计划完成任务。

任务：{goal}

已批准的计划：
{plan}

要求：直接动手（用可用工具），完成后用 1-3 句话说明你做了什么、结果如何。
"""

REVIEW_PROMPT = """你是独立审查者。请严格审查执行结果，不要客气、不要假设它做对了。

原始任务：{goal}
执行者自述：{draft}

要求：
1. 逐条核对任务要求是否真的满足（有证据吗？还是只是"声称完成"？）
2. 明确指出缺失、做错、或投机取巧的地方
3. 最后一行必须严格输出以下两者之一：
   VERDICT: APPROVE
   VERDICT: NEEDS_FIX
   若 NEEDS_FIX，在 VERDICT 行之前用编号列出必须修复的问题。
"""

REPAIR_PROMPT = """你是执行者。独立审查发现了问题，请修复它们。

原始任务：{goal}
当前结果自述：{draft}

审查意见：
{issues}

要求：针对每条意见实际修复（不要只解释），完成后简述改了什么。
"""


def parse_verdict(text: str) -> tuple[str, list[str]]:
    """解析审查结论 → (APPROVE|NEEDS_FIX|UNKNOWN, 问题列表)

    确定性规则：
    - 出现 `VERDICT: NEEDS_FIX` → NEEDS_FIX（优先级高于 APPROVE，防止模型两种都写）
    - 只有 `VERDICT: APPROVE` → APPROVE
    - 都没有 → UNKNOWN（不猜成通过，按"未通过"处理）
    """
    body = text or ""
    if VERDICT_NEEDS_FIX in body:
        verdict = "NEEDS_FIX"
        head = body.split(VERDICT_NEEDS_FIX)[0]
        issues = [
            re.sub(r"^\s*(?:\d+[.、)]|[-*])\s*", "", ln).strip()
            for ln in head.splitlines()
            if re.match(r"^\s*(?:\d+[.、)]|[-*])\s*\S", ln)
        ]
        return verdict, issues[:10]
    if VERDICT_APPROVE in body:
        return "APPROVE", []
    return "UNKNOWN", []


@dataclass
class PhaseRecord:
    """一个阶段的执行记录（可查、可审计）"""

    phase: str          # plan | execute | review | repair
    engine: str
    ok: bool
    seconds: float
    text: str = ""
    error: str = ""


@dataclass
class CollabResult:
    goal: str
    plan: str = ""
    draft: str = ""
    final: str = ""
    verdict: str = "UNKNOWN"
    issues: list[str] = field(default_factory=list)
    rounds: int = 0
    phases: list[PhaseRecord] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict == "APPROVE"

    def summary(self) -> str:
        engines = " → ".join(f"{p.phase}({p.engine})" for p in self.phases)
        return (
            f"协同流水线：{engines}\n"
            f"审查结论：{self.verdict}"
            + (f"（问题 {len(self.issues)} 条）" if self.issues else "")
            + f" · 返工 {self.rounds} 轮"
        )


BackendFactory = Callable[[str], Any]


def _default_factory(workdir: Any, max_iterations: int) -> BackendFactory:
    """按引擎名返回后端，并**按名字缓存**

    为什么必须缓存：实测三阶段协同会各建一次引擎 —— 日志里"世界模型初始化完成"
    出现 3 次，每次几秒到几十秒纯属浪费。缓存后同一引擎跨阶段复用（也共享工具池）。
    """
    cache: dict[str, Any] = {}

    def factory(name: str) -> Any:
        key = name or "native"
        if key in cache:
            return cache[key]
        from ..backends import registry
        from ..backends.native import NativeBackend

        if key in ("native", "clawd"):
            backend = NativeBackend(workdir=workdir, max_iterations=max_iterations)
        else:
            backend = registry.get_backend(key, workdir=workdir)
        cache[key] = backend
        return backend

    return factory


class Collaborator:
    """规划-执行-审查-返工 编排器"""

    def __init__(
        self,
        goal: str,
        *,
        planner: str = "native",
        executor: str = "native",
        reviewer: str = "native",
        max_repair_rounds: int = 1,
        timeout: float = 900.0,
        backend_factory: BackendFactory | None = None,
        workdir: Any = ".",
        max_iterations: int = 10,
    ):
        self.goal = goal
        self.planner = planner
        self.executor = executor
        self.reviewer = reviewer
        self.max_repair_rounds = max(0, max_repair_rounds)
        self.timeout = timeout
        self._factory = backend_factory or _default_factory(workdir, max_iterations)

    # ---------- 内部 ----------
    def _run_phase(self, phase: str, engine: str, prompt: str) -> tuple[str, PhaseRecord]:
        started = time.perf_counter()
        try:
            backend = self._factory(engine)
            result = backend.run(prompt, timeout=self.timeout)
            text = str(getattr(result, "text", "") or "")
            ok = bool(getattr(result, "ok", False)) or bool(text.strip())
            errors = getattr(result, "errors", None) or []
            rec = PhaseRecord(
                phase=phase, engine=engine, ok=ok,
                seconds=round(time.perf_counter() - started, 1),
                text=text[:2000],
                error="; ".join(str(e) for e in errors[:2]),
            )
            return text, rec
        except Exception as e:  # noqa: BLE001 — 阶段失败要记录而不是炸掉整条流水线
            rec = PhaseRecord(
                phase=phase, engine=engine, ok=False,
                seconds=round(time.perf_counter() - started, 1),
                error=f"{type(e).__name__}: {e}",
            )
            return "", rec

    # ---------- 主流程 ----------
    def run(self) -> CollabResult:
        out = CollabResult(goal=self.goal)

        plan_text, rec = self._run_phase(
            "plan", self.planner, PLAN_PROMPT.format(goal=self.goal)
        )
        out.phases.append(rec)
        out.plan = plan_text
        if not plan_text.strip():
            out.verdict = "UNKNOWN"
            out.issues = [f"规划阶段失败: {rec.error or '无输出'}"]
            return out

        draft, rec = self._run_phase(
            "execute", self.executor,
            EXEC_PROMPT.format(goal=self.goal, plan=plan_text),
        )
        out.phases.append(rec)
        out.draft = draft

        review_text, rec = self._run_phase(
            "review", self.reviewer,
            REVIEW_PROMPT.format(goal=self.goal, draft=draft or "(执行阶段无输出)"),
        )
        out.phases.append(rec)
        verdict, issues = parse_verdict(review_text)
        out.verdict, out.issues = verdict, issues

        rounds = 0
        while verdict == "NEEDS_FIX" and rounds < self.max_repair_rounds:
            rounds += 1
            fixed, rec = self._run_phase(
                "repair", self.executor,
                REPAIR_PROMPT.format(
                    goal=self.goal, draft=draft,
                    issues="\n".join(f"{i}. {x}" for i, x in enumerate(issues, 1)) or "(未给出细节)",
                ),
            )
            out.phases.append(rec)
            if fixed.strip():
                draft = fixed
                out.draft = fixed

            review_text, rec = self._run_phase(
                "review", self.reviewer,
                REVIEW_PROMPT.format(goal=self.goal, draft=draft),
            )
            out.phases.append(rec)
            verdict, issues = parse_verdict(review_text)
            out.verdict, out.issues = verdict, issues

        out.rounds = rounds
        out.final = draft
        return out

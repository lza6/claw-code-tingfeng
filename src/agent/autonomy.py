"""挂机自主决策引擎（无人值守）

用户场景：**挂机让 Agent 自己把任务跑完**。

难点不是"放行一切"，而是"没人在的时候怎么决策才不闯祸"：
- 遇到需要审批的操作，没人能批 → 必须有**规则化自决**，而不是默认放行或直接卡死
- 必须能在**该停的时候停**（预算烧完、连续失败、反复空转），而不是无限跑
- 每个"自作主张"都要留痕，事后能查（中文可读）

设计要点（全部用中文表达，用户不需懂英文枚举）：

| 挂机级别 | 行为 |
|:---|:---|
| `supervised`（有人看着，默认） | 需要审批就问你，机器人不替你做主 |
| `semi`（半挂机） | 只对**高风险**操作出声（保护路径写入、禁命令），其余自决 |
| `unattended`（全挂机） | 完全不打扰：读放行、普通写入自决放行、危险操作静默跳过并记录 |

自决规则（`unattended` 下对"需确认"的操作）：
1. 只读 → 放行
2. 写入工作区内非保护路径 → 放行（记一条审计）
3. 写入受保护路径（`.git`、密钥、token 文件）→ **跳过**（不执行，理由回灌模型）
4. 执行被策略**禁止**的命令 → 跳过
5. 执行被策略标记**需审批**的命令 → 跳过（挂机时没人批，绝不能默认放行）
6. 连续跳过超过阈值 → **中止整轮**（说明模型在硬闯护栏，继续跑没意义）

停止条件（`check_stop`）：
- 迭代数超上限 / 连续失败超上限 / 成本超预算 / 时长超时 / 空转（无进展）
"""

from __future__ import annotations

import json
import time

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..core.permissions import Effect, PermissionRequest, protected_reason


class AutonomyLevel(str, Enum):
    """挂机级别"""

    SUPERVISED = "supervised"
    SEMI = "semi"
    UNATTENDED = "unattended"

    @property
    def label(self) -> str:
        return {
            "supervised": "有人盯（默认，需审批就问你）",
            "semi": "半挂机（只有高风险才问你）",
            "unattended": "全挂机（不打扰，按规则自决）",
        }.get(self.value, self.value)

    @property
    def is_unattended(self) -> bool:
        return self is AutonomyLevel.UNATTENDED


class Action(str, Enum):
    """自主决策的动作"""

    PROCEED = "proceed"   # 继续执行该操作
    SKIP = "skip"         # 跳过该操作，把理由回灌给模型
    ABORT = "abort"       # 中止整轮任务
    ASK = "ask"           # 交给人确认

    @property
    def label(self) -> str:
        return {
            "proceed": "放行",
            "skip": "跳过",
            "abort": "中止",
            "ask": "询问",
        }.get(self.value, self.value)


@dataclass
class AutonomyDecision:
    """一次自主决策（含中文理由，便于用户事后看懂）"""

    action: Action
    reason: str
    needs_human: bool = False

    @property
    def proceed(self) -> bool:
        return self.action is Action.PROCEED


@dataclass
class AutonomyBudget:
    """挂机预算与护栏"""

    max_iterations: int = 40
    max_consecutive_failures: int = 5
    max_skips: int = 5           # 连续跳过多少次就认为在硬闯护栏
    max_cost_usd: float = 5.0
    max_minutes: float = 120.0


@dataclass
class AutonomyStats:
    """运行统计（用于最终中文报告）"""

    started_at: float = field(default_factory=time.time)
    proceeded: int = 0
    skipped: int = 0
    asked: int = 0
    consecutive_skips: int = 0
    consecutive_failures: int = 0

    def note(self, action: Action) -> None:
        if action is Action.PROCEED:
            self.proceeded += 1
            self.consecutive_skips = 0
        elif action is Action.SKIP:
            self.skipped += 1
            self.consecutive_skips += 1
        elif action is Action.ASK:
            self.asked += 1


class AutonomyEngine:
    """挂机自主决策引擎

    用法：
        engine = AutonomyEngine(level=AutonomyLevel.UNATTENDED, workdir=Path('.'))
        decision = engine.decide_permission(req, Effect.ASK, "需审批", approval_mode="default")
        if not decision.proceed: ...  # 把 decision.reason 回灌给模型
        stop, why = engine.check_stop(iterations=12, cost_usd=1.2)
    """

    def __init__(
        self,
        level: AutonomyLevel | str = AutonomyLevel.SUPERVISED,
        *,
        workdir: Path | str | None = None,
        budget: AutonomyBudget | None = None,
        audit: bool = True,
    ):
        self.level = AutonomyLevel(level) if isinstance(level, str) else level
        self.workdir = Path(workdir).resolve() if workdir else Path.cwd().resolve()
        self.budget = budget or AutonomyBudget()
        self.stats = AutonomyStats()
        self.audit = audit
        self.dir = self.workdir / ".clawd" / "autonomy"
        self.audit_path = self.dir / "decisions.jsonl"
        #: 用户预先放行的命令前缀文件（挂机前用 `clawd autonomy allow` 添加）
        self.allow_path = self.dir / "allow.json"
        #: 用户放置 `STOP` 文件即可让挂机在下一次检查点停下
        self.stop_path = self.dir / "STOP"
        self._extra_allow: list[list[str]] | None = None

    # ---------- 决策 ----------
    def decide_permission(
        self,
        req: PermissionRequest,
        effect: Effect,
        reason: str = "",
        *,
        approval_mode: str = "default",
        policy: str = "",
    ) -> AutonomyDecision:
        """对一次权限请求给出自主决策

        Args:
            req: 权限请求
            effect: 权限引擎给出的结论
            reason: 权限引擎给出的中文理由
            approval_mode: 当前审批模式
            policy: 命令策略判决（allow/prompt/forbidden/空）。
                **挂机自决必须用它区分"策略明确允许"与"策略要求审批"**
        """
        # 放行/拒绝是明确的，不需要"自主判断"
        if effect is Effect.ALLOW:
            self.stats.note(Action.PROCEED)
            return AutonomyDecision(Action.PROCEED, reason or "权限引擎放行")

        if effect is Effect.DENY:
            self.stats.note(Action.SKIP)
            return AutonomyDecision(Action.SKIP, reason or "权限引擎拒绝")

        # 以下 effect == ASK：无人值守时才需要自决
        if self.level is AutonomyLevel.SUPERVISED:
            self.stats.note(Action.ASK)
            return AutonomyDecision(Action.ASK, "需要你确认", needs_human=True)

        if self.level is AutonomyLevel.SEMI:
            # 半挂机：只有真正高风险才出声，其余自决放行
            # 高风险定义：受保护路径 / 禁命令 / **策略要求审批的命令**（policy=prompt）
            # 注意：策略明确允许的命令（policy=allow，如 git status）在半挂机时自决放行，
            # 否则半挂机退化成"每条命令都问"，失去意义
            if self._is_high_risk(req, policy=policy):
                self.stats.note(Action.ASK)
                return AutonomyDecision(
                    Action.ASK, f"高风险操作（{protected_reason(req.path) or '危险命令'}），需你确认",
                    needs_human=True,
                )
            return self._auto_proceed(req, "半挂机：非高风险操作，自决放行")

        # UNATTENDED：完全自决
        if protected_reason(req.path):
            self.stats.note(Action.SKIP)
            decision = AutonomyDecision(
                Action.SKIP,
                f"挂机模式：目标路径受保护（{protected_reason(req.path)}），已跳过该操作；"
                f"请换个不触碰该路径的做法",
            )
            self._record(req, decision)
            return decision

        if self._exec_is_forbidden(reason):
            self.stats.note(Action.SKIP)
            decision = AutonomyDecision(
                Action.SKIP,
                f"挂机模式：命令被策略禁止（{reason}），已跳过；请改用安全等价做法",
            )
            self._record(req, decision)
            return decision

        # 用户挂机前显式授权的命令前缀 → 等同于策略允许
        if req.action == "exec" and self._user_preapproved(getattr(req, "command", "")):
            return self._auto_proceed(
                req, f"挂机模式：命令命中你预先放行的清单（{req.command}），自决放行"
            )

        if req.action == "exec" and policy == "allow":
            # 策略明确允许的命令（如 ls / git status）：挂机时放行，否则挂机会寸步难行
            return self._auto_proceed(
                req, f"挂机模式：该命令在策略允许清单内（{reason or '策略允许'}），自决放行"
            )

        if req.action == "exec":
            # 挂机时"需审批/未列入清单的命令"绝不能默认放行
            self.stats.note(Action.SKIP)
            decision = AutonomyDecision(
                Action.SKIP,
                f"挂机模式：该命令需要人工审批（{reason or '策略要求审批'}），"
                f"无人可批，已跳过；请改用只读或明确安全的替代方案",
            )
            self._record(req, decision)
            return decision

        return self._auto_proceed(req, "挂机模式：工作区内普通操作，自决放行")

    def _auto_proceed(self, req: PermissionRequest, why: str) -> AutonomyDecision:
        self.stats.note(Action.PROCEED)
        decision = AutonomyDecision(Action.PROCEED, why)
        self._record(req, decision)
        return decision

    @staticmethod
    def _exec_is_forbidden(reason: str) -> bool:
        return "rejected:" in (reason or "")

    def _is_high_risk(self, req: PermissionRequest, *, policy: str = "") -> bool:
        if protected_reason(req.path):
            return True
        if self._exec_is_forbidden(getattr(req, "command", "") or ""):
            return True
        if req.action == "exec":
            # 策略要求审批（或未命中任何规则）→ 高风险；策略明确允许 → 不算
            return policy != "allow"
        return False

    # ---------- 用户预先放行（挂机前授权，避免挂在半路） ----------
    def extra_allowed_prefixes(self) -> list[list[str]]:
        """读取用户预先放行的命令前缀（每次重新读，支持挂机中途追加）"""
        import json as _json

        try:
            raw = _json.loads(self.allow_path.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            return []
        items = raw.get("commands") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return []
        out: list[list[str]] = []
        for item in items:
            if isinstance(item, str) and item.strip():
                out.append(item.strip().split())
            elif isinstance(item, list) and item:
                out.append([str(x) for x in item])
        return out

    def _user_preapproved(self, command: str | None) -> bool:
        if not command:
            return False
        argv = command.strip().split()
        for prefix in self.extra_allowed_prefixes():
            if len(argv) >= len(prefix) and argv[:len(prefix)] == prefix:
                return True
        return False

    def stop_requested(self) -> bool:
        """用户是否请求停止（放置 .clawd/autonomy/STOP 文件）"""
        return self.stop_path.exists()

    # ---------- 停止条件 ----------
    def check_stop(
        self,
        *,
        iterations: int = 0,
        consecutive_failures: int = 0,
        cost_usd: float = 0.0,
        progress_made: bool = True,
    ) -> tuple[bool, str]:
        """是否该停下（返回：是否停止 + 中文理由）"""
        b = self.budget

        if self.stop_requested():
            return True, (
                "检测到 .clawd/autonomy/STOP 文件：你要求停止，已按停并保留当前进度"
            )
        if self.stats.consecutive_skips >= b.max_skips:
            return True, (
                f"连续跳过 {self.stats.consecutive_skips} 次（超过上限 {b.max_skips}）："
                f"模型在硬闯安全护栏，继续执行不会有好结果，已中止"
            )
        if iterations >= b.max_iterations:
            return True, f"已执行 {iterations} 步，达到上限 {b.max_iterations}，先停下交付阶段性成果"
        if consecutive_failures >= b.max_consecutive_failures:
            return True, (
                f"连续失败 {consecutive_failures} 次（超过上限 {b.max_consecutive_failures}）："
                f"再试大概率还是失败，建议先排查根因"
            )
        if cost_usd >= b.max_cost_usd:
            return True, f"已花费 ${cost_usd:.2f}，达到预算上限 ${b.max_cost_usd:.2f}"
        elapsed_min = (time.time() - self.stats.started_at) / 60
        if elapsed_min >= b.max_minutes:
            return True, f"已运行 {elapsed_min:.0f} 分钟，达到时长上限 {b.max_minutes:.0f} 分钟"
        return False, ""

    # ---------- 审计 ----------
    def _record(self, req: PermissionRequest, decision: AutonomyDecision) -> None:
        if not self.audit:
            return
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "挂机级别": self.level.label,
                "工具": req.tool,
                "动作类型": req.action,
                "目标": req.path or "",
                "命令": getattr(req, "command", "") or "",
                "决策": decision.action.label,
                "理由": decision.reason,
            }
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + chr(10))
        except OSError:
            pass  # 审计写入失败不能影响主流程

    def allowed_command_hint(self) -> str:
        """挂机时给模型的"能用什么命令"中文提示

        真实 E2E 教训：不告诉模型可用清单，它会用 `pwd; ls`、`find ... | head` 这类
        复合/管道命令，而这些在挂机时会被保守跳过，白烧迭代。
        """
        try:
            from ..core.exec_policy import Decision as _D
            from ..core.exec_policy import ExecPolicy

            allowed = [
                " ".join(r.prefix) for r in ExecPolicy().rules if r.decision is _D.ALLOW
            ]
        except Exception:
            return ""
        if not allowed:
            return ""
        sample = "、".join(f"`{p}`" for p in allowed[:14])
        hint = [
            "",
            "## 挂机模式下的命令限制（重要）",
            "你现在处于**无人值守挂机模式**：没有人能审批命令。",
            f"- **可直接执行**：{sample} 等只读命令",
            "- **会被跳过**：管道（|）、复合命令（;、&&）、重定向（>）、以及任何不在允许清单里的命令",
            "- 因此请**一次只发一条简单命令**，不要拼接；文件操作用文件工具而不是 shell。",
            "- 被跳过的调用会返回拒绝理由，请换做法，不要重复尝试同一条命令。",
        ]
        return chr(10).join(hint)

    def summary(self) -> str:
        """中文运行小结（挂机结束后给用户看的）"""
        elapsed = (time.time() - self.stats.started_at) / 60
        return (
            f"挂机级别：{self.level.label}\n"
            f"自主放行 {self.stats.proceeded} 次 · 主动跳过 {self.stats.skipped} 次 · "
            f"转人工 {self.stats.asked} 次 · 用时 {elapsed:.1f} 分钟\n"
            f"审计日志：{self.audit_path}"
        )


def level_from_env(default: str = "supervised") -> AutonomyLevel:
    """从环境变量读挂机级别（`CLAWD_AUTONOMY=unattended`）"""
    import os

    raw = (os.environ.get("CLAWD_AUTONOMY") or default).strip().lower()
    try:
        return AutonomyLevel(raw)
    except ValueError:
        return AutonomyLevel.SUPERVISED

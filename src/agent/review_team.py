"""多角色并行评审 —— 让 `prompts/agents/` 里的 review 角色真的被调度起来

审计事实（P1-14）：仓库里有 6 个 REVIEW 角色定义 + 34 个 prompt 模板，但**没有任何
调度器并行跑它们**；生产侧只有 `factory.get_prompt()` 一个调用方，实际评审是单点
`AuditorAgent` 一次扫全文件。等于"review 面有名无实"。

本模块补的就是那个调度器，并且刻意做成：

- **可测**：`provider_factory` 可注入，离线用假 provider 跑完整并发路径，零付费调用；
- **确定性裁决**：`VERDICT: APPROVE|NEEDS_FIX` 与 `CRITICAL/HIGH/MEDIUM/LOW` 由正则解析，
  不靠 LLM 自己"总结成通过"；
- **不伪造通过**：任一角色报错 → 整份报告 `INCOMPLETE`，绝不把"没评审"算成"没问题"。
"""
from __future__ import annotations

import asyncio
import re
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from ..utils.logger import get_logger

logger = get_logger(__name__)

#: 默认参与并行评审的角色（`prompts/agents/<role>.md` 必须真实存在）
DEFAULT_ROLES: tuple[str, ...] = (
    "code-reviewer",
    "security-reviewer",
    "performance-reviewer",
    "style-reviewer",
)

SEVERITIES: tuple[str, ...] = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
_SEVERITY_RE = re.compile(r"\b(" + "|".join(SEVERITIES) + r")\b")
_VERDICT_RE = re.compile(
    r"(?:VERDICT|结论|判定)\s*[:：]\s*\**\s*"
    r"(APPROVE|NEEDS[ _]?FIX|PASS|OK|LGTM|REJECT|通过|无问题|无需修改|需要修复|需修复|有问题)",
    re.IGNORECASE,
)
#: 裁决词归一（真实模型会英文/中文/口语混写；只认一种写法会把"通过"误判成 UNKNOWN）
_APPROVE_WORDS = ("approve", "pass", "ok", "lgtm", "通过", "无问题", "无需修改")
_NEEDS_FIX_WORDS = ("needsfix", "reject", "需要修复", "需修复", "有问题")

#: 单个角色看到的代码上限（字符）——评审要的是证据，不是把整个仓库塞进 prompt
MAX_PAYLOAD_CHARS = 24_000

#: 绝不送进 LLM 的文件（评审会把内容发给模型，密钥类文件必须先剔除）
SECRET_PATH_PATTERNS: tuple[str, ...] = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore",
    "id_rsa*", "id_ed25519*", "credentials*", "secrets*", ".npmrc", ".pypirc",
)

#: 聚合裁决
VERDICT_APPROVE = "APPROVE"
VERDICT_NEEDS_FIX = "NEEDS_FIX"
VERDICT_INCOMPLETE = "INCOMPLETE"  # 有角色没跑成/没给裁决：不下结论


@dataclass
class RoleReview:
    """单个角色的评审结果"""

    role: str
    verdict: str = "UNKNOWN"
    severities: dict[str, int] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    raw: str = ""
    error: str = ""
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "verdict": self.verdict,
            "severities": self.severities,
            "findings": self.findings[:20],
            "error": self.error,
            "duration_s": round(self.duration_s, 2),
        }


@dataclass
class ReviewReport:
    """一次多角色评审的汇总"""

    roles: list[RoleReview] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    diff_included: bool = False

    # ---------- 判定 ----------
    @property
    def failed_roles(self) -> list[RoleReview]:
        return [r for r in self.roles if not r.ok]

    @property
    def blocking_findings(self) -> list[str]:
        """CRITICAL / HIGH 的行（这些是必须修的）"""
        out: list[str] = []
        for review in self.roles:
            for finding in review.findings:
                head = finding.lstrip("-* \t").upper()
                if head.startswith(("CRITICAL", "HIGH", "P0", "P1")):
                    out.append(f"[{review.role}] {finding}")
        return out

    @property
    def severity_totals(self) -> dict[str, int]:
        totals = {name: 0 for name in SEVERITIES}
        for review in self.roles:
            for name, count in review.severities.items():
                totals[name] = totals.get(name, 0) + count
        return totals

    @property
    def verdict(self) -> str:
        """聚合裁决（宁可 INCOMPLETE，也不假装通过）"""
        if not self.roles:
            return VERDICT_INCOMPLETE
        if self.failed_roles:
            return VERDICT_INCOMPLETE
        needs_fix = any(r.verdict == VERDICT_NEEDS_FIX for r in self.roles)
        unknown = any(r.verdict == "UNKNOWN" for r in self.roles)
        if needs_fix or self.blocking_findings:
            return VERDICT_NEEDS_FIX
        if unknown:
            return VERDICT_INCOMPLETE
        return VERDICT_APPROVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "files": self.files,
            "diff_included": self.diff_included,
            "severity_totals": self.severity_totals,
            "blocking_findings": self.blocking_findings,
            "roles": [r.to_dict() for r in self.roles],
        }

    def summary_line(self) -> str:
        totals = self.severity_totals
        severity_text = " ".join(f"{k}:{v}" for k, v in totals.items() if v) or "无分级问题"
        return (
            f"review[{self.verdict}] {len(self.roles)} 角色 · {len(self.files)} 文件 · "
            f"{severity_text}"
            + (f" · {len(self.failed_roles)} 角色失败" if self.failed_roles else "")
        )


def parse_role_output(role: str, text: str, duration_s: float = 0.0) -> RoleReview:
    """从角色输出里确定性解析裁决与分级问题（不猜、不补）"""
    body = text or ""
    review = RoleReview(role=role, raw=body, duration_s=duration_s)

    for name in _SEVERITY_RE.findall(body.upper()):
        review.severities[name] = review.severities.get(name, 0) + 1

    for line in body.splitlines():
        head = line.lstrip("-* \t")
        if head.upper().startswith(SEVERITIES):
            review.findings.append(line.strip())

    verdict_match = _VERDICT_RE.search(body)
    if verdict_match:
        raw = verdict_match.group(1).lower().strip()
        compact = raw.replace("_", "").replace(" ", "")
        approve = {w.replace(" ", "") for w in _APPROVE_WORDS}
        needs_fix = {w.replace(" ", "") for w in _NEEDS_FIX_WORDS}
        if compact in approve:
            review.verdict = VERDICT_APPROVE
        elif compact in needs_fix:
            review.verdict = VERDICT_NEEDS_FIX
        else:
            review.verdict = "UNKNOWN"
    else:
        # 没写裁决行时**不猜"通过"**：按它自己报的分级兜底
        # （有 CRITICAL/HIGH/MEDIUM → NEEDS_FIX；只报 LOW 或啥都没报 → UNKNOWN）
        blocking = {k for k, v in review.severities.items() if v} & {"CRITICAL", "HIGH", "MEDIUM"}
        review.verdict = VERDICT_NEEDS_FIX if blocking else "UNKNOWN"

    return review


def available_review_roles() -> dict[str, str]:
    """可用的评审角色 → prompt 文件名

    只挑评审类模板（`*reviewer*` 以及 verifier / qa-tester / critic），
    避免用户随手传一个 `designer`/`writer` 让评审变成"写文案"。
    """
    from prompts.agents import PROMPT_FILES

    picked: dict[str, str] = {}
    for name, filename in PROMPT_FILES.items():
        if "review" in name or name in ("verifier", "qa-tester", "critic"):
            picked[name] = filename
    return picked


def build_role_prompt(role: str, payload: str, files: Sequence[str], diff_text: str = "") -> str:
    """拼出该角色的评审输入（角色模板 + 真实代码/差异）"""
    from prompts.agents import get_prompt

    template = get_prompt(role)
    if not template:
        raise ValueError(f"找不到角色模板: prompts/agents/{role}.md")

    parts = [
        template.strip(),
        "",
        "---",
        f"## 你的角色: `{role}`（模板 prompts/agents/{role}.md）",
        "---",
        "## 待评审目标",
        "文件: " + (", ".join(files) if files else "(未指定)"),
    ]
    if diff_text.strip():
        parts += ["", "## 变更差异（git diff）", "```diff", diff_text[:MAX_PAYLOAD_CHARS], "```"]
    parts += ["", "## 代码内容", "```", payload[:MAX_PAYLOAD_CHARS], "```"]
    parts += [
        "",
        "---",
        "## 输出契约（必须严格遵守）",
        "1. 每条问题单独一行，以 `CRITICAL:` / `HIGH:` / `MEDIUM:` / `LOW:` 开头，"
        "并给出文件与行号、为什么是问题、怎么改。",
        "2. 没有问题就只写 `VERDICT: APPROVE`，不要编造问题。",
        "3. 最后一行必须写 `VERDICT: APPROVE` 或 `VERDICT: NEEDS_FIX`。",
        "4. 不确定的地方写 `UNKNOWN: <原因>`，不要假设。",
    ]
    return "\n".join(parts)


def _looks_secret(path: Path) -> bool:
    """是否属于"绝不能发给模型"的文件（按文件名匹配）"""
    import fnmatch

    name = path.name.lower()
    return any(fnmatch.fnmatch(name, pattern.lower()) for pattern in SECRET_PATH_PATTERNS)


def _read_files(files: Sequence[str | Path], max_chars: int = MAX_PAYLOAD_CHARS) -> tuple[str, list[str]]:
    """读取目标文件正文（带截断，保证总长度可控；密钥类文件一律跳过）"""
    chunks: list[str] = []
    used: list[str] = []
    budget = max_chars
    for item in files:
        path = Path(item)
        if not path.is_file():
            continue
        if _looks_secret(path):
            logger.warning(f"跳过疑似密钥文件（不发给模型）: {path}")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning(f"评审读取失败 {path}: {e}")
            continue
        used.append(str(path))
        snippet = text[:budget]
        chunks.append(f"### {path}\n{snippet}")
        budget -= len(snippet)
        if budget <= 0:
            break
    return "\n\n".join(chunks), used


ProviderFactory = Callable[[], Any]


def _default_provider_factory() -> Any:
    from ..llm.config import LLMConfig
    from ..llm.providers import create_llm_provider

    return create_llm_provider(LLMConfig.from_env())


class ReviewTeam:
    """并行多角色评审器

    用法（离线可测）::

        team = ReviewTeam(provider_factory=lambda: FakeProvider())
        report = asyncio.run(team.review(["src/app.py"]))
    """

    def __init__(
        self,
        provider_factory: ProviderFactory | None = None,
        roles: Sequence[str] = DEFAULT_ROLES,
        *,
        timeout: float = 180.0,
    ) -> None:
        self._provider_factory = provider_factory or _default_provider_factory
        self.roles = tuple(roles)
        self.timeout = timeout

    async def _ask(self, provider: Any, prompt: str) -> str:
        from ..llm.config import LLMMessage

        response = await provider.chat([LLMMessage(role="user", content=prompt)])
        return str(getattr(response, "content", "") or "")

    async def _review_role(self, role: str, prompt: str, provider: Any) -> RoleReview:
        started = time.perf_counter()
        try:
            text = await asyncio.wait_for(self._ask(provider, prompt), timeout=self.timeout)
        except asyncio.TimeoutError:
            return RoleReview(role=role, duration_s=time.perf_counter() - started,
                              error=f"超时（{self.timeout:g}s）")
        except Exception as e:  # noqa: BLE001 — 单角色失败不拖垮整轮
            return RoleReview(role=role, duration_s=time.perf_counter() - started,
                              error=f"{type(e).__name__}: {e}")
        return parse_role_output(role, text, duration_s=time.perf_counter() - started)

    async def review(
        self,
        files: Sequence[str | Path],
        diff_text: str = "",
        *,
        extra_context: str = "",
    ) -> ReviewReport:
        """并行评审（每个角色一次独立调用，互不阻塞）"""
        payload, used = _read_files(files)
        if extra_context:
            payload = (extra_context + "\n\n" + payload)[:MAX_PAYLOAD_CHARS]

        report = ReviewReport(files=used, diff_included=bool(diff_text.strip()))
        if not used and not diff_text.strip():
            logger.warning("评审目标为空（既没有可读文件，也没有 diff）")
            return report

        provider = self._provider_factory()
        tasks = [
            self._review_role(role, build_role_prompt(role, payload, used, diff_text), provider)
            for role in self.roles
        ]
        report.roles = list(await asyncio.gather(*tasks))
        logger.info(
            f"并行评审完成: {report.verdict} · "
            f"{[(r.role, r.verdict) for r in report.roles]}"
        )
        return report


def collect_review_targets(paths: Sequence[str] | None = None, workdir: Path | None = None) -> list[Path]:
    """决定评审哪些文件：显式路径 > 未提交改动 > 无"""
    base = Path(workdir or Path.cwd())
    if paths:
        return [Path(p) if Path(p).is_absolute() else base / p for p in paths]

    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(base), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"读取 git 改动失败: {e}")
        return []
    if result.returncode != 0:
        return []
    return [base / line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def get_git_diff(workdir: Path | None = None, max_chars: int = MAX_PAYLOAD_CHARS) -> str:
    """取未提交 diff（评审需要"改了什么"，而不只是"现在长什么样"）"""
    import subprocess

    base = Path(workdir or Path.cwd())
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(base), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "")[:max_chars]


__all__ = [
    "DEFAULT_ROLES",
    "SECRET_PATH_PATTERNS",
    "available_review_roles",
    "MAX_PAYLOAD_CHARS",
    "ReviewReport",
    "ReviewTeam",
    "RoleReview",
    "VERDICT_APPROVE",
    "VERDICT_INCOMPLETE",
    "VERDICT_NEEDS_FIX",
    "build_role_prompt",
    "collect_review_targets",
    "get_git_diff",
    "parse_role_output",
]

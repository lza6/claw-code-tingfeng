"""命令执行策略引擎 —— 借鉴 Codex `codex-rs/execpolicy` + `core/src/exec_policy.rs`

Codex 的机制（Rust, Apache-2.0）：
- 规则是**命令前缀匹配**（按 argv 逐段比），三种决策：`Allow` / `Prompt`（需审批）/ `Forbidden`（直接禁）
- **最长匹配获胜**（most specific wins），每条规则可带 `justification`
- 拒绝理由三档文案：
  - 有 justification → `` `cmd` rejected: {justification} ``
  - 无 → `` `cmd` rejected: policy forbids commands starting with `{prefix}` ``
  - 完全无匹配却仍被禁 → `` `cmd` rejected: blocked by policy ``
- 需审批时：`` `cmd` requires approval: {justification} `` / `` ... requires approval by policy ``

为什么要它：权限引擎（ADR-0013）只能按"读/写/执行"分类，无法表达
"`git status` 可以、`git push --force` 不行、`rm -rf` 一律禁止"这种**命令级**策略。
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

#: 命令策略结论的中文名
DECISION_LABELS: dict[str, str] = {
    "allow": "允许执行",
    "prompt": "需审批",
    "forbidden": "禁止执行",
}


class Decision(str, Enum):
    ALLOW = "allow"
    PROMPT = "prompt"
    FORBIDDEN = "forbidden"

    @property
    def label(self) -> str:
        return DECISION_LABELS.get(self.value, self.value)


@dataclass(frozen=True)
class Rule:
    """一条前缀规则

    Attributes:
        prefix: 命令前缀（按 argv 段比较，如 ("git", "push")）
        decision: 命中后的决策
        justification: 给模型看的理由/替代建议
    """

    prefix: tuple[str, ...]
    decision: Decision
    justification: str = ""

    def matches(self, argv: Sequence[str]) -> bool:
        if not self.prefix or len(argv) < len(self.prefix):
            return False
        return all(argv[i] == p for i, p in enumerate(self.prefix))

    @property
    def specificity(self) -> int:
        return len(self.prefix)


@dataclass
class Evaluation:
    """一次评估结果"""

    decision: Decision
    reason: str = ""
    matched_prefix: tuple[str, ...] | None = None
    command: str = ""


#: 内置默认规则（宁严勿松；可通过 .clawd/exec_policy.json 覆盖/追加）
BUILTIN_RULES: tuple[Rule, ...] = (
    # —— 一律禁止 ——
    Rule(("rm", "-rf"), Decision.FORBIDDEN, "递归强删不可逆；如需清理请指定具体文件"),
    Rule(("rm", "-fr"), Decision.FORBIDDEN, "递归强删不可逆；如需清理请指定具体文件"),
    Rule(("rm", "-r"), Decision.PROMPT, "递归删除需确认"),
    Rule(("git", "push", "--force"), Decision.FORBIDDEN, "禁止强推（ADr 与团队规范）"),
    Rule(("git", "push", "-f"), Decision.FORBIDDEN, "禁止强推"),
    Rule(("git", "reset", "--hard"), Decision.FORBIDDEN, "会丢弃未提交改动；可用 git stash 先保存"),
    Rule(("git", "clean", "-fd"), Decision.FORBIDDEN, "会删除未跟踪文件且不可恢复"),
    Rule(("git", "clean", "-f"), Decision.PROMPT, "会删除未跟踪文件"),
    Rule(("mkfs",), Decision.FORBIDDEN, "格式化磁盘"),
    Rule(("dd",), Decision.FORBIDDEN, "裸写设备风险极高"),
    Rule(("shutdown",), Decision.FORBIDDEN, ""),
    Rule(("reboot",), Decision.FORBIDDEN, ""),
    Rule(("chmod", "777"), Decision.PROMPT, "777 权限过大，建议按需授权"),
    Rule(("chown",), Decision.PROMPT, ""),
    Rule(("curl",), Decision.PROMPT, "网络下载需确认目标与用途"),
    Rule(("wget",), Decision.PROMPT, ""),
    Rule(("npm", "publish"), Decision.PROMPT, "发布到 npm 是对外不可逆动作"),
    Rule(("pip", "install"), Decision.PROMPT, "安装依赖会改动环境"),
    Rule(("docker", "rm"), Decision.PROMPT, ""),
    Rule(("docker", "rmi"), Decision.PROMPT, ""),
    Rule(("kubectl", "delete"), Decision.PROMPT, ""),
    Rule(("terraform", "destroy"), Decision.FORBIDDEN, "销毁基础设施不可逆"),
    # —— 明确放行（提高可用性，避免什么都问） ——
    Rule(("git", "status"), Decision.ALLOW, ""),
    Rule(("git", "diff"), Decision.ALLOW, ""),
    Rule(("git", "log"), Decision.ALLOW, ""),
    Rule(("git", "show"), Decision.ALLOW, ""),
    Rule(("git", "add"), Decision.ALLOW, ""),
    Rule(("git", "commit"), Decision.ALLOW, ""),
    Rule(("ls",), Decision.ALLOW, ""),
    Rule(("cat",), Decision.ALLOW, ""),
    Rule(("grep",), Decision.ALLOW, ""),
    Rule(("rg",), Decision.ALLOW, ""),
    Rule(("pwd",), Decision.ALLOW, ""),
    Rule(("echo",), Decision.ALLOW, ""),
    # 只读探查类（挂机时模型需要这些来了解现状，否则寸步难行）
    Rule(("find",), Decision.ALLOW, ""),
    Rule(("head",), Decision.ALLOW, ""),
    Rule(("tail",), Decision.ALLOW, ""),
    Rule(("wc",), Decision.ALLOW, ""),
    Rule(("sort",), Decision.ALLOW, ""),
    Rule(("uniq",), Decision.ALLOW, ""),
    Rule(("tree",), Decision.ALLOW, ""),
    Rule(("du",), Decision.ALLOW, ""),
    Rule(("df",), Decision.ALLOW, ""),
    Rule(("which",), Decision.ALLOW, ""),
    Rule(("whoami",), Decision.ALLOW, ""),
    Rule(("date",), Decision.ALLOW, ""),
    Rule(("git", "branch"), Decision.ALLOW, ""),
    Rule(("git", "rev-parse"), Decision.ALLOW, ""),
    Rule(("python", "--version"), Decision.ALLOW, ""),
    Rule(("mkdir",), Decision.ALLOW, "只创建目录，可回滚"),
    Rule(("python", "-c"), Decision.PROMPT, "任意代码执行需确认"),
    Rule(("node", "-e"), Decision.PROMPT, "任意代码执行需确认"),
)


def _render(argv: Sequence[str]) -> str:
    try:
        return shlex.join(list(argv))
    except (ValueError, AttributeError):
        return " ".join(argv)


def split_command(command: str | Sequence[str]) -> list[str]:
    """把命令拆成 argv（字符串用 shlex，失败则按空白切）"""
    if isinstance(command, (list, tuple)):
        return [str(a) for a in command]
    text = (command or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


@dataclass
class ExecPolicy:
    """命令前缀策略

    规则集 = 内置默认 + 用户文件里的规则；同前缀时**用户规则优先**。
    评估时按最具体（前缀最长）命中决定。
    """

    rules: list[Rule] = field(default_factory=lambda: list(BUILTIN_RULES))
    #: 无任何规则命中时的默认决策（Codex 的默认是 Allow + 由 sandbox 兜底）
    default_decision: Decision = Decision.PROMPT

    # ---------- 构造 ----------
    @classmethod
    def with_user_rules(
        cls,
        rules: Iterable[Rule],
        *,
        default_decision: Decision = Decision.PROMPT,
    ) -> "ExecPolicy":
        # 用户规则放前面：同前缀时先命中用户定义
        merged = list(rules) + [r for r in BUILTIN_RULES if r.prefix not in {u.prefix for u in rules}]
        return cls(rules=merged, default_decision=default_decision)

    @classmethod
    def load(cls, path: str | Path | None) -> "ExecPolicy":
        """从 JSON 文件加载用户规则

        格式:
            {"default": "prompt",
             "rules": [{"prefix": ["git","push"], "decision": "forbidden",
                        "justification": "原因"}]}
        文件不存在或损坏时回退到内置规则（并保留 default）。
        """
        if path is None:
            return cls()
        p = Path(path)
        if not p.is_file():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()

        raw_rules = data.get("rules") or []
        parsed: list[Rule] = []
        for item in raw_rules:
            if not isinstance(item, dict):
                continue
            prefix = item.get("prefix")
            if isinstance(prefix, str):
                prefix = [prefix]
            if not isinstance(prefix, list) or not prefix:
                continue
            try:
                decision = Decision(str(item.get("decision") or "prompt").lower())
            except ValueError:
                continue
            parsed.append(Rule(
                prefix=tuple(str(x) for x in prefix),
                decision=decision,
                justification=str(item.get("justification") or ""),
            ))
        try:
            default = Decision(str(data.get("default") or "prompt").lower())
        except ValueError:
            default = Decision.PROMPT
        return cls.with_user_rules(parsed, default_decision=default)

    # ---------- 评估 ----------
    def evaluate(self, command: str | Sequence[str]) -> Evaluation:
        argv = split_command(command)
        rendered = _render(argv)
        if not argv:
            return Evaluation(Decision.FORBIDDEN, "空命令", command=rendered)

        matched = [r for r in self.rules if r.matches(argv)]
        if not matched:
            if self.default_decision is Decision.ALLOW:
                return Evaluation(Decision.ALLOW, "", command=rendered)
            if self.default_decision is Decision.FORBIDDEN:
                return Evaluation(
                    Decision.FORBIDDEN,
                    f"`{rendered}` rejected: blocked by policy",
                    command=rendered,
                )
            return Evaluation(
                Decision.PROMPT,
                f"`{rendered}` requires approval by policy",
                command=rendered,
            )

        # 最长前缀获胜（Codex: most specific wins）
        best = max(matched, key=lambda r: r.specificity)
        if best.decision is Decision.FORBIDDEN:
            if best.justification:
                reason = f"`{rendered}` rejected: {best.justification}"
            else:
                prefix = _render(best.prefix)
                reason = (
                    f"`{rendered}` rejected: policy forbids commands starting with `{prefix}`"
                )
            return Evaluation(Decision.FORBIDDEN, reason, best.prefix, rendered)

        if best.decision is Decision.PROMPT:
            if best.justification:
                reason = f"`{rendered}` requires approval: {best.justification}"
            else:
                reason = f"`{rendered}` requires approval by policy"
            return Evaluation(Decision.PROMPT, reason, best.prefix, rendered)

        return Evaluation(Decision.ALLOW, "", best.prefix, rendered)


def default_policy_path(workdir: Path | str) -> Path:
    return Path(workdir).resolve() / ".clawd" / "exec_policy.json"

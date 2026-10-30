"""权限决策引擎 —— 三处源码级借鉴的合体

| 借鉴 | 来源 | 采纳的洞见 |
|:---|:---|:---|
| 会话级细粒度授权 | OpenCode `internal/permission/permission.go` | 授权按 (tool, action, 目录) 记住，同一会话内同类操作不再重复问 |
| 拒绝带理由回灌模型 | Codex `core/src/apply_patch.rs`、`exec_policy.rs` | 拒绝不是静默失败，返回 `` `tool` rejected: reason ``，模型据此换方案 |
| 写入边界（保护路径） | Pi `readonly-boundary.ts`（Windows 可移植部分） | 有些路径无论什么模式都不许写，且要说明为什么 |

注意：Pi 的 OS 级沙箱（bwrap / sandbox-exec）在 Windows 无原语，未采纳；
我们保留"Docker 沙箱 + 本模块的路径边界"作为等价防线。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

#: 权限结论的中文名（对外一律中文，避免用户看不懂 allow/deny/ask）
EFFECT_LABELS: dict[str, str] = {
    "allow": "放行",
    "deny": "拒绝",
    "ask": "需确认",
}


class Effect(str, Enum):
    """决策结果"""

    ALLOW = "allow"     # 放行
    DENY = "deny"       # 拒绝（带理由，回灌给模型）
    ASK = "ask"         # 需要人确认

    @property
    def label(self) -> str:
        return EFFECT_LABELS.get(self.value, self.value)


#: 任何模式下都不允许写入/执行的目标（相对项目根的 glob 片段）
PROTECTED_DIR_NAMES = (".git",)
PROTECTED_FILE_NAMES = (".clawd_host_port",)
PROTECTED_SUFFIXES = (".pem", ".key", ".pfx", ".p12")
PROTECTED_NAME_PREFIXES = ("id_rsa", "id_ed25519")


@dataclass(frozen=True)
class PermissionRequest:
    """一次工具调用的权限请求"""

    tool: str
    action: str  # read | write | exec
    path: str | None = None
    session_id: str = "default"
    command: str | None = None  # exec 类：待执行的命令（供命令前缀策略评估）

    @property
    def scope_dir(self) -> str:
        """授权的作用域目录（父目录；无路径时用空串）"""
        if not self.path:
            return ""
        try:
            return str(Path(self.path).expanduser().parent.resolve())
        except (OSError, RuntimeError):
            return str(Path(self.path).parent)


@dataclass(frozen=True)
class Decision:
    effect: Effect
    reason: str = ""
    #: 命令前缀策略的判决（allow / prompt / forbidden / ""）
    #: 挂机自决需要它来区分"策略允许但模式要问"与"策略要求审批"——两者天差地别
    policy: str = ""

    @property
    def allowed(self) -> bool:
        return self.effect is Effect.ALLOW


# ---------------------------------------------------------------------------
# 保护路径（Pi 的边界思路）
# ---------------------------------------------------------------------------


def protected_reason(path: str | None) -> str | None:
    """该路径是否受保护（受保护则返回理由，否则 None）

    只对**写入/执行**有意义的调用方使用；读取一律放行。
    """
    if not path:
        return None
    p = Path(path)
    parts = {part.lower() for part in p.parts}
    for name in PROTECTED_DIR_NAMES:
        if name in parts:
            return f"路径位于受保护的版本控制目录 {name}/ 内"
    if p.name.lower() in {n.lower() for n in PROTECTED_FILE_NAMES}:
        return f"{p.name} 含敏感运行时凭据，禁止由工具改写"
    if p.suffix.lower() in PROTECTED_SUFFIXES:
        return f"{p.suffix} 为密钥/证书类文件，禁止由工具改写"
    if p.name.lower().startswith(PROTECTED_NAME_PREFIXES):
        return f"{p.name} 为私钥文件，禁止由工具改写"
    return None


# ---------------------------------------------------------------------------
# 会话级授权（OpenCode 的 sessionPermissions）
# ---------------------------------------------------------------------------


@dataclass
class SessionGrants:
    """按 (tool, action, scope_dir) 记住的会话级授权

    OpenCode 的匹配键是 (tool_name, action, session_id, path_dir)——
    我们保留前三个：session_id 在本进程内由调用方区分即可。
    """

    _keys: set[tuple[str, str, str, str]] = field(default_factory=set)

    def grant(self, req: PermissionRequest) -> None:
        self._keys.add((req.session_id, req.tool, req.action, req.scope_dir))

    def matches(self, req: PermissionRequest) -> bool:
        return (req.session_id, req.tool, req.action, req.scope_dir) in self._keys

    def clear(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._keys.clear()
            return
        self._keys = {k for k in self._keys if k[0] != session_id}

    def __len__(self) -> int:
        return len(self._keys)


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------


@dataclass
class PermissionEngine:
    """把模式、保护路径、会话授权合成一个决策

    决策顺序（先硬后软）：
    1. read → 放行
    2. 保护路径 → 拒绝（任何模式，含 YOLO；理由回灌）
    3. 会话已授权 → 放行
    4. 其余 → 交给调用方按 ApprovalMode 询问
    """

    grants: SessionGrants = field(default_factory=SessionGrants)
    #: 命令前缀策略（exec 类；None 表示不评估）
    exec_policy: Any = None
    #: 是否禁止写保护路径（测试/特殊场景可关，但默认开）
    enforce_protected: bool = True
    #: YOLO 模式下是否仍守保护路径（默认守：密钥/版本库不该被模型改）
    protect_even_in_yolo: bool = True

    def decide(self, req: PermissionRequest, *, approval_mode: str = "default") -> Decision:
        if req.action == "read":
            return Decision(Effect.ALLOW, "只读操作")

        # 注意：这两个变量必须在策略分支**之前**初始化，否则后面会被重置成空值，
        # 导致"策略明确允许"的判决丢失（挂机自决就分不清 allow 与 prompt）
        exec_allowed_reason = ""
        exec_policy_verdict = ""

        # exec 类：过命令前缀策略（Codex execpolicy 语义，比"写/执行"分类更具体）
        if req.action == "exec" and self.exec_policy is not None and req.command:
            evaluation = self.exec_policy.evaluate(req.command)
            if evaluation.decision.value == "forbidden":
                return Decision(Effect.DENY, evaluation.reason, policy="forbidden")
            if evaluation.decision.value == "prompt":
                # 策略要求审批：跳过会话授权（命令级 prompt 每次确认更安全）
                return Decision(Effect.ASK, evaluation.reason, policy="prompt")
            # ALLOW 只表示"策略不禁止"，不越过 ApprovalMode 的询问语义
            #（否则 AUTO_EDIT/DEFAULT 下 echo 之类就永不再问，与既有契约冲突）
            exec_allowed_reason = evaluation.reason
            exec_policy_verdict = "allow"

        if self.enforce_protected:
            reason = protected_reason(req.path)
            if reason and (self.protect_even_in_yolo or approval_mode != "yolo"):
                return Decision(Effect.DENY, reason)

        if self.grants.matches(req):
            return Decision(
                Effect.ALLOW,
                exec_allowed_reason or "本会话内已授权同类操作",
                policy=exec_policy_verdict,
            )

        return Decision(Effect.ASK, exec_allowed_reason, policy=exec_policy_verdict)

    # ------------------------------------------------------------------
    @staticmethod
    def denial_message(req: PermissionRequest, reason: str) -> str:
        """Codex 风格的拒绝文案（会被当作工具错误回灌给模型）

        Codex 在 `apply_patch.rs` 里用 `patch rejected: {reason}`，
        `exec_policy.rs` 用 `` `cmd` rejected: {justification} ``。
        我们也让模型看到"什么被拒 + 为什么"，它才能换方案而不是重试。
        """
        # 已经是 Codex 风格文案（命令策略生成的）就直接用，避免 "rejected: ... rejected: ..."
        already_formatted = reason.startswith("`") and (
            " rejected:" in reason or " requires approval" in reason
        )
        if already_formatted:
            return reason
        target = f" `{req.path}`" if req.path else ""
        return f"`{req.tool}`{target} rejected: {reason}"

    def grant_session(self, req: PermissionRequest) -> None:
        self.grants.grant(req)

    def reset(self) -> None:
        self.grants.clear()


def extract_target_path(tool_args: dict | None) -> str | None:
    """从工具参数里提取目标路径（各家工具命名不一，按常见键依次尝试）"""
    if not tool_args:
        return None
    for key in ("path", "file_path", "filepath", "target", "filename", "file"):
        value = tool_args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # exec 类工具：没有路径概念，用 cwd 兜底
    cwd = tool_args.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return str(Path(cwd.strip()) / "_")
    return None


def extract_command(tool_args: dict | None) -> str | None:
    """从工具参数里提取待执行命令（BashTool 等用 command / cmd）"""
    if not tool_args:
        return None
    for key in ("command", "cmd", "script", "shell_command"):
        value = tool_args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def current_session_id() -> str:
    """进程内会话 id（供审计/授权隔离）"""
    return os.environ.get("CLAWD_SESSION_ID", "default")

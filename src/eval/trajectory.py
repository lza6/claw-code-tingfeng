"""轨迹录制 + 回放式回归（计划书 X-3）

记录一次 agent 运行的 ``(plan → action → observation → verify)`` 序列；回放时
固定 observation，只断言「工具调用序列 + 决策分支」不退化。

**零 LLM 调用、零网络**：只依赖标准库
（json / os / tempfile / contextlib / pathlib / dataclasses / datetime / typing）。

录制来源按项目**真实落盘结构**适配，不凭空设计字段：

1. ``.clawd/sessions/*.json`` 引擎格式（由 ``src/core/session_bridge.py`` 写入）::

       {"session_id": ..., "title": ..., "status": ...,
        "messages": [{"role": "user"|"assistant"|"tool",
                      "content": str, "timestamp": float,
                      "name"?: str, "ok"?: bool}],
        "metadata": {...}}

   - ``role="tool"`` → 一条 ``action`` + 一条 ``observation``；
     会话里**没有工具入参**，因此 ``action.payload["args"] = None`` 且
     ``args_known = False`` —— 不伪造参数。
   - ``role="user"`` → ``plan``（本轮指令）；``role="assistant"`` → ``plan``
     （决策/回复文本，payload 保留原始 role 以便区分）。
   - ``ok`` / ``name`` 缺失时写 ``None`` 并在 payload 打 ``*_unknown`` 标记。

2. ``AgentSession`` 结构（``src/agent/engine_session_data.py``）::

       {"goal": ..., "steps": [{"step_type": "plan|execute|verify|report|llm",
                                "action": str, "result": str, "success": bool}],
        "final_result": ..., "is_complete": bool}

   - ``execute`` → ``action``（action 字段）+ ``observation``（result 字段）；
   - ``plan`` → ``plan``；``verify`` → ``verify``；
   - ``report`` / ``llm`` → ``plan``，原始 ``step_type`` 保留在 payload 里；
   - 未知 step_type 同样落为 ``plan`` 并标 ``unknown_step_type``。

3. 旧格式（``src/core/session_store.py``，messages 是字符串）→ 记为 ``plan``，
   并标 ``payload["role_unknown"] = True``（旧格式没有 role，不能编一个）。

回放规则（每条规则判定的对象数计入 ``checked``）:

- ``tool_sequence``           提供 ``expect_tools`` 时，action 的工具名序列必须一致
                              （``expect_order=False`` 时按多重集比较）；
- ``action_observation_pair`` 每个 action 在下一个 action 之前必须有 observation；
- ``no_retry_after_failure``  失败后用**相同参数**重试同名工具即违规
                              （参数/失败状态未知时如实记为 undetermined，不判通过）；
- ``verify_present``          录制里有 verify 时：verify 不得失败，且最后一个 action
                              不得发生在最后一次 verify 之后。

**禁止空集合假绿**：一条规则都没判定（``checked == 0``）时 ``ok=False``，
并给出 ``rule="undetermined"`` 的失败项与 undetermined 明细。
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = 1

StepKind = Literal["plan", "action", "observation", "verify"]

_VALID_KINDS = frozenset({"plan", "action", "observation", "verify"})

RULE_TOOL_SEQUENCE = "tool_sequence"
RULE_ACTION_OBSERVATION = "action_observation_pair"
RULE_NO_RETRY = "no_retry_after_failure"
RULE_VERIFY = "verify_present"
RULE_UNDETERMINED = "undetermined"

#: AgentSession 的 step_type → 本模块的 Step.kind
_AGENT_STEP_KIND = {
    "plan": "plan",
    "execute": "action",
    "verify": "verify",
    "report": "plan",
    "llm": "plan",
}


class TrajectoryFormatError(ValueError):
    """轨迹数据/文件格式非法（消息为中文，便于 CLI 直接展示）"""


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class Step:
    """轨迹中的一步

    Attributes:
        kind: plan / action / observation / verify
        name: 工具名（仅 action/observation 通常有值），未知为 None
        payload: 结构化内容（原始字段原样保留 + 未知标记）
        ok: True/False 表示明确结果；None 表示会话里没有记录，**不补默认值**
        ts: ISO 8601 UTC 时间戳；无时间戳为 None
    """

    kind: StepKind
    name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    ok: bool | None = None
    ts: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "payload": dict(self.payload),
            "ok": self.ok,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, raw: Any, *, where: str) -> Step:
        if not isinstance(raw, dict):
            raise TrajectoryFormatError(f"{where} 必须是对象，实际是 {type(raw).__name__}")
        kind = raw.get("kind")
        if kind not in _VALID_KINDS:
            raise TrajectoryFormatError(
                f"{where} 的 kind 非法: {kind!r}（允许: {sorted(_VALID_KINDS)}）"
            )
        name = raw.get("name")
        if name is not None and not isinstance(name, str):
            raise TrajectoryFormatError(f"{where} 的 name 必须是字符串或 null")
        payload = raw.get("payload", {})
        if not isinstance(payload, dict):
            raise TrajectoryFormatError(f"{where} 的 payload 必须是对象")
        ok = raw.get("ok")
        if ok is not None and not isinstance(ok, bool):
            raise TrajectoryFormatError(f"{where} 的 ok 必须是布尔值或 null")
        ts = raw.get("ts")
        if ts is not None and not isinstance(ts, str):
            raise TrajectoryFormatError(f"{where} 的 ts 必须是字符串或 null")
        return cls(kind=kind, name=name, payload=dict(payload), ok=ok, ts=ts)


@dataclass
class Trajectory:
    """一条完整轨迹（可 JSON 往返）"""

    id: str
    goal: str
    steps: list[Step] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, raw: Any, *, source: str = "") -> Trajectory:
        where = f"轨迹{(' ' + source) if source else ''}"
        if not isinstance(raw, dict):
            raise TrajectoryFormatError(f"{where} 必须是 JSON 对象")
        for key in ("id", "goal", "steps"):
            if key not in raw:
                raise TrajectoryFormatError(f"{where} 缺少必需字段: {key}")
        traj_id, goal = raw["id"], raw["goal"]
        if not isinstance(traj_id, str) or not traj_id.strip():
            raise TrajectoryFormatError(f"{where} 的 id 必须是非空字符串")
        if not isinstance(goal, str):
            raise TrajectoryFormatError(f"{where} 的 goal 必须是字符串")
        raw_steps = raw["steps"]
        if not isinstance(raw_steps, list):
            raise TrajectoryFormatError(f"{where} 的 steps 必须是数组")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TrajectoryFormatError(f"{where} 的 metadata 必须是对象")
        version = raw.get("schema_version", SCHEMA_VERSION)
        if not isinstance(version, int) or isinstance(version, bool):
            raise TrajectoryFormatError(f"{where} 的 schema_version 必须是整数")
        if version > SCHEMA_VERSION:
            raise TrajectoryFormatError(
                f"{where} 的 schema_version={version} 高于当前支持的 {SCHEMA_VERSION}，"
                "请升级 clawd 后再读取"
            )
        steps = [
            Step.from_dict(item, where=f"{where} 的 steps[{idx}]")
            for idx, item in enumerate(raw_steps)
        ]
        return cls(
            id=traj_id,
            goal=goal,
            steps=steps,
            metadata=dict(metadata),
            schema_version=version,
        )


@dataclass
class ReplayResult:
    """回放判定结果

    Attributes:
        ok: 只有 ``checked > 0`` 且无 failures 才为 True
        checked: 真正被判定的规则/对象数量（0 表示什么都没判定）
        failures: ``[{"rule": ..., "detail": ...}]``
        undetermined: 无法判定（缺参数/缺数据）的规则明细，不冒充通过
    """

    ok: bool
    checked: int
    failures: list[dict[str, str]] = field(default_factory=list)
    undetermined: list[dict[str, str]] = field(default_factory=list)

    @property
    def failed_rules(self) -> list[str]:
        return [f["rule"] for f in self.failures]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "failures": list(self.failures),
            "undetermined": list(self.undetermined),
        }


# ---------------------------------------------------------------------------
# 录制
# ---------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _iso_ts(value: Any) -> str | None:
    """会话时间戳（float 秒）→ ISO 8601 UTC；字符串原样保留；缺失为 None"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        return value
    return None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def record_from_session(session: dict[str, Any]) -> Trajectory:
    """把会话数据（落盘结构或 AgentSession 结构）转成 Trajectory

    优先按 ``messages`` 解析（这是真正落盘的结构），其次按 ``steps``
    （AgentSession，运行期结构）。

    Raises:
        TrajectoryFormatError: 输入不是 dict，或既无 messages 也无 steps
    """
    if not isinstance(session, dict):
        raise TrajectoryFormatError(
            f"会话数据必须是 dict，实际是 {type(session).__name__}"
        )
    if isinstance(session.get("messages"), list):
        return _record_from_messages(session)
    if isinstance(session.get("steps"), list):
        return _record_from_agent_steps(session)
    raise TrajectoryFormatError("会话数据既没有 messages 也没有 steps，无法录制轨迹")


def _record_from_messages(session: dict[str, Any]) -> Trajectory:
    messages: list[Any] = session["messages"]
    meta_in = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}

    steps: list[Step] = []
    skipped = 0
    role_unknown = 0
    tool_missing_name = 0
    tool_missing_ok = 0
    goal = ""
    goal_source = "unknown"

    for idx, raw in enumerate(messages):
        if isinstance(raw, str):
            steps.append(
                Step(
                    kind="plan",
                    payload={
                        "role": "unknown",
                        "content": raw,
                        "role_unknown": True,
                        "index": idx,
                    },
                )
            )
            role_unknown += 1
            continue
        if not isinstance(raw, dict):
            skipped += 1
            continue

        role = _text(raw.get("role")) or "unknown"
        content = _text(raw.get("content"))
        ts = _iso_ts(raw.get("timestamp"))

        if role == "tool":
            name = _text(raw.get("name"))
            ok = _bool_or_none(raw.get("ok"))
            if name is None:
                tool_missing_name += 1
            if ok is None:
                tool_missing_ok += 1
            action_payload: dict[str, Any] = {
                "tool": name,
                "args": None,
                "args_known": False,
                "source": "session.messages",
                "index": idx,
            }
            if name is None:
                action_payload["tool_name_unknown"] = True
            if ok is None:
                action_payload["ok_unknown"] = True
            obs_payload: dict[str, Any] = {"content": content, "index": idx}
            if content is None:
                obs_payload["content_unknown"] = True
            if ok is None:
                obs_payload["ok_unknown"] = True
            steps.append(Step(kind="action", name=name, payload=action_payload, ok=ok, ts=ts))
            steps.append(
                Step(kind="observation", name=name, payload=obs_payload, ok=ok, ts=ts)
            )
            continue

        plan_payload: dict[str, Any] = {"role": role, "content": content, "index": idx}
        if content is None:
            plan_payload["content_unknown"] = True
        if role not in ("user", "assistant", "system"):
            plan_payload["role_unknown"] = True
            role_unknown += 1
        steps.append(Step(kind="plan", payload=plan_payload, ts=ts))

        if role == "user" and not goal and content:
            goal = content
            goal_source = "first_user_message"

    if not goal:
        title = _text(session.get("title"))
        if title:
            goal, goal_source = title, "title"

    session_id = _text(session.get("session_id")) or _text(session.get("id"))
    metadata: dict[str, Any] = {
        "source_format": "messages",
        "session_id": session_id,
        "session_title": _text(session.get("title")),
        "status": _text(session.get("status")),
        "model": _text(meta_in.get("model")),
        "provider": _text(meta_in.get("provider")),
        "created_at": session.get("created_at"),
        "message_count": len(messages),
        "action_count": sum(1 for s in steps if s.kind == "action"),
        "observation_count": sum(1 for s in steps if s.kind == "observation"),
        "goal_source": goal_source,
        "skipped_non_mapping": skipped,
        "role_unknown_count": role_unknown,
        "tool_missing_name": tool_missing_name,
        "tool_missing_ok": tool_missing_ok,
    }
    if session_id is None:
        metadata["id_unknown"] = True
    return Trajectory(
        id=session_id or "unknown-session",
        goal=goal,
        steps=steps,
        metadata=metadata,
    )


def _record_from_agent_steps(session: dict[str, Any]) -> Trajectory:
    raw_steps: list[Any] = session["steps"]
    steps: list[Step] = []
    skipped = 0
    unknown_types: list[str] = []

    for idx, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            skipped += 1
            continue
        step_type = _text(raw.get("step_type")) or "unknown"
        action = _text(raw.get("action")) or ""
        result = _text(raw.get("result")) or ""
        ok = _bool_or_none(raw.get("success"))

        if step_type == "execute":
            steps.append(
                Step(
                    kind="action",
                    payload={
                        "tool": None,
                        "action": action,
                        "args": None,
                        "args_known": False,
                        "source": "agent_session.steps",
                        "index": idx,
                    },
                    ok=ok,
                )
            )
            steps.append(
                Step(
                    kind="observation",
                    payload={"content": result, "index": idx},
                    ok=ok,
                )
            )
            continue

        kind = _AGENT_STEP_KIND.get(step_type)
        if kind is None:
            unknown_types.append(step_type)
            kind = "plan"
        payload: dict[str, Any] = {
            "role": "agent",
            "step_type": step_type,
            "content": result or action,
            "action": action,
            "index": idx,
        }
        if step_type not in _AGENT_STEP_KIND:
            payload["unknown_step_type"] = step_type
        steps.append(Step(kind=kind, payload=payload, ok=ok))

    goal = _text(session.get("goal")) or ""
    goal_source = "goal" if goal else "unknown"
    metadata: dict[str, Any] = {
        "source_format": "agent_steps",
        "session_id": _text(session.get("session_id")),
        "step_count": len(raw_steps),
        "action_count": sum(1 for s in steps if s.kind == "action"),
        "observation_count": sum(1 for s in steps if s.kind == "observation"),
        "verify_count": sum(1 for s in steps if s.kind == "verify"),
        "is_complete": session.get("is_complete"),
        "goal_source": goal_source,
        "skipped_non_mapping": skipped,
        "unknown_step_types": unknown_types,
    }
    if metadata["session_id"] is None:
        metadata["id_unknown"] = True
    return Trajectory(
        id=_text(session.get("session_id")) or "unknown-session",
        goal=goal,
        steps=steps,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------


def save_trajectory(traj: Trajectory, path: str | Path) -> Path:
    """原子写入 JSON（utf-8、ensure_ascii=False、同目录临时文件 + os.replace）"""
    if not isinstance(traj, Trajectory):
        raise TrajectoryFormatError(
            f"save_trajectory 需要 Trajectory 对象，实际是 {type(traj).__name__}"
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(traj.to_dict(), ensure_ascii=False, indent=2)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return target


def trajectory_from_dict(raw: Any, *, source: str = "") -> Trajectory:
    """从已解析的 JSON 对象构造 Trajectory（严格校验，中文错误）"""
    return Trajectory.from_dict(raw, source=source)


def load_trajectory(path: str | Path) -> Trajectory:
    """读取轨迹文件

    Raises:
        TrajectoryFormatError: 文件不存在 / 不是合法 JSON / 字段不合规
    """
    target = Path(path)
    if not target.is_file():
        raise TrajectoryFormatError(f"轨迹文件不存在: {target}")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise TrajectoryFormatError(f"轨迹文件无法解析: {target}: {e}") from e
    return Trajectory.from_dict(raw, source=str(target))


# ---------------------------------------------------------------------------
# 回放断言
# ---------------------------------------------------------------------------


def _tool_label(step: Step) -> str:
    return step.name if step.name else "<unknown>"


def _args(step: Step) -> tuple[Any, bool]:
    payload = step.payload or {}
    known = bool(payload.get("args_known")) and isinstance(payload.get("args"), dict)
    return payload.get("args"), known


def _first_diff(expected: list[str], actual: list[str]) -> str:
    limit = min(len(expected), len(actual))
    for idx in range(limit):
        if expected[idx] != actual[idx]:
            return f"首个差异在第 {idx + 1} 步: 期望 {expected[idx]!r} 实际 {actual[idx]!r}"
    if len(expected) != len(actual):
        return f"步数不一致: 期望 {len(expected)} 实际 {len(actual)}"
    return ""


def replay(
    traj: Trajectory,
    *,
    expect_tools: list[str] | None = None,
    expect_order: bool = True,
) -> ReplayResult:
    """回放轨迹并断言（固定 observation，零 LLM/网络）

    Args:
        traj: 待回放轨迹（通常来自 load_trajectory / record_from_session）
        expect_tools: 期望的工具名序列；None 表示不判定序列（不会拿录制序列
            自己跟自己比来冒充通过）
        expect_order: True 按顺序比较；False 按多重集比较（只关心调了哪些工具）

    Returns:
        ReplayResult；``checked == 0`` 时 ``ok=False`` 并给出 undetermined
    """
    if not isinstance(traj, Trajectory):
        raise TrajectoryFormatError(
            f"replay 需要 Trajectory 对象，实际是 {type(traj).__name__}"
        )

    checked = 0
    failures: list[dict[str, str]] = []
    undetermined: list[dict[str, str]] = []

    # 空轨迹（一条步骤都没有）永远不给结论：``expect_tools=[]`` 会与"零个 action"
    # 互相印证成绿 —— 那是"没录制到任何东西"，不是"没有多余工具调用"。
    if not traj.steps:
        undetermined = [
            {"rule": rule, "detail": "轨迹里没有任何步骤（空轨迹），无法判定"}
            for rule in (RULE_TOOL_SEQUENCE, RULE_ACTION_OBSERVATION, RULE_NO_RETRY, RULE_VERIFY)
        ]
        undetermined.append(
            {
                "rule": RULE_UNDETERMINED,
                "detail": "轨迹里没有任何步骤（空轨迹），无法判定任何规则",
            }
        )
        return ReplayResult(
            ok=False,
            checked=0,
            failures=[
                {
                    "rule": RULE_UNDETERMINED,
                    "detail": "没有任何规则被判定（checked=0），拒绝给出通过；未判定原因: 轨迹里没有任何步骤（空轨迹）",
                }
            ],
            undetermined=undetermined,
        )

    actions = [(idx, step) for idx, step in enumerate(traj.steps) if step.kind == "action"]

    # 规则 1：工具序列
    if expect_tools is None:
        undetermined.append(
            {
                "rule": RULE_TOOL_SEQUENCE,
                "detail": "未提供 expect_tools，无法判定工具序列是否退化（不回显录制序列冒充断言）",
            }
        )
    else:
        checked += 1
        expected = [str(name) for name in expect_tools]
        actual = [_tool_label(step) for _, step in actions]
        if expect_order:
            matched = actual == expected
        else:
            matched = Counter(actual) == Counter(expected)
        if not matched:
            suffix = f"（{_first_diff(expected, actual)}）" if expect_order else "（多重集不一致）"
            failures.append(
                {
                    "rule": RULE_TOOL_SEQUENCE,
                    "detail": f"工具序列退化: 期望 {expected} 实际 {actual}{suffix}",
                }
            )

    # 规则 2：每个 action 后、下一个 action 前必须有 observation
    if not actions:
        undetermined.append(
            {
                "rule": RULE_ACTION_OBSERVATION,
                "detail": "轨迹中没有 action 步骤，无法判定 action/observation 配对",
            }
        )
    else:
        for pos, (idx, step) in enumerate(actions):
            next_idx = actions[pos + 1][0] if pos + 1 < len(actions) else len(traj.steps)
            has_obs = any(
                traj.steps[j].kind == "observation" for j in range(idx + 1, next_idx)
            )
            checked += 1
            if not has_obs:
                failures.append(
                    {
                        "rule": RULE_ACTION_OBSERVATION,
                        "detail": (
                            f"第 {pos + 1} 个 action（{_tool_label(step)}，步骤索引 {idx}）"
                            "之后没有 observation"
                        ),
                    }
                )

    # 规则 3：失败后不得用相同参数原地重试
    judged_pairs = 0
    unknown_pairs = 0
    for pos in range(len(actions) - 1):
        (prev_idx, prev_step), (next_idx, next_step) = actions[pos], actions[pos + 1]
        if _tool_label(prev_step) != _tool_label(next_step):
            judged_pairs += 1  # 不同工具，明确不是"原地重试"
            continue
        if prev_step.ok is True:
            judged_pairs += 1  # 上一次成功，不存在"失败后重试"
            continue
        if prev_step.ok is None:
            unknown_pairs += 1
            continue
        prev_args, prev_known = _args(prev_step)
        next_args, next_known = _args(next_step)
        if not (prev_known and next_known):
            unknown_pairs += 1
            continue
        judged_pairs += 1
        if prev_args == next_args:
            failures.append(
                {
                    "rule": RULE_NO_RETRY,
                    "detail": (
                        f"失败后用相同参数重试: 工具 {_tool_label(prev_step)} "
                        f"参数 {prev_args}（步骤 {prev_idx} 失败 → 步骤 {next_idx} 重试）"
                    ),
                }
            )

    if judged_pairs:
        checked += judged_pairs
    if unknown_pairs:
        undetermined.append(
            {
                "rule": RULE_NO_RETRY,
                "detail": (
                    f"{unknown_pairs} 对连续同名 action 缺少失败状态或工具参数，"
                    "无法判定是否原地重试（不判为通过）"
                ),
            }
        )
    if not judged_pairs and not unknown_pairs:
        undetermined.append(
            {
                "rule": RULE_NO_RETRY,
                "detail": "连续 action 少于 2 个，无法判定重试行为",
            }
        )

    # 规则 4：verify 覆盖（只有录制里有 verify 才判定）
    verify_idx = [idx for idx, step in enumerate(traj.steps) if step.kind == "verify"]
    if not verify_idx:
        undetermined.append(
            {
                "rule": RULE_VERIFY,
                "detail": "录制中没有 verify 步骤，无法判定验证覆盖",
            }
        )
    else:
        checked += 1
        failed_verify = [idx for idx in verify_idx if traj.steps[idx].ok is False]
        last_action_idx = actions[-1][0] if actions else -1
        if failed_verify:
            failures.append(
                {
                    "rule": RULE_VERIFY,
                    "detail": f"verify 步骤记录为失败（步骤索引 {failed_verify}）",
                }
            )
        elif last_action_idx > verify_idx[-1]:
            failures.append(
                {
                    "rule": RULE_VERIFY,
                    "detail": (
                        f"最后一个 action（索引 {last_action_idx}）发生在最后一次 verify"
                        f"（索引 {verify_idx[-1]}）之后，验证未覆盖后续动作"
                    ),
                }
            )

    if checked == 0:
        detail = "没有任何规则被判定（checked=0），拒绝给出通过"
        if undetermined:
            detail += "；未判定原因: " + "；".join(item["detail"] for item in undetermined)
        failures.append({"rule": RULE_UNDETERMINED, "detail": detail})

    return ReplayResult(
        ok=checked > 0 and not failures,
        checked=checked,
        failures=failures,
        undetermined=undetermined,
    )

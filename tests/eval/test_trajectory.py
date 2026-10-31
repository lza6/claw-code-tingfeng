"""轨迹录制 + 回放式回归测试（计划书 X-3）

全部离线：不发起任何 LLM/网络调用，只用标准库 + pytest。
会话样例按项目真实落盘结构构造（``.clawd/sessions/*.json`` 引擎格式，
见 ``src/core/session_bridge.py::persist_agent_session``）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.eval import (
    ReplayResult,
    Step,
    Trajectory,
    TrajectoryFormatError,
    load_trajectory,
    record_from_session,
    replay,
    save_trajectory,
)
from src.eval.trajectory import SCHEMA_VERSION, StepKind, trajectory_from_dict


def _session(messages: list[dict], **extra) -> dict:
    """构造引擎格式会话（字段名与 .clawd/sessions 真实落盘一致）"""
    payload = {
        "session_id": "sess-test",
        "user_id": None,
        "title": "读 README 后总结",
        "status": "completed",
        "messages": messages,
        "created_at": 1793311030.0350912,
        "updated_at": 1793311030.0350912,
        "metadata": {
            "input_tokens": 999,
            "output_tokens": 12,
            "total_cost": 0.0,
            "turn_count": 1,
            "parent_session_id": "",
            "summary_message_id": "",
            "model": "test-model",
            "provider": "openai",
        },
    }
    payload.update(extra)
    return payload


def _msg(role: str, content: str, **extra) -> dict:
    message = {"role": role, "content": content, "timestamp": 1793311030.0350912}
    message.update(extra)
    return message


def _full_session() -> dict:
    return _session([
        _msg("user", "读 README 后总结"),
        _msg("tool", "内容", name="FileReadTool", ok=True),
        _msg("tool", "Error: failed", name="BashTool", ok=False),
        _msg("assistant", "完成"),
    ])


# ==========================================================================
# 录制：真实会话结构 → steps
# ==========================================================================


class TestRecordFromSession:
    def test_steps_count_and_order_are_exact(self):
        traj = record_from_session(_full_session())

        assert [s.kind for s in traj.steps] == [
            "plan",  # user
            "action",  # tool 1
            "observation",  # tool 1 结果
            "action",  # tool 2
            "observation",  # tool 2 结果
            "plan",  # assistant
        ]
        assert [s.name for s in traj.steps if s.kind == "action"] == ["FileReadTool", "BashTool"]
        assert [s.ok for s in traj.steps if s.kind == "observation"] == [True, False]

    def test_tool_message_becomes_action_plus_observation(self):
        traj = record_from_session(_session([
            _msg("user", "g"),
            _msg("tool", "ok-text", name="FileReadTool", ok=True),
        ]))

        action = next(s for s in traj.steps if s.kind == "action")
        obs = next(s for s in traj.steps if s.kind == "observation")
        assert action.name == "FileReadTool" and action.ok is True
        assert obs.name == "FileReadTool" and obs.ok is True
        assert obs.payload["content"] == "ok-text"
        # 会话里没有工具入参 → 不伪造
        assert action.payload["args"] is None
        assert action.payload["args_known"] is False

    def test_goal_comes_from_first_user_message(self):
        traj = record_from_session(_full_session())

        assert traj.goal == "读 README 后总结"
        assert traj.metadata["goal_source"] == "first_user_message"
        assert traj.id == "sess-test"
        assert traj.schema_version == SCHEMA_VERSION

    def test_timestamps_converted_to_iso8601(self):
        traj = record_from_session(_full_session())

        plan = traj.steps[0]
        assert plan.ts is not None
        assert plan.ts.startswith("20") and "T" in plan.ts

    def test_missing_fields_are_tolerated_and_marked_unknown(self):
        traj = record_from_session(_session([
            _msg("user", "g"),
            {"role": "tool", "content": "x"},  # 缺 name / ok / timestamp
            {"role": "mystery", "content": "?"},  # 未知 role
        ]))

        action = next(s for s in traj.steps if s.kind == "action")
        assert action.name is None
        assert action.ok is None
        assert action.payload["tool_name_unknown"] is True
        assert action.payload["ok_unknown"] is True
        assert traj.metadata["tool_missing_name"] == 1
        assert traj.metadata["tool_missing_ok"] == 1
        assert traj.metadata["role_unknown_count"] >= 1

    def test_legacy_string_messages_recorded_as_unknown_plan(self):
        traj = record_from_session({
            "session_id": "legacy-1",
            "messages": ["hello", "world"],
            "input_tokens": 3,
        })

        assert [s.kind for s in traj.steps] == ["plan", "plan"]
        assert all(s.payload["role_unknown"] is True for s in traj.steps)
        assert traj.metadata["role_unknown_count"] == 2
        assert traj.metadata["source_format"] == "messages"

    def test_agent_session_steps_structure(self):
        traj = record_from_session({
            "session_id": "agent-1",
            "goal": "修 bug",
            "steps": [
                {"step_type": "plan", "action": "plan", "result": "先读文件", "success": True},
                {"step_type": "execute", "action": "FileReadTool", "result": "内容", "success": True},
                {"step_type": "verify", "action": "pytest", "result": "1 passed", "success": True},
                {"step_type": "report", "action": "report", "result": "完成", "success": True},
            ],
            "is_complete": True,
        })

        assert [s.kind for s in traj.steps] == [
            "plan", "action", "observation", "verify", "plan",
        ]
        assert traj.metadata["source_format"] == "agent_steps"
        assert traj.metadata["verify_count"] == 1
        assert traj.goal == "修 bug"

    def test_invalid_input_raises_chinese_error(self):
        with pytest.raises(TrajectoryFormatError, match="既没有 messages 也没有 steps"):
            record_from_session({"session_id": "x"})
        with pytest.raises(TrajectoryFormatError, match="必须是 dict"):
            record_from_session(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_unknown_step_type_falls_back_to_plan_and_is_marked(self):
        traj = record_from_session({
            "session_id": "agent-2",
            "goal": "g",
            "steps": [
                {"step_type": "teleport", "action": "x", "result": "y", "success": None},
            ],
        })

        assert [s.kind for s in traj.steps] == ["plan"]
        assert traj.steps[0].payload["unknown_step_type"] == "teleport"
        assert traj.steps[0].ok is None
        assert traj.metadata["unknown_step_types"] == ["teleport"]

    def test_non_mapping_entries_are_counted_not_invented(self):
        traj = record_from_session(_session([
            _msg("user", "g"),
            42,  # 无法映射
            _msg("tool", "x", name="FileReadTool", ok=True),
        ]))

        assert traj.metadata["skipped_non_mapping"] == 1
        assert [s.kind for s in traj.steps] == ["plan", "action", "observation"]

    def test_goal_falls_back_to_title(self):
        traj = record_from_session({
            "session_id": "no-user",
            "title": "来自标题的目标",
            "messages": [_msg("assistant", "直接回答")],
        })

        assert traj.goal == "来自标题的目标"
        assert traj.metadata["goal_source"] == "title"

    def test_missing_session_id_is_unknown_not_invented(self):
        traj = record_from_session({"messages": [_msg("user", "g")]})

        assert traj.id == "unknown-session"
        assert traj.metadata["id_unknown"] is True

    def test_string_timestamp_is_preserved(self):
        traj = record_from_session(_session([
            _msg("user", "g", timestamp="2026-10-31T00:00:00+00:00"),
        ]))

        assert traj.steps[0].ts == "2026-10-31T00:00:00+00:00"

    def test_unusable_timestamps_become_none(self):
        traj = record_from_session(_session([
            _msg("user", "g", timestamp=True),
            _msg("user", "g2", timestamp=1e30),
            _msg("user", "g3", timestamp="   "),
            _msg("user", "g4", timestamp=None),
        ]))

        assert [s.ts for s in traj.steps] == [None, None, None, None]

    def test_missing_content_is_marked_unknown(self):
        traj = record_from_session(_session([
            {"role": "user"},
            {"role": "tool", "name": "FileReadTool", "ok": True},
        ]))

        plan = traj.steps[0]
        action = next(s for s in traj.steps if s.kind == "action")
        obs = next(s for s in traj.steps if s.kind == "observation")
        assert plan.payload["content_unknown"] is True
        assert obs.payload["content_unknown"] is True
        assert action.payload["args_known"] is False

    def test_agent_steps_non_mapping_and_missing_id(self):
        traj = record_from_session({
            "steps": [
                "not-a-dict",
                {"step_type": "plan", "action": "a", "result": "r", "success": True},
            ],
        })

        assert traj.metadata["skipped_non_mapping"] == 1
        assert traj.metadata["id_unknown"] is True
        assert traj.id == "unknown-session"
        assert traj.goal == ""
        assert traj.metadata["goal_source"] == "unknown"


# ==========================================================================
# 持久化：JSON 往返
# ==========================================================================


class TestPersistence:
    def test_roundtrip_preserves_fields(self, tmp_path: Path):
        traj = record_from_session(_full_session())
        path = save_trajectory(traj, tmp_path / "t.json")

        loaded = load_trajectory(path)

        assert loaded.id == traj.id
        assert loaded.goal == traj.goal
        assert loaded.schema_version == traj.schema_version
        assert loaded.metadata == traj.metadata
        assert [s.to_dict() for s in loaded.steps] == [s.to_dict() for s in traj.steps]

    def test_saved_file_is_utf8_without_ascii_escape(self, tmp_path: Path):
        traj = record_from_session(_full_session())
        path = save_trajectory(traj, tmp_path / "t.json")

        text = path.read_text(encoding="utf-8")
        assert "读 README 后总结" in text
        assert "\\u" not in text

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        traj = record_from_session(_full_session())
        path = save_trajectory(traj, tmp_path / "a" / "b" / "t.json")

        assert path.is_file()

    def test_save_is_atomic_no_tmp_leftover(self, tmp_path: Path):
        traj = record_from_session(_full_session())
        save_trajectory(traj, tmp_path / "t.json")

        assert [p.name for p in tmp_path.iterdir()] == ["t.json"]

    def test_save_failure_cleans_tmp_and_propagates(self, tmp_path: Path, monkeypatch):
        import src.eval.trajectory as tj

        traj = record_from_session(_full_session())

        def _boom(*_a, **_k):
            raise OSError("磁盘满")

        monkeypatch.setattr(tj.os, "replace", _boom)

        with pytest.raises(OSError, match="磁盘满"):
            save_trajectory(traj, tmp_path / "t.json")
        # 临时文件必须清掉，不能留下半成品
        assert list(tmp_path.iterdir()) == []

    def test_save_overwrites_existing_file(self, tmp_path: Path):
        target = tmp_path / "t.json"
        save_trajectory(record_from_session(_full_session()), target)
        first = target.read_text(encoding="utf-8")

        shorter = Trajectory(id="other", goal="短", steps=[])
        save_trajectory(shorter, target)

        assert target.read_text(encoding="utf-8") != first
        assert load_trajectory(target).id == "other"

    def test_load_missing_file_raises_chinese(self, tmp_path: Path):
        with pytest.raises(TrajectoryFormatError, match="轨迹文件不存在"):
            load_trajectory(tmp_path / "nope.json")

    def test_load_broken_json_raises_chinese(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{oops", encoding="utf-8")

        with pytest.raises(TrajectoryFormatError, match="无法解析"):
            load_trajectory(bad)

    def test_swapped_step_name_type_raises_chinese(self):
        with pytest.raises(TrajectoryFormatError, match="name 必须是字符串或 null"):
            trajectory_from_dict(
                {"id": "x", "goal": "g", "steps": [{"kind": "plan", "name": 1}]}
            )

    def test_swapped_step_ts_type_raises_chinese(self):
        with pytest.raises(TrajectoryFormatError, match="ts 必须是字符串或 null"):
            trajectory_from_dict(
                {"id": "x", "goal": "g", "steps": [{"kind": "plan", "ts": 123}]}
            )

    def test_goal_type_raises_chinese(self):
        with pytest.raises(TrajectoryFormatError, match="goal 必须是字符串"):
            trajectory_from_dict({"id": "x", "goal": 5, "steps": []})

    def test_save_rejects_non_trajectory(self, tmp_path: Path):
        with pytest.raises(TrajectoryFormatError, match="需要 Trajectory 对象"):
            save_trajectory({"id": "x"}, tmp_path / "t.json")  # type: ignore[arg-type]

    def test_replay_rejects_non_trajectory(self):
        with pytest.raises(TrajectoryFormatError, match="需要 Trajectory 对象"):
            replay({"id": "x"})  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("payload", "needle"),
        [
            ({"goal": "g", "steps": []}, "缺少必需字段: id"),
            ({"id": "x", "steps": []}, "缺少必需字段: goal"),
            ({"id": "x", "goal": "g"}, "缺少必需字段: steps"),
            ({"id": "", "goal": "g", "steps": []}, "id 必须是非空字符串"),
            ({"id": "x", "goal": "g", "steps": {}}, "steps 必须是数组"),
            ({"id": "x", "goal": "g", "steps": [], "metadata": []}, "metadata 必须是对象"),
            (
                {"id": "x", "goal": "g", "steps": [], "schema_version": "1"},
                "schema_version 必须是整数",
            ),
            (
                {"id": "x", "goal": "g", "steps": [], "schema_version": 99},
                "高于当前支持的",
            ),
            (
                {"id": "x", "goal": "g", "steps": [{"kind": "bogus"}]},
                "kind 非法",
            ),
            (
                {"id": "x", "goal": "g", "steps": [{"kind": "action", "ok": "yes"}]},
                "ok 必须是布尔值或 null",
            ),
            (
                {"id": "x", "goal": "g", "steps": [{"kind": "action", "payload": []}]},
                "payload 必须是对象",
            ),
            ({"id": "x", "goal": "g", "steps": ["not-a-dict"]}, "必须是对象"),
        ],
    )
    def test_invalid_payloads_raise_chinese_errors(self, payload, needle):
        with pytest.raises(TrajectoryFormatError, match=needle):
            trajectory_from_dict(payload)

    def test_non_object_json_raises(self, tmp_path: Path):
        bad = tmp_path / "list.json"
        bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        with pytest.raises(TrajectoryFormatError, match="必须是 JSON 对象"):
            load_trajectory(bad)


# ==========================================================================
# 回放断言
# ==========================================================================


def _traj(steps: list[Step], *, goal: str = "g") -> Trajectory:
    return Trajectory(id="t", goal=goal, steps=steps)


def _action(name: str, ok: bool | None, *, args: dict | None = None) -> Step:
    known = args is not None
    return Step(
        kind="action",
        name=name,
        payload={"tool": name, "args": args, "args_known": known},
        ok=ok,
    )


def _obs(name: str, ok: bool | None = True) -> Step:
    return Step(kind="observation", name=name, payload={"content": "r"}, ok=ok)


class TestReplayToolSequence:
    def test_matching_sequence_passes(self):
        traj = _traj([
            _action("FileReadTool", True), _obs("FileReadTool"),
            _action("FileEditTool", True), _obs("FileEditTool"),
        ])

        result = replay(traj, expect_tools=["FileReadTool", "FileEditTool"])

        assert isinstance(result, ReplayResult)
        assert result.ok is True
        assert result.checked > 0
        assert result.failures == []
        assert "tool_sequence" not in result.failed_rules

    def test_degraded_sequence_fails_with_named_rule(self):
        traj = _traj([
            _action("FileEditTool", True), _obs("FileEditTool"),
            _action("FileReadTool", True), _obs("FileReadTool"),
        ])

        result = replay(traj, expect_tools=["FileReadTool", "FileEditTool"])

        assert result.ok is False
        assert "tool_sequence" in result.failed_rules
        detail = next(f["detail"] for f in result.failures if f["rule"] == "tool_sequence")
        assert "首个差异在第 1 步" in detail

    def test_extra_tool_call_fails(self):
        traj = _traj([
            _action("FileReadTool", True), _obs("FileReadTool"),
            _action("BashTool", True), _obs("BashTool"),
        ])

        result = replay(traj, expect_tools=["FileReadTool"])

        assert result.ok is False
        assert "tool_sequence" in result.failed_rules

    def test_order_insensitive_compares_multiset(self):
        traj = _traj([
            _action("BashTool", True), _obs("BashTool"),
            _action("FileReadTool", True), _obs("FileReadTool"),
        ])

        ordered = replay(traj, expect_tools=["FileReadTool", "BashTool"])
        unordered = replay(traj, expect_tools=["FileReadTool", "BashTool"], expect_order=False)

        assert ordered.ok is False
        assert unordered.ok is True


class TestReplayObservationPairing:
    def test_action_without_observation_fails(self):
        traj = _traj([
            _action("FileReadTool", True), _obs("FileReadTool"),
            _action("BashTool", True),  # 没有 observation
        ])

        result = replay(traj, expect_tools=["FileReadTool", "BashTool"])

        assert result.ok is False
        assert "action_observation_pair" in result.failed_rules
        detail = next(
            f["detail"] for f in result.failures if f["rule"] == "action_observation_pair"
        )
        assert "BashTool" in detail


class TestReplayNoRetry:
    def test_same_args_retry_after_failure_fails(self):
        traj = _traj([
            _action("BashTool", False, args={"command": "pytest"}), _obs("BashTool", False),
            _action("BashTool", False, args={"command": "pytest"}), _obs("BashTool", False),
        ])

        result = replay(traj, expect_tools=["BashTool", "BashTool"])

        assert result.ok is False
        assert "no_retry_after_failure" in result.failed_rules

    def test_retry_with_changed_args_is_allowed(self):
        traj = _traj([
            _action("BashTool", False, args={"command": "pytest"}), _obs("BashTool", False),
            _action("BashTool", True, args={"command": "pytest -x"}), _obs("BashTool", True),
        ])

        result = replay(traj, expect_tools=["BashTool", "BashTool"])

        assert result.ok is True
        assert "no_retry_after_failure" not in result.failed_rules

    def test_retry_after_success_is_not_a_violation(self):
        traj = _traj([
            _action("BashTool", True, args={"command": "ls"}), _obs("BashTool", True),
            _action("BashTool", True, args={"command": "ls"}), _obs("BashTool", True),
        ])

        result = replay(traj, expect_tools=["BashTool", "BashTool"])

        assert result.ok is True

    def test_unknown_args_are_undetermined_not_pass(self):
        """真实会话不带工具入参 → 不能判"没有重试"，也不能判通过"""
        traj = _traj([
            _action("BashTool", False), _obs("BashTool", False),
            _action("BashTool", False), _obs("BashTool", False),
        ])

        result = replay(traj, expect_tools=["BashTool", "BashTool"])

        assert "no_retry_after_failure" not in result.failed_rules
        rules = [u["rule"] for u in result.undetermined]
        assert "no_retry_after_failure" in rules
        detail = next(u["detail"] for u in result.undetermined if u["rule"] == "no_retry_after_failure")
        assert "无法判定是否原地重试" in detail

    def test_unknown_previous_status_is_undetermined(self):
        traj = _traj([
            _action("BashTool", None, args={"command": "ls"}), _obs("BashTool", None),
            _action("BashTool", None, args={"command": "ls"}), _obs("BashTool", None),
        ])

        result = replay(traj, expect_tools=["BashTool", "BashTool"])

        assert "no_retry_after_failure" not in result.failed_rules
        detail = next(u["detail"] for u in result.undetermined if u["rule"] == "no_retry_after_failure")
        assert "缺少失败状态" in detail


class TestReplayVerify:
    def test_missing_verify_is_reported_undetermined(self):
        traj = _traj([_action("FileReadTool", True), _obs("FileReadTool")])

        result = replay(traj, expect_tools=["FileReadTool"])

        assert result.ok is True
        assert "verify_present" in [u["rule"] for u in result.undetermined]

    def test_failed_verify_fails(self):
        traj = _traj([
            _action("FileEditTool", True), _obs("FileEditTool"),
            Step(kind="verify", name="pytest", payload={"content": "1 failed"}, ok=False),
        ])

        result = replay(traj, expect_tools=["FileEditTool"])

        assert result.ok is False
        assert "verify_present" in result.failed_rules

    def test_action_after_verify_fails(self):
        traj = _traj([
            Step(kind="verify", name="pytest", payload={"content": "ok"}, ok=True),
            _action("FileEditTool", True), _obs("FileEditTool"),
        ])

        result = replay(traj, expect_tools=["FileEditTool"])

        assert result.ok is False
        detail = next(f["detail"] for f in result.failures if f["rule"] == "verify_present")
        assert "验证未覆盖后续动作" in detail

    def test_verify_covering_all_actions_passes(self):
        traj = _traj([
            _action("FileEditTool", True), _obs("FileEditTool"),
            Step(kind="verify", name="pytest", payload={"content": "passed"}, ok=True),
        ])

        result = replay(traj, expect_tools=["FileEditTool"])

        assert result.ok is True
        assert result.failures == []


class TestReplayNoEmptyGreen:
    def test_empty_trajectory_is_undetermined_and_not_ok(self):
        result = replay(_traj([]))

        assert result.ok is False
        assert result.checked == 0
        assert "undetermined" in result.failed_rules
        rules = {u["rule"] for u in result.undetermined}
        assert {"tool_sequence", "action_observation_pair", "verify_present"} <= rules
        detail = next(f["detail"] for f in result.failures if f["rule"] == "undetermined")
        assert "没有任何规则被判定" in detail

    def test_plan_only_trajectory_is_never_green(self):
        traj = _traj([Step(kind="plan", payload={"role": "user", "content": "hi"})])

        result = replay(traj)

        assert result.ok is False
        assert result.checked == 0

    def test_expect_tools_none_is_undetermined_not_self_compare(self):
        traj = _traj([_action("FileReadTool", True), _obs("FileReadTool")])

        result = replay(traj, expect_tools=None)

        assert result.ok is True  # 其它规则判定了
        detail = next(u["detail"] for u in result.undetermined if u["rule"] == "tool_sequence")
        assert "未提供 expect_tools" in detail

    def test_empty_expect_tools_cannot_green_an_empty_trajectory(self):
        """`expect_tools=[]` 遇上空轨迹 = "零个 action 匹配零个期望"，这是假绿"""

        result = replay(_traj([]), expect_tools=[])

        assert result.ok is False
        assert result.checked == 0
        assert "undetermined" in result.failed_rules

    def test_replay_result_to_dict_is_json_safe(self):
        result = replay(_traj([]), expect_tools=["FileReadTool"])

        payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))

        assert payload["ok"] is False
        assert payload["checked"] == 0
        assert isinstance(payload["failures"], list)
        assert isinstance(payload["undetermined"], list)


class TestReplayEndToEndFromSession:
    def test_real_shaped_session_roundtrip_and_replay(self, tmp_path: Path):
        traj = record_from_session(_full_session())
        path = save_trajectory(traj, tmp_path / "traj.json")
        loaded = load_trajectory(path)

        result = replay(loaded, expect_tools=["FileReadTool", "BashTool"])

        assert result.ok is True
        assert result.checked >= 2
        # 两个 action 名字不同 → 明确不是"原地重试"，该规则确实判定了（判定为通过）
        assert result.failed_rules == []
        # 会话没有 verify 步骤 → 不判 verify，如实列为未判定
        assert "verify_present" in [u["rule"] for u in result.undetermined]

    def test_regression_detected_after_recording(self, tmp_path: Path):
        """录制的是 A→B，回放期望 A→B；若 agent 退化成 B→A 必须红"""
        traj = record_from_session(_session([
            _msg("user", "g"),
            _msg("tool", "x", name="BashTool", ok=True),
            _msg("tool", "y", name="FileReadTool", ok=True),
        ]))
        save_trajectory(traj, tmp_path / "traj.json")
        loaded = load_trajectory(tmp_path / "traj.json")

        result = replay(loaded, expect_tools=["FileReadTool", "BashTool"])

        assert result.ok is False
        assert "tool_sequence" in result.failed_rules


# ==========================================================================
# 约束：零 LLM / 零网络
# ==========================================================================


class TestOfflineGuarantee:
    def test_module_imports_no_network_or_llm_libs(self):
        import ast

        source = (
            Path(__file__).resolve().parents[2] / "src" / "eval" / "trajectory.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])

        forbidden = {
            "requests", "httpx", "aiohttp", "urllib", "http", "socket", "openai",
            "anthropic", "src", "litellm", "httpcore",
        }
        assert not (imported & forbidden), f"轨迹模块不得依赖: {imported & forbidden}"
        assert imported <= {
            "contextlib", "json", "os", "tempfile", "collections",
            "dataclasses", "datetime", "pathlib", "typing", "__future__",
        }, f"出现未预期的依赖: {imported}"

    def test_replay_makes_no_network_calls(self, monkeypatch):
        import socket

        def _boom(*_a, **_k):
            raise AssertionError("回放期间不得发起网络连接")

        monkeypatch.setattr(socket, "create_connection", _boom)
        monkeypatch.setattr(socket.socket, "connect", _boom)

        traj = record_from_session(_full_session())

        assert replay(traj, expect_tools=["FileReadTool", "BashTool"]).ok is True


# ==========================================================================
# 类型契约
# ==========================================================================


def test_step_kind_literal_covers_all_used_kinds():
    traj = record_from_session(_full_session())

    allowed = set(StepKind.__args__)  # type: ignore[attr-defined]
    assert allowed == {"plan", "action", "observation", "verify"}
    assert {s.kind for s in traj.steps} <= allowed


def test_first_diff_helper_reports_index_length_and_equal_case():
    from src.eval.trajectory import _first_diff

    assert "首个差异在第 2 步" in _first_diff(["a", "b"], ["a", "c"])
    assert "步数不一致: 期望 2 实际 1" in _first_diff(["a", "b"], ["a"])
    assert _first_diff(["a"], ["a"]) == ""

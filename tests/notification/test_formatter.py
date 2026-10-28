"""Tests for src.notification.formatter — 通知消息格式化真实行为。

覆盖三类真实行为：
1. tmux pane 原始输出 → 干净可读文本（UI chrome 过滤、块分组、预算截断）
2. payload → 各事件的 markdown 文本（字段出现/缺席、footer、时长人类可读化）
3. 事件 → 格式化函数的分发完整性

说明：formatter 以 duck-typing 方式读取 payload（`payload.agent_name`、
`payload.tmux_tail` 等），因此格式化契约测试使用 `SimpleNamespace` 提供
这些字段；`FullNotificationPayload` 曾缺失这些字段导致崩溃的问题已修复
（types.py 补齐三字段），由文末 `TestRealPayloadContractGap` 三个用例锁定。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from src.notification import formatter as fmt
from src.notification.types import FullNotificationPayload, NotificationEvent

# ---------------------------------------------------------------------------
# payload 工厂
# ---------------------------------------------------------------------------

_OPTIONAL_DEFAULTS = {
    "tmux_session": None,
    "project_path": None,
    "project_name": None,
    "modes_used": None,
    "context_summary": None,
    "duration_ms": None,
    "agents_spawned": None,
    "agents_completed": None,
    "reason": None,
    "active_mode": None,
    "iteration": None,
    "max_iterations": None,
    "question": None,
    "incomplete_tasks": None,
    "tmux_pane": None,
    "tmux_tail": None,
    "agent_name": None,
    "agent_type": None,
}

# 所有可选字段都填满的 payload —— 用于触发表单式里每个 `if payload.x` 分支
RICH_FIELDS = {
    "session_id": "sess-1",
    "message": "msg",
    "timestamp": "1700000000",
    "tmux_session": "tmux-A",
    "project_path": "C:/work/proj-x",
    "project_name": "proj-x",
    "modes_used": ["ralph"],
    "context_summary": "build the thing",
    "duration_ms": 61_000,
    "agents_spawned": 3,
    "agents_completed": 2,
    "reason": "boom",
    "active_mode": "ralph",
    "iteration": 2,
    "max_iterations": 5,
    "question": "continue?",
    "incomplete_tasks": 1,
    "tmux_pane": "%1",
    "tmux_tail": "● spinner\n$ pytest -q\nPASSED test_a.py\nctrl+o to expand",
    "agent_name": "worker-a",
    "agent_type": "builder",
}


class _FakeEvent:
    """可哈希的伪事件对象，用于测试兜底分支。"""

    def __init__(self, value: str) -> None:
        self.value = value


def _make(**overrides) -> SimpleNamespace:
    data = dict(_OPTIONAL_DEFAULTS)
    data.update(RICH_FIELDS)
    data["event"] = NotificationEvent.SESSION_START
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.fixture
def rich():
    """字段全满的 payload 工厂。"""
    return _make


@pytest.fixture
def minimal():
    """仅必填字段的 payload 工厂（所有可选字段为 None）。"""
    def _minimal(event=NotificationEvent.SESSION_START, **overrides):
        data = dict(_OPTIONAL_DEFAULTS)
        data.update(
            session_id="sess-1",
            message="msg",
            timestamp="1700000000",
            event=event,
        )
        data.update(overrides)
        return SimpleNamespace(**data)
    return _minimal


# ---------------------------------------------------------------------------
# parse_tmux_tail
# ---------------------------------------------------------------------------


class TestParseTmuxTail:
    def test_strips_ansi_escape_sequences(self):
        raw = "\x1b[32m$ pytest -q\x1b[0m\n\x1b[1mPASSED test_a.py\x1b[0m"
        assert fmt.parse_tmux_tail(raw) == "$ pytest -q\nPASSED test_a.py"

    def test_drops_spinner_hud_hint_bypass_lines(self):
        raw = (
            "● Running tests\n"
            "⎿  waiting\n"
            "[OMX#1.2.3] model ready\n"
            "[OMX] unversioned hud\n"
            "ctrl+o to expand\n"
            "⏵ bypass permissions on\n"
            "PASSED test_a.py"
        )
        assert fmt.parse_tmux_tail(raw) == "PASSED test_a.py"

    def test_drops_box_drawing_lines(self):
        raw = "────────────\n╔══╗\n┌──┐\nPASSED test_a.py"
        assert fmt.parse_tmux_tail(raw) == "PASSED test_a.py"

    def test_drops_bare_prompt_line(self):
        raw = "❯\n>\n$\nPASSED test_a.py"
        assert fmt.parse_tmux_tail(raw) == "PASSED test_a.py"

    def test_drops_low_alnum_density_line(self):
        # 11 个符号，\w 密度 0% < MIN_ALNUM_RATIO(0.15)
        raw = "▲△▽▼▷◁◇◆★☆◈\nPASSED test_a.py"
        assert fmt.parse_tmux_tail(raw) == "PASSED test_a.py"

    def test_short_symbol_line_is_kept(self):
        # 长度 < 8 时跳过密度检查，符号行被保留
        raw = "▲▲\nPASSED test_a.py"
        assert fmt.parse_tmux_tail(raw) == "▲▲\nPASSED test_a.py"

    def test_blank_and_whitespace_lines_are_skipped(self):
        raw = "first line\n\n   \n\t\nsecond line"
        assert fmt.parse_tmux_tail(raw) == "first line\nsecond line"

    def test_indented_continuation_joins_previous_block(self):
        raw = "Traceback (most recent call last):\n  File \"a.py\", line 3\n    boom()"
        assert fmt.parse_tmux_tail(raw) == (
            'Traceback (most recent call last):\n  File "a.py", line 3\n    boom()'
        )

    def test_leading_continuation_without_previous_block_starts_new_block(self):
        raw = "  orphan indented\nplain line"
        assert fmt.parse_tmux_tail(raw) == "  orphan indented\nplain line"

    def test_trailing_whitespace_on_content_line_is_stripped(self):
        raw = "PASSED test_a.py\x1b[0m   "
        assert fmt.parse_tmux_tail(raw) == "PASSED test_a.py"

    def test_keeps_only_recent_ten_blocks(self):
        raw = "\n".join(f"b{i:02d}aaaa" for i in range(15))
        lines = fmt.parse_tmux_tail(raw).split("\n")
        assert len(lines) == fmt.MAX_TAIL_BLOCKS
        assert lines[0] == "b05aaaa"
        assert lines[-1] == "b14aaaa"

    def test_respects_char_budget(self):
        raw = "\n".join("x" * 400 + str(i) for i in range(6))
        lines = fmt.parse_tmux_tail(raw).split("\n")
        # 后两块 401 字符可放下（401 + 1 + 401 = 803），第三块超 1200 预算
        assert len(lines) == 2
        assert lines[0] == "x" * 400 + "4"
        assert lines[1] == "x" * 400 + "5"

    def test_single_block_larger_than_budget_is_still_kept(self):
        raw = "y" * (fmt.MAX_TAIL_CHARS + 500)
        assert fmt.parse_tmux_tail(raw) == raw

    def test_empty_input(self):
        assert fmt.parse_tmux_tail("") == ""
        assert fmt.parse_tmux_tail("\n\n \n") == ""


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------


class TestFormatDuration:
    @pytest.mark.parametrize(
        ("ms", "expected"),
        [
            (None, "unknown"),
            (0, "unknown"),
            (1, "0s"),
            (999, "0s"),
            (1000, "1s"),
            (59_000, "59s"),
            (60_000, "1m 0s"),
            (61_000, "1m 1s"),
            (3_599_000, "59m 59s"),
            (3_600_000, "1h 0m 0s"),
            (3_723_000, "1h 2m 3s"),
        ],
    )
    def test_human_readable(self, ms, expected):
        assert fmt.format_duration(ms) == expected


# ---------------------------------------------------------------------------
# project_display / footer / tail block
# ---------------------------------------------------------------------------


class TestProjectDisplay:
    def test_prefers_explicit_project_name(self, rich):
        payload = rich(project_name="explicit", project_path="C:/work/from-path")
        assert fmt.project_display(payload) == "explicit"

    def test_falls_back_to_path_basename(self, minimal):
        payload = minimal(project_path="C:/work/from-path")
        assert fmt.project_display(payload) == "from-path"

    def test_unknown_when_neither_present(self, minimal):
        assert fmt.project_display(minimal()) == "unknown"


class TestBuildFooter:
    def test_markdown_with_tmux_session(self, rich):
        assert fmt.build_footer(rich(), markdown=True) == (
            "**tmux:** `tmux-A` | **project:** `proj-x`"
        )

    def test_plain_with_tmux_session(self, rich):
        assert fmt.build_footer(rich(), markdown=False) == "tmux: tmux-A | project: proj-x"

    def test_markdown_without_tmux_session(self, minimal):
        payload = minimal(project_name="proj-x")
        assert fmt.build_footer(payload, markdown=True) == "**project:** `proj-x`"

    def test_plain_without_tmux_session(self, minimal):
        payload = minimal(project_name="proj-x")
        assert fmt.build_footer(payload, markdown=False) == "project: proj-x"


class TestBuildTmuxTailBlock:
    def test_empty_when_no_tail(self, minimal):
        assert fmt.build_tmux_tail_block(minimal()) == ""

    def test_empty_when_tail_is_all_chrome(self, rich):
        payload = rich(tmux_tail="● spinner\n────\nctrl+o to expand", )
        assert fmt.build_tmux_tail_block(payload) == ""

    def test_fenced_code_block_with_cleaned_content(self, rich):
        block = fmt.build_tmux_tail_block(rich())
        assert block == (
            "\n**Recent output:**\n```\n$ pytest -q\nPASSED test_a.py\n```"
        )


# ---------------------------------------------------------------------------
# 事件 → markdown 分发（字段全满分支）
# ---------------------------------------------------------------------------

_DISPATCH_CASES = [
    (NotificationEvent.SESSION_START, "# Session Started",
     ["**Session:** `sess-1`", "**Project:** `proj-x`", "**tmux:** `tmux-A`", "**Time:** "]),
    (NotificationEvent.SESSION_STOP, "# Session Continuing",
     ["**Mode:** ralph", "**Iteration:** 2/5", "**Incomplete tasks:** 1",
      "**Recent output:**", "PASSED test_a.py",
      "**tmux:** `tmux-A` | **project:** `proj-x`"]),
    (NotificationEvent.SESSION_END, "# Session Completed",
     ["**Session:** `sess-1`", "**Duration:** 1m 1s", "**Agents spawned:** 3",
      "**Agents completed:** 2", "**Recent output:**"]),
    (NotificationEvent.SESSION_IDLE, "# Session Idle",
     ["**Iteration:** 2/5", "**Recent output:**", "**project:** `proj-x`"]),
    (NotificationEvent.ASK_USER_QUESTION, "# Awaiting User Input",
     ["**Question:** continue?", "**Recent output:**"]),
    (NotificationEvent.USER_RESPONDED, "# User Responded",
     ["**Session:** `sess-1`", "**Question:** continue?"]),
    (NotificationEvent.AGENT_START, "# Agent Started",
     ["**Session:** `sess-1`", "**Agent:** `worker-a`", "**Type:** builder"]),
    (NotificationEvent.AGENT_END, "# Agent Completed",
     ["**Session:** `sess-1`", "**Agent:** `worker-a`", "**Duration:** 1m 1s"]),
    (NotificationEvent.TASK_CREATED, "# Task Created",
     ["**Created by:** `worker-a`", "**Recent output:**"]),
    (NotificationEvent.TASK_ASSIGNED, "# Task Assigned",
     ["**Assigned to:** `worker-a`", "**Recent output:**"]),
    (NotificationEvent.TASK_STARTED, "# Task Started",
     ["**Worker:** `worker-a`", "**Recent output:**"]),
    (NotificationEvent.TASK_COMPLETE, "# Task Completed",
     ["**Completed by:** `worker-a`", "**Duration:** 1m 1s"]),
    (NotificationEvent.TASK_FAILED, "# Task Failed",
     ["**Worker:** `worker-a`", "**Reason:** boom"]),
    (NotificationEvent.TASK_RETRY, "# Task Retry",
     ["**Retrying with:** `worker-a`", "**Attempt:** 2"]),
    (NotificationEvent.PIPELINE_START, "# Pipeline Started",
     ["**Session:** `sess-1`", "**Task:** build the thing"]),
    (NotificationEvent.PIPELINE_STAGE_START, "# Stage Started",
     ["**Stage:** worker-a", "**Mode:** ralph"]),
    (NotificationEvent.PIPELINE_STAGE_COMPLETE, "# Stage Completed",
     ["**Stage:** worker-a", "**Duration:** 1m 1s"]),
    (NotificationEvent.PIPELINE_STAGE_FAILED, "# Stage Failed",
     ["**Stage:** worker-a", "**Reason:** boom"]),
    (NotificationEvent.PIPELINE_COMPLETE, "# Pipeline Completed",
     ["**Session:** `sess-1`", "**Total Duration:** 1m 1s", "**Agents completed:** 2"]),
    (NotificationEvent.PIPELINE_RESUMED, "# Pipeline Resumed",
     ["**Session:** `sess-1`", "**Iteration:** 2"]),
    (NotificationEvent.WORKER_JOINED, "# Worker Joined",
     ["**Worker:** `worker-a`", "**Type:** builder"]),
    (NotificationEvent.WORKER_LEFT, "# Worker Left",
     ["**Worker:** `worker-a`", "**Reason:** boom"]),
    (NotificationEvent.TEAM_DISPATCH, "# Team Dispatch",
     ["**Dispatcher:** `worker-a`", "**Agents spawned:** 3"]),
    (NotificationEvent.TEAM_RESULT, "# Team Result",
     ["**Completed:** 2", "**Incomplete:** 1"]),
    (NotificationEvent.AUDIT_REQUEST, "# Audit Request",
     ["**Auditor:** `worker-a`", "**Recent output:**"]),
    (NotificationEvent.AUDIT_RESULT, "# Audit Result",
     ["**Auditor:** `worker-a`", "**Recent output:**"]),
    (NotificationEvent.REVIEW_REQUEST, "# Review Request",
     ["**Reviewer:** `worker-a`", "**Recent output:**"]),
    (NotificationEvent.REVIEW_RESULT, "# Review Result",
     ["**Reviewer:** `worker-a`", "**Recent output:**"]),
    (NotificationEvent.ERROR_DETECTED, "# Error Detected",
     ["**Error:** boom", "**Recent output:**"]),
    (NotificationEvent.ERROR_DIAGNOSED, "# Error Diagnosed",
     ["**Diagnosed by:** `worker-a`", "**Diagnosis:** boom"]),
    (NotificationEvent.FIX_APPLIED, "# Fix Applied",
     ["**Applied by:** `worker-a`", "**Recent output:**"]),
    (NotificationEvent.HEAL_COMPLETE, "# Heal Completed",
     ["**Duration:** 1m 1s", "**project:** `proj-x`"]),
    (NotificationEvent.HEAL_FAILED, "# Heal Failed",
     ["**Reason:** boom", "**Recent output:**"]),
    (NotificationEvent.BUDGET_EXCEEDED, "# Budget Exceeded",
     ["**Budget:** boom", "**project:** `proj-x`"]),
    (NotificationEvent.RESOURCE_WARNING, "# Resource Warning",
     ["**Warning:** boom", "**project:** `proj-x`"]),
    (NotificationEvent.NOTIFICATION_SENT, "# Notification Sent",
     ["**Event:** notification-sent"]),
    (NotificationEvent.NOTIFICATION_FAILED, "# Notification Failed",
     ["**Reason:** boom"]),
    (NotificationEvent.BLOCKED, "# Blocked",
     ["**Reason:** boom", "**Recent output:**"]),
]


class TestFormatNotificationDispatch:
    @pytest.mark.parametrize(("event", "heading", "expected_parts"), _DISPATCH_CASES)
    def test_rich_payload(self, event, heading, expected_parts):
        payload = _make(event=event)
        output = fmt.format_notification(event, payload)
        assert output.split("\n")[0] == heading
        for part in expected_parts:
            assert part in output

    @pytest.mark.parametrize(("event", "heading", "expected_parts"), _DISPATCH_CASES)
    def test_minimal_payload_omits_optional_sections(self, event, heading, expected_parts):
        payload = _make(
            event=event,
            **{key: None for key in _OPTIONAL_DEFAULTS},
        )
        output = fmt.format_notification(event, payload)
        assert output.split("\n")[0] == heading
        assert "**Recent output:**" not in output
        assert "**Mode:**" not in output
        assert "worker-a" not in output
        # session-end 是唯一无条件输出时长行的事件（缺失时显示 unknown）
        if event is NotificationEvent.SESSION_END:
            assert "**Duration:** unknown" in output
        else:
            assert "**Duration:**" not in output
        # 不落入兜底分支
        assert not output.startswith("Event: ")

    @pytest.mark.parametrize("event", list(NotificationEvent))
    def test_every_event_has_explicit_formatter(self, event):
        """38 个事件都应有专属格式器，不应落到 `Event: ...` 兜底。"""
        output = fmt.format_notification(event, _make(event=event))
        assert not output.startswith("Event: ")
        assert output.startswith("# ")

    def test_fallback_for_unknown_event_value(self):
        payload = _make(session_id="sess-9")
        assert fmt.format_notification(_FakeEvent("brand-new-event"), payload) == (
            "Event: brand-new-event\nSession: sess-9"
        )

    def test_dispatch_uses_payload_event_for_notification_sent(self):
        output = fmt.format_notification(
            NotificationEvent.NOTIFICATION_SENT,
            _make(event=NotificationEvent.BLOCKED),
        )
        assert "**Event:** blocked" in output


# ---------------------------------------------------------------------------
# 各表单式的条件分支细节
# ---------------------------------------------------------------------------


class TestSessionFormatters:
    def test_session_start_time_comes_from_epoch_timestamp(self, minimal):
        payload = minimal(timestamp="1700000000", project_name="proj-x")
        expected_time = datetime.fromtimestamp(1700000000.0).strftime("%H:%M:%S")
        output = fmt.format_session_start(payload)
        assert f"**Time:** {expected_time}" in output
        assert "**tmux:**" not in output

    def test_session_start_lines_layout(self, minimal):
        payload = minimal(timestamp="1700000000", project_name="proj-x")
        assert fmt.format_session_start(payload) == "\n".join([
            "# Session Started",
            "",
            "**Session:** `sess-1`",
            "**Project:** `proj-x`",
            f"**Time:** {datetime.fromtimestamp(1700000000.0).strftime('%H:%M:%S')}",
        ])

    def test_session_stop_hides_zero_incomplete_tasks(self, minimal):
        payload = minimal(incomplete_tasks=0, project_name="proj-x")
        assert "Incomplete tasks" not in fmt.format_session_stop(payload)

    def test_session_stop_requires_iteration_and_max_together(self, minimal):
        payload = minimal(iteration=3, max_iterations=None, project_name="proj-x")
        assert "**Iteration:**" not in fmt.format_session_stop(payload)

    def test_session_stop_tail_and_footer_order(self, rich):
        payload = rich(tmux_tail="PASSED test_a.py")
        assert fmt.format_session_stop(payload) == "\n".join([
            "# Session Continuing",
            "",
            "**Mode:** ralph",
            "**Iteration:** 2/5",
            "**Incomplete tasks:** 1",
            "\n**Recent output:**\n```\nPASSED test_a.py\n```",
            "",
            "**tmux:** `tmux-A` | **project:** `proj-x`",
        ])

    def test_session_end_zero_agents_still_reported(self, minimal):
        payload = minimal(duration_ms=1000, agents_spawned=0, project_name="proj-x")
        output = fmt.format_session_end(payload)
        assert "**Agents spawned:** 0" in output
        assert "**Agents completed:**" not in output

    def test_session_end_unknown_duration(self, minimal):
        output = fmt.format_session_end(minimal(project_name="proj-x"))
        assert "**Duration:** unknown" in output


class TestTaskAndTeamFormatters:
    def test_team_result_hides_zero_completed(self, minimal):
        """agents_completed 用真值判断（与 session_end 的 `is not None` 不一致）。"""
        output = fmt.format_team_result(minimal(agents_completed=0, incomplete_tasks=0))
        assert "**Completed:**" not in output
        assert "**Incomplete:**" not in output

    def test_task_retry_hides_zero_iteration(self, minimal):
        output = fmt.format_task_retry(minimal(iteration=0, agent_name="w"))
        assert "**Attempt:**" not in output

    def test_task_failed_without_reason_or_worker(self, minimal):
        assert fmt.format_task_failed(minimal()) == "# Task Failed\n"

    def test_pipeline_resumed_hides_zero_iteration(self, minimal):
        output = fmt.format_pipeline_resumed(minimal(project_name="proj-x"))
        assert "**Iteration:**" not in output
        assert "**project:** `proj-x`" in output

    def test_pipeline_start_without_context_summary(self, minimal):
        output = fmt.format_pipeline_start(minimal(project_name="proj-x"))
        assert "**Task:**" not in output
        assert "**Session:** `sess-1`" in output


class TestResourceFormatters:
    def test_budget_exceeded_default_message(self, minimal):
        assert "**Resource budget exceeded**" in fmt.format_budget_exceeded(
            minimal(project_name="p")
        )

    def test_resource_warning_default_message(self, minimal):
        assert "**Resource pressure detected**" in fmt.format_resource_warning(
            minimal(project_name="p")
        )

    def test_notification_failed_default_message(self, minimal):
        assert "**Failed to send notification**" in fmt.format_notification_failed(
            minimal(project_name="p")
        )


# ---------------------------------------------------------------------------
# 真实 payload 类型契约缺口（缺陷记录，不修 src）
# ---------------------------------------------------------------------------


class TestRealPayloadContractGap:
    """formatter 读取了 `FullNotificationPayload` 未声明的字段。

    这三个用例锁定 2026-10-28 已修复的缺陷（types.py 补齐 tmux_tail/agent_name/
    agent_type 字段；formatter 时间戳兼容 ISO-8601），现为正常通过用例。
    """

    def test_tail_block_works_with_declared_payload(self):
        payload = FullNotificationPayload(
            event=NotificationEvent.SESSION_END,
            session_id="s",
            message="",
            timestamp="1700000000",
            tmux_pane="%1",
        )
        assert fmt.format_session_end(payload).startswith("# Session Completed")

    def test_agent_formatter_works_with_declared_payload(self):
        payload = FullNotificationPayload(
            event=NotificationEvent.AGENT_START,
            session_id="s",
            message="",
            timestamp="1700000000",
        )
        assert fmt.format_agent_start(payload).startswith("# Agent Started")

    def test_session_start_accepts_iso_timestamp(self):
        payload = FullNotificationPayload(
            event=NotificationEvent.SESSION_START,
            session_id="s",
            message="",
            timestamp="2026-10-28T10:26:32+00:00",
        )
        assert "# Session Started" in fmt.format_session_start(payload)

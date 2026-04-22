"""Notification Message Formatters

Produces human-readable notification messages for each event type.
Supports markdown (Discord/Telegram) and plain text (Slack/webhook) formats.
"""

import re
from datetime import datetime
from pathlib import Path

from .types import FullNotificationPayload, NotificationEvent

# ANSI CSI escape sequences and two-character escapes
ANSI_RE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-9;]*[A-Za-z])')

# OMX UI chrome: spinner/progress indicator characters
SPINNER_LINE_RE = re.compile(r'^[●⎿✻·◼]')

# tmux expand hint injected by some pane-capture scripts
CTRL_O_RE = re.compile(r'ctrl\+o to expand', re.IGNORECASE)

# Lines composed entirely of box-drawing characters and whitespace
BOX_DRAWING_RE = re.compile(r'^[\s─═│║┌┐└┘┬┴├┤╔╗╚╝╠╣╦╩╬╟╢╤╧╪━┃┏┓┗┛┣┫┳┻╋┠┨┯┷┿╂]+$')

# OMX HUD status lines: [OMX#...] or [OMX] (unversioned)
OMX_HUD_RE = re.compile(r'\[OMX[#\]]')

# Bypass-permissions indicator lines starting with ⏵
BYPASS_PERM_RE = re.compile(r'^⏵')

# Bare shell prompt with no command after it
BARE_PROMPT_RE = re.compile(r'^[❯>$%#]+$')

# Minimum ratio of alphanumeric characters for a line to be "meaningful"
MIN_ALNUM_RATIO = 0.15

# Unicode-aware letters/numbers for density checks across non-Latin scripts
# Using \w with UNICODE flag to match Unicode word characters
UNICODE_ALNUM_RE = re.compile(r'\w', re.UNICODE)

# Maximum number of meaningful output blocks to include in a notification
MAX_TAIL_BLOCKS = 10

# Maximum recent-output character budget before older blocks are dropped
MAX_TAIL_CHARS = 1200


def parse_tmux_tail(raw: str) -> str:
    """Parse raw tmux pane output into clean, human-readable text.

    Strips:
    - ANSI escape codes
    - UI chrome lines (spinner/progress characters)
    - "ctrl+o to expand" hint lines
    - Box-drawing character lines
    - OMX HUD status lines
    - Bypass-permissions indicator lines
    - Bare shell prompt lines
    - Lines with < 15% Unicode letter/number density (for lines >= 8 chars)

    Groups indented continuation lines into the previous logical block.
    Keeps the most recent 10 logical blocks within a 1200-character budget.
    """
    blocks = []

    for line in raw.split("\n"):
        stripped = ANSI_RE.sub('', line)
        trimmed = stripped.strip()

        if not trimmed:
            continue
        if SPINNER_LINE_RE.match(trimmed):
            continue
        if CTRL_O_RE.search(trimmed):
            continue
        if BOX_DRAWING_RE.match(trimmed):
            continue
        if OMX_HUD_RE.search(trimmed):
            continue
        if BYPASS_PERM_RE.match(trimmed):
            continue
        if BARE_PROMPT_RE.match(trimmed):
            continue

        # Unicode-aware density check
        alnum_count = len(UNICODE_ALNUM_RE.findall(trimmed))
        if len(trimmed) >= 8 and alnum_count / len(trimmed) < MIN_ALNUM_RATIO:
            continue

        cleaned_line = stripped.rstrip()
        is_continuation = bool(re.match(r'^[\t ]+', cleaned_line))

        if is_continuation and blocks:
            blocks[-1].append(cleaned_line)
            continue

        blocks.append([cleaned_line])

    # Join blocks
    block_texts = ['\n'.join(block) for block in blocks]
    recent_blocks = []
    total_chars = 0

    # Take most recent blocks (reversed iteration)
    for block in reversed(block_texts):
        if len(recent_blocks) >= MAX_TAIL_BLOCKS:
            break

        next_total = total_chars + len(block) + (1 if recent_blocks else 0)
        if recent_blocks and next_total > MAX_TAIL_CHARS:
            break

        recent_blocks.insert(0, block)
        total_chars = next_total

    return '\n'.join(recent_blocks)


def format_duration(ms: int | None) -> str:
    """Format milliseconds into human-readable duration."""
    if not ms:
        return "unknown"

    seconds = ms // 1000
    minutes = seconds // 60
    hours = minutes // 60

    if hours > 0:
        return f"{hours}h {minutes % 60}m {seconds % 60}s"
    if minutes > 0:
        return f"{minutes}m {seconds % 60}s"
    return f"{seconds}s"


def project_display(payload: FullNotificationPayload) -> str:
    """Get display name for project."""
    if payload.project_name:
        return payload.project_name
    if payload.project_path:
        return Path(payload.project_path).name
    return "unknown"


def build_tmux_tail_block(payload: FullNotificationPayload) -> str:
    """Build tmux tail block for notification."""
    if not payload.tmux_tail:
        return ""

    cleaned = parse_tmux_tail(payload.tmux_tail)
    if not cleaned:
        return ""

    return f"\n**Recent output:**\n```\n{cleaned}\n```"


def build_footer(payload: FullNotificationPayload, markdown: bool = True) -> str:
    """Build footer with tmux session and project info."""
    parts = []

    if payload.tmux_session:
        if markdown:
            parts.append(f"**tmux:** `{payload.tmux_session}`")
        else:
            parts.append(f"tmux: {payload.tmux_session}")

    parts.append(
        f"**project:** `{project_display(payload)}`"
        if markdown
        else f"project: {project_display(payload)}"
    )

    return " | ".join(parts)


def format_session_start(payload: FullNotificationPayload) -> str:
    """Format session start notification."""
    time = datetime.fromtimestamp(float(payload.timestamp)).strftime("%H:%M:%S")
    project = project_display(payload)

    lines = [
        "# Session Started",
        "",
        f"**Session:** `{payload.session_id}`",
        f"**Project:** `{project}`",
        f"**Time:** {time}",
    ]

    if payload.tmux_session:
        lines.append(f"**tmux:** `{payload.tmux_session}`")

    return "\n".join(lines)


def format_session_stop(payload: FullNotificationPayload) -> str:
    """Format session stop (pause/interruption) notification."""
    lines = ["# Session Continuing", ""]

    if payload.active_mode:
        lines.append(f"**Mode:** {payload.active_mode}")

    if payload.iteration is not None and payload.max_iterations is not None:
        lines.append(f"**Iteration:** {payload.iteration}/{payload.max_iterations}")

    if payload.incomplete_tasks is not None and payload.incomplete_tasks > 0:
        lines.append(f"**Incomplete tasks:** {payload.incomplete_tasks}")

    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)

    lines.append("")
    lines.append(build_footer(payload, markdown=True))

    return "\n".join(lines)


def format_session_end(payload: FullNotificationPayload) -> str:
    """Format session end (completion) notification."""
    duration = format_duration(payload.duration_ms)
    project = project_display(payload)

    lines = [
        "# Session Completed",
        "",
        f"**Session:** `{payload.session_id}`",
        f"**Project:** `{project}`",
        f"**Duration:** {duration}",
    ]

    if payload.agents_spawned is not None:
        lines.append(f"**Agents spawned:** {payload.agents_spawned}")
    if payload.agents_completed is not None:
        lines.append(f"**Agents completed:** {payload.agents_completed}")

    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)

    lines.append("")
    lines.append(build_footer(payload, markdown=True))

    return "\n".join(lines)


def format_session_idle(payload: FullNotificationPayload) -> str:
    """Format session idle notification."""
    lines = ["# Session Idle", ""]

    if payload.iteration is not None and payload.max_iterations is not None:
        lines.append(f"**Iteration:** {payload.iteration}/{payload.max_iterations}")

    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)

    lines.append("")
    lines.append(build_footer(payload, markdown=True))

    return "\n".join(lines)


def format_ask_user_question(payload: FullNotificationPayload) -> str:
    """Format ask-user-question notification."""
    lines = ["# Awaiting User Input", ""]

    if payload.question:
        lines.append(f"**Question:** {payload.question}")

    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)

    lines.append("")
    lines.append(build_footer(payload, markdown=True))

    return "\n".join(lines)


def format_user_responded(payload: FullNotificationPayload) -> str:
    """Format user-responded notification."""
    lines = ["# User Responded", ""]
    lines.append(f"**Session:** `{payload.session_id}`")
    if payload.question:
        lines.append(f"**Question:** {payload.question}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_agent_start(payload: FullNotificationPayload) -> str:
    """Format agent-start notification."""
    lines = ["# Agent Started", ""]
    lines.append(f"**Session:** `{payload.session_id}`")
    if payload.agent_name:
        lines.append(f"**Agent:** `{payload.agent_name}`")
    if payload.agent_type:
        lines.append(f"**Type:** {payload.agent_type}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_agent_end(payload: FullNotificationPayload) -> str:
    """Format agent-end notification."""
    lines = ["# Agent Completed", ""]
    lines.append(f"**Session:** `{payload.session_id}`")
    if payload.agent_name:
        lines.append(f"**Agent:** `{payload.agent_name}`")
    if payload.duration_ms:
        lines.append(f"**Duration:** {format_duration(payload.duration_ms)}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_task_created(payload: FullNotificationPayload) -> str:
    """Format task-created notification."""
    lines = ["# Task Created", ""]
    if payload.agent_name:
        lines.append(f"**Created by:** `{payload.agent_name}`")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_task_assigned(payload: FullNotificationPayload) -> str:
    """Format task-assigned notification."""
    lines = ["# Task Assigned", ""]
    if payload.agent_name:
        lines.append(f"**Assigned to:** `{payload.agent_name}`")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_task_started(payload: FullNotificationPayload) -> str:
    """Format task-started notification."""
    lines = ["# Task Started", ""]
    if payload.agent_name:
        lines.append(f"**Worker:** `{payload.agent_name}`")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_task_complete(payload: FullNotificationPayload) -> str:
    """Format task-complete notification."""
    lines = ["# Task Completed", ""]
    if payload.agent_name:
        lines.append(f"**Completed by:** `{payload.agent_name}`")
    if payload.duration_ms:
        lines.append(f"**Duration:** {format_duration(payload.duration_ms)}")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_task_failed(payload: FullNotificationPayload) -> str:
    """Format task-failed notification."""
    lines = ["# Task Failed", ""]
    if payload.agent_name:
        lines.append(f"**Worker:** `{payload.agent_name}`")
    if payload.reason:
        lines.append(f"**Reason:** {payload.reason}")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_task_retry(payload: FullNotificationPayload) -> str:
    """Format task-retry notification."""
    lines = ["# Task Retry", ""]
    if payload.agent_name:
        lines.append(f"**Retrying with:** `{payload.agent_name}`")
    if payload.iteration:
        lines.append(f"**Attempt:** {payload.iteration}")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_pipeline_start(payload: FullNotificationPayload) -> str:
    """Format pipeline-start notification."""
    lines = ["# Pipeline Started", ""]
    lines.append(f"**Session:** `{payload.session_id}`")
    if payload.context_summary:
        lines.append(f"**Task:** {payload.context_summary}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_pipeline_stage_start(payload: FullNotificationPayload) -> str:
    """Format pipeline-stage-start notification."""
    lines = ["# Stage Started", ""]
    if payload.agent_name:
        lines.append(f"**Stage:** {payload.agent_name}")
    if payload.active_mode:
        lines.append(f"**Mode:** {payload.active_mode}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_pipeline_stage_complete(payload: FullNotificationPayload) -> str:
    """Format pipeline-stage-complete notification."""
    lines = ["# Stage Completed", ""]
    if payload.agent_name:
        lines.append(f"**Stage:** {payload.agent_name}")
    if payload.duration_ms:
        lines.append(f"**Duration:** {format_duration(payload.duration_ms)}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_pipeline_stage_failed(payload: FullNotificationPayload) -> str:
    """Format pipeline-stage-failed notification."""
    lines = ["# Stage Failed", ""]
    if payload.agent_name:
        lines.append(f"**Stage:** {payload.agent_name}")
    if payload.reason:
        lines.append(f"**Reason:** {payload.reason}")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_pipeline_complete(payload: FullNotificationPayload) -> str:
    """Format pipeline-complete notification."""
    lines = ["# Pipeline Completed", ""]
    lines.append(f"**Session:** `{payload.session_id}`")
    if payload.duration_ms:
        lines.append(f"**Total Duration:** {format_duration(payload.duration_ms)}")
    if payload.agents_completed is not None:
        lines.append(f"**Agents completed:** {payload.agents_completed}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_pipeline_resumed(payload: FullNotificationPayload) -> str:
    """Format pipeline-resumed notification."""
    lines = ["# Pipeline Resumed", ""]
    lines.append(f"**Session:** `{payload.session_id}`")
    if payload.iteration:
        lines.append(f"**Iteration:** {payload.iteration}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_worker_joined(payload: FullNotificationPayload) -> str:
    """Format worker-joined notification."""
    lines = ["# Worker Joined", ""]
    if payload.agent_name:
        lines.append(f"**Worker:** `{payload.agent_name}`")
    if payload.agent_type:
        lines.append(f"**Type:** {payload.agent_type}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_worker_left(payload: FullNotificationPayload) -> str:
    """Format worker-left notification."""
    lines = ["# Worker Left", ""]
    if payload.agent_name:
        lines.append(f"**Worker:** `{payload.agent_name}`")
    if payload.reason:
        lines.append(f"**Reason:** {payload.reason}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_team_dispatch(payload: FullNotificationPayload) -> str:
    """Format team-dispatch notification."""
    lines = ["# Team Dispatch", ""]
    if payload.agent_name:
        lines.append(f"**Dispatcher:** `{payload.agent_name}`")
    if payload.agents_spawned:
        lines.append(f"**Agents spawned:** {payload.agents_spawned}")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_team_result(payload: FullNotificationPayload) -> str:
    """Format team-result notification."""
    lines = ["# Team Result", ""]
    if payload.agents_completed:
        lines.append(f"**Completed:** {payload.agents_completed}")
    if payload.incomplete_tasks:
        lines.append(f"**Incomplete:** {payload.incomplete_tasks}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_audit_request(payload: FullNotificationPayload) -> str:
    """Format audit-request notification."""
    lines = ["# Audit Request", ""]
    if payload.agent_name:
        lines.append(f"**Auditor:** `{payload.agent_name}`")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_audit_result(payload: FullNotificationPayload) -> str:
    """Format audit-result notification."""
    lines = ["# Audit Result", ""]
    if payload.agent_name:
        lines.append(f"**Auditor:** `{payload.agent_name}`")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_review_request(payload: FullNotificationPayload) -> str:
    """Format review-request notification."""
    lines = ["# Review Request", ""]
    if payload.agent_name:
        lines.append(f"**Reviewer:** `{payload.agent_name}`")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_review_result(payload: FullNotificationPayload) -> str:
    """Format review-result notification."""
    lines = ["# Review Result", ""]
    if payload.agent_name:
        lines.append(f"**Reviewer:** `{payload.agent_name}`")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_error_detected(payload: FullNotificationPayload) -> str:
    """Format error-detected notification."""
    lines = ["# Error Detected", ""]
    if payload.reason:
        lines.append(f"**Error:** {payload.reason}")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_error_diagnosed(payload: FullNotificationPayload) -> str:
    """Format error-diagnosed notification."""
    lines = ["# Error Diagnosed", ""]
    if payload.agent_name:
        lines.append(f"**Diagnosed by:** `{payload.agent_name}`")
    if payload.reason:
        lines.append(f"**Diagnosis:** {payload.reason}")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_fix_applied(payload: FullNotificationPayload) -> str:
    """Format fix-applied notification."""
    lines = ["# Fix Applied", ""]
    if payload.agent_name:
        lines.append(f"**Applied by:** `{payload.agent_name}`")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_heal_complete(payload: FullNotificationPayload) -> str:
    """Format heal-complete notification."""
    lines = ["# Heal Completed", ""]
    if payload.duration_ms:
        lines.append(f"**Duration:** {format_duration(payload.duration_ms)}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_heal_failed(payload: FullNotificationPayload) -> str:
    """Format heal-failed notification."""
    lines = ["# Heal Failed", ""]
    if payload.reason:
        lines.append(f"**Reason:** {payload.reason}")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_budget_exceeded(payload: FullNotificationPayload) -> str:
    """Format budget-exceeded notification."""
    lines = ["# Budget Exceeded", ""]
    if payload.reason:
        lines.append(f"**Budget:** {payload.reason}")
    else:
        lines.append("**Resource budget exceeded**")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_resource_warning(payload: FullNotificationPayload) -> str:
    """Format resource-warning notification."""
    lines = ["# Resource Warning", ""]
    if payload.reason:
        lines.append(f"**Warning:** {payload.reason}")
    else:
        lines.append("**Resource pressure detected**")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_notification_sent(payload: FullNotificationPayload) -> str:
    """Format notification-sent notification."""
    lines = ["# Notification Sent", ""]
    lines.append(f"**Event:** {payload.event.value}")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_notification_failed(payload: FullNotificationPayload) -> str:
    """Format notification-failed notification."""
    lines = ["# Notification Failed", ""]
    if payload.reason:
        lines.append(f"**Reason:** {payload.reason}")
    else:
        lines.append("**Failed to send notification**")
    lines.append(build_footer(payload, markdown=True))
    return "\n".join(lines)


def format_blocked(payload: FullNotificationPayload) -> str:
    """Format blocked notification."""
    lines = ["# Blocked", ""]
    if payload.reason:
        lines.append(f"**Reason:** {payload.reason}")
    tail = build_tmux_tail_block(payload)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_notification(
    event: NotificationEvent,
    payload: FullNotificationPayload,
) -> str:
    """Format notification message based on event type."""
    formatters = {
        # 会话生命周期
        NotificationEvent.SESSION_START: format_session_start,
        NotificationEvent.SESSION_STOP: format_session_stop,
        NotificationEvent.SESSION_END: format_session_end,
        NotificationEvent.SESSION_IDLE: format_session_idle,
        NotificationEvent.ASK_USER_QUESTION: format_ask_user_question,
        NotificationEvent.USER_RESPONDED: format_user_responded,

        # Agent 生命周期
        NotificationEvent.AGENT_START: format_agent_start,
        NotificationEvent.AGENT_END: format_agent_end,

        # 任务/工作流
        NotificationEvent.TASK_CREATED: format_task_created,
        NotificationEvent.TASK_ASSIGNED: format_task_assigned,
        NotificationEvent.TASK_STARTED: format_task_started,
        NotificationEvent.TASK_COMPLETE: format_task_complete,
        NotificationEvent.TASK_FAILED: format_task_failed,
        NotificationEvent.TASK_RETRY: format_task_retry,

        # Pipeline 阶段
        NotificationEvent.PIPELINE_START: format_pipeline_start,
        NotificationEvent.PIPELINE_STAGE_START: format_pipeline_stage_start,
        NotificationEvent.PIPELINE_STAGE_COMPLETE: format_pipeline_stage_complete,
        NotificationEvent.PIPELINE_STAGE_FAILED: format_pipeline_stage_failed,
        NotificationEvent.PIPELINE_COMPLETE: format_pipeline_complete,
        NotificationEvent.PIPELINE_RESUMED: format_pipeline_resumed,

        # 团队协作
        NotificationEvent.WORKER_JOINED: format_worker_joined,
        NotificationEvent.WORKER_LEFT: format_worker_left,
        NotificationEvent.TEAM_DISPATCH: format_team_dispatch,
        NotificationEvent.TEAM_RESULT: format_team_result,

        # 审核/审查
        NotificationEvent.AUDIT_REQUEST: format_audit_request,
        NotificationEvent.AUDIT_RESULT: format_audit_result,
        NotificationEvent.REVIEW_REQUEST: format_review_request,
        NotificationEvent.REVIEW_RESULT: format_review_result,

        # 自我修复
        NotificationEvent.ERROR_DETECTED: format_error_detected,
        NotificationEvent.ERROR_DIAGNOSED: format_error_diagnosed,
        NotificationEvent.FIX_APPLIED: format_fix_applied,
        NotificationEvent.HEAL_COMPLETE: format_heal_complete,
        NotificationEvent.HEAL_FAILED: format_heal_failed,

        # 资源/性能
        NotificationEvent.BUDGET_EXCEEDED: format_budget_exceeded,
        NotificationEvent.RESOURCE_WARNING: format_resource_warning,

        # 通知系统自身
        NotificationEvent.NOTIFICATION_SENT: format_notification_sent,
        NotificationEvent.NOTIFICATION_FAILED: format_notification_failed,

        # 阻塞
        NotificationEvent.BLOCKED: format_blocked,
    }

    formatter = formatters.get(event)
    if formatter:
        return formatter(payload)

    # Fallback
    return f"Event: {event.value}\nSession: {payload.session_id}"

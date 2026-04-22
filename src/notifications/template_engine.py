"""
Template Interpolation Engine - 模板插值引擎

从 oh-my-codex-main/src/notifications/template-engine.ts 迁移而来。

功能:
- Lightweight {{variable}} interpolation with {{#if var}}...{{/if}} conditionals
- No external dependencies
- Produces output matching current formatter functions
- 支持计算变量和条件渲染
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

# Set of known template variables for validation
KNOWN_VARIABLES = {
    # Raw payload fields
    "event", "sessionId", "message", "timestamp", "tmuxSession",
    "projectPath", "projectName", "modesUsed", "contextSummary",
    "durationMs", "agentsSpawned", "agentsCompleted",
    "reason", "activeMode", "iteration", "maxIterations",
    "question", "incompleteTasks", "agentName", "agentType",
    "tmuxTail", "tmuxPaneId",
    # Reply context (from OPENCLAW_REPLY_* env vars; populated in OpenClaw
    # instruction templates, empty in standard notification templates)
    "replyChannel", "replyTarget", "replyThread",
    # Computed variables
    "duration", "time", "modesDisplay", "iterationDisplay",
    "agentDisplay", "projectDisplay", "footer", "tmuxTailBlock",
    "reasonDisplay",
}


def format_duration(ms: int | None) -> str:
    """Format duration from milliseconds to human-readable string.
    
    Mirrors formatDuration() in formatter.ts.
    
    Args:
        ms: Duration in milliseconds (can be None)
        
    Returns:
        Human-readable duration string
    """
    if not ms:
        return "unknown"

    seconds = int(ms / 1000)
    minutes = int(seconds / 60)
    hours = int(minutes / 60)

    if hours > 0:
        return f"{hours}h {minutes % 60}m {seconds % 60}s"
    if minutes > 0:
        return f"{minutes}m {seconds % 60}s"
    return f"{seconds}s"


def get_project_display(payload: dict[str, Any]) -> str:
    """Get project display name from payload.
    
    Mirrors projectDisplay() in formatter.ts.
    
    Args:
        payload: Notification payload
        
    Returns:
        Project display name
    """
    if payload.get("projectName"):
        return str(payload["projectName"])
    if payload.get("projectPath"):
        return Path(payload["projectPath"]).name
    return "unknown"


def build_footer_text(payload: dict[str, Any]) -> str:
    """Build common footer with tmux and project info (markdown).
    
    Mirrors buildFooter(payload, true) in formatter.ts.
    
    Args:
        payload: Notification payload
        
    Returns:
        Formatted footer string
    """
    parts = []
    if payload.get("tmuxSession"):
        parts.append(f"**tmux:** `{payload['tmuxSession']}`")
    parts.append(f"**project:** `{get_project_display(payload)}`")
    return " | ".join(parts)


def build_tmux_tail_block(payload: dict[str, Any]) -> str:
    """Build tmux tail block with code fence, or empty string.
    
    Mirrors buildTmuxTailBlock() in formatter.ts.
    Includes two leading newlines (blank line separator) to match formatter output.
    
    Args:
        payload: Notification payload
        
    Returns:
        Formatted tmux tail block
    """
    tmux_tail = payload.get("tmuxTail")
    if not tmux_tail:
        return ""

    # Simple parsing - in real implementation, this would be more sophisticated
    parsed = str(tmux_tail).strip()
    if not parsed:
        return ""

    return f"\n\n**Recent output:**\n```\n{parsed}\n```"


def compute_template_variables(payload: dict[str, Any]) -> dict[str, str]:
    """Build the full variable map from a notification payload.
    
    Includes raw payload fields (string-converted) and computed variables.
    
    Args:
        payload: Notification payload
        
    Returns:
        Dictionary of template variables
    """
    vars_dict: dict[str, str] = {}

    # Raw payload fields (null/undefined → "")
    vars_dict["event"] = str(payload.get("event", ""))
    vars_dict["sessionId"] = str(payload.get("sessionId", ""))
    vars_dict["message"] = str(payload.get("message", ""))
    vars_dict["timestamp"] = str(payload.get("timestamp", ""))
    vars_dict["tmuxSession"] = str(payload.get("tmuxSession", ""))
    vars_dict["projectPath"] = str(payload.get("projectPath", ""))
    vars_dict["projectName"] = str(payload.get("projectName", ""))
    vars_dict["modesUsed"] = ", ".join(payload["modesUsed"]) if isinstance(payload.get("modesUsed"), list) else str(payload.get("modesUsed", ""))
    vars_dict["contextSummary"] = str(payload.get("contextSummary", ""))
    vars_dict["durationMs"] = str(payload.get("durationMs", "")) if payload.get("durationMs") is not None else ""
    vars_dict["agentsSpawned"] = str(payload.get("agentsSpawned", "")) if payload.get("agentsSpawned") is not None else ""
    vars_dict["agentsCompleted"] = str(payload.get("agentsCompleted", "")) if payload.get("agentsCompleted") is not None else ""
    vars_dict["reason"] = str(payload.get("reason", ""))
    vars_dict["activeMode"] = str(payload.get("activeMode", ""))
    vars_dict["iteration"] = str(payload.get("iteration", "")) if payload.get("iteration") is not None else ""
    vars_dict["maxIterations"] = str(payload.get("maxIterations", "")) if payload.get("maxIterations") is not None else ""
    vars_dict["question"] = str(payload.get("question", ""))
    # incompleteTasks: undefined/null → "" (so {{#if}} is falsy when unset)
    # 0 → "0" (distinguishable from unset; templates can display "0 incomplete tasks")
    incomplete_tasks = payload.get("incompleteTasks")
    vars_dict["incompleteTasks"] = str(incomplete_tasks) if incomplete_tasks is not None else ""
    vars_dict["agentName"] = str(payload.get("agentName", ""))
    vars_dict["agentType"] = str(payload.get("agentType", ""))
    vars_dict["tmuxTail"] = str(payload.get("tmuxTail", ""))
    vars_dict["tmuxPaneId"] = str(payload.get("tmuxPaneId", ""))

    # Computed variables
    vars_dict["duration"] = format_duration(payload.get("durationMs"))
    vars_dict["time"] = ""
    timestamp = payload.get("timestamp")
    if timestamp:
        try:
            # Try to parse ISO timestamp
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            vars_dict["time"] = dt.strftime("%H:%M:%S")
        except (ValueError, AttributeError):
            vars_dict["time"] = str(timestamp)

    vars_dict["modesDisplay"] = ", ".join(payload["modesUsed"]) if isinstance(payload.get("modesUsed"), list) and payload["modesUsed"] else str(payload.get("modesUsed", ""))

    iteration = payload.get("iteration")
    max_iterations = payload.get("maxIterations")
    if iteration is not None and max_iterations is not None:
        vars_dict["iterationDisplay"] = f"{iteration}/{max_iterations}"
    else:
        vars_dict["iterationDisplay"] = ""

    agents_spawned = payload.get("agentsSpawned")
    agents_completed = payload.get("agentsCompleted")
    if agents_spawned is not None:
        completed = agents_completed if agents_completed is not None else 0
        vars_dict["agentDisplay"] = f"{completed}/{agents_spawned} completed"
    else:
        vars_dict["agentDisplay"] = ""

    vars_dict["projectDisplay"] = get_project_display(payload)
    vars_dict["footer"] = build_footer_text(payload)
    vars_dict["tmuxTailBlock"] = build_tmux_tail_block(payload)
    vars_dict["reasonDisplay"] = str(payload.get("reason", "unknown"))

    return vars_dict


def process_conditionals(template: str, vars_dict: dict[str, str]) -> str:
    """Process {{#if var}}...{{/if}} conditionals.
    
    Only simple truthy checks (non-empty string). No nesting, no else.
    
    Args:
        template: Template string with conditionals
        vars_dict: Variable dictionary
        
    Returns:
        Processed template string
    """
    def replace_func(match):
        var_name = match.group(1)
        content = match.group(2)
        value = vars_dict.get(var_name, "")
        return content if value else ""

    return re.sub(r"\{\{#if\s+(\w+)\}\}([\s\S]*?)\{\{/if\}\}", replace_func, template)


def replace_variables(template: str, vars_dict: dict[str, str]) -> str:
    """Replace {{variable}} placeholders with values.
    
    Unknown/missing variables become empty string.
    
    Args:
        template: Template string with variables
        vars_dict: Variable dictionary
        
    Returns:
        Template with variables replaced
    """
    def replace_func(match):
        var_name = match.group(1)
        return vars_dict.get(var_name, "")

    return re.sub(r"\{\{(\w+)\}\}", replace_func, template)


def post_process(text: str) -> str:
    """Post-process interpolated text.
    
    - Trim trailing whitespace
    - Note: No newline collapsing — templates use self-contained conditionals
    - (leading \n inside {{#if}} blocks) to produce exact output.
    
    Args:
        text: Text to post-process
        
    Returns:
        Post-processed text
    """
    return text.rstrip()


def interpolate_template(template: str, payload: dict[str, Any]) -> str:
    """Interpolate a template string with payload values.
    
    1. Process {{#if var}}...{{/if}} conditionals
    2. Replace {{variable}} placeholders
    3. Post-process to normalize blank lines
    
    Args:
        template: Template string
        payload: Notification payload
        
    Returns:
        Interpolated string
    """
    # Step 1: Compute template variables
    vars_dict = compute_template_variables(payload)

    # Step 2: Process conditionals
    processed = process_conditionals(template, vars_dict)

    # Step 3: Replace variables
    replaced = replace_variables(processed, vars_dict)

    # Step 4: Post-process
    return post_process(replaced)


# ===== 便捷函数 =====

def render_notification_template(
    template: str,
    event: str,
    session_id: str,
    message: str,
    timestamp: str | None = None,
    **kwargs
) -> str:
    """Render a notification template with common fields.
    
    Args:
        template: Template string
        event: Notification event type
        session_id: Session ID
        message: Main message content
        timestamp: Optional timestamp (defaults to now)
        **kwargs: Additional payload fields
        
    Returns:
        Rendered notification string
    """
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    payload = {
        "event": event,
        "sessionId": session_id,
        "message": message,
        "timestamp": timestamp,
        **kwargs
    }

    return interpolate_template(template, payload)

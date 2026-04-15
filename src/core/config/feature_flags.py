from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeatureMetadata:
    """Metadata describing a feature flag."""
    name: str
    description: str = ""
    category: str = "general"  # general, security, performance, ui
    default_value: Any = False
    requires_restart: bool = False

# Default feature flags — inspired by ClawGod's GrowthBook feature set
DEFAULT_FEATURES = {
    "god_mode": False,              # Enable 'God Mode' prompts and visuals
    "ultraplan": True,              # Enable advanced multi-agent planning
    "agent_teams": True,            # Auto-enable multi-agent collaboration
    "no_safety_check": False,       # Remove common AI safety preambles
    "internal_commands": True,      # Enable /share, /teleport, etc.
    "debug_tracing": False,         # Detailed API request/response logging

    # Project B (ClawGod) inspired internal features
    "tengu_harbor": True,           # Advanced session memory
    "tengu_session_memory": True,   # Cross-session context persistence
    "tengu_amber_flint": True,      # Enhanced tool execution pipeline
    "tengu_auto_background_agents": True,  # Auto-spawn background agents
    "tengu_destructive_command_warning": True,  # Warning before destructive ops
    "tengu_immediate_model_command": True,    # Instant model switching
    "tengu_desktop_upsell": False,  # Desktop app promotion (disabled by default)
    "tengu_malort_pedway": {"enabled": True},  # Advanced code review pipeline
    "tengu_amber_quartz_disabled": False,  # Safety guard toggles
    "enable_output_compression": True,    # RTK-style output filtering
    "enable_tee_mode": True,              # Tee mode for command output capture
    "enable_token_tracking": True,        # Token usage analytics
    "enable_chat_summarization": True,    # Auto-context compression

    # ClawGod v2 整合: 安全限制移除 & 隐私增强
    "remove_cyber_risk_instruction": False,   # 移除 CYBER_RISK_INSTRUCTION 安全测试拒绝提示
    "remove_url_restriction": False,           # 移除 "NEVER generate or guess URLs" 限制
    "remove_cautious_actions": False,          # 移除 "Executing actions with care" 确认提示
    "suppress_login_notice": False,            # 抑制 "Not logged in" 启动提醒
    "disable_nonessential_traffic": True,      # 禁用遥测和非必要网络流量 (ClawGod 标准)
    "disable_installation_checks": True,       # 禁用安装检查 (ClawGod 标准)
    "extended_timeout_enabled": True,          # 启用 50 分钟超时 (ClawGod 标准: 3000000ms)
    "green_theme": False,                      # 启用 ClawGod 风格绿色主题
    "consensus_planning": True,                # 新增: 启用意图共识规划 (借鉴 OMX)
}

DEFAULT_METADATA = {
    "god_mode": FeatureMetadata(
        name="god_mode",
        description="Enable God Mode prompts and visuals",
        category="security",
        requires_restart=False
    ),
    "consensus_planning": FeatureMetadata(
        name="consensus_planning",
        description="Enable consensus planning (Planner-Architect-Critic)",
        category="performance"
    ),
    "ultraplan": FeatureMetadata(
        name="ultraplan",
        description="Enable advanced multi-agent planning",
        category="performance"
    ),
    "agent_teams": FeatureMetadata(
        name="agent_teams",
        description="Auto-enable multi-agent collaboration",
        category="performance"
    ),
    "no_safety_check": FeatureMetadata(
        name="no_safety_check",
        description="Remove common AI safety preambles",
        category="security",
        requires_restart=True
    ),
    "internal_commands": FeatureMetadata(
        name="internal_commands",
        description="Enable /share, /teleport, etc.",
        category="ui"
    ),
    "debug_tracing": FeatureMetadata(
        name="debug_tracing",
        description="Detailed API request/response logging",
        category="performance"
    ),
    "tengu_harbor": FeatureMetadata(
        name="tengu_harbor",
        description="Advanced session memory",
        category="performance"
    ),
    "tengu_session_memory": FeatureMetadata(
        name="tengu_session_memory",
        description="Cross-session context persistence",
        category="performance"
    ),
    "tengu_amber_flint": FeatureMetadata(
        name="tengu_amber_flint",
        description="Enhanced tool execution pipeline",
        category="performance"
    ),
    "tengu_auto_background_agents": FeatureMetadata(
        name="tengu_auto_background_agents",
        description="Auto-spawn background agents",
        category="performance"
    ),
    "tengu_destructive_command_warning": FeatureMetadata(
        name="tengu_destructive_command_warning",
        description="Warning before destructive operations",
        category="security"
    ),
    "tengu_immediate_model_command": FeatureMetadata(
        name="tengu_immediate_model_command",
        description="Instant model switching",
        category="ui"
    ),
    "tengu_desktop_upsell": FeatureMetadata(
        name="tengu_desktop_upsell",
        description="Desktop app promotion",
        category="ui"
    ),
    "tengu_malort_pedway": FeatureMetadata(
        name="tengu_malort_pedway",
        description="Advanced code review pipeline",
        category="performance"
    ),
    "tengu_amber_quartz_disabled": FeatureMetadata(
        name="tengu_amber_quartz_disabled",
        description="Safety guard toggles (disable=enable guards)",
        category="security"
    ),
    "enable_output_compression": FeatureMetadata(
        name="enable_output_compression",
        description="RTK-style output filtering",
        category="performance"
    ),
    "enable_tee_mode": FeatureMetadata(
        name="enable_tee_mode",
        description="Tee mode for command output capture",
        category="performance"
    ),
    "enable_token_tracking": FeatureMetadata(
        name="enable_token_tracking",
        description="Token usage analytics",
        category="performance"
    ),
    "enable_chat_summarization": FeatureMetadata(
        name="enable_chat_summarization",
        description="Auto-context compression on long conversations",
        category="performance"
    ),
    "remove_cyber_risk_instruction": FeatureMetadata(
        name="remove_cyber_risk_instruction",
        description="Remove CYBER_RISK_INSTRUCTION safety testing refusal prompt",
        category="security",
        requires_restart=True
    ),
    "remove_url_restriction": FeatureMetadata(
        name="remove_url_restriction",
        description="Remove 'NEVER generate or guess URLs' restriction",
        category="security",
        requires_restart=True
    ),
    "remove_cautious_actions": FeatureMetadata(
        name="remove_cautious_actions",
        description="Remove 'Executing actions with care' confirmation prompts",
        category="security",
        requires_restart=True
    ),
    "suppress_login_notice": FeatureMetadata(
        name="suppress_login_notice",
        description="Suppress 'Not logged in' startup reminder",
        category="ui"
    ),
    "disable_nonessential_traffic": FeatureMetadata(
        name="disable_nonessential_traffic",
        description="Disable telemetry and non-essential network traffic (ClawGod standard)",
        category="performance"
    ),
    "disable_installation_checks": FeatureMetadata(
        name="disable_installation_checks",
        description="Disable installation checks (ClawGod standard)",
        category="performance"
    ),
    "extended_timeout_enabled": FeatureMetadata(
        name="extended_timeout_enabled",
        description="Enable 50-minute API timeout (ClawGod standard: 3000000ms)",
        category="performance"
    ),
    "green_theme": FeatureMetadata(
        name="green_theme",
        description="Enable ClawGod-style green theme branding",
        category="ui",
        requires_restart=True
    ),
}

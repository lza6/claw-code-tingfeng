"""Agent Model Table Utilities

Provides utilities for managing agent model configuration tables,
inspired by oh-my-codex's agents-model-table.ts.
"""

import re
from dataclasses import dataclass
from pathlib import Path

OMX_MODELS_START_MARKER = "<!-- OMX:MODELS:START -->"
OMX_MODELS_END_MARKER = "<!-- OMX:MODELS:END -->"


@dataclass
class AgentsModelTableContext:
    """Context for building agent model table."""
    frontier_model: str = "claude-3-sonnet"
    coding_model: str = "claude-3-haiku"
    small_model: str = "gpt-4o-mini"
    budget_model: str = "gpt-4o-mini"
    max_budget_tier: str = "fast"
    max_iterations: int = 10
    default_temperature: float = 0.7
    use_case: str = "general"
    expertise: str = "fullstack"


def resolve_agents_model_table_context(
    config_toml_content: str,
    codex_home: str | None = None,
) -> AgentsModelTableContext:
    """Resolve agent model table context from config.toml.
    
    Args:
        config_toml_content: Content of config.toml
        codex_home: Path to Codex home directory
        
    Returns:
        Resolved context with defaults
    """
    context = AgentsModelTableContext()

    # Parse TOML (simple version - full TOML parsing would use toml library)
    # For now, use regex to extract key values
    frontier_match = re.search(r'frontier_model\s*=\s*["\']([^"\']+)["\']', config_toml_content)
    if frontier_match:
        context.frontier_model = frontier_match.group(1)

    coding_match = re.search(r'coding_model\s*=\s*["\']([^"\']+)["\']', config_toml_content)
    if coding_match:
        context.coding_model = coding_match.group(1)

    small_match = re.search(r'small_model\s*=\s*["\']([^"\']+)["\']', config_toml_content)
    if small_match:
        context.small_model = small_match.group(1)

    budget_match = re.search(r'budget_model\s*=\s*["\']([^"\']+)["\']', config_toml_content)
    if budget_match:
        context.budget_model = budget_match.group(1)

    # Check for max_iterations
    iterations_match = re.search(r'max_iterations\s*=\s*(\d+)', config_toml_content)
    if iterations_match:
        context.max_iterations = int(iterations_match.group(1))

    return context


def build_agents_model_table(
    context: AgentsModelTableContext,
) -> str:
    """Build agent model configuration table in markdown format.
    
    Args:
        context: Agent model table context
        
    Returns:
        Markdown table content
    """
    # Define agent tiers with their models and descriptions
    agent_tiers = [
        {
            "name": "Frontier Agent",
            "model": context.frontier_model,
            "description": "Complex reasoning, architecture, difficult problems",
            "use_case": "strategic",
            "cost_tier": "premium",
        },
        {
            "name": "Coding Agent",
            "model": context.coding_model,
            "description": "Implementation, debugging, refactoring",
            "use_case": "tactical",
            "cost_tier": "balanced",
        },
        {
            "name": "Quick Agent",
            "model": context.small_model,
            "description": "Simple tasks, reviews, quick questions",
            "use_case": "operational",
            "cost_tier": "budget",
        },
    ]

    # Build table
    lines = [
        f"<!-- {OMX_MODELS_START_MARKER} -->",
        "",
        "## Agent Model Configuration",
        "",
        "This table is auto-generated from your config.toml settings.",
        "",
        "| Agent | Model | Use Case | Cost Tier |",
        "|-------|-------|----------|-----------|",
    ]

    for tier in agent_tiers:
        lines.append(
            f"| {tier['name']} | {tier['model']} | {tier['use_case']} | {tier['cost_tier']} |"
        )

    lines.append("")
    lines.append("### Model Details")
    lines.append("")
    lines.append(f"**Frontier** (`{context.frontier_model}`): {agent_tiers[0]['description']}")
    lines.append(f"**Coding** (`{context.coding_model}`): {agent_tiers[1]['description']}")
    lines.append(f"**Quick** (`{context.small_model}`): {agent_tiers[2]['description']}")
    lines.append("")
    lines.append(f"**Max iterations:** {context.max_iterations}")
    lines.append(f"**Default temperature:** {context.default_temperature}")
    lines.append("")
    lines.append(f"<!-- {OMX_MODELS_END_MARKER} -->")

    return "\n".join(lines)


def render_agents_model_table_block(
    context: AgentsModelTableContext,
) -> str:
    """Render the full agent model table block.
    
    Args:
        context: Agent model table context
        
    Returns:
        Complete markdown block
    """
    return build_agents_model_table(context)


def upsert_agents_model_table(
    content: str,
    context: AgentsModelTableContext,
    markers: tuple[str, str] = (OMX_MODELS_START_MARKER, OMX_MODELS_END_MARKER),
) -> str:
    """Update or insert agent model table in content.
    
    Args:
        content: Existing content (e.g., README.md)
        context: Agent model table context
        markers: Start and end markers
        
    Returns:
        Updated content
    """
    start_marker, end_marker = markers
    new_table = build_agents_model_table(context)

    # Check if existing table
    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)

    if start_idx != -1 and end_idx != -1:
        # Replace existing block
        before = content[:start_idx]
        after = content[end_idx + len(end_marker):]
        return before + new_table + after

    # Append to end
    return content + "\n\n" + new_table


def parse_agents_model_table(content: str) -> AgentsModelTableContext | None:
    """Parse agent model table from content.
    
    Args:
        content: Content containing agent model table
        
    Returns:
        Parsed context or None if not found
    """
    start_idx = content.find(OMX_MODELS_START_MARKER)
    end_idx = content.find(OMX_MODELS_END_MARKER)

    if start_idx == -1 or end_idx == -1:
        return None

    table_content = content[start_idx:end_idx + len(OMX_MODELS_END_MARKER)]
    context = AgentsModelTableContext()

    # Extract models using regex
    frontier_match = re.search(r'Frontier.*?`([^`]+)`', table_content)
    if frontier_match:
        context.frontier_model = frontier_match.group(1)

    coding_match = re.search(r'Coding.*?`([^`]+)`', table_content)
    if coding_match:
        context.coding_model = coding_match.group(1)

    small_match = re.search(r'Quick.*?`([^`]+)`', table_content)
    if small_match:
        context.small_model = small_match.group(1)

    return context


def get_agent_model_table(
    config_path: str | None = None,
    codex_home: str | None = None,
) -> str:
    """Get agent model table for insertion into documentation.
    
    Args:
        config_path: Path to config.toml
        codex_home: Codex home directory
        
    Returns:
        Markdown table content
    """
    # Load config.toml
    config_content = ""
    if config_path:
        try:
            config_content = Path(config_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            pass

    # Resolve context
    context = resolve_agents_model_table_context(config_content, codex_home)

    # Build table
    return render_agents_model_table_block(context)

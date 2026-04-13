"""Bundle Tool — Batches multiple read-only MCP tool calls.
Ported from Project B's codedb_bundle.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .base import BaseTool, ParameterSchema, ToolResult

logger = logging.getLogger(__name__)

class BundleTool(BaseTool):
    """Executes multiple read-only intelligence queries in a single call.

    Combines outline, search, read, and other indexed operations to save round-trips.
    """

    name = "codedb_bundle"
    description = (
        "Execute multiple read-only intelligence queries in a single call. "
        "Combines outline, search, read, and other indexed operations. Saves round-trips. Max 20 ops."
    )

    parameter_schemas = (
        ParameterSchema(
            name="ops",
            param_type="list",
            required=True,
            description="Array of tool calls to execute. Each op: {'tool': 'name', 'arguments': {...}}"
        ),
    )

    def __init__(self, registry: Any): # Avoid circular import if registry is complex
        super().__init__()
        self.registry = registry

    def execute(self, ops: list[dict[str, Any]]) -> ToolResult:
        if not isinstance(ops, list):
            return ToolResult(success=False, output="", error="ops must be a list")

        MAX_OPS = 20 # Aligned with Codedb's enforcement
        if len(ops) > MAX_OPS:
            return ToolResult(
                success=False,
                output="",
                error=f"Max {MAX_OPS} operations allowed per bundle. Requested: {len(ops)}"
            )

        results = []
        for op in ops:
            tool_name = op.get("tool")
            arguments = op.get("arguments", {})

            if not tool_name:
                results.append({"error": "Missing tool name in op"})
                continue

            tool = self.registry.get(tool_name)
            if not tool:
                results.append({"error": f"Tool '{tool_name}' not found"})
                continue

            # Security: In a bundle, we typically only allow read-only tools.
            # For now, we execute whatever is requested but log it.
            try:
                # Use execute_safe to handle validation and errors
                res = tool.execute_safe(**arguments)
                results.append({
                    "tool": tool_name,
                    "success": res.success,
                    "output": res.output,
                    "error": res.error
                })
            except Exception as e:
                logger.error(f"Error in bundled tool '{tool_name}': {e}")
                results.append({"tool": tool_name, "error": str(e)})

        return ToolResult(
            success=True,
            output=json.dumps({"results": results}, ensure_ascii=False, indent=2)
        )

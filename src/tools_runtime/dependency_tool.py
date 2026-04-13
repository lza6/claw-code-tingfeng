"""Dependency Tool - Queries reverse dependencies (who imports this file).

Inspired by Codedb's codedb_deps tool.
"""
from __future__ import annotations

from typing import Any

from ..core.dependency_analyzer import DependencyAnalyzer
from .base import BaseTool, ToolResult


class DependencyTool(BaseTool):
    """Tool to find which files import another file (reverse dependencies)."""

    name = "dependency_query"
    description = (
        "Find which files in the project import or depend on a given file. "
        "Useful for understanding the impact of a change or tracing usages."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file to check for dependencies."
            },
            "recursive": {
                "type": "boolean",
                "description": "Whether to check for nested dependencies (default false).",
                "default": False
            }
        },
        "required": ["path"]
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        rel_path = kwargs.get("path", "")
        recursive = kwargs.get("recursive", False)

        if not rel_path:
            return ToolResult(output="错误: 必须提供路径。", exit_code=1)

        analyzer = DependencyAnalyzer(self.workdir)
        # In a real scenario, we'd use a pre-built graph from the SearchEngine/Index
        # Here we scan the project to build the graph on the fly (or reuse if available)
        self._build_graph(analyzer)

        importers = analyzer.graph.get_importers(rel_path)

        if not importers:
            return ToolResult(output=f"未找到引用 '{rel_path}' 的文件。")

        output = [f"引用 '{rel_path}' 的文件:"]
        for imp in sorted(importers):
            output.append(f"- {imp}")
            if recursive:
                # Add second-level importers
                second_level = analyzer.graph.get_importers(imp)
                for s_imp in sorted(second_level):
                    if s_imp != rel_path and s_imp not in importers:
                        output.append(f"  └─ {s_imp}")

        return ToolResult(output="\n".join(output))

    def _build_graph(self, analyzer: DependencyAnalyzer):
        """Build the dependency graph by scanning files."""
        # Simple implementation: scan files with relevant extensions
        for ext in ('.py', '.ts', '.js', '.zig'):
            for path in self.workdir.rglob(f'*{ext}'):
                if path.is_file():
                    try:
                        content = path.read_text(errors='ignore')
                        rel = str(path.relative_to(self.workdir))
                        analyzer.analyze_file(rel, content)
                    except Exception:
                        continue

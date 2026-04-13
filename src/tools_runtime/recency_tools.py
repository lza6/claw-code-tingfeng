"""Recency and Dependency Tools — Ported from Project B.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..rag.symbol_extractor import SymbolExtractor
from ..utils.recency import RecencyTracker
from .base import BaseTool, ParameterSchema, ToolResult

if TYPE_CHECKING:
    from ..rag.text_indexer import TextIndexer

logger = logging.getLogger(__name__)

class HotFilesTool(BaseTool):
    """Get the most recently modified files in the codebase."""

    name = "codedb_hot"
    description = "Get the most recently modified files in the codebase, ordered by recency."

    parameter_schemas = (
        ParameterSchema(
            name="limit",
            param_type="int",
            required=False,
            default=10,
            description="Number of files to return (default: 10)"
        ),
    )

    def __init__(self, tracker: RecencyTracker):
        super().__init__()
        self.tracker = tracker

    def execute(self, limit: int = 10) -> ToolResult:
        try:
            hot_files = self.tracker.get_hot_files(limit=limit)
            return ToolResult(
                success=True,
                output=json.dumps({"hot_files": hot_files}, indent=2)
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

class DependencyTool(BaseTool):
    """Get reverse dependencies for a file."""

    name = "codedb_deps"
    description = "Get reverse dependencies: which files import/depend on the given file."

    parameter_schemas = (
        ParameterSchema(
            name="path",
            param_type="str",
            required=True,
            description="File path to check dependencies for"
        ),
    )

    def __init__(self, root_dir: str | Path, indexer: TextIndexer | None = None):
        super().__init__()
        self.root_dir = Path(root_dir)
        self.extractor = SymbolExtractor()
        self.indexer = indexer

    def execute(self, path: str) -> ToolResult:
        """Execute the dependency check.

        If an indexer is available, uses the pre-built dependency graph (O(1)).
        Otherwise, falls back to a directory-wide grep (O(N)).
        """
        try:
            # Try high-performance index-based lookup first
            if self.indexer and hasattr(self.indexer, 'get_imported_by'):
                dependents = self.indexer.get_imported_by(path)
                return ToolResult(
                    success=True,
                    output=json.dumps({"imported_by": dependents, "source": "index"}, indent=2)
                )

            # Fallback to slow grep-based implementation
            target_path = Path(path)
            search_term = target_path.name # Use basename for broader matching

            dependents = []

            import os
            # Optimization: limit grep search if possible, but here we do full scan for accuracy
            for root, _, files in os.walk(self.root_dir):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix not in ('.py', '.ts', '.js', '.zig', '.rs', '.go'):
                        continue
                    if file_path == self.root_dir / target_path:
                        continue

                    try:
                        content = file_path.read_text(errors='ignore')
                        if search_term in content:
                            dependents.append(str(file_path.relative_to(self.root_dir)))
                    except Exception:
                        continue

            return ToolResult(
                success=True,
                output=json.dumps({"imported_by": dependents, "source": "grep_fallback"}, indent=2)
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

"""Dependency Analyzer - Traces imports and builds a reverse dependency graph.

Ported from Project B (Codedb) Zig implementation.
"""
from __future__ import annotations

import collections
import re
from pathlib import Path


class DepGraph:
    """Reverse dependency graph.

    Maps file -> set of files that import it.
    """
    def __init__(self):
        # path -> set of paths that import it
        self.importers: dict[str, set[str]] = collections.defaultdict(set)
        # path -> set of paths that this file imports (forward)
        self.exports: dict[str, set[str]] = collections.defaultdict(set)

    def remove_file(self, path: str):
        """Remove a file from the graph."""
        if path in self.exports:
            imported_files = self.exports.pop(path)
            for imp in imported_files:
                if imp in self.importers:
                    self.importers[imp].discard(path)
                    if not self.importers[imp]:
                        self.importers.pop(imp)

        # Also remove this file as an importer of others
        if path in self.importers:
            # This is harder to remove without scanning everything,
            # but usually we only care about who imports THIS file.
            pass

    def add_import(self, importer: str, imported: str):
        """Record that 'importer' imports 'imported'."""
        self.importers[imported].add(importer)
        self.exports[importer].add(imported)

    def get_importers(self, path: str) -> set[str]:
        """Who imports this file?"""
        return self.importers.get(path, set())

    def get_imports(self, path: str) -> set[str]:
        """What does this file import?"""
        return self.exports.get(path, set())

class DependencyAnalyzer:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.graph = DepGraph()

    def analyze_file(self, rel_path: str, content: str):
        """Parse imports from content and update graph."""
        self.graph.remove_file(rel_path)

        # Regex-based import extraction (supports Python, JS/TS, Zig)
        imports = self._extract_imports(rel_path, content)
        for imp in imports:
            resolved = self._resolve_path(rel_path, imp)
            if resolved:
                self.graph.add_import(rel_path, resolved)

    def _extract_imports(self, path: str, content: str) -> list[str]:
        """Extraction logic for different languages."""
        suffix = Path(path).suffix
        found = []

        if suffix == '.py':
            # import foo, from foo import bar
            # Handles 'from .utils import file_ops' -> '.utils'
            patterns = [
                r'^import\s+([\w\.]+)',
                r'^from\s+([\w\.]+)\s+import'
            ]
            for p in patterns:
                found.extend(re.findall(p, content, re.MULTILINE))

        elif suffix in ('.ts', '.js', '.tsx', '.jsx'):
            # import { x } from './y', import x from 'y'
            # require('./y')
            patterns = [
                r"from\s+['\"]([^'\"]+)['\"]",
                r"import\s+['\"]([^'\"]+)['\"]",
                r"require\(['\"]([^'\"]+)['\"]\)"
            ]
            for p in patterns:
                found.extend(re.findall(p, content))

        elif suffix == '.zig':
            # @import("foo.zig"), @import("std"), etc.
            patterns = [
                r'@import\("([^"]+)"\)'
            ]
            for p in patterns:
                found.extend(re.findall(p, content))

            # Also catch using namespace @import(...)
            patterns_ns = [
                r'usingnamespace\s+@import\("([^"]+)"\)'
            ]
            for p in patterns_ns:
                found.extend(re.findall(p, content))

        return found

    def _resolve_path(self, importer_rel: str, import_str: str) -> str | None:
        """Resolve import string to a relative path within the project."""
        # This is a simplified resolution logic.
        # Real resolution depends on PYTHONPATH, node_modules, etc.
        # For Claw/Codedb, we focus on local project imports.

        importer_path = self.root_dir / importer_rel
        parent_dir = importer_path.parent

        # 1. Handle relative imports like '.utils', './foo'
        if import_str.startswith('.'):
            # Python style: .utils, ..core
            # JS style: ./utils, ../core
            dots = 0
            while dots < len(import_str) and import_str[dots] == '.':
                dots += 1

            clean_path = import_str[dots:].replace('.', '/')
            if clean_path.startswith('/'):
                clean_path = clean_path[1:]

            parts = parent_dir.parts
            target_parts = parts[:-dots] if dots > 1 else parts
            target_dir = Path(*target_parts)

            # Try to find the file
            for ext in ('.py', '.ts', '.js', '.zig', ''):
                candidate = target_dir / (clean_path + ext)
                if candidate.is_file():
                    try:
                        return str(candidate.relative_to(self.root_dir))
                    except ValueError:
                        pass

        # 2. Handle absolute project imports or standard imports
        # Check if it matches any project file by treating import_str as a path
        try:
            # Replace dots with slashes for Python-style absolute imports if no slash exists
            clean_import = import_str
            if '.' in import_str and '/' not in import_str:
                clean_import = import_str.replace('.', '/')

            candidate = self.root_dir / clean_import
            for ext in ('.py', '.ts', '.js', '.zig', '/__init__.py', '.tsx', '.jsx'):
                full_cand = candidate.with_suffix(ext) if not ext.startswith('/') else candidate / '__init__.py'
                if full_cand.is_file():
                    return str(full_cand.relative_to(self.root_dir))

            # Fuzzy match: if import_str is just a filename, look for it in the project
            # (matches Codedb's broader identifier lookup)
            import_name = Path(import_str).name
            for cand in self.root_dir.rglob(f"{import_name}*"):
                if cand.is_file() and cand.suffix in ('.py', '.ts', '.js', '.zig', '.tsx', '.jsx'):
                    return str(cand.relative_to(self.root_dir))

        except Exception:
            pass

        return None

"""Ignore Parser — Ported and Adapted from Project B

Provides .gitignore and .clawdignore parsing and matching logic.
Uses standard library fnmatch for pattern matching.
"""
from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path


class IgnoreFilter:
    """A robust hierarchical .gitignore parser matching Project B behavior.

    Provides .gitignore and .clawdignore parsing and matching logic with
    correct support for nested directories and negation.
    """

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.cache: dict[Path, list[str]] = {}
        self.global_patterns: list[str] = ['.git']
        self._load_global_excludes()

    def _load_global_excludes(self) -> None:
        """Load patterns from .git/info/exclude (Ported from Project B)."""
        exclude_file = self.project_root / '.git' / 'info' / 'exclude'
        if exclude_file.exists():
            self.global_patterns.extend(self.load_ignore_file(exclude_file))

    def _normalize_pattern(self, pattern: str, base_dir: Path) -> str | None:
        """Normalizes a gitignore pattern to be relative to project root.

        Matches Project B's loadPatternsForFile anchoring logic.
        """
        pattern = pattern.strip()
        if not pattern or pattern.startswith('#'):
            return None

        is_negative = pattern.startswith('!')
        if is_negative:
            pattern = pattern[1:]

        is_anchored = pattern.startswith('/')
        if is_anchored:
            pattern = pattern[1:]

        # Handle directory-only patterns
        is_dir_only = pattern.endswith('/')
        if is_dir_only:
            pattern = pattern[:-1]

        try:
            rel_base = base_dir.relative_to(self.project_root)
        except ValueError:
            # If base_dir is outside project root, treat as root
            rel_base = Path('.')

        if rel_base == Path('.'):
            new_pattern = pattern
        else:
            # Anchoring logic from Project B:
            # If no slash and not anchored, it matches in any subdirectory
            if not is_anchored and '/' not in pattern:
                new_pattern = f"**/{pattern}"
            else:
                new_pattern = str(rel_base / pattern)

        # Normalize to forward slashes
        new_pattern = new_pattern.replace('\\', '/')

        # Absolute anchor for patterns originating from ignore files
        if not new_pattern.startswith('/'):
            new_pattern = '/' + new_pattern

        if is_negative:
            new_pattern = '!' + new_pattern

        return new_pattern

    def load_ignore_file(self, file_path: Path) -> list[str]:
        """Loads patterns from a .gitignore style file."""
        if not file_path.exists():
            return []

        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
            base_dir = file_path.parent
            patterns = []
            for line in content.splitlines():
                if not line.strip() or line.startswith('#'):
                    continue
                p = self._normalize_pattern(line, base_dir)
                if p:
                    patterns.append(p)
            return patterns
        except Exception:
            return []

    def is_ignored(self, file_path: str | Path) -> bool:
        """Checks if a path is ignored (Matches Project B's recursive check)."""
        target_path = Path(file_path)
        if target_path.is_absolute():
            try:
                rel_path = target_path.relative_to(self.project_root)
            except ValueError:
                return False
        else:
            rel_path = target_path

        # Normalize path for matching (forward slashes, no double slashes)
        norm_path = ('/' + str(rel_path).replace('\\', '/')).replace('//', '/')

        # 1. Check global/root patterns
        active_patterns = self._get_cached_patterns(self.project_root).copy()
        active_patterns.extend(self.global_patterns)

        if self._check_patterns(norm_path, active_patterns):
            return True

        # 2. Hierarchical check (Project B logic: walk down and prune)
        path_parts = rel_path.parts
        current_abs_dir = self.project_root

        for i in range(len(path_parts) - 1):
            current_abs_dir = current_abs_dir / path_parts[i]
            rel_dir = '/' + str(current_abs_dir.relative_to(self.project_root)).replace('\\', '/')

            # If this directory is already ignored, everything inside is ignored
            if self._check_patterns(rel_dir, active_patterns):
                return True

            # Accumulate patterns from .gitignore in this sub-directory
            level_patterns = self._get_cached_patterns(current_abs_dir)
            if level_patterns:
                 active_patterns.extend(level_patterns)

            if self._check_patterns(norm_path, active_patterns):
                return True

        return self._check_patterns(norm_path, active_patterns)

    def _get_cached_patterns(self, directory: Path) -> list[str]:
        """Gets patterns for a directory, using cache."""
        if directory in self.cache:
            return self.cache[directory]

        patterns = self.load_ignore_file(directory / '.gitignore')
        # Also check for .clawdignore (Project A specific)
        patterns.extend(self.load_ignore_file(directory / '.clawdignore'))

        self.cache[directory] = patterns
        return patterns

    def _check_patterns(self, norm_path: str, patterns: list[str]) -> bool:
        """Evaluate path against a list of patterns with negation support."""
        ignored = False
        for p in patterns:
            if p.startswith('!'):
                if self._match_pattern(norm_path, p[1:]):
                    ignored = False
            else:
                if self._match_pattern(norm_path, p):
                    ignored = True
        return ignored

    def _match_pattern(self, path: str, pattern: str) -> bool:
        """Helper to match a path against a glob pattern."""
        # Normalize pattern to remove leading / for fnmatch if needed,
        # but keep it if we want it anchored to root.

        # Convert gitignore glob to regex for better accuracy than fnmatch
        try:
            regex = self._pattern_to_regex(pattern)
            return bool(re.match(regex, path))
        except Exception:
            # Fallback to simple fnmatch
            return fnmatch(path, pattern) or fnmatch(path.lstrip('/'), pattern)

    def _pattern_to_regex(self, pattern: str) -> str:
        """Converts a gitignore-style glob pattern to a regular expression.

        Robust implementation following gitignore rules.
        """
        p = pattern
        is_dir_only = p.endswith('/')
        if is_dir_only:
            p = p[:-1]

        # Escape special regex chars
        res = re.escape(p)

        # Replace escaped stars/questions with regex equivalents
        # \*\* is special: matches zero or more directories
        res = res.replace(r'\*\*/', '(?:.*/)?') # middle or start **/
        res = res.replace(r'/\*\*', '(?:/.*)?') # end /**
        res = res.replace(r'\*\*', '.*')         # other **
        res = res.replace(r'\*', '[^/]*')       # single *
        res = res.replace(r'\?', '[^/]')        # ?

        # If it was dir only, it must match a directory (ends with / or followed by /)
        if is_dir_only:
            return f"^{res}(?:/.*)?$"

        # Otherwise it can match a file or directory
        return f"^{res}(?:/.*)?$"

def get_ignore_filter(root: str | Path) -> IgnoreFilter:
    """Factory function to get an IgnoreFilter."""
    return IgnoreFilter(root)

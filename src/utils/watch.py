"""File Watcher - File change monitoring from Aider

Adapted from aider/watch.py
Provides: Watch files for changes and AI comment detection
"""

import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern


def load_gitignores(gitignore_paths: list[Path]) -> PathSpec | None:
    """Load and parse .gitignore files into a PathSpec."""
    if not gitignore_paths:
        return None

    # Default ignore patterns
    patterns = [
        ".aider*",
        ".git",
        "*~", "*.bak", "*.swp", "*.swo", "\\#*\\#", ".#*",
        "*.tmp", "*.temp", "*.orig",
        "*.pyc", "__pycache__/",
        ".DS_Store", "Thumbs.db",
        "*.svg", "*.pdf",
        ".idea/", ".vscode/", "*.sublime-*",
        ".project", ".settings/", "*.code-workspace",
        ".env", ".venv/", "node_modules/", "vendor/",
        "*.log", ".cache/", ".pytest_cache/", "coverage/",
    ]

    for path in gitignore_paths:
        if path.exists():
            try:
                with open(path) as f:
                    patterns.extend(f.readlines())
            except OSError:
                pass

    return PathSpec.from_lines(GitWildMatchPattern, patterns) if patterns else None


# AI comment detection pattern
AI_COMMENT_PATTERN = re.compile(
    r"(?:#|//|--|;+) *(ai\b.*|ai\b.*|.*\bai[?!]?) *$",
    re.IGNORECASE
)


class FileWatcher:
    """Watch source files for changes and AI comments."""

    def __init__(
        self,
        root: Path,
        gitignores: list[str] | None = None,
        verbose: bool = False,
        on_change: Callable[..., Any] | None = None
    ):
        self.root = Path(root)
        self.verbose = verbose
        self.on_change = on_change
        self.changed_files: set[str] = set()
        self._stop_event = threading.Event()
        self._watcher_thread: threading.Thread | None = None

        # Load gitignore
        self.gitignore_spec = load_gitignores(
            [Path(g) for g in gitignores] if gitignores else []
        )

    def get_roots_to_watch(self) -> list[str]:
        """Get root paths to watch based on gitignore."""
        if self.gitignore_spec:
            roots = [
                str(p) for p in self.root.iterdir()
                if not self.gitignore_spec.match_file(
                    p.relative_to(self.root).as_posix() + ("/" if p.is_dir() else "")
                )
            ]
            return roots if roots else [str(self.root)]
        return [str(self.root)]

    def should_watch(self, path: Path) -> bool:
        """Check if path should be watched."""
        path_abs = path.absolute()

        # Must be within root
        if not path_abs.is_relative_to(self.root.absolute()):
            return False

        # Check gitignore
        rel_path = path_abs.relative_to(self.root)
        if self.gitignore_spec and self.gitignore_spec.match_file(
            rel_path.as_posix() + ("/" if path_abs.is_dir() else "")
        ):
            return False

        # Skip large files (>1MB)
        return not (path_abs.is_file() and path_abs.stat().st_size > 1024 * 1024)

    def has_ai_comment(self, file_path: Path) -> bool:
        """Check if file contains AI markers."""
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read(8192)  # Read first 8KB
            return bool(AI_COMMENT_PATTERN.search(content))
        except Exception:
            return False

    def on_file_change(self, file_path: str):
        """Handle a file change event."""
        path = Path(file_path)

        if not self.should_watch(path):
            return

        # Check for AI comments
        if self.has_ai_comment(path):
            self.changed_files.add(file_path)
            if self.verbose:
                print(f"AI comment detected in: {path}")

            if self.on_change:
                self.on_change(file_path)

    def start(self):
        """Start watching for file changes."""
        if self._watcher_thread and self._watcher_thread.is_alive():
            return

        self._stop_event.clear()
        self._watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watcher_thread.start()

    def stop(self):
        """Stop watching for file changes."""
        self._stop_event.set()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=2)

    def _watch_loop(self):
        """Main watch loop."""
        try:
            from watchfiles import watch
        except ImportError:
            return

        roots = self.get_roots_to_watch()
        if not roots:
            return

        try:
            for changes in watch(*roots, stop_event=self._stop_event):
                for change_type, path in changes:
                    if change_type in (1, 2):  # Modified or Created
                        self.on_file_change(path)
        except Exception as e:
            if self.verbose:
                print(f"Watcher error: {e}")

    def get_changed_files(self) -> set[str]:
        """Get set of changed files."""
        return self.changed_files.copy()

    def clear_changed(self):
        """Clear the changed files set."""
        self.changed_files.clear()


def is_available() -> bool:
    """Check if file watcher is available."""
    try:
        from watchfiles import watch
        return True
    except ImportError:
        return False


__all__ = [
    "FileWatcher",
    "is_available",
    "load_gitignores",
]

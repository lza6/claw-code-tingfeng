"""Path Security Utilities — Ported from Project B

Provides robust validation and filtering for filesystem operations to prevent
path traversal and unintended exposure of sensitive files (.env, keys, etc).
"""
from __future__ import annotations

import os
from pathlib import Path

# Paths that should NEVER be indexed or read by the AI agent
SENSITIVE_PATTERNS = frozenset({
    '.env', '.env.local', '.env.development', '.env.production',
    'id_rsa', 'id_ed25519', '.pem', '.key', 'credentials.json',
    'secrets.yaml', 'secrets.json', 'passwd', 'shadow'
})

# Directories to always skip
FORBIDDEN_DIRS = frozenset({
    '.git', '.svn', '.hg', 'CVS', '__pycache__', 'node_modules',
    '.venv', 'venv', 'env', '.clawd'
})

def is_sensitive_file(path: str | Path) -> bool:
    """Check if a file matches known sensitive name patterns."""
    basename = os.path.basename(str(path)).lower()

    # Direct match or suffix match (e.g. .env.test)
    return bool(any(p in basename for p in SENSITIVE_PATTERNS))

def validate_path(path: str | Path, base_path: Path) -> Path:
    """Validate that a path is safe and within the base_path boundary.

    Prevents path traversal attacks.
    """
    base = base_path.resolve()
    target = Path(path).expanduser()

    # If target is relative, make it relative to base
    if not target.is_absolute():
        target = (base / target).resolve()
    else:
        target = target.resolve()

    # Boundary check — use is_relative_to for robust path traversal prevention
    if not target.is_relative_to(base):
        raise PermissionError(f"Adversarial path detected: {path} is outside of {base}")

    # Sensitive file check
    if is_sensitive_file(target):
        raise PermissionError(f"Access denied to sensitive file: {target.name}")

    # Forbidden directory check
    for part in target.parts:
        if part in FORBIDDEN_DIRS:
            raise PermissionError(f"Access denied to forbidden directory: {part}")

    return target

def filter_files_for_indexing(file_paths: list[Path]) -> list[Path]:
    """Prune paths that should not be indexed."""
    allowed = []
    for fp in file_paths:
        try:
            # Check components
            if any(part in FORBIDDEN_DIRS for part in fp.parts):
                continue
            if is_sensitive_file(fp):
                continue
            allowed.append(fp)
        except Exception:
            continue
    return allowed

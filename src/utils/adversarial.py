"""Adversarial Security - Protects against malicious paths and shell injections.

Ported from Project B (Codedb) Zig/Adversarial implementation.
"""
from __future__ import annotations

import re
from pathlib import Path


class PathValidator:
    """Validates file paths to prevent traversal and access to sensitive files."""

    # Sensitive file patterns from Codedb (Aligned with index.zig)
    SENSITIVE_PATTERNS = [
        r'\.env', r'credentials\.json', r'secrets\..*', r'\.pem$', r'\.key$',
        r'passwd$', r'shadow$', r'authorized_keys$', r'config\.json$',
        r'\.db$', r'id_rsa', r'id_ed25519', r'aws/config', r'ssh/config'
    ]

    # Paths that should NEVER be indexed or accessed (from root_policy.zig)
    NOT_ALLOWED_PATHS = [
        '.git', 'node_modules', 'zig-cache', 'zig-out', '__pycache__',
        '.claude', '.clawd', '.gemini', '.pytest_cache', '.ruff_cache'
    ]

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()

    def is_safe(self, path_str: str) -> bool:
        """Check if a path is safe to access."""
        try:
            # 1. Prevent path traversal using resolve()
            path = Path(path_str)
            if not path.is_absolute():
                path = (self.root_dir / path).resolve()
            else:
                path = path.resolve()

            # Must be within root_dir
            if not str(path).startswith(str(self.root_dir)):
                return False

            # 3. Block sensitive files
            filename = path.name
            for p in self.SENSITIVE_PATTERNS:
                if re.search(p, filename, re.IGNORECASE):
                    return False

            # 4. Block not allowed paths in any part of the path
            parts = path.relative_to(self.root_dir).parts
            for part in parts:
                if part in self.NOT_ALLOWED_PATHS:
                    return False

            # 5. Block special files
            if path.is_reserved(): # Windows specific (CON, PRN, etc.)
                return False

            return True
        except Exception:
            return False

class CommandValidator:
    """Analyzes shell commands for potentially dangerous behavior."""

    # Dangerous commands or patterns
    DANGEROUS_PATTERNS = [
        r'rm\s+-rf\s+/',           # Delete root
        r'chmod\s+777',             # Overly permissive
        r'>\s+/dev/null',           # Suppressing output might hide malicious activity
        r'curl\s+.*\|\s+sh',        # Direct pipe to shell
        r'nc\s+-e',                 # Reverse shell
        r'rm\s+.*\.db',             # Deleting databases
        r'kill\s+-9\s+-1',          # Kill all processes
        r'mkfs\.',                   # Format disk
        r'dd\s+if=/dev/zero'        # Wipe disk
    ]

    @staticmethod
    def is_safe(command: str) -> bool:
        """Check if a shell command is safe."""
        command_clean = command.strip()

        # 1. Block dangerous patterns
        for p in CommandValidator.DANGEROUS_PATTERNS:
            if re.search(p, command_clean, re.IGNORECASE):
                return False

        # 2. Block chaining with sensitive files
        if '>>' in command_clean or '>' in command_clean:
            if '.env' in command_clean or '.key' in command_clean:
                return False

        return True

def validate_path(root_dir: Path, path_str: str) -> bool:
    return PathValidator(root_dir).is_safe(path_str)

def validate_command(command: str) -> bool:
    return CommandValidator.is_safe(command)

"""Atomic File Operations — Ported from Project B

Features:
- Atomic write: write to temp file then rename to ensure file integrity.
- Windows-safe rename: retries on EPERM/EACCES errors.
"""
from __future__ import annotations

import builtins
import contextlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def get_file_info(path: str | Path) -> dict[str, Any] | None:
    """Get metadata for a file (mtime, size).

    Matches Project B's cheap stat check in watcher.zig.
    """
    path = Path(path)
    try:
        if not path.is_file():
            return None
        stat = path.stat()
        return {
            "mtime": int(stat.st_mtime * 1000), # ms since epoch
            "size": stat.st_size
        }
    except OSError:
        return None

def is_binary(data: bytes | None, sample_size: int = 512) -> bool:
    """Checks if a bytes buffer is likely binary by testing for NULL bytes.

    Ported from Project B's isBinary.
    """
    if not data:
        return False

    sample = data[:sample_size]
    return b'\x00' in sample

def normalize_content(content: str) -> str:
    """Normalizes text content by stripping UTF-8 BOM and unifying line endings to LF.

    Ported from Project B's normalizeContent.
    """
    # Strip UTF-8 BOM
    if content.startswith('\ufeff'):
        content = content[1:]

    # Normalize line endings to LF (\n)
    return content.replace('\r\n', '\n').replace('\r', '\n')

def atomic_write(file_path: str | Path, content: str | bytes, encoding: str = 'utf-8', retries: int = 3) -> None:
    """Writes content to a file atomically by using a temporary file and renaming it.

    Enhanced for Windows (Ported from Project B):
    - Uses random hex suffix for temp file to avoid collisions.
    - Explicit retry with exponential backoff on locked files.
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Use secrets for cryptographically safe random suffix (Matches Project B's crypto.randomBytes)
    suffix = secrets.token_hex(4)
    temp_path = file_path.with_name(f"{file_path.name}.{suffix}.tmp")

    try:
        if isinstance(content, str):
            temp_path.write_text(content, encoding=encoding)
        else:
            temp_path.write_bytes(content)

        # Rename temp file to target path
        _rename_with_retry(str(temp_path), str(file_path), retries=retries)
    except Exception as e:
        if temp_path.exists():
            with contextlib.suppress(builtins.BaseException):
                temp_path.unlink()
        raise e

def atomic_write_json(file_path: str | Path, data: Any, indent: int = 2, retries: int = 3) -> None:
    """Atomically write JSON data to a file."""
    content = json.dumps(data, indent=indent, ensure_ascii=False)
    atomic_write(file_path, content, retries=retries)

def _rename_with_retry(src: str, dest: str, retries: int = 3, delay_ms: int = 50) -> None:
    """Atomically rename a file with retries for Windows compatibility (EPERM/EACCES).

    Matches Project B's renameWithRetry behavior.
    """
    for attempt in range(retries + 1):
        try:
            # os.replace handles existing file on Windows (equivalent to fs.rename behavior in Node)
            os.replace(src, dest)
            return
        except (PermissionError, OSError) as e:
            # On Windows, PermissionError (EPERM) or OSError with code 13/32 is common
            # EPERM (13): Permission denied
            # EACCES (13): Permission denied
            # ERROR_SHARING_VIOLATION (32): File in use
            is_retryable = (
                isinstance(e, PermissionError) or
                (hasattr(e, 'errno') and e.errno in (13, 32)) or
                (hasattr(e, 'winerror') and e.winerror in (13, 32))
            )

            if not is_retryable or attempt == retries:
                logger.error(f"Failed to rename {src} to {dest} (attempt {attempt+1}/{retries+1}): {e}")
                raise e

            # Exponential backoff (Match Project B: delayMs * 2 ** attempt)
            sleep_time = (delay_ms * (2 ** attempt)) / 1000.0
            logger.warning(f"File locked or access denied ({e.errno if hasattr(e, 'errno') else 'unknown'}), retrying rename ({attempt+1}/{retries}) in {sleep_time:.3f}s...")
            time.sleep(sleep_time)

def write_with_backup(file_path: str | Path, content: str | bytes, backup_suffix: str = '.bak', encoding: str = 'utf-8') -> None:
    """Safely writes content to a file with backup protection.

    Ported from Project B's writeWithBackup:
    1. Write content to a temporary file.
    2. If target exists, rename it to backup_suffix.
    3. Rename temp file to target.
    4. If failure occurs during rename, attempt to restore from backup.
    """
    file_path = Path(file_path)
    temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    backup_path = file_path.with_suffix(file_path.suffix + backup_suffix)

    # Step 1: Write to temporary file
    try:
        if isinstance(content, str):
            temp_path.write_text(content, encoding=encoding)
        else:
            temp_path.write_bytes(content)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise e

    # Step 2: If target exists, back it up
    exists = file_path.exists()
    if exists:
        try:
            _rename_with_retry(str(file_path), str(backup_path))
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to backup existing file: {e}") from e

    # Step 3: Rename temp file to target
    try:
        _rename_with_retry(str(temp_path), str(file_path))
    except Exception as e:
        # Step 4: Attempt recovery
        restore_failed = False
        if backup_path.exists():
            try:
                _rename_with_retry(str(backup_path), str(file_path))
            except Exception as restore_err:
                restore_failed = True
                logger.error(f"Automatic restore failed: {restore_err}")

        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

        if restore_failed:
            raise RuntimeError(f"Failed to write file: {e}. Restore failed. Manual recovery required from {backup_path}") from e
        elif exists:
            raise RuntimeError(f"Failed to write file: {e}. Target restored from backup.") from e
        else:
            raise RuntimeError(f"Failed to write file: {e}. No backup available.") from e


def apply_line_edit(file_path: str | Path, start_line: int, end_line: int, new_content: str) -> str:
    """Applies a line-range edit to a file.

    Ported from Project B (codedb_edit):
    - start_line: 1-indexed start line (inclusive).
    - end_line: 1-indexed end line (inclusive).
    - new_content: The new text to put in that range.

    If start_line > total_lines, it appends to the end.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        if start_line == 1:
            atomic_write(file_path, new_content)
            return new_content
        raise FileNotFoundError(f"File not found: {file_path}")

    content = file_path.read_text(encoding='utf-8', errors='replace')
    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    # Convert to 0-indexed
    s = max(0, start_line - 1)
    e = min(total_lines, end_line)

    # Reconstruct content
    new_lines = [*lines[:s], new_content + ('\n' if not new_content.endswith('\n') else ''), *lines[e:]]
    final_content = "".join(new_lines)

    atomic_write(file_path, final_content)
    return final_content


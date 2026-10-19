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
import shutil
import threading
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

def atomic_write(file_path: str | Path, content: str | bytes, encoding: str = 'utf-8', retries: int = 8) -> None:
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

def atomic_write_json(file_path: str | Path, data: Any, indent: int = 2, retries: int = 8) -> None:
    """Atomically write JSON data to a file."""
    content = json.dumps(data, indent=indent, ensure_ascii=False)
    atomic_write(file_path, content, retries=retries)

_lock_state = threading.local()


@contextlib.contextmanager
def file_lock(file_path: str | Path, timeout: float = 10.0, stale_after: float = 60.0):
    """跨平台、**可重入**的文件锁（原子 `mkdir` + owner token）。

    - 同一线程重复获取同一把锁直接放行：读改写函数内部再调用
      `locked_atomic_write_json` 时不会自锁；
    - 锁目录内写入 `pid-随机串`，释放时只删除自己持有的锁；
    - 陈旧锁通过原子 rename 回收，避免与刚获得锁的新持有者竞争；
    - 不依赖 fcntl/msvcrt，Windows 可用。

    Args:
        file_path: 被保护的**目标文件**路径（锁目录为同级的 `<name>.lock`）。
        timeout: 获取锁的最长等待秒数。
        stale_after: 锁目录超过该秒数视为陈旧并回收；<=0 表示不回收。
    """
    lock_dir = Path(str(file_path) + '.lock')
    key = str(lock_dir)

    held = getattr(_lock_state, 'held', None)
    if held is None:
        held = {}
        _lock_state.held = held

    # 可重入：同一线程已经持有 -> 直接进入
    if key in held:
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return

    deadline = time.monotonic() + timeout
    owner = f'{os.getpid()}-{secrets.token_hex(8)}'
    owner_written = False

    while True:
        try:
            lock_dir.mkdir(parents=True, exist_ok=False)
            try:
                (lock_dir / 'owner').write_text(owner, encoding='utf-8')
                owner_written = True
            except OSError:
                pass
            break
        except FileExistsError:
            try:
                is_stale = (
                    stale_after > 0
                    and time.time() - lock_dir.stat().st_mtime > stale_after
                )
            except FileNotFoundError:
                continue

            if is_stale:
                # 先原子移走，再删除：不会误删刚获得锁的新持有者目录。
                stale_dir = lock_dir.with_name(
                    f'{lock_dir.name}.stale.{secrets.token_hex(4)}'
                )
                try:
                    os.replace(lock_dir, stale_dir)
                    shutil.rmtree(stale_dir, ignore_errors=True)
                except OSError:
                    pass
                continue

            if time.monotonic() >= deadline:
                raise TimeoutError(f'获取文件锁超时: {lock_dir}')
            time.sleep(0.05)
        except OSError:
            # Windows 上杀软/索引器短暂占用目录时 mkdir/stat 可能抛
            # PermissionError。这不是锁冲突，重试直到 timeout 即可。
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)

    held[key] = 1
    try:
        yield
    finally:
        held.pop(key, None)
        if owner_written:
            try:
                current_owner = (lock_dir / 'owner').read_text(encoding='utf-8').strip()
            except OSError:
                current_owner = ''
            if current_owner == owner:
                with contextlib.suppress(OSError):
                    (lock_dir / 'owner').unlink()
                with contextlib.suppress(OSError):
                    lock_dir.rmdir()
            # owner 不匹配：锁已被回收/换主，绝不能删除别人的锁。
        else:
            with contextlib.suppress(OSError):
                lock_dir.rmdir()


def locked_atomic_write_json(file_path: str | Path, data: Any, indent: int = 2) -> None:
    """加锁 + 原子写 JSON。用于多执行者共享的状态文件。"""
    with file_lock(file_path):
        atomic_write_json(file_path, data, indent=indent)


def _rename_with_retry(src: str, dest: str, retries: int = 8, delay_ms: int = 50) -> None:
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


"""Truncation Utility — Ported from Project B

Provides logic to truncate large tool outputs and save the full content to a
temporary file, ensuring the LLM context remains manageable.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import TypedDict


class TruncationResult(TypedDict):
    content: str
    output_file: str | None

def find_structural_split(content: str, target_line: int, window: int = 10) -> int:
    """Attempt to find a clean split point (e.g. between functions) near the target line."""
    lines = content.splitlines()
    search_start = max(0, target_line - window)
    search_end = min(len(lines), target_line + window)

    # Heuristic: Find empty lines or lines followed by top-level definitions
    for i in range(target_line, search_start - 1, -1):
        if i < len(lines) and (not lines[i].strip() or lines[i].startswith(('def ', 'class ', '@'))):
            return i

    for i in range(target_line, search_end):
        if i < len(lines) and (not lines[i].strip() or lines[i].startswith(('def ', 'class ', '@'))):
            return i

    return target_line

def truncate_and_save_to_file(
    content: str,
    file_name: str,
    project_temp_dir: str | Path,
    threshold: int = 10000,
    max_lines: int = 500,
    use_structural: bool = True
) -> TruncationResult:
    """Truncated large content and saves full version to a temp file.

    Ported from Project B's truncateAndSaveToFile + Structural Awareness.
    """
    lines = content.splitlines()

    # Check if truncation is needed (Token-aware threshold)
    token_count = estimate_tokens(content)
    if len(content) <= threshold and len(lines) <= max_lines:
        return {"content": content, "output_file": None}

    project_temp_dir = Path(project_temp_dir)
    project_temp_dir.mkdir(parents=True, exist_ok=True)

    # Calculate head and tail budgets
    effective_lines = min(max_lines, len(lines))
    head_count = max(effective_lines // 5, 1)

    if use_structural:
        head_count = find_structural_split(content, head_count)

    tail_count = effective_lines - head_count
    tail_start = max(len(lines) - tail_count, head_count + 1)

    if use_structural:
        tail_start = find_structural_split(content, tail_start)

    separator = f"\n\n---\n... [CONTENT TRUNCATED: {len(lines) - (head_count + (len(lines) - tail_start))} lines removed] ...\n---\n\n"
    ellipsis = "..."

    # Head Collection
    head_budget = threshold // 5
    beginning = []
    head_chars = 0
    for i in range(min(head_count, len(lines))):
        line = lines[i]
        remaining = head_budget - head_chars
        if remaining <= 0:
            break
        if len(line) + 1 > remaining:
            slice_len = max(remaining - len(ellipsis), 0)
            beginning.append(line[:slice_len] + ellipsis)
            head_chars = head_budget
            break
        beginning.append(line)
        head_chars += len(line) + 1

    # Tail Collection
    tail_budget = max(threshold - head_chars - len(separator), 0)
    end = []
    tail_chars = 0
    for i in range(len(lines) - 1, tail_start - 1, -1):
        line = lines[i]
        remaining = tail_budget - tail_chars
        if remaining <= 0:
            break
        if len(line) + 1 > remaining:
            slice_len = max(remaining - len(ellipsis), 0)
            end.insert(0, ellipsis + line[-slice_len:])
            tail_chars = tail_budget
            break
        end.insert(0, line)
        tail_chars += len(line) + 1

    truncated_content = "\n".join(beginning) + separator + "\n".join(end)

    # Save to file
    safe_name = f"{Path(file_name).name}.output"
    output_file = project_temp_dir / safe_name

    try:
        output_file.write_text(content, encoding='utf-8', errors='replace')

        return {
            "content": (
                f"Tool output was too large ({len(content)} chars, ~{token_count} tokens) and has been truncated.\n"
                f"Full output (with structural split): {output_file}\n"
                f"Head lines: {len(beginning)}, Tail lines: {len(end)}\n\n"
                f"Truncated part:\n{truncated_content}"
            ),
            "output_file": str(output_file)
        }
    except Exception:
        return {
            "content": truncated_content + "\n[Note: Could not save full output to file]",
            "output_file": None
        }

def truncate_tool_output(
    tool_name: str,
    content: str,
    temp_dir: str | Path,
    threshold: int = 10000,
    max_lines: int = 500,
    use_structural: bool = True
) -> TruncationResult:
    """High-level truncation helper."""
    if threshold <= 0 or max_lines <= 0:
        return {"content": content, "output_file": None}

    random_suffix = secrets.token_hex(3)
    file_name = f"{tool_name}_{random_suffix}"

    return truncate_and_save_to_file(
        content,
        file_name,
        temp_dir,
        threshold,
        max_lines,
        use_structural=use_structural
    )

from __future__ import annotations

import difflib
import logging

logger = logging.getLogger(__name__)

def create_progress_bar(percentage: float, width: int = 30) -> str:
    """创建美观的进度条 (0-100)"""
    block = '█'
    empty = '░'
    filled_blocks = int(width * percentage // 100)
    empty_blocks = max(0, width - filled_blocks)
    return block * filled_blocks + empty * empty_blocks

def find_best_fence(text: str) -> str:
    """选择不与内容冲突的 Markdown 代码围栏"""
    for i in range(3, 11):
        backticks = '`' * i
        if backticks not in text:
            return backticks
    return '```````````'

def get_diff_stats(old: str | list[str], new: str | list[str]) -> dict[str, int]:
    """计算详细的差异统计信息，支持字符串和列表输入"""
    old_lines = old.splitlines() if isinstance(old, str) else old
    new_lines = new.splitlines() if isinstance(new, str) else new

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    stats = {
        'additions': 0, 'deletions': 0, 'modifications': 0, 'unchanged': 0,
        'added': 0, 'removed': 0  # Aider 兼容键
    }

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            stats['unchanged'] += i2 - i1
        elif tag == 'replace':
            stats['modifications'] += max(i2 - i1, j2 - j1)
        elif tag == 'delete':
            stats['deletions'] += i2 - i1
            stats['removed'] += i2 - i1
        elif tag == 'insert':
            stats['additions'] += j2 - j1
            stats['added'] += j2 - j1
    return stats

def find_last_non_deleted_line(lines_orig: list[str], lines_updated: list[str]) -> int | None:
    """查找最后一个未被删除的原始行号 (1-indexed)"""
    diff = list(difflib.ndiff(lines_orig, lines_updated))
    num_orig = 0
    last_non_deleted = None
    for line in diff:
        code = line[0]
        if code == ' ':
            num_orig += 1
            last_non_deleted = num_orig
        elif code == '-':
            num_orig += 1
    return last_non_deleted

def generate_partial_update_diff(
    lines_orig: list[str],
    lines_updated: list[str],
    final: bool = False,
    filename: str | None = None
) -> str:
    """生成流式编辑过程中的增量 Diff 显示"""
    num_orig_lines = len(lines_orig)
    if final:
        last_non_deleted = num_orig_lines
    else:
        last_non_deleted = find_last_non_deleted_line(lines_orig, lines_updated)

    if last_non_deleted is None:
        return ""

    pct = (last_non_deleted * 100 / num_orig_lines) if num_orig_lines else 100
    bar = create_progress_bar(pct)
    progress_info = f' {last_non_deleted:3d} / {num_orig_lines:3d} lines [{bar}] {pct:3.0f}%\n'

    # 截断原始行
    lines_orig_sub = lines_orig[:last_non_deleted]
    lines_updated_sub = lines_updated if final else [*lines_updated[:-1], progress_info]

    diff_lines = list(difflib.unified_diff(lines_orig_sub, lines_updated_sub, n=5))[2:]
    diff_content = "".join(diff_lines)
    if not diff_content.endswith('\n'):
        diff_content += '\n'

    fence = find_best_fence(diff_content)
    header = f"{fence}diff\n"
    if filename:
        header += f"--- {filename} (original)\n+++ {filename} (updated)\n"

    return f"{header}{diff_content}{fence}\n\n"

def show_diff(lines_orig: list[str], lines_updated: list[str], fname: str = '', context_lines: int = 5) -> str:
    """显示统一 Diff 格式"""
    return "".join(difflib.unified_diff(
        lines_orig, lines_updated,
        fromfile=f'{fname} (original)' if fname else 'original',
        tofile=f'{fname} (updated)' if fname else 'updated',
        n=context_lines
    ))

def format_diff_summary(stats: dict[str, int]) -> str:
    """格式化差异统计摘要"""
    parts = []
    if stats.get('additions'):
        parts.append(f"+{stats['additions']}")
    if stats.get('deletions'):
        parts.append(f"-{stats['deletions']}")
    if stats.get('modifications'):
        parts.append(f"~{stats['modifications']}")
    # Aider 兼容键
    if not parts:
        if stats.get('added'):
            parts.append(f"+{stats['added']}")
        if stats.get('removed'):
            parts.append(f"-{stats['removed']}")

    return ' '.join(parts) if parts else 'no changes'

def simple_diff(old: str, new: str, context: int = 3) -> str:
    """简单的字符串 Diff"""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return "".join(difflib.unified_diff(old_lines, new_lines, n=context))

def format_diff_line(line: str, prefix: str = " ") -> str:
    """格式化单行 Diff 显示"""
    if line.startswith("+"):
        return f"+ {line[1:]}"
    elif line.startswith("-"):
        return f"- {line[1:]}"
    return f"  {line}"

def is_diff_hunk_header(line: str) -> bool:
    """检查是否为 Diff 块头 (@@)"""
    return line.startswith("@@")

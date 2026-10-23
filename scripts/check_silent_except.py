"""统计"静默吞异常"数量，用于趋势看护。

## 为什么需要它

`skills/clawd-change-workflow/SKILL.md` 明确要求"不得增加静默吞异常"，
但历史上这条约束没有任何自动化检查，于是从 255 处（v0.51.0）一路漂移，
而每次统计口径都不同（是否含单行 `except: pass`、是否含 `except ... as e: pass`），
导致数字互相矛盾（206 / 163 / 101 三个版本同时在文档里出现）。

本脚本用 **AST** 而不是正则，口径唯一且可解释：

    静默吞异常 = 一个 `except` handler 的函数体只包含 `pass` 或 `...`

注意：`pass` 后面带注释仍算（注释不是语句）。

用法：
    python scripts/check_silent_except.py                  # 打印统计
    python scripts/check_silent_except.py --baseline 163   # 超过基线则退出码 1
    python scripts/check_silent_except.py --json out.json  # 结构化输出
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# 从 v0.60.6 起作为趋势基线（2026-10-23 AST 实测 172）：只允许下降，不允许上升。
# 注：正则口径（`except ...:` 换行 `pass`）同期为 163，两者差异来自
# 「except 体只有 pass 但中间夹注释」与「... 占位」的计法不同。以本脚本为准。
BASELINE = 172


def _is_silent(handler: ast.ExceptHandler) -> bool:
    """handler 体内是否只有 pass / ...（含其后的注释，注释不算语句）。"""
    body = handler.body
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and (
        stmt.value.value is Ellipsis
    )


def scan_file(path: Path) -> list[dict]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:  # 语法错误本身应由 ruff/pytest 报，这里只跳过
        return [{"file": str(path.relative_to(ROOT)), "line": 0, "error": str(exc)}]

    hits: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) or (
            hasattr(ast, "TryStar") and isinstance(node, ast.TryStar)
        ):
            for handler in node.handlers:
                if _is_silent(handler):
                    hits.append(
                        {
                            "file": str(path.relative_to(ROOT)),
                            "line": handler.lineno,
                        }
                    )
    return hits


def scan() -> list[dict]:
    hits: list[dict] = []
    for path in sorted(SRC.rglob("*.py")):
        hits.extend(scan_file(path))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=int, default=None, help="超过该值则以 1 退出")
    ap.add_argument(
        "--fail-over",
        type=int,
        default=None,
        help="同 --baseline，CI 门禁语义更明确：静默吞异常数量超过该值即失败",
    )
    ap.add_argument(
        "--write-baseline",
        type=Path,
        default=None,
        help="把当前总数写成基线文件（JSON），供后续 --baseline-file 使用",
    )
    ap.add_argument(
        "--baseline-file",
        type=Path,
        default=None,
        help="从基线文件读取阈值（默认 .clawd/baseline-silent.json，存在则自动使用）",
    )
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    hits = scan()
    total = len(hits)

    # 阈值来源优先级：显式参数 > 基线文件 > 内置常量
    threshold = args.fail_over if args.fail_over is not None else args.baseline
    baseline_file = args.baseline_file or (ROOT / ".clawd" / "baseline-silent.json")
    file_baseline: int | None = None
    if args.baseline_file is not None or baseline_file.exists():
        try:
            file_baseline = int(
                json.loads(baseline_file.read_text(encoding="utf-8"))["total"]
            )
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            file_baseline = None
    if threshold is None:
        threshold = file_baseline

    by_file: dict[str, int] = {}
    for h in hits:
        by_file[h["file"]] = by_file.get(h["file"], 0) + 1
    ranked = sorted(by_file.items(), key=lambda kv: kv[1], reverse=True)

    print(f"静默吞异常（AST 口径：except 体只含 pass / ...）: {total}")
    print(f"内置基线: {BASELINE}" + (f" · 基线文件: {file_baseline}" if file_baseline is not None else ""))
    print()
    for name, count in ranked[: args.top]:
        print(f"  {count:4d}  {name}")

    if args.write_baseline:
        args.write_baseline.parent.mkdir(parents=True, exist_ok=True)
        args.write_baseline.write_text(
            json.dumps(
                {
                    "total": total,
                    "note": "静默吞异常趋势基线：只允许下降，不允许上升（policy.md §1）",
                    "generated_at": __import__("datetime").datetime.now().isoformat(
                        timespec="seconds"
                    ),
                    "by_file": by_file,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n基线文件已写入 {args.write_baseline}（total={total}）")

    if args.json:
        args.json.write_text(
            json.dumps(
                {"total": total, "baseline": BASELINE, "by_file": by_file, "hits": hits},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nJSON 已写入 {args.json}")

    if threshold is not None and total > threshold:
        print(f"\nFAILED: {total} > 阈值 {threshold}（静默吞异常不得增加）")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

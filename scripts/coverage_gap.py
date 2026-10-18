"""列出「生产可达但覆盖率低」的模块 —— 用于决定补测试的优先级。

## 为什么不是直接看 coverage.json 的全局排行

全局未覆盖行数最高的文件往往是**死代码**（例如 `git_utils`、`state_impl`）。
给死代码补测试只会美化数字，不会提升产品质量。

本工具先把 `scripts/reachability.py` 的生产可达集合与覆盖率报告求交，
只列出「真的会被执行、但测试很少覆盖」的模块。

## 用法

```bash
# 1) 生成覆盖率报告
python -m pytest tests/ -q --cov=src --cov-report=json:coverage.json

# 2) 列出可达模块的覆盖缺口
python scripts/coverage_gap.py --min-statements 60 --top 20
```
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_reachability():
    spec = importlib.util.spec_from_file_location("reachability", ROOT / "scripts" / "reachability.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", type=Path, default=ROOT / "coverage.json")
    ap.add_argument("--min-statements", type=int, default=60)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    if not args.coverage.exists():
        print(f"找不到覆盖率报告: {args.coverage}")
        print("先生成: python -m pytest tests/ -q --cov=src --cov-report=json:coverage.json")
        return 2

    reach = _load_reachability()
    table = reach.build_module_table()
    prod = reach.reachable_from(["src.main", "src.cli.entrypoint"], table)

    data = json.loads(args.coverage.read_text(encoding="utf-8"))
    rows = []
    for file_path, info in data.get("files", {}).items():
        module = file_path[:-3].replace(chr(92), ".").replace("/", ".")
        if module not in prod:
            continue
        summary = info["summary"]
        if summary["num_statements"] < args.min_statements:
            continue
        rows.append(
            (
                summary["missing_lines"],
                summary["percent_covered"],
                module,
                summary["num_statements"],
            )
        )

    rows.sort(reverse=True)
    print(f"生产可达模块 {len(rows)} 个（语句数 ≥ {args.min_statements}），按未覆盖行数排序：\n")
    print(f"{'missing':>8}  {'cover%':>7}  {'stmt':>6}  module")
    for missing, pct, module, stmts in rows[: args.top]:
        print(f"{missing:8d}  {pct:6.1f}%  {stmts:6d}  {module}")

    total = data["totals"]
    print(
        f"\n全局覆盖率: {total['percent_covered']:.2f}% "
        f"({total['covered_lines']}/{total['num_statements']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

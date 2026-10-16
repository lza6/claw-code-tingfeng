"""找出"整目录死亡 + 存在同名存活实现"的重复品。

判据（保守）：只有当某目录**全部模块都不可达**，且仓库中存在**名字近似
且存活**的实现时，才视为"已被取代的重复品"，可以安全删除。

不符合该判据的死模块一律不删 —— 它们更可能是"从未接线的功能"，
删除等于砍掉能力，必须由产品决策而非自动清理决定。
"""
from __future__ import annotations

import importlib.util
from collections import defaultdict
from pathlib import Path

spec = importlib.util.spec_from_file_location("r", "scripts/reachability.py")
reach = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reach)

table = reach.build_module_table()
prod = ["src.main", "src.cli.entrypoint", "src.__init__"]
prod_reach = reach.reachable_from([s for s in prod if s in table], table)

test_seeds = [x for x in reach.test_modules() if x in table]
extra: set[str] = set()
for p in (Path(".") / "tests").rglob("*.py"):
    extra |= reach.extract_imports(p)
test_seeds += [c for c in extra if c in table]
alive = prod_reach | reach.reachable_from(test_seeds, table)

bydir: dict[str, list] = defaultdict(list)
for mod, path in table.items():
    bydir[str(path.parent)].append((mod, path))

print("整目录死亡 + 存在近名存活实现（= 可安全删除的重复品）\n")
total_lines = 0
suspects = []

for d, entries in sorted(bydir.items()):
    dead = [(mod, p) for mod, p in entries if mod not in alive]
    if len(dead) != len(entries) or len(entries) < 2:
        continue
    dirname = Path(d).name.lower().rstrip("s")
    lines = sum(
        len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) for _, p in dead
    )
    matches = sorted(a for a in alive if dirname in a.lower())

    rel = d.replace("\\", "/").split("claw-code-tingfeng/")[-1]
    if matches:
        total_lines += lines
        suspects.append((lines, rel, matches))
        print(f"[{lines:>5} 行] {rel}")
        for x in matches[:3]:
            print(f"             存活对照 -> {x}")
        print()

print(f"可安全删除合计: {len(suspects)} 个目录 / {total_lines} 行")

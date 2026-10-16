"""生成死代码复核清单（**不授权自动删除**）。

## 为什么这个脚本只出清单、不判"可删"

初版用一个"近名存活实现存在 → 判为已取代的重复品"的启发式。实测它**误报严重**：

    src.core.hook_registry.async_executor   "对照" src.core.hook_registry
        —— 后者是**同一个包**，前者是它的子模块，不是重复品
    src.workflow.worktree_isolation         "对照" src.cli.commands.workflow_commands
        —— 仅仅因为名字里都含 "workflow"

名称相似 ≠ 语义重复。**基于名称的启发式不足以授权删除源码。**

因此本脚本只做一件事：把"生产不加载"的模块按**有无近名存活模块**分桶，
输出给人工逐条复核。真正的删除判据必须是**读源码确认同一能力**，
而不是名字像。

实际执行过的删除（4 组）都经过人工核对：确认来自**同一个 TypeScript 源文件**、
且存活侧已被生产路径引用。

用法: python scripts/deadcode_inventory.py
"""
from __future__ import annotations

import importlib.util
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

dead = {m: p for m, p in table.items() if m not in alive}


def lines_of(mod: str) -> int:
    try:
        return len(table[mod].read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def top_pkg(mod: str) -> str:
    return ".".join(mod.split(".")[:3])


near_name: list[tuple[int, str, list[str]]] = []
no_counterpart: list[tuple[int, str]] = []

for mod in sorted(dead):
    dirname = Path(table[mod]).parent.name.lower().rstrip("s")
    # 只认"**跨顶层包**的近名存活模块" —— 同包内的兄弟模块不算对照。
    # 这仍不足以授权删除，只是把复核范围缩小。
    matches = sorted(
        a for a in alive
        if dirname and dirname in a.lower() and top_pkg(a) != top_pkg(mod)
    )
    if matches:
        near_name.append((lines_of(mod), mod, matches[:3]))
    else:
        no_counterpart.append((lines_of(mod), mod))

near_name.sort(reverse=True)
no_counterpart.sort(reverse=True)

total = sum(lines_of(m) for m in dead)
print(f"生产不加载模块: {len(dead)} 个 / {total} 行")
print(f"  ├ 有跨包近名存活模块（值得优先复核）: {len(near_name)}  "
      f"行数 {sum(s[0] for s in near_name)}")
print(f"  └ 无任何近名对照（疑似纯未接线功能）: {len(no_counterpart)}  "
      f"行数 {sum(u[0] for u in no_counterpart)}")
print()
print("⚠️  两个桶都**不能**直接删除。判据是读源码确认同一能力，不是名字像。")
print()
print("=" * 78)
print("无近名对照 —— 疑似未接线功能（删除前必须确认产品是否还需要）")
print("=" * 78)
for n, mod in no_counterpart[:40]:
    print(f"{n:5d}  {mod}")
if len(no_counterpart) > 40:
    print(f"      ... 另有 {len(no_counterpart) - 40} 个")
print()
print("=" * 78)
print("有跨包近名存活模块 —— 优先复核（前 30 个）")
print("=" * 78)
for n, mod, m in near_name[:30]:
    print(f"{n:5d}  {mod}")
    print(f"       └ 近名存活: {m[0]}")


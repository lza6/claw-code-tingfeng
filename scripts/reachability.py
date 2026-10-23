"""从入口点出发的传递可达性分析。

## 为什么需要它

此前用过两种判据，都不够：

1. **前缀匹配**（"有没有 import 前缀等于该模块"）—— 过于宽松，把
   `src.llm` 被引用当成 `src.llm.circuit_breaker` 被引用。误报 213 个。
2. **直接导入者**（"谁 import 了这个模块"）—— 过于宽松的另一面：
   `src.tools_runtime.file_processor` 被 `connectors.py` 导入，
   但 `connectors.py` 自己无人引用 —— 于是 file_processor 也被误判为"活的"。

正确判据是**传递可达性**：从真正的入口点出发做 BFS，只有能被走到的模块
才是运行时真的会加载的模块。

## 入口点定义

- `src/main.py`、`src/cli/entrypoint.py` —— `pyproject.toml` 的
  `[project.scripts]` 与实际启动路径
- `src/__init__.py` —— 包初始化
- `tests/**` —— 测试会加载的模块（单独统计，便于区分"仅测试可达"）

## 用法
    python scripts/reachability.py            # 概要
    python scripts/reachability.py --list     # 列出不可达模块
    python scripts/reachability.py --list --prod   # 只看"连测试都到不了"的
"""
from __future__ import annotations

import argparse
import ast
import contextlib
from collections import deque
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 模块表
# ---------------------------------------------------------------------------

def build_module_table() -> dict[str, Path]:
    """扫描 src/ 建立 点分模块名 -> 文件路径 的映射。"""
    table: dict[str, Path] = {}
    for p in (REPO / "src").rglob("*.py"):
        rel = p.relative_to(REPO)
        parts = list(rel.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            table[".".join(parts)] = p
    return table


# ---------------------------------------------------------------------------
# 单个文件的 import 提取
# ---------------------------------------------------------------------------

def _resolve_relative(file_parts: list[str], is_package: bool, level: int, mod: str) -> str:
    """把相对导入解析成绝对点分名。

    Python（PEP 328）的规则是：`from . import x` 里的 `.` 指向**当前模块所属的包**。

      - 普通模块 `a.b.c`  (a/b/c.py)   所属包 = `a.b`
      - 包      `a.b`    (a/b/__init__.py) 所属包 = `a.b` 自身（不是 `a`）

    所以两者减去的层数不同：
        非包: base = file_parts[: len - level]
        包  : base = file_parts[: len - level + 1]

    初版统一用了前者，导致**每个 `__init__.py` 里的相对导入都少解析一层** ——
    `src/llm/__init__.py` 里的 `from .factory import ...` 被算成
    `src.factory`（不存在）而不是 `src.llm.factory`。结果整棵 `src.llm.*`
    子树被误判为"生产不可达"。
    """
    if level <= 0:
        return mod
    cut = len(file_parts) - level + (1 if is_package else 0)
    base = file_parts[: max(0, cut)]
    return ".".join(base + ([mod] if mod else []))


def extract_imports(path: Path) -> set[str]:
    """提取一个文件里出现的所有候选模块名（含函数体内的延迟导入）。

    对 `from X import Y` 同时产出 `X` 和 `X.Y`：
    前者可能是因为 Y 是 X 的子模块，后者可能是因为 Y 只是模块内符号。
    由调用方用模块表做实际判定，多余的候选会被自然丢弃。
    """
    path = Path(path).resolve()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return set()

    try:
        rel = path.relative_to(REPO)
    except ValueError:
        return set()

    raw_parts = list(rel.with_suffix("").parts)
    is_package = bool(raw_parts) and raw_parts[-1] == "__init__"
    file_parts = raw_parts[:-1] if is_package else raw_parts

    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                mod = _resolve_relative(file_parts, is_package, node.level, mod)
            if not mod:
                continue
            out.add(mod)
            for alias in node.names:
                if alias.name != "*":
                    out.add(f"{mod}.{alias.name}")
    return out


# ---------------------------------------------------------------------------
# BFS
# ---------------------------------------------------------------------------

def reachable_from(seeds: list[str], table: dict[str, Path]) -> set[str]:
    """从种子模块出发做 BFS，返回所有可达的 src.* 模块。"""
    seen: set[str] = set()
    queue: deque[str] = deque()

    for s in seeds:
        if s in table and s not in seen:
            seen.add(s)
            queue.append(s)

    cache: dict[str, set[str]] = {}
    while queue:
        mod = queue.popleft()
        if mod not in cache:
            cache[mod] = extract_imports(table[mod])
        for cand in cache[mod]:
            if not cand.startswith("src."):
                continue
            # 精确命中，或命中了某个包（cand 是包名、实际加载其 __init__）
            for target in (cand, cand.rsplit(".", 1)[0]):
                if target in table and target not in seen:
                    seen.add(target)
                    queue.append(target)
    return seen


def test_modules() -> list[str]:
    """测试文件自身的模块名（作为一组种子）。"""
    out = []
    for p in (REPO / "tests").rglob("*.py"):
        rel = p.relative_to(REPO)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            continue
        out.append(".".join(parts))
    return out


# 生产入口种子（**唯一来源**）。
#
# 2026-10-23 教训：`scripts/deadcode_triage.py` 一开始自己硬编码了一份简化列表，
# 漏掉 `src.__main__`，于是 `python -m src` 的规范入口被算进"完全不可达"，
# 差点被当成死代码。任何需要生产可达集的脚本都必须复用本函数，
# 禁止各自复制一份列表。
#
# 另注：`src.main` 是历史 argparse 入口（`python -m src.main`），
# `src.cli.entrypoint` 是 `clawd` console script 与 `python -m src` 的共同实现。
PROD_SEED_MODULES: tuple[str, ...] = (
    "src.__init__",
    "src.__main__",  # `python -m src` 的规范入口（= src.cli.entrypoint.main）
    "src.main",  # 历史 argparse 入口，保留兼容
    "src.cli.entrypoint",
    "src.cli.__init__",
)


def prod_seeds(table: dict[str, Path]) -> list[str]:
    """返回在模块表中真实存在的生产入口种子。"""
    return [s for s in PROD_SEED_MODULES if s in table]


def compute_reachability(
    table: dict[str, Path],
) -> tuple[set[str], set[str], set[str]]:
    """返回 (生产可达, 全部可达, 完全不可达)。所有脚本共用同一口径。"""
    prod_reach = reachable_from(prod_seeds(table), table)

    test_seeds = [m for m in test_modules() if m in table]
    extra: set[str] = set()
    for p in (REPO / "tests").rglob("*.py"):
        extra |= extract_imports(p)
    test_seeds += [c for c in extra if c in table]
    test_reach = reachable_from(test_seeds, table)

    all_reach = prod_reach | test_reach
    fully_unreachable = set(table) - all_reach
    return prod_reach, all_reach, fully_unreachable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="列出不可达模块")
    ap.add_argument("--prod", action="store_true", help="只统计『连测试都到不了』的模块")
    ap.add_argument(
        "--min-reachable",
        type=int,
        default=None,
        help="生产可达模块数低于该值时以 1 退出（删码/重构后防倒退，CI 用）",
    )
    args = ap.parse_args()

    table = build_module_table()

    prod_reach = reachable_from(prod_seeds(table), table)

    # 测试种子（测试文件本身 + 它们 import 的）
    test_seeds = [m for m in test_modules() if m in table]
    extra = set()
    for p in (REPO / "tests").rglob("*.py"):
        extra |= extract_imports(p)
    test_seeds += [c for c in extra if c in table]
    test_reach = reachable_from(test_seeds, table)

    all_reach = prod_reach | test_reach
    unreachable = sorted(set(table) - all_reach)
    # 「生产不加载」= 从生产入口走不到，不管测试有没有覆盖它。
    # 这是判断"这段代码用户跑应用时会不会被执行"的正确口径。
    not_prod = sorted(set(table) - prod_reach)

    def lines(mods: list[str]) -> int:
        total = 0
        for m in mods:
            with contextlib.suppress(OSError):
                total += len(table[m].read_text(encoding="utf-8", errors="ignore").splitlines())
        return total

    print(f"src 模块总数                    : {len(table)}")
    print(f"从生产入口可达                  : {len(prod_reach)}")
    print(f"生产不加载（含仅测试可达）      : {len(not_prod)}   行数 {lines(not_prod)}")
    print(f"   其中『连测试都到不了』       : {len(unreachable)}   行数 {lines(unreachable)}")
    print()

    target = not_prod if args.prod else unreachable
    label = "生产不加载" if args.prod else "连测试都到不了"
    if args.list:
        print(f"=== {label} 的模块（{len(target)} 个）===")
        for m in target:
            n = len(table[m].read_text(encoding="utf-8", errors="ignore").splitlines())
            print(f"{n:5d} 行  {m}")
    else:
        print("（加 --list 查看明细）")

    # 门禁：删码批次必须证明"生产可达数没下降"。2026-10-23 实测基线 = 442。
    # 只在启动器 import 形式保持为显式语句时有效（importlib 字符串导入会从图中消失，
    # 见 skills/clawd-change-workflow 的 AST 建图陷阱）。
    if args.min_reachable is not None and len(prod_reach) < args.min_reachable:
        print()
        print(
            f"FAILED: 生产可达 {len(prod_reach)} < 要求 {args.min_reachable}。"
            "删码/改导入后可达数下降，说明有模块从生产图中消失了。"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

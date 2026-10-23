"""对"完全不可达"模块做三问机械筛查，产出判定报告（**只判定，不删除**）。

## 为什么需要它

`计划书/下一步改进指南.md` §9.8 的 W6 要求对 135 个"连测试都到不了"的模块
逐条判定，每条回答三问。人工逐条读源码约需 11 小时，本脚本把**可机械化的部分**
（引用搜索、动态导入搜索）一次性做掉，剩下的"语义是否已被替换"留给人工，
并在报告里显式标 `需人工确认`。

## 三问

1. 有无**静态引用**：模块名（全名 / 末段）是否出现在 `src/ tests/ scripts/ docs/ *.md`
   中除自身之外的任何地方。
2. 有无**动态引用**：`importlib.import_module("...")` / `__import__("...")` /
   `globals()[...]` / `getattr(module, "...")` 里出现该名。
3. 有无**文档/配置引用**：`*.md`、`.clawd/`、`*.toml`、`*.json` 中出现该名。

## 判定输出

- `NO_REFS`：三问全空 → 候选删除（仍需人工读 10~30 行确认它不是"未来功能入口"）
- `DOC_ONLY`：只有文档提到 → 优先改文档，再判代码
- `HAS_REFS`：代码里有引用但可达性说不可达 → 说明是**条件导入或字符串路径**，禁止删
- `DYNAMIC`：有动态导入命中 → 禁止删

用法：
    py -3.10 scripts/deadcode_triage.py                    # 打印摘要
    py -3.10 scripts/deadcode_triage.py --md out.md        # 写 Markdown 判定报告
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 复用 reachability 的模块表与可达性计算（不重复实现 AST 建图）
_spec = importlib.util.spec_from_file_location(
    "reach", REPO / "scripts" / "reachability.py"
)
assert _spec and _spec.loader
reach = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reach)

SEARCH_DIRS = ["src", "tests", "scripts", "docs"]
SEARCH_ROOT_MD = ["*.md"]
SEARCH_CONFIG = [".clawd", "pyproject.toml", "skills-lock.json", "opencode.json"]


def _iter_search_files() -> list[Path]:
    files: list[Path] = []
    for d in SEARCH_DIRS:
        base = REPO / d
        if base.exists():
            files.extend(p for p in base.rglob("*") if p.is_file() and p.suffix in {".py", ".md", ".json", ".toml", ".yaml", ".yml"})
    for pattern in SEARCH_ROOT_MD:
        files.extend(p for p in REPO.glob(pattern) if p.is_file())
    for item in SEARCH_CONFIG:
        base = REPO / item
        if base.is_file():
            files.append(base)
        elif base.is_dir():
            files.extend(p for p in base.rglob("*") if p.is_file() and p.suffix in {".json", ".toml", ".yaml", ".yml", ".md"})
    # 去重并排除生成物/缓存
    seen: set[Path] = set()
    out: list[Path] = []
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        if any(part in {"__pycache__", "node_modules", "venv", ".git"} for part in f.parts):
            continue
        out.append(f)
    return out


def _module_file(module: str) -> Path | None:
    """把 src.a.b 映射到 src/a/b.py，取不到就 None（用于排除自引用）。"""
    rel = module.replace(".", "/")
    for cand in (REPO / f"{rel}.py", REPO / rel / "__init__.py"):
        if cand.exists():
            return cand
    return None


_DYNAMIC_PATTERNS = [
    re.compile(r"import_module\(\s*[\"']([^\"']+)[\"']"),
    re.compile(r"__import__\(\s*[\"']([^\"']+)[\"']"),
    re.compile(r"[\"']([a-zA-Z_][\w.]*)[\"']\s*\)"),  # globals()["x"] / getattr(o,"x")
]

# `src.a.b` 形式的模块 token（用于一次性抽取每个文件引用了哪些模块）
SRC_TOKEN = re.compile(r"\bsrc(?:\.[A-Za-z_]\w*)+")


def _scan_dynamic(files: list[Path]) -> dict[str, list[str]]:
    """返回 {被动态引用的字符串: [出现位置]}。"""
    hits: dict[str, list[str]] = {}
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in _DYNAMIC_PATTERNS:
            for m in pat.finditer(text):
                target = m.group(1)
                if not target.startswith("src"):
                    continue
                with contextlib.suppress(ValueError):
                    line = text[: m.start()].count("\n") + 1
                    hits.setdefault(target, []).append(f"{path.relative_to(REPO)}:{line}")
    return hits


def triage() -> list[dict]:
    table = reach.build_module_table()
    # 复用 reachability 的**唯一**口径（2026-10-23：本脚本曾自己硬编码种子列表，
    # 漏掉 src.__main__ 导致 `python -m src` 的入口被判成"完全不可达"）
    _prod_reach, _all_reach, fully_unreachable = reach.compute_reachability(table)
    fully_unreachable = sorted(fully_unreachable)
    files = _iter_search_files()
    dynamic = _scan_dynamic(files)

    # 预读所有文本并一次性抽出 `src.x.y` 形式的 token 集合。
    # 不做「每个模块 × 每个文件」的正则扫描——135 × 500 次全文正则会跑十分钟以上。
    corpus: dict[Path, str] = {}
    tokens: dict[Path, set[str]] = {}
    for path in files:
        with contextlib.suppress(OSError):
            text = path.read_text(encoding="utf-8", errors="replace")
            corpus[path] = text
            tokens[path] = set(SRC_TOKEN.findall(text))

    results: list[dict] = []
    for module in fully_unreachable:
        parent = module.rsplit(".", 1)[0] if "." in module else module
        leaf = module.rsplit(".", 1)[-1]
        own_file = _module_file(module)

        # 判据必须严格到"能证明存在引用"，而不是"名字像"。
        # 第一版用「末段作为独立标识符」匹配，实测 135/135 全被判为 HAS_REFS——
        # `modes`、`architect` 这类末段在别处当变量名/字符串频繁出现，
        # 这就是 ADR-0001 / ADR-0004 记录的「名称相似 ≠ 语义重复」陷阱重现。
        # 现在只认四种**确切导入形式**：
        #   1) 全限定名出现在文本中：src.a.b
        #   2) import src.a.b
        #   3) from src.a.b import ...
        #   4) from src.a import b（父包 + 末段）
        code_refs: list[str] = []
        doc_refs: list[str] = []
        for path, text in corpus.items():
            if own_file is not None and path == own_file:
                continue
            hit = module in tokens[path]
            if not hit and parent in tokens[path]:
                hit = re.search(
                    rf"\bfrom\s+{re.escape(parent)}\s+import\s+[^\n]*\b{re.escape(leaf)}\b",
                    text,
                ) is not None
            if not hit:
                continue
            rel = str(path.relative_to(REPO))
            if path.suffix == ".md":
                doc_refs.append(rel)
            else:
                code_refs.append(rel)

        dyn = [loc for key, locs in dynamic.items() if key == module or key.endswith("." + leaf) for loc in locs]

        if dyn:
            verdict = "DYNAMIC"
        elif code_refs:
            verdict = "HAS_REFS"
        elif doc_refs:
            verdict = "DOC_ONLY"
        else:
            verdict = "NO_REFS"

        loc = 0
        if module in table:
            with contextlib.suppress(OSError):
                loc = len(table[module].read_text(encoding="utf-8", errors="ignore").splitlines())

        results.append(
            {
                "module": module,
                "lines": loc,
                "verdict": verdict,
                "code_refs": sorted(set(code_refs))[:6],
                "doc_refs": sorted(set(doc_refs))[:6],
                "dynamic": dyn[:4],
            }
        )
    return results


LABEL = {
    "NO_REFS": "无任何引用（候选删除，仍需人工读码确认）",
    "DOC_ONLY": "仅文档提到（改文档 or 判代码）",
    "HAS_REFS": "代码中有引用（禁止删）",
    "DYNAMIC": "动态导入命中（禁止删）",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", type=Path, default=None, help="输出 Markdown 判定报告")
    ap.add_argument("--limit", type=int, default=0, help="仅打印前 N 条（0=全部）")
    args = ap.parse_args()

    results = triage()
    counts = Counter(r["verdict"] for r in results)
    total_lines = sum(r["lines"] for r in results)

    print(f"完全不可达模块: {len(results)} 个 / {total_lines} 行")
    for key, label in LABEL.items():
        print(f"  {key:9s} {counts.get(key, 0):4d}  {label}")

    if args.md:
        lines = [
            "# 死代码判定报告（W6，只判定不删除）",
            "",
            f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
            "> 生成方式：`py -3.10 scripts/deadcode_triage.py --md <本文件>`",
            "> 口径：`reachability.py` 判定的『连测试都到不了』的模块；"
            "三问由脚本机械筛查，**最终删除需人工确认语义**（ADR-0001/ADR-0004）。",
            "",
            "## 汇总",
            "",
            "| 判定 | 数量 | 含义 |",
            "|:---|---:|:---|",
        ]
        for key, label in LABEL.items():
            lines.append(f"| `{key}` | {counts.get(key, 0)} | {label} |")
        lines += ["", f"合计 **{len(results)} 个模块 / {total_lines} 行**。", ""]

        for key, label in LABEL.items():
            group = [r for r in results if r["verdict"] == key]
            if not group:
                continue
            lines += [f"## {key} — {label}", ""]
            for r in group:
                lines.append(f"### `{r['module']}`（{r['lines']} 行）")
                lines.append("")
                lines.append(f"- 三问结论：**{r['verdict']}**")
                lines.append(
                    "- 静态引用：" + ("无" if not r["code_refs"] else "、".join(f"`{x}`" for x in r["code_refs"]))
                )
                lines.append(
                    "- 文档引用：" + ("无" if not r["doc_refs"] else "、".join(f"`{x}`" for x in r["doc_refs"]))
                )
                lines.append(
                    "- 动态导入：" + ("无" if not r["dynamic"] else "、".join(f"`{x}`" for x in r["dynamic"]))
                )
                lines.append("")
            lines.append("")

        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n判定报告已写入 {args.md}")

    shown = results if not args.limit else results[: args.limit]
    for r in shown:
        if r["verdict"] in {"NO_REFS", "DOC_ONLY"}:
            print(f"  [{r['verdict']}] {r['module']} ({r['lines']} 行)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

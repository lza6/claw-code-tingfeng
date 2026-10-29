"""`src/core/` 边界治理检查（P3-1）

审计原话：`src/core/` 是"杂物间"（161 文件 / 34,923 行）。
彻底拆分是重构级工程（风险高、收益慢），所以先做**可执行的边界约束**，防止它继续膨胀：

1. **分层方向**：`core` 是底层，**不允许** import 上层（`cli` / `tools_runtime` / `agent` / `server` / `workflow`）；
2. **公开面清单**：`src/core/__init__.py` 里 export 的符号即"对外承诺"，新模块若想对外必须先登记；
3. **规模告警**：文件数 / 行数超过阈值时提示（阈值可调，不阻断），避免无声膨胀。

用法：
    venv/Scripts/python.exe scripts/core_surface.py           # 报告；有越界 import 则退出 1
    venv/Scripts/python.exe scripts/core_surface.py --json
"""
from __future__ import annotations

import argparse
import ast
import json
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "core"
UPWARD_LAYERS = ("cli", "tools_runtime", "agent", "server", "workflow")
MAX_FILES = 200          # 超过就提示（当前基线见输出）
MAX_LINES = 40000


def _iter_core_files() -> list[Path]:
    return sorted(p for p in CORE.rglob("*.py") if "__pycache__" not in p.parts)


def _imports(path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level and module:
                out.append((node.lineno, "." * node.level + module))
            elif module:
                out.append((node.lineno, module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.append((node.lineno, alias.name))
    return out


def find_upward_violations() -> list[dict]:
    violations: list[dict] = []
    for path in _iter_core_files():
        rel = path.relative_to(ROOT)
        for lineno, module in _imports(path):
            normalized = module.replace("src.", "").lstrip(".")
            head = normalized.split(".")[0]
            if head not in UPWARD_LAYERS:
                continue
            # 允许 core 内部以相对层级引用上游？不允许：core 必须最底层
            violations.append({
                "file": str(rel).replace("\\", "/"),
                "line": lineno,
                "import": module,
                "rule": f"core 不允许 import 上层模块 {head}",
            })
    return violations


def public_surface() -> list[str]:
    init = CORE / "__init__.py"
    if not init.is_file():
        return []
    try:
        tree = ast.parse(init.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    try:
                        names = [str(ast.literal_eval(node.value)[i]) for i in range(len(ast.literal_eval(node.value)))]
                    except (ValueError, SyntaxError, IndexError):
                        names = []
    return names


def load_allow() -> set[tuple[str, str]]:
    path = ROOT / "scripts" / "core_surface_allow.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {(item.get("file", ""), item.get("import", "")) for item in data.get("allowed", [])}


def main() -> int:
    ap = argparse.ArgumentParser(description="src/core 边界治理检查")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    files = _iter_core_files()
    total_lines = sum(len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) for p in files)
    all_violations = find_upward_violations()
    allowed = load_allow()
    violations = [v for v in all_violations if (v["file"], v["import"]) not in allowed]
    known = [v for v in all_violations if (v["file"], v["import"]) in allowed]
    surface = public_surface()

    payload = {
        "files": len(files),
        "lines": total_lines,
        "files_over_threshold": max(0, len(files) - MAX_FILES),
        "lines_over_threshold": max(0, total_lines - MAX_LINES),
        "upward_violations": violations,
        "upward_known": known,
        "public_surface": surface,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("=" * 72)
        print("src/core 边界治理")
        print("=" * 72)
        print(f"文件 {len(files)} 个 / {total_lines} 行"
              f"（阈值 {MAX_FILES} 文件 / {MAX_LINES} 行）")
        if len(files) > MAX_FILES or total_lines > MAX_LINES:
            print("  ⚠ 已超过阈值：新能力请优先放到专用子包（如 src/agent / src/rag / src/workflow），不要再往 core 堆")
        print(f"对外公开符号 {len(surface)} 个（{', '.join(surface[:8])}{'…' if len(surface) > 8 else ''}）")
        if known:
            print(f"[已知存量] 向上层 import {len(known)} 处（已登记，需逐步清零）：")
            for item in known[:10]:
                print(f"  - {item['file']}:{item['line']}  {item['import']}")
        if violations:
            print(f"[FAIL] 新增越界 import {len(violations)} 处（未登记）：")
            for item in violations[:20]:
                print(f"  - {item['file']}:{item['line']}  {item['import']}（{item['rule']}）")
        else:
            print("[PASS] 没有新增的向上层 import（存量已登记）")
        print("=" * 72)
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())

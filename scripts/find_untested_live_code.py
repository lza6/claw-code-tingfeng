"""找出"生产在跑但零测试覆盖"的模块 —— 最高风险区域。

判据: 覆盖率 0% 且模块**自身**被 src/ 中的活代码 import。

⚠️ 判据修正记录（2026-10-16）:
    初版用一个宽松判据 —— "模块的父包被 import 过" 也算活。
    结果 `src.llm.circuit_breaker` 因为 `src.llm` 被广泛 import 而误判为
    "生产在跑"，实际上它**没有任何调用方**。父包被引用 ≠ 该模块被引用。
    现改为精确匹配：必须 `import X.Y` 或 `from X import Y` 明确指向本模块。

用法: python scripts/find_untested_live_code.py
"""
import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def module_key(path_str: str) -> str:
    """把文件路径转成点分模块名。"""
    norm = path_str.replace("\\", "/")
    if norm.startswith("src/"):
        norm = norm[len("src/"):]
    if norm.endswith(".py"):
        norm = norm[:-3]
    if norm.endswith("/__init__"):
        norm = norm[: -len("/__init__")]
    return "src." + norm.replace("/", ".")


def collect_imports(roots: list[Path]) -> set[str]:
    """收集所有被 import 的完整点分名。

    对 `from X import Y` 同时记录 `X` 与 `X.Y` —— 后者才是"Y 是本包内
    的一个模块"的精确证据。
    """
    found: set[str] = set()
    files = [p for root in roots for p in root.rglob("*.py")]
    for p in files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        fp = list(p.with_suffix("").parts)
        if fp[-1] == "__init__":
            fp = fp[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    found.add(a.name)
            elif isinstance(node, ast.ImportFrom):
                m = node.module or ""
                if node.level:
                    base = fp[: len(fp) - node.level]
                    m = ".".join(base + ([m] if m else []))
                if not m:
                    continue
                found.add(m)
                for a in node.names:
                    if a.name != "*":
                        found.add(f"{m}.{a.name}")
    return found


def main() -> int:
    cov_path = REPO / "coverage.json"
    if not cov_path.exists():
        print(f"缺少 {cov_path}；先运行 pytest --cov=src --cov-report=json", file=sys.stderr)
        return 1

    cov = json.loads(cov_path.read_text(encoding="utf-8"))
    zero: dict[str, tuple[int, str]] = {}
    for f, v in cov["files"].items():
        s = v["summary"]
        if s["num_statements"] >= 40 and s["percent_covered"] == 0.0:
            zero[module_key(f)] = (s["num_statements"], f.replace("\\", "/"))

    imported = collect_imports([REPO / "src"])

    risky = [
        (stmts, key, path)
        for key, (stmts, path) in zero.items()
        if key in imported or any(i.startswith(key + ".") for i in imported)
    ]
    risky.sort(reverse=True)

    print(f"零覆盖模块（>=40 语句）总数        : {len(zero)}")
    print(f"其中模块自身被 src 活代码 import 的 : {len(risky)}")
    print(f"涉及未测语句数                     : {sum(r[0] for r in risky)}")
    print()

    if not risky:
        print("没有『生产在跑但零测试』的模块。")
        return 0

    print("=== 逐项（按语句数降序）===")
    for stmts, key, path in risky:
        print(f"{stmts:5d} 语句  {path}    [{key}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

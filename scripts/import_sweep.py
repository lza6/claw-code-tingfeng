"""全库导入扫描：找出所有在 import 期就失败的模块。

## 为什么要做这个

静态可达性（`reachability.py`）回答的是"从生产入口能不能走到"，
它**不回答**"走到了会不会炸"。一个模块可以静态可达却根本导入不了。

本脚本逐个 import `src/` 下每个模块，把结果分成三档：

- `IMPORT-OK`      正常导入
- `IMPORT-FAIL`    自身代码缺陷（TypeError / NameError / SyntaxError / ImportError）
- `DEP-MISSING`    依赖未安装（环境问题，不是代码问题，不计入缺陷）

## 关键区分

`ModuleNotFoundError` 指向上游**项目内模块**（`src.*`）是**真缺陷**（配错了路径）；
指向**第三方包**（litellm 等）是**环境缺依赖**。两者绝不能混为一谈——
把后者当缺陷会制造大量假问题。

用法：
    python scripts/import_sweep.py              # 只报失败项
    python scripts/import_sweep.py --all        # 报告全部
    python scripts/import_sweep.py --json out.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def discover_modules() -> list[str]:
    """枚举 src 下全部可导入模块名（含包与子模块）。"""
    mods: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        mods.append(".".join(parts))
    return mods


def classify(exc: BaseException) -> str:
    """把异常分成 '代码缺陷' vs '环境缺依赖'。

    判断依据：缺失的顶层包名是否存在于 src/ 下。
    指向 src.* 的是项目内路径配错 —— 真缺陷。
    指向第三方的是环境问题 —— 不是本仓库的代码问题。
    """
    if isinstance(exc, ModuleNotFoundError):
        name = getattr(exc, "name", "") or ""
        top = name.split(".")[0] if name else ""
        # 项目内模块缺失 → 真缺陷
        if top == "src" or (SRC / top).exists():
            return "IMPORT-FAIL"
        # 第三方依赖缺失 → 环境问题
        return "DEP-MISSING"
    if isinstance(exc, ImportError):
        return "IMPORT-FAIL"
    if isinstance(exc, (TypeError, NameError, AttributeError, ValueError, SyntaxError)):
        return "IMPORT-FAIL"
    return "IMPORT-FAIL"


def sweep() -> tuple[list[dict], int]:
    results: list[dict] = []
    # 先确保项目根在 sys.path 上
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    for mod in discover_modules():
        rec: dict = {"module": mod, "status": "IMPORT-OK", "error": ""}
        try:
            importlib.import_module(mod)
        except BaseException as e:  # noqa: BLE001 - 扫描需要吞下一切
            rec["status"] = classify(e)
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["exc_type"] = type(e).__name__
            rec["missing"] = getattr(e, "name", "") or ""
            if rec["status"] == "IMPORT-FAIL":
                rec["traceback_tail"] = traceback.format_exc().strip().splitlines()[-4:]
        results.append(rec)
    return results, len(results)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="报告全部模块")
    ap.add_argument("--json", type=Path, default=None, help="写 JSON 报告")
    args = ap.parse_args()

    results, total = sweep()
    ok = [r for r in results if r["status"] == "IMPORT-OK"]
    fail = [r for r in results if r["status"] == "IMPORT-FAIL"]
    dep = [r for r in results if r["status"] == "DEP-MISSING"]

    print(f"扫描模块总数        : {total}")
    print(f"  IMPORT-OK         : {len(ok)}")
    print(f"  IMPORT-FAIL (缺陷): {len(fail)}")
    print(f"  DEP-MISSING (环境): {len(dep)}")
    print()

    if fail:
        print("=== 导入期失败（项目内代码缺陷）===")
        for r in sorted(fail, key=lambda x: x["module"]):
            print(f"  {r['module']}")
            print(f"      {r['error']}")
    else:
        print("没有项目内导入缺陷。")

    if dep:
        print()
        print("=== 第三方依赖缺失（环境问题，非代码缺陷）===")
        tops = sorted({(r["missing"].split(".")[0] or "?") for r in dep})
        print(f"  受影响模块 {len(dep)} 个；缺失顶层包: {', '.join(tops)}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {"total": total, "ok": len(ok), "fail": fail, "dep_missing": dep},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nJSON 报告已写入 {args.json}")

    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""全库导入扫描：找出所有在 import 期就失败的模块。

## 为什么要做这个

静态可达性（`reachability.py`）回答的是"从生产入口能不能走到"，
它**不回答**"走到了会不会炸"。一个模块可以静态可达却根本导入不了。

本脚本逐个 import `src/` 下每个模块，把结果分成四档：

- `IMPORT-OK`      正常导入
- `IMPORT-FAIL`    自身代码缺陷（TypeError / NameError / SyntaxError / ImportError）
- `DEP-MISSING`    依赖未安装（环境问题，不是代码问题，不计入缺陷）
- `IMPORT-EXIT`    导入期主动退出进程（`SystemExit` / `KeyboardInterrupt`），
                   通常是模块把"缺可选依赖"写成了模块级 `sys.exit(1)`——
                   它掩盖了真实原因，**单列**而不计入缺陷，但必须人工复核。

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
    """把异常分成 '代码缺陷' / '环境缺依赖' / '导入期退出'。

    判断依据：缺失的顶层包名是否存在于 src/ 下。
    指向 src.* 的是项目内路径配错 —— 真缺陷。
    指向第三方的是环境问题 —— 不是本仓库的代码问题。

    `SystemExit` 单列：它常常是"缺可选依赖 → 模块级 sys.exit(1)"的结果，
    真实成因被掩盖。归入 IMPORT-FAIL 会让红线永久失真（见 2026-10-23 复核：
    `src.cli.surface_viewer` 因 venv 缺 jsonschema 被误判为代码缺陷）。
    """
    if isinstance(exc, (SystemExit, KeyboardInterrupt)):
        return "IMPORT-EXIT"
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
    ap.add_argument(
        "--strict-exit",
        action="store_true",
        help="IMPORT-EXIT > 0 时也以 1 退出（用于 CI 门禁，防止用 sys.exit 掩盖真实错误）",
    )
    args = ap.parse_args()

    results, total = sweep()
    ok = [r for r in results if r["status"] == "IMPORT-OK"]
    fail = [r for r in results if r["status"] == "IMPORT-FAIL"]
    dep = [r for r in results if r["status"] == "DEP-MISSING"]
    exited = [r for r in results if r["status"] == "IMPORT-EXIT"]

    print(f"扫描模块总数        : {total}")
    print(f"  IMPORT-OK         : {len(ok)}")
    print(f"  IMPORT-FAIL (缺陷): {len(fail)}")
    print(f"  DEP-MISSING (环境): {len(dep)}")
    if exited:
        print(f"  IMPORT-EXIT (待复核): {len(exited)}")
    print()

    if fail:
        print("=== 导入期失败（项目内代码缺陷）===")
        for r in sorted(fail, key=lambda x: x["module"]):
            print(f"  {r['module']}")
            print(f"      {r['error']}")
    else:
        print("没有项目内导入缺陷。")

    if exited:
        print()
        print("=== 导入期主动退出（多为缺可选依赖后 sys.exit，需人工复核）===")
        for r in sorted(exited, key=lambda x: x["module"]):
            print(f"  {r['module']}")
            print(f"      {r['error']}")

    if dep:
        print()
        print("=== 第三方依赖缺失（环境问题，非代码缺陷）===")
        tops = sorted({(r["missing"].split(".")[0] or "?") for r in dep})
        print(f"  受影响模块 {len(dep)} 个；缺失顶层包: {', '.join(tops)}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {"total": total, "ok": len(ok), "fail": fail,
                 "dep_missing": dep, "import_exit": exited},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nJSON 报告已写入 {args.json}")

    if args.strict_exit and exited:
        print(
            f"\nFAILED(--strict-exit): {len(exited)} 个模块在导入期主动退出进程。"
            "这类模块会把任何 import 它的调用方（含本脚本、插件发现逻辑）整个杀掉，"
            "必须改为抛异常并由调用方处理。"
        )
        return 1

    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
